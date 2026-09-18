"""Seeded stress scenarios, visibly synthetic and excluded from live monitoring."""

from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy.engine import Engine

from ml_platform.data.validation import FEATURES, ID, PAY_STATUS
from ml_platform.inference.batch import score_csv
from ml_platform.inference.schema import validate_features
from ml_platform.inference.service import Snapshot
from ml_platform.monitoring.report import build_report, save_report


def shifted(frame: pd.DataFrame, severity: str, rows: int = 600, seed: int = 42) -> pd.DataFrame:
    if severity not in ("none", "mild", "moderate", "severe") or not 100 <= rows <= 10000:
        raise ValueError("Invalid simulation severity or size")
    rng = np.random.default_rng(seed)
    sample = (
        frame.sample(rows, replace=True, random_state=seed)[FEATURES].copy().reset_index(drop=True)
    )
    fraction, multiplier, delay = {
        "none": (0, 1, 0),
        "mild": (0.1, 0.9, 1),
        "moderate": (0.5, 0.65, 2),
        "severe": (0.95, 0.3, 4),
    }[severity]
    mask = rng.random(rows) < fraction
    sample.loc[mask, "limit_bal"] = (sample.loc[mask, "limit_bal"] * multiplier).clip(1).astype(int)
    for column in PAY_STATUS:
        sample.loc[mask, column] = (sample.loc[mask, column] + delay).clip(-2, 9)
    validate_features(sample)
    sample.insert(0, ID, np.arange(1_000_000, 1_000_000 + rows))
    return sample


def simulate(
    frame: pd.DataFrame, output: Path, snapshot: Snapshot, engine: Engine, model_name: str
) -> dict[str, Any]:
    output.mkdir(parents=True, exist_ok=True)
    results = {}
    for severity in ("none", "mild", "moderate", "severe"):
        source = output / f"synthetic-{severity}.csv"
        shifted(frame, severity).to_csv(source, index=False)
        cohort = f"synthetic-{severity}"
        batch = score_csv(
            source, output / f"scores-{severity}.csv", snapshot, engine, model_name, cohort
        )
        report = build_report(engine, snapshot, model_name, cohort)
        save_report(engine, report)
        results[severity] = {
            "batch": batch,
            "monitoring": report,
            "note": "Synthetic stress scenario; no true labels or live performance claims.",
        }
    return results
