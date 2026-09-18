"""Read live API/container security settings without changing the serving model."""

import argparse
import json
import os
import subprocess
from pathlib import Path

import httpx

from ml_platform.core.config import Settings
from ml_platform.core.io import write_json


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def container_checks() -> dict[str, bool]:
    container = subprocess.check_output(
        ["docker", "compose", "ps", "-q", "ml-api"], text=True
    ).strip()
    require(bool(container), "API container was not found")
    # Never print inspect output: Config.Env contains secrets.
    detail = json.loads(subprocess.check_output(["docker", "inspect", container], text=True))[0]
    host = detail["HostConfig"]
    checks = {
        "non_root": detail["Config"]["User"] in {"appuser", "10001", "10001:10001"},
        "read_only_root": host["ReadonlyRootfs"],
        "all_capabilities_dropped": "ALL" in [c.upper() for c in host.get("CapDrop", [])],
        "no_new_privileges": bool(
            {"no-new-privileges", "no-new-privileges:true", "no-new-privileges=true"}.intersection(
                host.get("SecurityOpt") or []
            )
        ),
        "loopback_binding": bool(host["PortBindings"])
        and all(
            port["HostIp"] == "127.0.0.1"
            for ports in host["PortBindings"].values()
            for port in (ports or [])
        ),
        "registry_read_only": any(
            mount["Destination"] == "/registry-control" and not mount["RW"]
            for mount in detail["Mounts"]
        ),
        "proxy_headers_disabled": "--no-proxy-headers" in detail["Config"]["Cmd"],
    }
    require(
        all(checks.values()),
        "Container hardening failed: "
        + ", ".join(name for name, passed in checks.items() if not passed),
    )
    return checks


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bootstrap", action="store_true", help="CI only: no model is loaded yet.")
    parser.add_argument(
        "--check-rate-limit", action="store_true", help="CI only: exhaust anonymous quota."
    )
    args = parser.parse_args()
    os.chdir(Path(__file__).resolve().parents[1])
    settings = Settings()
    require(settings.auth_enabled, "Run upgrade_milestone9.py to enable authentication")
    require(settings.api_key is not None and settings.admin_key is not None, "Keys are required")
    api = {"X-API-Key": settings.api_key.get_secret_value()}
    admin = {"X-Admin-Key": settings.admin_key.get_secret_value()}
    checks = {}
    with httpx.Client(base_url="http://127.0.0.1:8000", timeout=60, trust_env=False) as client:
        for path in ("/health", "/ready", "/api/v1/dashboard"):
            response = client.get(path)
            require(response.status_code == 200, path + " is unavailable")
            require(response.headers.get("X-Content-Type-Options") == "nosniff", "Headers missing")
        require(
            client.get("/health").json()["version"] == "0.4.0", "Old API image is still running"
        )
        for path in ("/metrics", "/api/v1/model", "/api/v1/monitoring"):
            require(client.get(path).status_code == 401, path + " allowed anonymous access")
        require(
            client.post("/api/v1/predict", json={}).status_code == 401, "Prediction auth failed"
        )
        require(
            client.post("/api/v1/models/reload", headers=api).status_code == 403,
            "Role check failed",
        )
        require(
            client.post("/api/v1/labels", json={"labels": []}, headers=admin).status_code == 422,
            "Admin key was not accepted, or invalid labels were accepted",
        )
        for headers in (api, admin):
            require(
                client.get("/metrics", headers=headers).status_code == 200, "Metrics key failed"
            )
        require(
            client.post(
                "/api/v1/predict",
                headers={**api, "Content-Type": "application/json"},
                content=b" " * (settings.max_request_bytes + 1),
            ).status_code
            == 413,
            "Body size limit was not enforced",
        )
        require(
            client.get("/health", headers={"Host": "untrusted.invalid"}).status_code == 400,
            "Host restriction failed",
        )
        model_version = None
        if not args.bootstrap:
            response = client.get("/api/v1/model", headers=api)
            require(response.status_code == 200, "Serving model unavailable")
            model_version = response.json()["model_version"]
            payload = json.loads(Path("examples/predict.json").read_text())
            response = client.post(
                "/api/v1/predict", json=payload, headers={**admin, "X-Data-Cohort": "verification"}
            )
            require(response.status_code == 200, "Authenticated prediction failed")
            require(response.json()["model_version"] == model_version, "Serving version changed")
            response = client.get("/api/v1/monitoring?cohort=verification", headers=api)
            require(response.status_code == 200, "Authenticated monitoring failed")
        checks["anonymous_denied"] = checks["roles_enforced"] = checks["body_limit_enforced"] = True
        checks["rate_limit_live"] = "not run; covered by unit tests"
        if args.check_rate_limit:
            for _ in range(settings.anonymous_rate_limit_per_minute + 1):
                response = client.get("/metrics")
                if response.status_code == 429:
                    require(int(response.headers["Retry-After"]) > 0, "Retry-After missing")
                    break
                require(response.status_code == 401, "Unexpected response during rate-limit check")
            else:
                raise RuntimeError("Rate limiter did not reject excess anonymous traffic")
            checks["rate_limit_live"] = "passed"
    result = {
        "milestone": 9,
        "api_checks": checks,
        "container_checks": container_checks(),
        "model_version": model_version,
        "bootstrap": args.bootstrap,
        "remote_security_scans": "Run the Security and Docker jobs in GitHub Actions",
    }
    write_json(Path("reports/milestone-9-verification.json"), result)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
