import json

import httpx
import pytest
from test_milestone9_scripts import load_script


def deployment_transport(request):
    headers = {
        "Strict-Transport-Security": "max-age=31536000; includeSubDomains",
        "X-Content-Type-Options": "nosniff",
    }
    if request.url.path == "/health":
        return httpx.Response(200, json={"status": "ok"}, headers=headers)
    if request.url.path == "/ready":
        return httpx.Response(200, json={"checks": {"model": "1"}}, headers=headers)
    if request.url.path in {"/docs", "/openapi.json"}:
        return httpx.Response(404, headers=headers)
    if request.url.path == "/api/v1/model":
        if request.headers.get("X-API-Key") == "wrong":
            return httpx.Response(401, headers=headers)
        return httpx.Response(
            200, json={"model_name": "credit-default", "model_version": "1"}, headers=headers
        )
    if request.url.path == "/api/v1/predict":
        assert json.loads(request.content)
        return httpx.Response(200, json={"model_version": "1"}, headers=headers)
    raise AssertionError(request.url.path)


def test_verify_aws_deployment_contract(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    examples = tmp_path / "examples"
    examples.mkdir()
    (examples / "predict.json").write_text('{"LIMIT_BAL": 1000}')
    script = load_script("verify_aws_deployment")
    with httpx.Client(
        base_url="https://ml.example.com",
        headers={"X-API-Key": "a" * 32},
        transport=httpx.MockTransport(deployment_transport),
    ) as client:
        result = script.verify(client, "1")
    assert result["status"] == "verified"


def test_verify_aws_deployment_rejects_wrong_model(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    examples = tmp_path / "examples"
    examples.mkdir()
    (examples / "predict.json").write_text("{}")
    script = load_script("verify_aws_deployment")
    with httpx.Client(
        base_url="https://ml.example.com",
        headers={"X-API-Key": "a" * 32},
        transport=httpx.MockTransport(deployment_transport),
    ) as client:
        with pytest.raises(RuntimeError, match="Wrong model"):
            script.verify(client, "2")
