import json
import logging

from fastapi.testclient import TestClient

from ml_platform.api.main import create_app
from ml_platform.observability.logging import JsonFormatter


def test_liveness_without_database(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.headers["X-Request-ID"]


def test_readiness_database_unavailable(client):
    response = client.get("/ready")
    assert response.status_code == 503
    assert response.json()["checks"]["database"] == "unavailable"
    assert "password" not in response.text


def test_request_ids(client):
    assert (
        client.get("/health", headers={"X-Request-ID": "trace_123"}).headers["X-Request-ID"]
        == "trace_123"
    )
    response = client.get("/health", headers={"X-Request-ID": "a" * 1000})
    assert len(response.headers["X-Request-ID"]) == 32


def test_metrics_do_not_use_raw_paths(client):
    client.get("/customer-secret-123")
    metrics = client.get("/metrics")
    assert metrics.status_code == 200
    assert 'endpoint="unmatched"' in metrics.text
    assert "customer-secret-123" not in metrics.text


def test_unhandled_error_is_sanitized(settings):
    app = create_app(settings)

    @app.get("/fail")
    def fail():
        raise RuntimeError("secret-password")

    with TestClient(app) as client:
        response = client.get("/fail")
        assert response.status_code == 500
        assert "secret-password" not in response.text
        assert response.json()["request_id"] == response.headers["X-Request-ID"]


def test_production_docs_disabled(settings):
    settings = settings.model_copy(
        update={"environment": "production", "db_sslmode": "verify-full"}
    )
    with TestClient(create_app(settings)) as client:
        assert client.get("/docs").status_code == 404
        assert client.get("/openapi.json").status_code == 404


def test_logs_allowlist_fields():
    record = logging.LogRecord("test", logging.INFO, "", 1, "request_completed", (), None)
    record.password = "never-log-this"
    record.request_id = "trace"
    output = JsonFormatter().format(record)
    assert json.loads(output)["request_id"] == "trace"
    assert "never-log-this" not in output


def test_default_cors_rejects_external_origin(client):
    response = client.options(
        "/health",
        headers={"Origin": "https://external.example", "Access-Control-Request-Method": "GET"},
    )
    assert response.status_code == 400
    assert "access-control-allow-origin" not in response.headers
