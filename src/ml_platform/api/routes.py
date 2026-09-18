from datetime import datetime
from time import perf_counter
from typing import Annotated, Any, cast

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import AwareDatetime, BaseModel, ConfigDict, Field
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from ml_platform.api.dashboard import DASHBOARD
from ml_platform.api.security import content_policy, matches
from ml_platform.db.models import MonitoringReport
from ml_platform.inference.schema import PredictionInput
from ml_platform.inference.service import Snapshot
from ml_platform.inference.storage import COHORTS, attach_labels, log_predictions
from ml_platform.monitoring.report import build_report, save_report

router = APIRouter(prefix="/api/v1")


def admin(request: Request, x_admin_key: str = Header(default="")) -> None:
    expected = request.app.state.config.admin_key
    if not matches(expected, x_admin_key):
        raise HTTPException(403, "A valid X-Admin-Key is required")


def snapshot(request: Request) -> Snapshot:
    service = request.app.state.models
    if service is None:
        raise HTTPException(503, "Inference is not configured")
    try:
        return cast(Snapshot, service.current())
    except RuntimeError as exc:
        raise HTTPException(503, "No verified model is available") from exc


def cohort(
    request: Request,
    x_data_cohort: str = Header(default="live"),
    x_admin_key: str = Header(default=""),
) -> str:
    if x_data_cohort not in COHORTS:
        raise HTTPException(422, "Unknown observation cohort")
    if x_data_cohort != "live":
        admin(request, x_admin_key)
    request.state.cohort = x_data_cohort
    return x_data_cohort


def predict(
    payload: PredictionInput,
    request: Request,
    model: Snapshot,
    selected_cohort: str,
    explain: bool = False,
) -> dict[str, Any]:
    start = perf_counter()
    X = payload.frame()
    probabilities = model.score(X)
    explanation = model.explain(X) if explain else None
    try:
        result = log_predictions(
            request.app.state.engine,
            model,
            X,
            probabilities,
            request.state.request_id,
            request.app.state.config.model_name,
            selected_cohort,
            (perf_counter() - start) * 1000,
        )[0]
    except SQLAlchemyError as exc:
        raise HTTPException(503, "Prediction storage is unavailable") from exc
    metrics = request.app.state.metrics
    metrics.predictions.labels(model.version, str(result["prediction"])).inc()
    metrics.scores.observe(result["risk_score"])
    if explanation is not None:
        result["explanation"] = explanation
    return result


@router.post("/predict", tags=["inference"])
def prediction(
    payload: PredictionInput,
    request: Request,
    model: Annotated[Snapshot, Depends(snapshot)],
    selected_cohort: Annotated[str, Depends(cohort)],
) -> dict[str, Any]:
    return predict(payload, request, model, selected_cohort)


@router.post("/explain", tags=["inference"])
def explanation(
    payload: PredictionInput,
    request: Request,
    model: Annotated[Snapshot, Depends(snapshot)],
    selected_cohort: Annotated[str, Depends(cohort)],
) -> dict[str, Any]:
    return predict(payload, request, model, selected_cohort, explain=True)


class Label(BaseModel):
    model_config = ConfigDict(extra="forbid")
    prediction_id: str = Field(pattern=r"^[a-f0-9]{32}$")
    actual_label: Annotated[int, Field(strict=True, ge=0, le=1)]
    observed_at: AwareDatetime


class Labels(BaseModel):
    model_config = ConfigDict(extra="forbid")
    labels: list[Label] = Field(min_length=1, max_length=1000)


@router.post("/labels", dependencies=[Depends(admin)], tags=["operations"])
def labels(payload: Labels, request: Request) -> dict[str, int]:
    try:
        return attach_labels(request.app.state.engine, [r.model_dump() for r in payload.labels])
    except LookupError as exc:
        raise HTTPException(404, str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc
    except SQLAlchemyError as exc:
        raise HTTPException(503, "Label storage unavailable") from exc


@router.post("/models/reload", dependencies=[Depends(admin)], tags=["operations"])
def reload_model(request: Request) -> dict[str, str]:
    if request.app.state.models is None:
        raise HTTPException(503, "Inference is not configured")
    try:
        loaded = request.app.state.models.reload()
        request.app.state.metrics.set_model(loaded.version)
        return {"status": "loaded", "model_version": loaded.version}
    except Exception as exc:
        raise HTTPException(
            503, "Model reload failed; inspect service logs and registry state"
        ) from exc


@router.get("/model", tags=["operations"])
def model_info(request: Request, model: Annotated[Snapshot, Depends(snapshot)]) -> dict[str, Any]:
    return {
        "model_name": request.app.state.config.model_name,
        "model_version": model.version,
        "threshold": model.evidence["threshold"],
        "run_id": model.evidence["run_id"],
        "schema_hash": model.evidence["schema_hash"],
    }


@router.get("/monitoring", tags=["monitoring"])
def monitoring(
    request: Request,
    model: Annotated[Snapshot, Depends(snapshot)],
    cohort: str = "live",
    hours: int = Query(default=24, ge=1, le=720),
    end: datetime | None = None,
) -> dict[str, Any]:
    if end is not None and end.tzinfo is None:
        raise HTTPException(422, "Window end must include a timezone")
    try:
        return build_report(
            request.app.state.engine, model, request.app.state.config.model_name, cohort, hours, end
        )
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    except SQLAlchemyError as exc:
        raise HTTPException(503, "Monitoring storage unavailable") from exc


@router.post("/monitoring/snapshot", dependencies=[Depends(admin)], tags=["monitoring"])
def monitoring_snapshot(
    request: Request,
    model: Annotated[Snapshot, Depends(snapshot)],
    cohort: str = "live",
    hours: int = Query(default=24, ge=1, le=720),
) -> dict[str, Any]:
    report = monitoring(request, model, cohort, hours, None)
    save_report(request.app.state.engine, report)
    return report


@router.get("/monitoring/history", tags=["monitoring"])
def history(request: Request, cohort: str = "live") -> list[dict[str, Any]]:
    if cohort not in COHORTS:
        raise HTTPException(422, "Unknown cohort")
    with Session(request.app.state.engine) as session:
        rows = session.scalars(
            select(MonitoringReport)
            .where(
                MonitoringReport.model_name == request.app.state.config.model_name,
                MonitoringReport.cohort == cohort,
            )
            .order_by(MonitoringReport.created_at.desc())
            .limit(20)
        )
        return [r.report for r in rows]


@router.get("/dashboard", response_class=HTMLResponse, include_in_schema=False)
def dashboard() -> HTMLResponse:
    return HTMLResponse(DASHBOARD, headers={"Content-Security-Policy": content_policy(DASHBOARD)})
