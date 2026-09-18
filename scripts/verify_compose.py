"""Run after `docker compose up --build -d --wait` (stdlib only)."""

import json
import os
from pathlib import Path
from urllib.request import Request, urlopen

# This verifier remains stdlib-only for bootstrap CI. Key initialization uses simple .env lines.
values = {}
env_path = Path(__file__).resolve().parents[1] / ".env"
if env_path.exists():
    for line in env_path.read_text(encoding="utf-8-sig").splitlines():
        name, separator, value = line.partition("=")
        if separator:
            values[name.strip()] = value.strip().strip("\"'")
key = os.environ.get("ML_API_KEY", values.get("ML_API_KEY", ""))
secret_file = os.environ.get("ML_API_KEY_FILE", values.get("ML_API_KEY_FILE", ""))
if secret_file:
    key = Path(secret_file).read_text().strip()

for endpoint in ("health", "ready", "metrics"):
    request = Request(
        f"http://localhost:8000/{endpoint}", headers={"X-API-Key": key} if key else {}
    )
    with urlopen(request, timeout=10) as response:
        assert response.status == 200
        payload = response.read().decode()
        if endpoint != "metrics":
            print(endpoint, json.loads(payload))
        else:
            assert "http_requests_total" in payload
            print(endpoint, "Prometheus metrics available")

with urlopen("http://localhost:5000/health", timeout=10) as response:
    assert response.status == 200
    print("mlflow", "healthy")
