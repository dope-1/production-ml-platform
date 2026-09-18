from pathlib import Path
from typing import Any

import pandas as pd
from sklearn.model_selection import StratifiedGroupKFold

from ml_platform.core.io import digest, fingerprint, read_json, write_json
from ml_platform.data.ingestion import SOURCE_PAGE, read_source
from ml_platform.data.validation import (
    FEATURE_VERSION,
    FEATURES,
    SCHEMA_HASH,
    TARGET,
    profile_groups,
    validate_frame,
)


def split_frame(frame: pd.DataFrame, seed: int) -> dict[str, pd.DataFrame]:
    validate_frame(frame)
    frame = frame.sort_values("customer_id").reset_index(drop=True)
    splitter = StratifiedGroupKFold(n_splits=5, shuffle=True, random_state=seed)
    folds = [
        index for _, index in splitter.split(frame[FEATURES], frame[TARGET], profile_groups(frame))
    ]
    partitions = {
        "test": frame.iloc[folds[0]],
        "validation": frame.iloc[folds[1]],
        "train": pd.concat([frame.iloc[i] for i in folds[2:]]),
    }
    seen: set[int] = set()
    for part in partitions.values():
        groups = set(profile_groups(part).astype(int))
        if seen.intersection(groups):
            raise ValueError("Predictor profile leakage across splits")
        seen.update(groups)
        if set(part[TARGET]) != {0, 1}:
            raise ValueError("Split lacks one target class")
    return {
        name: part.sort_values("customer_id").reset_index(drop=True)
        for name, part in partitions.items()
    }


def prepare_dataset(source: Path, output: Path, seed: int) -> Path:
    source_hash = digest(source)
    version = fingerprint(
        {
            "raw_sha256": source_hash,
            "seed": seed,
            "schema": SCHEMA_HASH,
            "split_policy": "stratified-profile-groups-v1",
        }
    )[:20]
    destination = output / version
    if destination.exists():
        load_dataset(destination)
        return destination
    frame = read_source(source)
    partitions = split_frame(frame, seed)
    destination.mkdir(parents=True)
    try:
        for name, part in partitions.items():
            part.to_csv(destination / f"{name}.csv", index=False)
        manifest: dict[str, Any] = {
            "dataset_version": version,
            "raw_sha256": source_hash,
            "source_file": source.name,
            "source_attribution": SOURCE_PAGE if source.suffix == ".zip" else "user-supplied CSV",
            "feature_version": FEATURE_VERSION,
            "schema_hash": SCHEMA_HASH,
            "seed": seed,
            "split_policy": "stratified-profile-groups-v1",
            "features": FEATURES,
            "rows": len(frame),
            "target_rate": float(frame[TARGET].mean()),
            "duplicate_predictor_profiles": int(profile_groups(frame).duplicated().sum()),
            "splits": {
                name: {
                    "rows": len(part),
                    "positive_rate": float(part[TARGET].mean()),
                    "sha256": digest(destination / f"{name}.csv"),
                }
                for name, part in partitions.items()
            },
        }
        write_json(destination / "manifest.json", manifest)
    except Exception:
        # An incomplete dataset is never accepted on the next run.
        raise
    return destination


def load_dataset(directory: Path) -> tuple[dict[str, pd.DataFrame], dict[str, Any]]:
    manifest = read_json(directory / "manifest.json")
    if manifest["schema_hash"] != SCHEMA_HASH:
        raise ValueError("Incompatible feature schema")
    partitions = {}
    seen_ids: set[int] = set()
    seen: set[int] = set()
    for name in ("train", "validation", "test"):
        path = directory / f"{name}.csv"
        if digest(path) != manifest["splits"][name]["sha256"]:
            raise ValueError(f"Dataset checksum mismatch: {name}")
        frame = pd.read_csv(path)
        validate_frame(frame)
        identifiers = set(frame["customer_id"].astype(int))
        if seen_ids.intersection(identifiers):
            raise ValueError("Customer ID leakage across splits")
        seen_ids.update(identifiers)
        groups = set(profile_groups(frame).astype(int))
        if seen.intersection(groups):
            raise ValueError("Predictor profile leakage")
        seen.update(groups)
        partitions[name] = frame
    return partitions, manifest
