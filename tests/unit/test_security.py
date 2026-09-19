import asyncio
import base64
import hashlib
import re
from pathlib import Path

import pytest
from fastapi import Request
from fastapi.testclient import TestClient
from pydantic import ValidationError

from ml_platform.api.main import create_app
from ml_platform.api.security import SecurityMiddleware, WindowLimiter
from ml_platform.core.config import Settings
from ml_platform.observability.telemetry import Metrics

API_KEY, ADMIN_KEY = "client-" + "a" * 32, "admin-" + "b" * 32


@pytest.fixture
def secured_settings(settings):
    return Settings(
        **{
            **settings.model_dump(),
            "auth_enabled": True,
            "api_key": API_KEY,
            "admin_key": ADMIN_KEY,
        }
    )


@pytest.fixture
def secured_client(secured_settings):
    app = create_app(secured_settings)

    @app.post("/api/v1/probe")
    async def probe(request: Request):
        return {"received": len(await request.body())}

    with TestClient(app) as client:
        yield client


def test_private_routes_require_key_before_validation_or_model_loading(secured_client):
    for path in ("/api/v1/predict", "/api/v1/explain", "/api/v1/labels"):
        response = secured_client.post(path, content=b"not even JSON")
        assert response.status_code == 401
    for path in ("/metrics", "/api/v1/model", "/api/v1/monitoring", "/api/v1/monitoring/history"):
        assert secured_client.get(path).status_code == 401
    for path in ("/health", "/api/v1/dashboard", "/docs", "/openapi.json"):
        assert secured_client.get(path).status_code == 200
    assert secured_client.get("/ready").status_code == 503  # DB unavailable, not auth-blocked.


def test_client_and_admin_roles(secured_client):
    api, admin = {"X-API-Key": API_KEY}, {"X-Admin-Key": ADMIN_KEY}
    assert secured_client.get("/metrics", headers=api).status_code == 200
    assert secured_client.get("/metrics", headers=admin).status_code == 200
    assert secured_client.post("/api/v1/probe", json={}, headers=api).status_code == 200
    for path in ("/api/v1/labels", "/api/v1/models/reload", "/api/v1/monitoring/snapshot"):
        assert secured_client.post(path, json={}, headers=api).status_code == 403
    assert secured_client.post("/api/v1/models/reload", headers=admin).status_code == 503
    response = secured_client.get("/metrics", headers={"X-Admin-Key": API_KEY})
    assert response.status_code == 401
    assert API_KEY not in response.text and ADMIN_KEY not in response.text
    schema = secured_client.get("/openapi.json").json()
    assert schema["paths"]["/api/v1/labels"]["post"]["security"] == [{"AdminKey": []}]


def test_duplicate_keys_and_path_aliases_cannot_bypass_authorization(secured_client):
    assert (
        secured_client.get(
            "/metrics", headers=[("X-API-Key", API_KEY), ("X-API-Key", API_KEY)]
        ).status_code
        == 400
    )
    for path in ("/api/v1/labels/", "/api/v1/%6cabels", "/api/v1/models/reload/"):
        assert secured_client.post(path, headers={"X-API-Key": API_KEY}).status_code == 403


def test_ingress_limits_and_security_headers(secured_client):
    headers = {"X-API-Key": API_KEY, "Content-Type": "application/json"}
    for changes, body, status in (
        ({"Content-Length": "1048577"}, b"{}", 413),
        ({"Content-Length": "-1"}, b"{}", 400),
        ({"Content-Encoding": "gzip"}, b"{}", 415),
        ({"Content-Type": "text/plain"}, b"{}", 415),
        ({"Content-Length": "1"}, b"{}", 400),
    ):
        response = secured_client.post(
            "/api/v1/probe", headers={**headers, **changes}, content=body
        )
        assert response.status_code == status
        assert response.headers["X-Content-Type-Options"] == "nosniff"
        assert response.headers["Cache-Control"] == "no-store"
        assert response.headers["X-Request-ID"]
    assert secured_client.get("/health", headers={"Host": "evil.example"}).status_code == 400


def test_production_adds_hsts(secured_settings):
    secured_settings.environment = "production"
    with TestClient(create_app(secured_settings)) as client:
        assert client.get("/health").headers["Strict-Transport-Security"] == (
            "max-age=31536000; includeSubDomains"
        )


def test_rate_limit_applies_to_shared_key_and_cannot_use_forwarded_ip_to_reset(secured_settings):
    secured_settings.rate_limit_per_minute = 2
    secured_settings.anonymous_rate_limit_per_minute = 2
    with TestClient(create_app(secured_settings)) as client:
        for i in range(2):
            assert client.get("/metrics", headers={"X-API-Key": API_KEY}).status_code == 200
            assert (
                client.get("/metrics", headers={"X-Forwarded-For": f"10.0.0.{i}"}).status_code
                == 401
            )
        for headers in ({"X-API-Key": API_KEY}, {"X-Forwarded-For": "10.0.0.99"}):
            response = client.get("/metrics", headers=headers)
            assert response.status_code == 429
            assert 1 <= int(response.headers["Retry-After"]) <= 60
        # Probes and the independent admin budget are still available.
        assert client.get("/health").status_code == 200
        assert client.get("/metrics", headers={"X-Admin-Key": ADMIN_KEY}).status_code == 200


def test_limiter_expiry_and_memory_bound():
    limiter = WindowLimiter(capacity=2)
    assert limiter.allow("a", 1, 0)[0]
    assert limiter.allow("b", 1, 0)[0]
    assert not limiter.allow("a", 1, 59.5)[0]
    assert not limiter.allow("c", 1, 59.5)[0]
    assert len(limiter.windows) == 2
    assert limiter.allow("c", 1, 60)[0]
    assert len(limiter.windows) == 1


@pytest.mark.parametrize("mode,expected", [("chunks", 413), ("timeout", 408), ("disconnect", None)])
def test_streamed_body_is_bounded_before_downstream(secured_settings, mode, expected):
    secured_settings.max_request_bytes = 1024
    secured_settings.request_body_timeout_seconds = 0.01
    sent, downstream = [], []

    async def run():
        async def app(scope, receive, send):
            downstream.append(True)

        async def receive():
            if mode == "timeout":
                await asyncio.sleep(1)
            if mode == "disconnect":
                return {"type": "http.disconnect"}
            return {"type": "http.request", "body": b"x" * 600, "more_body": True}

        async def send(message):
            sent.append(message)

        scope = {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/predict",
            "headers": [(b"x-api-key", API_KEY.encode())],
            "client": ("test", 1),
        }
        await SecurityMiddleware(app, secured_settings, Metrics())(scope, receive, send)

    asyncio.run(run())
    assert not downstream
    assert [r["status"] for r in sent if r["type"] == "http.response.start"] == (
        [] if expected is None else [expected]
    )


def test_dashboard_and_docs_inline_scripts_have_exact_csp_hashes(secured_client):
    for path in ("/api/v1/dashboard", "/docs"):
        response = secured_client.get(path)
        policy = response.headers["Content-Security-Policy"]
        assert "unsafe-inline" not in policy and "frame-ancestors 'none'" in policy
        for body in re.findall(r"<script[^>]*>(.*?)</script>", response.text, re.S):
            if body.strip():
                digest = base64.b64encode(hashlib.sha256(body.encode()).digest()).decode()
                assert "'sha256-" + digest + "'" in policy
    assert 'id="api-key"' in secured_client.get("/api/v1/dashboard").text


def test_cors_preflight_has_explicit_api_key_support(secured_settings):
    secured_settings.cors_origins = ["http://localhost:3000"]
    with TestClient(create_app(secured_settings)) as client:
        response = client.options(
            "/api/v1/predict",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "X-API-Key, Content-Type",
            },
        )
        assert response.status_code == 200
        assert response.headers["Access-Control-Allow-Origin"] == "http://localhost:3000"
        rejected = client.get("/metrics", headers={"Origin": "http://localhost:3000"})
        assert rejected.status_code == 401
        assert rejected.headers["Access-Control-Allow-Origin"] == "http://localhost:3000"


@pytest.mark.parametrize(
    "changes",
    [
        {"api_key": "short"},
        {"admin_key": API_KEY},
        {"allowed_hosts": ["*"]},
        {"cors_origins": ["https://*.example.com"]},
        {"cors_origins": ["https://example.com/path"]},
        {"environment": "production", "db_sslmode": "verify-full", "auth_enabled": False},
    ],
)
def test_security_configuration_fails_closed(secured_settings, changes):
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **{**secured_settings.model_dump(), **changes})


def test_secret_files_and_credential_redaction(tmp_path: Path, monkeypatch):
    for name in ("ML_DB_PASSWORD", "ML_API_KEY", "ML_ADMIN_KEY"):
        monkeypatch.delenv(name, raising=False)
        monkeypatch.delenv(name + "_FILE", raising=False)
    db, api, admin = [tmp_path / name for name in ("db", "api", "admin")]
    for path, value in ((db, "db-secret-" * 4), (api, API_KEY), (admin, ADMIN_KEY)):
        path.write_text(value + "\n")
    settings = Settings(
        _env_file=None,
        db_password_file=db,
        api_key_file=api,
        admin_key_file=admin,
        auth_enabled=True,
    )
    assert settings.api_key.get_secret_value() == API_KEY
    assert API_KEY not in repr(settings)
    with pytest.raises(ValidationError) as error:
        Settings(
            _env_file=None,
            db_password="db-secret-" * 4,
            api_key=API_KEY,
            api_key_file=api,
            admin_key=ADMIN_KEY,
            auth_enabled=True,
        )
    assert API_KEY not in str(error.value)
