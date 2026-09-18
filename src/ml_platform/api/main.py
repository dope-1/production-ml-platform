import logging
import re
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from time import perf_counter
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.openapi.utils import get_openapi
from fastapi.responses import HTMLResponse, JSONResponse
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from starlette.concurrency import run_in_threadpool
from starlette.middleware.trustedhost import TrustedHostMiddleware

from ml_platform import __version__
from ml_platform.api.routes import router
from ml_platform.api.security import SecurityMiddleware, content_policy
from ml_platform.core.config import Settings
from ml_platform.data.validation import FEATURES
from ml_platform.db.models import ApiEvent, Prediction
from ml_platform.db.session import check_database, create_db_engine
from ml_platform.inference.service import ModelService
from ml_platform.models.registry import RegistryReader
from ml_platform.observability.logging import configure_logging
from ml_platform.observability.telemetry import Metrics

logger = logging.getLogger("ml_platform.api")
REQUEST_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def create_app(
    settings: Settings | None = None,
    *,
    engine: Engine | None = None,
    model_service: ModelService | None = None,
) -> FastAPI:
    config = settings if settings is not None else Settings()
    configure_logging(config.log_level)
    metrics = Metrics()

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        app.state.engine = engine if engine is not None else create_db_engine(config)
        app.state.models = model_service
        if config.inference_enabled and model_service is None:
            try:
                app.state.models = ModelService(
                    RegistryReader(config.tracking_uri, config.model_name, config.control_dir)
                )
                await run_in_threadpool(app.state.models.reload)
                metrics.set_model(app.state.models.current().version)
            except Exception as exc:
                logger.warning("model_unavailable", extra={"error_type": type(exc).__name__})
        logger.info("application_started")
        try:
            yield
        finally:
            if engine is None:
                app.state.engine.dispose()
            logger.info("application_stopped")

    app = FastAPI(
        title="Production ML Platform",
        version=__version__,
        lifespan=lifespan,
        docs_url=None,
        swagger_ui_oauth2_redirect_url=None,
        redoc_url=None,
        openapi_url=None if config.environment == "production" else "/openapi.json",
    )
    app.state.config, app.state.metrics = config, metrics
    app.include_router(router)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        errors = [{"location": list(e["loc"]), "type": e["type"]} for e in exc.errors()]
        request.state.missing_features = [
            str(e["loc"][-1])
            for e in exc.errors()
            if e["type"] == "missing" and e["loc"][-1] in FEATURES
        ]
        return JSONResponse(status_code=422, content={"detail": errors})

    app.add_middleware(
        CORSMiddleware,
        allow_origins=config.cors_origins,
        allow_methods=["GET", "POST"],
        allow_headers=["X-Request-ID", "X-API-Key", "X-Admin-Key", "X-Data-Cohort", "Content-Type"],
    )

    @app.middleware("http")
    async def observe(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        supplied_id = request.headers.get("X-Request-ID", "")
        request_id = supplied_id if REQUEST_ID.fullmatch(supplied_id) else uuid4().hex
        request.state.request_id = request_id
        request.state.cohort = "live"
        request.state.missing_features = []
        start = perf_counter()
        try:
            response = await call_next(request)
        except Exception as exc:
            logger.error(
                "request_failed",
                extra={
                    "request_id": request_id,
                    "error_type": type(exc).__name__,
                },
            )
            response = JSONResponse(
                status_code=500,
                content={"detail": "Internal server error", "request_id": request_id},
            )
        elapsed = perf_counter() - start
        route = request.scope.get("route")
        endpoint = getattr(route, "path", "unmatched")
        metrics.requests.labels(endpoint, str(response.status_code)).inc()
        metrics.latency.labels(endpoint).observe(elapsed)
        if endpoint in ("/api/v1/predict", "/api/v1/explain"):

            def record_event() -> None:
                with Session(request.app.state.engine) as session, session.begin():
                    session.add(
                        ApiEvent(
                            event_id=uuid4().hex,
                            created_at=datetime.now(UTC),
                            endpoint=endpoint,
                            status=response.status_code,
                            latency_ms=elapsed * 1000,
                            cohort=request.state.cohort,
                            missing_features=request.state.missing_features,
                        )
                    )

            try:
                await run_in_threadpool(record_event)
            except SQLAlchemyError:
                logger.warning("operational_event_storage_unavailable")
        logger.info(
            "request_completed",
            extra={
                "request_id": request_id,
                "endpoint": endpoint,
                "status": response.status_code,
                "latency_ms": round(elapsed * 1000, 3),
            },
        )
        response.headers["X-Request-ID"] = request_id
        return response

    @app.get("/health", tags=["operations"])
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "ml-api", "version": __version__}

    @app.get("/ready", tags=["operations"])
    def ready(request: Request) -> JSONResponse:
        try:
            check_database(request.app.state.engine)
            if config.inference_enabled:
                with request.app.state.engine.connect() as connection:
                    connection.execute(select(Prediction.prediction_id).limit(0))
        except SQLAlchemyError as exc:
            logger.warning(
                "database_unavailable",
                extra={
                    "request_id": request.state.request_id,
                    "error_type": type(exc).__name__,
                },
            )
            return JSONResponse(
                status_code=503,
                content={"status": "not_ready", "checks": {"database": "unavailable"}},
            )
        checks = {"database": "ok"}
        if config.inference_enabled:
            try:
                if request.app.state.models is None:
                    raise RuntimeError("Model unavailable")
                checks["model"] = request.app.state.models.current().version
            except RuntimeError:
                return JSONResponse(
                    status_code=503,
                    content={"status": "not_ready", "checks": {**checks, "model": "unavailable"}},
                )
        return JSONResponse(content={"status": "ready", "checks": checks})

    @app.get("/metrics", include_in_schema=False)
    def prometheus_metrics() -> Response:
        return Response(
            content=generate_latest(metrics.registry), headers={"Content-Type": CONTENT_TYPE_LATEST}
        )

    if config.environment != "production":

        @app.get("/docs", include_in_schema=False)
        def documentation() -> HTMLResponse:
            response = get_swagger_ui_html(
                openapi_url="/openapi.json", title="Production ML Platform · API"
            )
            response.headers["Content-Security-Policy"] = content_policy(
                bytes(response.body).decode(), documentation=True
            )
            return response

    def security_schema() -> dict[str, Any]:
        if app.openapi_schema is not None:
            return app.openapi_schema
        schema = get_openapi(title=app.title, version=app.version, routes=app.routes)
        schema.setdefault("components", {})["securitySchemes"] = {
            "ApiKey": {"type": "apiKey", "in": "header", "name": "X-API-Key"},
            "AdminKey": {"type": "apiKey", "in": "header", "name": "X-Admin-Key"},
        }
        if config.auth_enabled:
            schema["security"] = [{"ApiKey": []}, {"AdminKey": []}]
            for path in ("/health", "/ready"):
                schema["paths"][path]["get"]["security"] = []
            for path in ("/api/v1/labels", "/api/v1/models/reload", "/api/v1/monitoring/snapshot"):
                schema["paths"][path]["post"]["security"] = [{"AdminKey": []}]
        app.openapi_schema = schema
        return schema

    app.openapi = security_schema  # type: ignore[method-assign]
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=config.allowed_hosts, www_redirect=False
    )
    app.add_middleware(SecurityMiddleware, settings=config, metrics=metrics)
    return app
