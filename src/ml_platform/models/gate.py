import math
from typing import Any

from ml_platform.core.training_config import GateConfig
from ml_platform.data.validation import SCHEMA_HASH


def evaluate_gate(
    candidate: dict[str, Any], champion: dict[str, Any] | None, policy: GateConfig
) -> dict[str, Any]:
    """Pure fail-closed validation. Test metrics never drive promotion."""
    reasons = []
    try:
        validation = candidate["validation"]
        required = [validation[k] for k in ("roc_auc", "pr_auc", "recall", "brier")]
        required += [candidate[k] for k in ("latency_p95_ms", "model_bytes", "cv_pr_auc_std")]
        if not all(
            isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)
            for v in required
        ):
            reasons.append("Missing/non-finite numeric evidence")
        if not all(0 <= validation[k] <= 1 for k in ("roc_auc", "pr_auc", "recall", "brier")):
            reasons.append("Metrics outside valid bounds")
        if not 0 < candidate["threshold"] < 1:
            reasons.append("Degenerate decision threshold")
        if candidate["schema_hash"] != SCHEMA_HASH:
            reasons.append("Feature schema mismatch")
        checks = candidate["checks"]
        for key in ("finite_features", "probability_bounds", "schema", "reload_equivalence"):
            if checks.get(key) is not True:
                reasons.append(f"Artifact check failed: {key}")
        for key, minimum in (
            ("roc_auc", policy.minimum_roc_auc),
            ("pr_auc", policy.minimum_pr_auc),
            ("recall", policy.minimum_recall),
        ):
            if validation[key] < minimum:
                reasons.append(f"Validation {key} below {minimum}")
        if validation["brier"] > policy.maximum_brier:
            reasons.append("Calibration Brier score exceeds maximum")
        if not 0 <= candidate["latency_p95_ms"] <= policy.max_latency_ms:
            reasons.append("Latency budget exceeded")
        if not 0 < candidate["model_bytes"] <= policy.max_model_bytes:
            reasons.append("Artifact size budget exceeded")
        if not 0 <= candidate["cv_pr_auc_std"] <= policy.max_cv_std:
            reasons.append("CV instability exceeds maximum")
        gap = candidate["subgroups"]["sex_recall_gap"]
        if gap is None or not math.isfinite(gap) or not 0 <= gap <= policy.max_sex_recall_gap:
            reasons.append("Sex subgroup recall guardrail failed or evidence insufficient")
        if champion:
            if candidate["validation_sha256"] != champion["validation_sha256"]:
                reasons.append("Champion and candidate must use the same validation cohort")
            previous = champion["validation"]
            for key in ("roc_auc", "pr_auc", "recall"):
                if validation[key] < previous[key] - policy.regression_tolerance:
                    reasons.append(f"Champion regression: {key}")
            if validation["brier"] > previous["brier"] + policy.regression_tolerance:
                reasons.append("Champion regression: brier")
            if validation["pr_auc"] < previous["pr_auc"] + policy.minimum_improvement:
                reasons.append("Insufficient PR-AUC improvement over champion")
    except (KeyError, TypeError, ValueError):
        reasons.append("Malformed or incomplete candidate evidence")
    return {
        "decision": "REJECT" if reasons else "PROMOTE",
        "reasons": reasons or ["All validation gates passed"],
    }
