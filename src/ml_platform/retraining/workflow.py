"""Single-controller retraining: fresh labeled inputs, fixed holdouts, gated deployment."""

import shutil
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
from filelock import FileLock
from sqlalchemy.engine import Engine

from ml_platform.core.io import digest, fingerprint, read_json, write_json
from ml_platform.core.training_config import TrainingConfig
from ml_platform.data.splitting import load_dataset
from ml_platform.data.validation import COLUMNS, ID, profile_groups, validate_frame
from ml_platform.inference.service import Snapshot
from ml_platform.models.registry import Registry
from ml_platform.monitoring.reference import load_reference, publish_reference
from ml_platform.monitoring.report import build_report, save_report
from ml_platform.training.train import train

TIME_COLUMNS = ["prediction_timestamp", "label_observed_at"]


def extend_dataset(
    base: Path, labeled_source: Path, destination: Path, now: datetime | None = None
) -> Path:
    """Never re-split: both original holdout files are copied byte-for-byte."""
    now = now or datetime.now(UTC)
    parts, manifest = load_dataset(base)
    incoming = pd.read_csv(labeled_source)
    if set(incoming.columns) != {*COLUMNS, *TIME_COLUMNS}:
        raise ValueError("Retraining CSV needs the canonical columns and both event timestamps")
    if len(incoming) < 100:
        raise ValueError("At least 100 newly labeled rows are required")
    for column in TIME_COLUMNS:
        # Mixed/naive timestamps are rejected instead of silently assuming a timezone.
        parsed = incoming[column].map(datetime.fromisoformat)
        if any(t.tzinfo is None for t in parsed):
            raise ValueError("Retraining timestamps must include timezones")
        incoming[column] = pd.to_datetime(incoming[column], utc=True)
    predicted, observed = incoming[TIME_COLUMNS[0]], incoming[TIME_COLUMNS[1]]
    if (
        predicted.isna().any()
        or observed.isna().any()
        or (observed < predicted).any()
        or (observed > now).any()
        or (observed < now - timedelta(days=90)).any()
    ):
        raise ValueError("Labels must follow prediction, be non-future and no older than 90 days")
    fresh = incoming[COLUMNS].copy()
    validate_frame(fresh)
    old_ids = set(pd.concat(list(parts.values()))[ID])
    if old_ids.intersection(fresh[ID]):
        raise ValueError("New customer IDs overlap an existing training or holdout record")
    holdout_profiles = set(profile_groups(pd.concat([parts["validation"], parts["test"]])))
    if holdout_profiles.intersection(profile_groups(fresh)):
        raise ValueError("New predictor profiles overlap a protected holdout")
    combined = pd.concat([parts["train"], fresh]).sort_values(ID).reset_index(drop=True)
    validate_frame(combined)
    version = fingerprint(
        {
            "base": manifest["dataset_version"],
            "source": digest(labeled_source),
            "policy": "append-new-labeled-preserve-holdouts-v1",
        }
    )[:20]
    folder = destination / version
    if folder.exists():
        load_dataset(folder)
        return folder
    destination.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=destination) as temporary:
        staging = Path(temporary) / "dataset"
        staging.mkdir()
        combined.to_csv(staging / "train.csv", index=False)
        for name in ("validation", "test"):
            shutil.copyfile(base / f"{name}.csv", staging / f"{name}.csv")
        updated = {
            **manifest,
            "dataset_version": version,
            "parent_dataset_version": manifest["dataset_version"],
            "new_source_sha256": digest(labeled_source),
            "new_rows": len(fresh),
            "split_policy": "append-new-labeled-preserve-holdouts-v1",
            "rows": sum(len(p) for p in parts.values()) + len(fresh),
            "target_rate": float(
                pd.concat([combined, parts["validation"], parts["test"]])["default"].mean()
            ),
            "splits": {
                **manifest["splits"],
                "train": {
                    "rows": len(combined),
                    "positive_rate": float(combined["default"].mean()),
                    "sha256": digest(staging / "train.csv"),
                },
            },
        }
        write_json(staging / "manifest.json", updated)
        load_dataset(staging)
        staging.replace(folder)
    return folder


def trigger_allowed(trigger: str, report: dict[str, Any] | None) -> bool:
    if trigger == "manual":
        return True
    if trigger not in ("drift", "performance"):
        raise ValueError("Unknown retraining trigger")
    if report is None or report["cohort"] != "live":
        return False
    return (
        report["drift"].get("drift_trigger") is True
        if trigger == "drift"
        else (report["performance"].get("performance_trigger") is True)
    )


def retrain(
    registry: Registry,
    base: Path,
    labeled_source: Path,
    config: TrainingConfig,
    output: Path,
    trigger: str = "manual",
    engine: Engine | None = None,
) -> dict[str, Any]:
    if registry.name != config.model_name:
        raise ValueError("Training configuration and target registry names differ")
    output.mkdir(parents=True, exist_ok=True)
    with FileLock(str(registry.directory / "retraining.lock"), timeout=1):
        model, champion = registry.load_production()
        # Force comparison on the same validation and test cohorts as the champion.
        _, manifest = load_dataset(base)
        if (
            manifest["splits"]["validation"]["sha256"] != champion["validation_sha256"]
            or manifest["splits"]["test"]["sha256"] != champion["test_sha256"]
            or manifest["dataset_version"] != champion["dataset_version"]
        ):
            raise ValueError("Base dataset does not match the current champion")
        key = fingerprint(
            {
                "source": digest(labeled_source),
                "base": manifest["dataset_version"],
                "model": registry.name,
                "configuration": config.model_dump(),
            }
        )[:20]
        job = output / key
        receipt = job / "result.json"
        if receipt.exists():
            return {**read_json(receipt), "idempotent_replay": True}
        report = None
        if trigger != "manual":
            if engine is None:
                raise ValueError("A live prediction database is required for automated triggers")
            snapshot = Snapshot(model, champion, load_reference(registry, champion))
            report = build_report(engine, snapshot, registry.name, "live")
            save_report(engine, report)
        if not trigger_allowed(trigger, report):
            result = {
                "decision": "SKIP",
                "reason": "Trigger lacks sufficient live evidence",
                "production_version": champion["model_version"],
                "trigger": trigger,
            }
            registry._event("retraining_skipped", **result)
            return result
        registry._event(
            "retraining_started",
            job=key,
            trigger=trigger,
            source_sha256=digest(labeled_source),
            monitoring_report_id=report["report_id"] if report else None,
        )
        try:
            dataset = extend_dataset(base, labeled_source, output / "datasets")
            checkpoint = job / "trained.json"
            if checkpoint.exists():
                candidate = read_json(checkpoint)
            else:
                candidate = train(
                    dataset, config, registry.tracking_uri, job / "training", evaluate_test=False
                )
                write_json(checkpoint, candidate)
            version = registry.register(candidate["run_id"])
            # A challenger must be fully serveable before its alias may be promoted.
            publish_reference(registry, dataset, version)
            # Registry.promote re-reads the current champion under its own lock.
            decision = registry.promote(version, config.gate)
            result = {
                **decision,
                "trigger": trigger,
                "job_id": key,
                "previous_version": champion["model_version"],
                "production_version": registry.alias(),
                "candidate_validation": candidate["validation"],
                "champion_validation": champion["validation"],
                "dataset": str(dataset),
                "test_used_for_selection": False,
                "serving_action": "Explicit API reload required after promotion",
            }
            write_json(receipt, result)
            registry._event("retraining_completed", **result)
            return result
        except Exception as exc:
            registry._event("retraining_failed", job=key, error_type=type(exc).__name__)
            raise
