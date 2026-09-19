"""Verify the externally visible Milestone 10 AWS deployment without changing it."""

import argparse
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from ml_platform.core.io import write_json


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def verify(client: httpx.Client, expected_model_version: str) -> dict[str, object]:
    health = client.get("/health")
    require(health.status_code == 200, "Public health endpoint is unavailable")
    require(health.json().get("status") == "ok", "Health response is invalid")
    require(
        health.headers.get("Strict-Transport-Security") == "max-age=31536000; includeSubDomains",
        "HSTS is missing from the production response",
    )
    require(health.headers.get("X-Content-Type-Options") == "nosniff", "Security headers missing")

    ready = client.get("/ready")
    require(ready.status_code == 200, "Deployment is not ready")
    require(ready.json().get("checks", {}).get("model") == expected_model_version, "Wrong model")

    for path in ("/docs", "/openapi.json"):
        require(client.get(path).status_code == 404, f"Production exposed {path}")
    require(
        client.get("/api/v1/model", headers={"X-API-Key": "wrong"}).status_code == 401,
        "Invalid API key was accepted",
    )

    model = client.get("/api/v1/model")
    require(model.status_code == 200, "Authenticated model endpoint is unavailable")
    model_data = model.json()
    require(str(model_data.get("model_version")) == expected_model_version, "Wrong model version")

    payload = json.loads(Path("examples/predict.json").read_text(encoding="utf-8"))
    prediction = client.post("/api/v1/predict", json=payload)
    require(prediction.status_code == 200, "Authenticated prediction failed")
    require(
        str(prediction.json().get("model_version")) == expected_model_version,
        "Prediction used the wrong model",
    )
    return {
        "milestone": 10,
        "status": "verified",
        "model_name": model_data.get("model_name"),
        "model_version": expected_model_version,
        "https": True,
        "hsts": True,
        "production_docs_disabled": True,
        "authentication_enforced": True,
        "prediction_verified": True,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--api-key-file", type=Path)
    parser.add_argument("--expected-model-version", default="1")
    parser.add_argument(
        "--output", type=Path, default=Path("reports/milestone-10-verification.json")
    )
    args = parser.parse_args()

    parsed = urlsplit(args.base_url)
    require(parsed.scheme == "https" and bool(parsed.hostname), "--base-url must be HTTPS")
    require(
        not parsed.path.rstrip("/") and not parsed.query and not parsed.fragment,
        "--base-url must not include a path, query or fragment",
    )
    if args.api_key_file:
        api_key = args.api_key_file.read_text(encoding="utf-8").strip()
    else:
        api_key = os.environ.get("ML_API_KEY", "")
    require(len(api_key) >= 32, "Set ML_API_KEY or pass --api-key-file")

    with httpx.Client(
        base_url=args.base_url.rstrip("/"),
        headers={"X-API-Key": api_key},
        timeout=60,
        follow_redirects=False,
        trust_env=False,
    ) as client:
        result = verify(client, args.expected_model_version)
    write_json(args.output, result)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
