"""Verify Milestones 6–8 against the user's actual API, MLflow and PostgreSQL services."""

import argparse
import asyncio
import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import httpx
import numpy as np
from benchmark_api import benchmark

from ml_platform.core.config import Settings
from ml_platform.core.io import read_json, write_json
from ml_platform.core.training_config import load_config
from ml_platform.data.splitting import load_dataset
from ml_platform.data.validation import FEATURES, model_features
from ml_platform.db.session import create_db_engine
from ml_platform.inference.service import ModelService
from ml_platform.models.registry import RegistryReader
from ml_platform.monitoring.simulation import simulate


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--tracking-uri", default="http://127.0.0.1:5000")
    parser.add_argument("--skip-software-checks", action="store_true")
    args = parser.parse_args()
    os.chdir(Path(__file__).resolve().parents[1])
    os.environ["PATH"] = str(Path(sys.executable).parent) + os.pathsep + os.environ["PATH"]
    os.environ["TEST_DATABASE"] = "1"
    os.environ["MLFLOW_ENABLE_ARTIFACTS_PROGRESS_BAR"] = "false"
    if not args.skip_software_checks:
        for command in (
            ["ruff", "check", "."],
            ["ruff", "format", "--check", "."],
            ["mypy"],
            ["pytest", "--cov=ml_platform", "--cov-report=term-missing"],
        ):
            subprocess.run([sys.executable, "-m", *command], check=True)
    settings = Settings()
    if settings.admin_key is None:
        raise SystemExit("Run upgrade_batch2.py to initialize the local admin key")
    config = load_config(Path("configs/training.yaml"))
    reader = RegistryReader(args.tracking_uri, config.model_name, Path(".state/registry"))
    service = ModelService(reader)
    snapshot = service.reload()
    dataset = Path(read_json(Path("data/processed/latest.json"))["directory"])
    parts, _ = load_dataset(dataset)
    # Historical UCI examples are tagged verification, never represented as new live observations.
    sample = parts["validation"].iloc[:120]
    headers = {
        "X-Admin-Key": settings.admin_key.get_secret_value(),
        "X-Data-Cohort": "verification",
    }
    with httpx.Client(base_url=args.url, headers=headers, timeout=120, trust_env=False) as client:
        client.get("/ready").raise_for_status()
        response = client.post("/api/v1/models/reload")
        response.raise_for_status()
        assert response.json()["model_version"] == snapshot.version
        rows = []
        for _, row in sample.iterrows():
            response = client.post(
                "/api/v1/predict", json={name: int(row[name]) for name in FEATURES}
            )
            response.raise_for_status()
            rows.append(response.json())
        np.testing.assert_allclose(
            [r["risk_score"] for r in rows], snapshot.score(model_features(sample)), atol=1e-12
        )
        payload = {name: int(sample.iloc[0][name]) for name in FEATURES}
        write_json(Path("reports/verified-example.json"), payload)
        explanation = client.post("/api/v1/explain", json=payload)
        explanation.raise_for_status()
        assert (
            abs(
                explanation.json()["explanation"]["reconstructed_risk_score"]
                - rows[0]["risk_score"]
            )
            < 1e-5
        )
        assert client.post("/api/v1/predict", json={}).status_code == 422
        labels = [
            {
                "prediction_id": row["prediction_id"],
                "actual_label": int(label),
                "observed_at": datetime.now(UTC).isoformat(),
            }
            for row, label in zip(rows, sample.default, strict=True)
        ]
        labeled = client.post("/api/v1/labels", json={"labels": labels})
        labeled.raise_for_status()
        assert labeled.json()["updated"] == 120
        repeated = client.post("/api/v1/labels", json={"labels": labels})
        repeated.raise_for_status()
        assert repeated.json()["unchanged"] == 120
        report = client.post("/api/v1/monitoring/snapshot?cohort=verification")
        report.raise_for_status()
        performance = report.json()["performance"]
        assert performance["labeled"] >= 120
        assert client.get("/api/v1/dashboard").status_code == 200
        assert "model_risk_score" in client.get("/metrics").text
    engine = create_db_engine(settings)
    try:
        simulation = simulate(
            parts["train"], Path("reports/simulation"), snapshot, engine, config.model_name
        )
        write_json(Path("reports/simulation/simulation.json"), simulation)
        assert simulation["severe"]["monitoring"]["drift"]["drift_trigger"]
    finally:
        engine.dispose()
    latency = asyncio.run(benchmark(args.url, payload, settings.admin_key.get_secret_value()))
    assert latency["errors"] == 0
    write_json(Path("reports/api-benchmark.json"), latency)
    result = {
        "milestones": [6, 7, 8],
        "software_checks_rerun": not args.skip_software_checks,
        "host_container_prediction_parity": True,
        "model_version": snapshot.version,
        "labels_attached": 120,
        "benchmark": latency,
        "simulation": {k: r["monitoring"]["drift"]["status"] for k, r in simulation.items()},
        "retraining_proof": "See test_real_retraining_retains_champion_without_improvement",
        "dashboard": args.url + "/api/v1/dashboard",
    }
    write_json(Path("reports/batch-2-verification.json"), result)
    print(json.dumps(result, indent=2))
    print("Batch 2 verification complete. Live champion retained; simulations are isolated.")


if __name__ == "__main__":
    main()
