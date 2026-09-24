"""Collect publishable aggregates from the existing local API; optionally run its benchmark."""

import argparse
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
URL = "http://127.0.0.1:8000"


def require(condition, message):
    if not condition:
        raise ValueError(message)


def pick(value, keys):
    return {key: value[key] for key in keys if key in value}


def monitoring_summary(report):
    """Publish explicit aggregate fields only, never an unfiltered API response."""
    result = pick(report, ("model_version", "cohort", "prediction_count", "created_at"))
    result["window"] = pick(report["window"], ("start", "end", "hours", "labels_as_of"))
    result["operational"] = pick(
        report["operational"], ("requests", "error_rate", "server_error_rate")
    )
    result["operational"]["latency_ms"] = pick(
        report["operational"]["latency_ms"], ("p50", "p95", "p99")
    )
    result["drift"] = pick(report["drift"], ("status", "drift_trigger"))
    result["performance"] = pick(report["performance"], ("status", "labeled", "coverage", "ece"))
    result["performance"]["support"] = pick(report["performance"].get("support", {}), ("0", "1"))
    return result


def benchmark_summary(report, expected_version):
    if report is None:
        return None
    require(
        report["errors"] == 0 and report["successes"] == report["requests"] > 0,
        "Benchmark has failed or incomplete requests; do not publish it as a successful run.",
    )
    require(
        report["model_versions"] == [expected_version],
        "Benchmark did not use exactly the expected model version.",
    )
    result = pick(
        report,
        (
            "requests",
            "warmup_requests",
            "concurrency",
            "successes",
            "errors",
            "duration_seconds",
            "throughput_rps",
            "model_versions",
        ),
    )
    result["error_rate"] = report["errors"] / report["requests"]
    result["latency_ms"] = pick(report["latency_ms"], ("p50", "p95", "p99"))
    result["client_environment"] = pick(
        report["client_environment"], ("platform", "python", "processor", "logical_cpus")
    )
    result["scope"] = (
        "Local loopback HTTP; backend and server hardware require operator confirmation."
    )
    return result


def collect(client, api_key, expected_version="1", measurement=None):
    headers = {"X-API-Key": api_key}

    def get(path):
        response = client.get(path, headers=headers)
        require(response.status_code == 200, f"{path} returned HTTP {response.status_code}.")
        return response.json()

    require(get("/health")["status"] == "ok", "API health is not OK.")
    require(get("/ready")["status"] == "ready", "API is not ready.")
    require(
        client.get("/api/v1/model").status_code == 401,
        "Anonymous access was not denied with HTTP 401; check authentication or quota.",
    )
    model = pick(
        get("/api/v1/model"), ("model_name", "model_version", "run_id", "threshold", "schema_hash")
    )
    require(model["model_version"] == expected_version, "Unexpected serving model version.")
    monitoring = {}
    for cohort in ("live", "verification", "benchmark"):
        report = get(f"/api/v1/monitoring?cohort={cohort}&hours=24")
        require(report["model_version"] == expected_version, "Monitoring model version changed.")
        require(report["cohort"] == cohort, "Monitoring returned a different cohort.")
        monitoring[cohort] = monitoring_summary(report)
    final_model = get("/api/v1/model")
    require(
        all(final_model.get(key) == value for key, value in model.items()),
        "Serving identity changed during collection; repeat against a stable deployment.",
    )
    return {
        "schema_version": 1,
        "captured_at": datetime.now(UTC).isoformat(),
        "scope": "Local demonstration; no AWS verification or real-customer performance claim.",
        "checks": {"health": True, "ready": True, "anonymous_denied": True},
        "model": model,
        "benchmark": benchmark_summary(measurement, expected_version),
        "monitoring": monitoring,
    }


def documents(evidence):
    prefix = (
        f"Captured: {evidence['captured_at']}\n\n"
        f"Model version: {evidence['model']['model_version']}; "
        f"MLflow run: `{evidence['model']['run_id']}`.\n\n"
    )
    report = evidence["benchmark"]
    benchmark = "# Current local benchmark\n\n" + prefix
    if report is None:
        benchmark += "Benchmark not run in this capture. No older result was substituted.\n"
    else:
        benchmark += (
            f"{report['requests']} timed requests; concurrency {report['concurrency']}; "
            f"{report['warmup_requests']} excluded warmups.\n\n"
            "| Metric | Measured value |\n|---|---:|\n"
            f"| Successes | {report['successes']} |\n"
            f"| Errors | {report['errors']} |\n"
            f"| Throughput | {report['throughput_rps']:.2f} requests/s |\n"
        )
        for key in ("p50", "p95", "p99"):
            benchmark += f"| {key.upper()} | {report['latency_ms'][key]:.2f} ms |\n"
        benchmark += "\nClient environment:\n\n```json\n"
        benchmark += json.dumps(report["client_environment"], indent=2) + "\n```\n"
    benchmark += (
        "\nScope: warm local loopback HTTP with repeated public example inputs. "
        "Per-request timing excludes semaphore queue wait. Server hardware, database backend "
        "and Docker resource allocation need operator confirmation. This is not a saturation "
        "study, cloud result or SLA.\n"
    )
    monitoring = "# Current local monitoring\n\n" + prefix
    monitoring += (
        "Window: 24 hours per cohort; earlier traffic in the window can be included.\n\n"
        "| Cohort | Predictions | Drift | Labels | Coverage | Performance |\n"
        "|---|---:|---|---:|---:|---|\n"
    )
    for name, row in evidence["monitoring"].items():
        performance = row["performance"]
        monitoring += (
            f"| {name} | {row['prediction_count']} | {row['drift']['status']} | "
            f"{performance['labeled']} | {performance['coverage']:.1%} | "
            f"{performance['status']} |\n"
        )
    monitoring += (
        "\nInsufficient evidence is not proof of model quality. Repeated benchmark inputs "
        "can cause drift and do not represent a real population. No labels were created by "
        "this collector. Review source timestamps in evidence.json; monitoring windows differ "
        "from the benchmark timing interval. No AWS monitoring result is claimed.\n"
    )
    return {"benchmark.md": benchmark, "monitoring.md": monitoring}


def git_identity():
    try:
        commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, stderr=subprocess.DEVNULL, text=True
        ).strip()
        dirty = bool(
            subprocess.check_output(
                ["git", "status", "--porcelain"], cwd=ROOT, stderr=subprocess.DEVNULL
            )
        )
        return {"commit": commit, "worktree_dirty": dirty}
    except (OSError, subprocess.CalledProcessError):
        return {"commit": None, "worktree_dirty": None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--benchmark", action="store_true", help="Send 210 tagged demo requests.")
    parser.add_argument("--expected-model-version", default="1")
    parser.add_argument("--output", type=Path, default=ROOT / "reports/portfolio")
    args = parser.parse_args()
    # Delayed imports keep aggregate/redaction tests independent of an installed application.
    import httpx

    from ml_platform.core.config import Settings

    settings = Settings()
    require(settings.auth_enabled and settings.api_key is not None, "Local API key is required.")
    api_key = settings.api_key.get_secret_value()
    args.output.mkdir(parents=True, exist_ok=True)
    with httpx.Client(base_url=URL, timeout=60, trust_env=False, follow_redirects=False) as client:
        # Check readiness/auth/model before sending benchmark traffic.
        initial = collect(client, api_key, args.expected_model_version)
        measurement = None
        if args.benchmark:
            require(
                settings.admin_key is not None, "An admin key is required for benchmark traffic."
            )
            benchmark_file = args.output / "api-benchmark-raw.json"
            subprocess.run(
                [
                    sys.executable,
                    str(ROOT / "scripts/benchmark_api.py"),
                    "--url",
                    URL,
                    "--requests",
                    "200",
                    "--concurrency",
                    "4",
                    "--output",
                    str(benchmark_file.resolve()),
                ],
                cwd=ROOT,
                check=True,
                stdout=subprocess.DEVNULL,
            )
            measurement = json.loads(benchmark_file.read_text(encoding="utf-8"))
        evidence = collect(client, api_key, args.expected_model_version, measurement)
        require(evidence["model"] == initial["model"], "Serving identity changed across benchmark.")
    evidence["source"] = git_identity()
    (args.output / "evidence.json").write_text(
        json.dumps(evidence, indent=2, allow_nan=False) + "\n", encoding="utf-8", newline="\n"
    )
    for name, content in documents(evidence).items():
        (args.output / name).write_text(content, encoding="utf-8", newline="\n")
    print(f"Local evidence collected at {args.output.resolve()}")
    print("Review evidence.json, benchmark.md and monitoring.md; this script does not verify AWS.")


if __name__ == "__main__":
    main()
