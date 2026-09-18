"""Version-specific, bounded observation windows with explicit evidence sufficiency."""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import numpy as np
from sqlalchemy import func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from ml_platform.data.validation import FEATURES
from ml_platform.db.models import ApiEvent, MonitoringReport, Prediction
from ml_platform.inference.service import Snapshot
from ml_platform.inference.storage import COHORTS, utc
from ml_platform.monitoring.reference import distribution
from ml_platform.training.evaluate import evaluate


def population_stability(reference: list[int], observed: list[int]) -> float:
    # Half-count smoothing handles empty bins without infinities.
    a, b = np.asarray(reference, dtype=float) + 0.5, np.asarray(observed, dtype=float) + 0.5
    a, b = a / a.sum(), b / b.sum()
    return float(np.sum((b - a) * np.log(b / a)))


def drift_summary(
    rows: list[Prediction], reference: dict[str, Any], minimum_samples: int = 100
) -> dict[str, Any]:
    if len(rows) < minimum_samples:
        return {
            "status": "insufficient_samples",
            "required": minimum_samples,
            "drift_trigger": False,
            "features": {},
        }
    features: dict[str, Any] = {}
    for name in FEATURES:
        expected = reference["features"][name]
        counts = np.bincount(
            [r.feature_buckets[name] for r in rows], minlength=len(expected["counts"])
        ).tolist()
        psi = population_stability(expected["counts"], counts)
        a = np.asarray(expected["counts"], dtype=float)
        b = np.asarray(counts, dtype=float)
        tv = float(np.abs(a / a.sum() - b / b.sum()).sum() / 2)
        categorical = expected["kind"] == "categorical"
        value, moderate, severe = (tv, 0.15, 0.30) if categorical else (psi, 0.20, 0.50)
        features[name] = {
            "psi": psi,
            "total_variation": tv,
            "kind": expected["kind"],
            "status": "severe"
            if value >= severe
            else "moderate"
            if value >= moderate
            else "stable",
        }
    scores = [r.risk_score for r in rows]
    baseline = reference["scores"]
    score_psi = population_stability(baseline["counts"], distribution(scores, baseline["cuts"]))
    mean_delta = float(np.mean(scores) - baseline["mean"])
    class_rate = float(np.mean([r.prediction for r in rows]))
    class_delta = class_rate - baseline["positive_rate"]
    changed = [name for name, r in features.items() if r["status"] != "stable"]
    prediction_drift = score_psi >= 0.20 and (abs(mean_delta) >= 0.03 or abs(class_delta) >= 0.10)
    return {
        "status": "drift" if len(changed) >= 3 or prediction_drift else "stable",
        "drift_trigger": len(changed) >= 3 or prediction_drift,
        "features": features,
        "changed_features": changed,
        "prediction": {
            "psi": score_psi,
            "mean_risk": float(np.mean(scores)),
            "mean_risk_delta": mean_delta,
            "positive_rate": class_rate,
            "positive_rate_delta": class_delta,
            "drift": prediction_drift,
        },
        "note": "Distribution drift is an investigation signal, not proof of degradation.",
    }


def performance_summary(
    rows: list[Prediction], evidence: dict[str, Any], labels_as_of: datetime
) -> dict[str, Any]:
    labeled = [
        r
        for r in rows
        if r.actual_label is not None
        and r.label_observed_at is not None
        and utc(r.label_observed_at) <= labels_as_of
    ]
    coverage = len(labeled) / len(rows) if rows else 0.0
    support = {str(value): sum(r.actual_label == value for r in labeled) for value in (0, 1)}
    result: dict[str, Any] = {
        "labeled": len(labeled),
        "coverage": coverage,
        "support": support,
        "performance_trigger": False,
        "note": "Metrics apply only to observed labels; label selection can bias them.",
    }
    if len(labeled) < 100 or min(support.values()) < 10 or coverage < 0.5:
        return {
            **result,
            "status": "insufficient_labels",
            "required": {"labels": 100, "each_class": 10, "coverage": 0.5},
        }
    y = np.asarray([r.actual_label for r in labeled], dtype=int)
    p = np.asarray([r.risk_score for r in labeled])
    metrics = evaluate(y, p, evidence["threshold"])
    bins = np.minimum((p * 10).astype(int), 9)
    calibration = [
        {
            "bin": i,
            "count": int((bins == i).sum()),
            "mean_probability": float(p[bins == i].mean()),
            "positive_rate": float(y[bins == i].mean()),
        }
        for i in range(10)
        if (bins == i).any()
    ]
    ece = sum(
        r["count"] * abs(r["mean_probability"] - r["positive_rate"]) for r in calibration
    ) / len(y)
    baseline = evidence["validation"]
    delta = {k: metrics[k] - baseline[k] for k in ("roc_auc", "pr_auc", "recall", "brier")}
    degradation = (
        delta["roc_auc"] < -0.05
        or delta["pr_auc"] < -0.05
        or delta["recall"] < -0.10
        or delta["brier"] > 0.05
    )
    return {
        **result,
        "status": "degraded" if degradation else "stable",
        "performance_trigger": degradation,
        "metrics": metrics,
        "validation_delta": delta,
        "calibration": calibration,
        "ece": ece,
    }


def build_report(
    engine: Engine,
    snapshot: Snapshot,
    model_name: str,
    cohort: str = "live",
    hours: int = 24,
    end: datetime | None = None,
    maximum_rows: int = 50_000,
) -> dict[str, Any]:
    if cohort not in COHORTS or not 1 <= hours <= 720:
        raise ValueError("Invalid cohort or monitoring window")
    now = datetime.now(UTC)
    end = utc(end) if end is not None else now
    if end > now + timedelta(seconds=1):
        raise ValueError("Monitoring window cannot end in the future")
    start = end - timedelta(hours=hours)
    with Session(engine) as session:
        query = select(Prediction).where(
            Prediction.model_name == model_name,
            Prediction.model_version == snapshot.version,
            Prediction.cohort == cohort,
            Prediction.created_at >= start,
            Prediction.created_at < end,
        )
        total = session.scalar(select(func.count()).select_from(query.subquery())) or 0
        event_query = select(ApiEvent).where(
            ApiEvent.created_at >= start, ApiEvent.created_at < end, ApiEvent.cohort == cohort
        )
        event_count = session.scalar(select(func.count()).select_from(event_query.subquery())) or 0
        if total > maximum_rows or event_count > maximum_rows:
            raise ValueError("Window exceeds 50000 observations; choose a shorter window")
        rows = list(session.scalars(query))
        events = list(session.scalars(event_query))
    latencies = [r.latency_ms for r in events]
    operational = {
        "requests": len(events),
        "requests_per_minute": len(events) / (hours * 60),
        "error_rate": sum(r.status >= 400 for r in events) / len(events) if events else None,
        "server_error_rate": sum(r.status >= 500 for r in events) / len(events) if events else None,
        "latency_ms": {
            f"p{q}": float(np.percentile(latencies, q)) if latencies else None for q in (50, 95, 99)
        },
        "missing_feature_rates": {
            f: sum(f in e.missing_features for e in events) / len(events) if events else None
            for f in FEATURES
        },
        "scope": "HTTP predict/explain attempts in this cohort; batch rows excluded",
    }
    return {
        "report_id": uuid4().hex,
        "created_at": now.isoformat(),
        "model_name": model_name,
        "model_version": snapshot.version,
        "cohort": cohort,
        "window": {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "hours": hours,
            "labels_as_of": now.isoformat(),
        },
        "prediction_count": len(rows),
        "operational": operational,
        "drift": drift_summary(rows, snapshot.reference),
        "performance": performance_summary(rows, snapshot.evidence, now),
        "policy": {
            "min_predictions": 100,
            "numeric_psi": 0.20,
            "categorical_tv": 0.15,
            "changed_feature_count": 3,
            "probability_psi": 0.20,
            "mean_score_delta": 0.03,
            "positive_rate_delta": 0.10,
        },
    }


def save_report(engine: Engine, report: dict[str, Any]) -> None:
    with Session(engine) as session, session.begin():
        session.add(
            MonitoringReport(
                report_id=report["report_id"],
                created_at=datetime.fromisoformat(report["created_at"]),
                model_name=report["model_name"],
                model_version=report["model_version"],
                cohort=report["cohort"],
                report=report,
            )
        )
