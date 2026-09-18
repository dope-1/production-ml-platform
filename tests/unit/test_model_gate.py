from copy import deepcopy

import numpy as np
import pytest

from ml_platform.core.training_config import GateConfig
from ml_platform.data.validation import SCHEMA_HASH
from ml_platform.models.gate import evaluate_gate
from ml_platform.training.evaluate import evaluate, select_threshold


@pytest.fixture
def evidence():
    # Explicit unit-test fixture numbers; never published as model results.
    return {
        "validation": {"roc_auc": 0.8, "pr_auc": 0.6, "recall": 0.7, "brier": 0.15},
        "threshold": 0.3,
        "schema_hash": SCHEMA_HASH,
        "latency_p95_ms": 5,
        "model_bytes": 1000,
        "cv_pr_auc_std": 0.01,
        "validation_sha256": "same-cohort",
        "subgroups": {"sex_recall_gap": 0.05},
        "checks": {
            "finite_features": True,
            "probability_bounds": True,
            "schema": True,
            "reload_equivalence": True,
        },
    }


def test_first_model_passes_absolute_gates(evidence):
    assert evaluate_gate(evidence, None, GateConfig())["decision"] == "PROMOTE"


@pytest.mark.parametrize(
    "field,value",
    [
        ("latency_p95_ms", 999),
        ("model_bytes", 99_000_000),
        ("cv_pr_auc_std", 0.9),
        ("schema_hash", "wrong"),
        ("threshold", 0),
        ("latency_p95_ms", float("nan")),
    ],
)
def test_gate_rejects_bad_evidence(evidence, field, value):
    evidence[field] = value
    assert evaluate_gate(evidence, None, GateConfig())["decision"] == "REJECT"


def test_gate_missing_checks_and_fairness_fail_closed(evidence):
    evidence["checks"] = {}
    evidence["subgroups"]["sex_recall_gap"] = None
    assert evaluate_gate(evidence, None, GateConfig())["decision"] == "REJECT"
    assert evaluate_gate({}, None, GateConfig())["decision"] == "REJECT"


def test_same_worse_and_incomparable_candidates_rejected(evidence):
    assert evaluate_gate(evidence, evidence, GateConfig())["decision"] == "REJECT"
    previous = deepcopy(evidence)
    evidence["validation"]["pr_auc"] = 0.7
    assert evaluate_gate(evidence, previous, GateConfig())["decision"] == "PROMOTE"
    evidence["validation_sha256"] = "different-cohort"
    assert evaluate_gate(evidence, previous, GateConfig())["decision"] == "REJECT"


def test_no_test_metrics_used_for_promotion(evidence):
    evidence["test"] = {"roc_auc": 0, "pr_auc": 0}
    assert evaluate_gate(evidence, None, GateConfig())["decision"] == "PROMOTE"


def test_threshold_uses_recall_constraint():
    y = np.array([0, 0, 1, 1, 1, 0])
    p = np.array([0.05, 0.2, 0.25, 0.35, 0.8, 0.7])
    threshold, rows = select_threshold(y, p, 0.66, 99)
    assert threshold != 0.5
    assert evaluate(y, p, threshold)["recall"] >= 0.66
    assert len(rows) == 101


def test_invalid_probabilities_and_single_class_rejected():
    with pytest.raises(ValueError):
        evaluate([0, 1], [0, np.nan], 0.5)
    with pytest.raises(ValueError):
        evaluate([0, 0], [0.1, 0.2], 0.5)


def test_registry_sets_artifact_tracking_uri_in_cold_process(tmp_path):
    import subprocess
    import sys

    code = """
import sys
from pathlib import Path
import mlflow
from ml_platform.models.registry import Registry
mlflow.set_tracking_uri(Path(sys.argv[1], 'unused-local-store').as_uri())
registry = Registry('http://127.0.0.1:5000', 'cold-process-test', Path(sys.argv[1], 'control'))
assert mlflow.get_tracking_uri() == registry.tracking_uri
"""
    subprocess.run([sys.executable, "-c", code, str(tmp_path)], check=True)
