from datetime import UTC, datetime, timedelta

import pandas as pd
import pytest
from tests_data import synthetic_frame

from ml_platform.core.io import digest
from ml_platform.data.splitting import load_dataset, prepare_dataset
from ml_platform.retraining.workflow import extend_dataset, trigger_allowed


@pytest.fixture
def inputs(tmp_path):
    frame = synthetic_frame()
    original = tmp_path / "source.csv"
    frame.to_csv(original, index=False)
    base = prepare_dataset(original, tmp_path / "base", 42)
    new = frame.iloc[:120].copy()
    new.customer_id += 10000
    new.bill_amt6 += 12345
    new["prediction_timestamp"] = (datetime.now(UTC) - timedelta(days=2)).isoformat()
    new["label_observed_at"] = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    source = tmp_path / "labeled.csv"
    new.to_csv(source, index=False)
    return base, source, new


def test_append_preserves_holdout_bytes(inputs, tmp_path):
    base, source, _ = inputs
    extended = extend_dataset(base, source, tmp_path / "extended")
    parts, manifest = load_dataset(extended)
    old, original = load_dataset(base)
    assert len(parts["train"]) == len(old["train"]) + 120
    for name in ("validation", "test"):
        assert digest(extended / f"{name}.csv") == digest(base / f"{name}.csv")
    assert manifest["parent_dataset_version"] == original["dataset_version"]
    assert extend_dataset(base, source, tmp_path / "extended") == extended


@pytest.mark.parametrize(
    "mistake", ["old_id", "holdout_profile", "future", "naive", "stale", "early_label"]
)
def test_leakage_and_bad_label_times_rejected(inputs, tmp_path, mistake):
    base, source, new = inputs
    if mistake == "old_id":
        new.loc[0, "customer_id"] = 1
    if mistake == "holdout_profile":
        holdout = pd.read_csv(base / "validation.csv").iloc[0]
        for col in (
            c
            for c in new.columns
            if c not in ("customer_id", "prediction_timestamp", "label_observed_at")
        ):
            new.loc[0, col] = holdout[col]
    if mistake == "future":
        new["label_observed_at"] = (datetime.now(UTC) + timedelta(days=1)).isoformat()
    if mistake == "naive":
        new["label_observed_at"] = "2026-01-01T00:00:00"
    if mistake == "stale":
        new["label_observed_at"] = (datetime.now(UTC) - timedelta(days=91)).isoformat()
    if mistake == "early_label":
        new["label_observed_at"] = (datetime.now(UTC) - timedelta(days=4)).isoformat()
    new.to_csv(source, index=False)
    with pytest.raises(ValueError):
        extend_dataset(base, source, tmp_path / "extended")


def test_triggers_require_live_evidence():
    report = {
        "cohort": "synthetic-severe",
        "drift": {"drift_trigger": True},
        "performance": {"performance_trigger": True},
    }
    assert not trigger_allowed("drift", report)
    report["cohort"] = "live"
    assert trigger_allowed("drift", report)
    assert trigger_allowed("performance", report)
    assert trigger_allowed("manual", None)
    assert not trigger_allowed("performance", None)
