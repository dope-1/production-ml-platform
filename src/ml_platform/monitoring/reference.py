"""Train-only, version-bound histograms. Raw prediction features are not retained."""

import tempfile
from pathlib import Path
from typing import Any, cast

import numpy as np
import pandas as pd

from ml_platform.core.io import digest, read_json, write_json
from ml_platform.data.splitting import load_dataset
from ml_platform.data.validation import FEATURES, PAY_STATUS, SCHEMA_HASH, model_features
from ml_platform.models.registry import Registry


def distribution(values: Any, cuts: list[float]) -> list[int]:
    return cast(
        list[int],
        (
            np.bincount(
                np.searchsorted(cuts, np.round(values, 12), side="right"), minlength=len(cuts) + 1
            )
            .astype(int)
            .tolist()
        ),
    )


def make_reference(
    model: Any, train: pd.DataFrame, evidence: dict[str, Any], train_sha256: str
) -> dict[str, Any]:
    X = model_features(train)
    features = {}
    for name in FEATURES:
        cuts = (
            np.arange(-1.5, 9, 1).tolist()
            if name in PAY_STATUS
            else np.unique(np.quantile(X[name], np.linspace(0.1, 0.9, 9))).tolist()
        )
        features[name] = {
            "kind": "categorical" if name in PAY_STATUS else "numeric",
            "cuts": cuts,
            "counts": distribution(X[name], cuts),
        }
    probabilities = model.predict_proba(X)[:, 1]
    cuts = np.linspace(0.1, 0.9, 9).tolist()
    return {
        "format": 1,
        "run_id": evidence["run_id"],
        "schema_hash": SCHEMA_HASH,
        "dataset_version": evidence["dataset_version"],
        "train_sha256": train_sha256,
        "sample_count": len(X),
        "features": features,
        "transformed_mean": np.asarray(model[:-1].transform(X)).mean(axis=0).tolist(),
        "scores": {
            "cuts": cuts,
            "counts": distribution(probabilities, cuts),
            "mean": round(float(probabilities.mean()), 12),
            "positive_rate": float((probabilities >= evidence["threshold"]).mean()),
        },
    }


def publish_reference(registry: Registry, dataset: Path, version: str | None = None) -> str:
    """Add monitoring evidence to an existing run without modifying its model artifact."""
    with registry.lock:
        registry._ensure_no_pending()
        selected = version or registry.alias()
        if selected is None:
            raise ValueError("A registered model is required")
        model, evidence = registry.load_version(selected, require_approved=version is None)
        parts, manifest = load_dataset(dataset)
        with tempfile.TemporaryDirectory() as temporary:
            original = read_json(
                Path(
                    registry.client.download_artifacts(
                        evidence["run_id"], "dataset.json", temporary
                    )
                )
            )
            if (
                manifest["dataset_version"] != evidence["dataset_version"]
                or manifest["splits"] != original["splits"]
            ):
                raise ValueError("Monitoring reference must use the exact original training split")
            reference = make_reference(
                model, parts["train"], evidence, manifest["splits"]["train"]["sha256"]
            )
            path = Path(temporary) / "reference.json"
            write_json(path, reference)
            checksum = digest(path)
            old = registry.client.get_run(evidence["run_id"]).data.tags.get(
                "monitoring_reference_sha256"
            )
            if old and old != checksum:
                raise ValueError("Existing reference differs; refusing to overwrite it")
            registry.client.log_artifact(evidence["run_id"], str(path), "monitoring")
            registry.client.set_tag(evidence["run_id"], "monitoring_reference_sha256", checksum)
        write_json(
            registry.directory / "datasets" / f"{selected}.json",
            {"directory": str(dataset.resolve()), "dataset_version": manifest["dataset_version"]},
        )
        registry._event("reference_published", version=selected, sha256=checksum)
        return checksum


def load_reference(registry: Any, evidence: dict[str, Any]) -> dict[str, Any]:
    run = registry.client.get_run(evidence["run_id"])
    checksum = run.data.tags.get("monitoring_reference_sha256")
    if not checksum:
        raise ValueError("Monitoring reference missing; run the reference command")
    with tempfile.TemporaryDirectory() as temporary:
        path = Path(
            registry.client.download_artifacts(
                run.info.run_id, "monitoring/reference.json", temporary
            )
        )
        if digest(path) != checksum:
            raise ValueError("Monitoring reference checksum mismatch")
        reference = read_json(path)
    if (
        reference["run_id"] != evidence["run_id"]
        or reference["schema_hash"] != SCHEMA_HASH
        or reference["dataset_version"] != evidence["dataset_version"]
    ):
        raise ValueError("Monitoring reference belongs to a different model")
    return reference


def bucket_features(frame: pd.DataFrame, reference: dict[str, Any]) -> list[dict[str, int]]:
    columns = {
        name: np.searchsorted(reference["features"][name]["cuts"], frame[name], side="right")
        .astype(int)
        .tolist()
        for name in FEATURES
    }
    return [{name: columns[name][i] for name in FEATURES} for i in range(len(frame))]
