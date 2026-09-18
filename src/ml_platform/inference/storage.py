from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import pandas as pd
from sqlalchemy import select
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import Session

from ml_platform.db.models import Prediction
from ml_platform.inference.service import Snapshot
from ml_platform.monitoring.reference import bucket_features

COHORTS = {
    "live",
    "verification",
    "benchmark",
    "synthetic-none",
    "synthetic-mild",
    "synthetic-moderate",
    "synthetic-severe",
}


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def log_predictions(
    engine: Engine | Connection,
    snapshot: Snapshot,
    frame: pd.DataFrame,
    probabilities: Any,
    request_id: str,
    model_name: str,
    cohort: str,
    latency_ms: float,
) -> list[dict[str, Any]]:
    if cohort not in COHORTS:
        raise ValueError("Unknown observation cohort")
    now = datetime.now(UTC)
    buckets = bucket_features(frame, snapshot.reference)
    rows, responses = [], []
    for score, features in zip(probabilities, buckets, strict=True):
        identifier = uuid4().hex
        label = int(score >= snapshot.evidence["threshold"])
        rows.append(
            Prediction(
                prediction_id=identifier,
                request_id=request_id,
                created_at=now,
                model_name=model_name,
                model_version=snapshot.version,
                cohort=cohort,
                feature_buckets=features,
                risk_score=float(score),
                prediction=label,
                latency_ms=latency_ms,
            )
        )
        responses.append(
            {
                "prediction_id": identifier,
                "request_id": request_id,
                "timestamp": now.isoformat(),
                "prediction": label,
                "risk_score": float(score),
                "model_version": snapshot.version,
            }
        )
    with Session(engine) as session, session.begin():
        session.add_all(rows)
    return responses


def attach_labels(engine: Engine, labels: list[dict[str, Any]]) -> dict[str, int]:
    if not 1 <= len(labels) <= 1000:
        raise ValueError("Attach between 1 and 1000 labels")
    if len({r["prediction_id"] for r in labels}) != len(labels):
        raise ValueError("Duplicate prediction IDs in label request")
    updated = 0
    with Session(engine) as session, session.begin():
        for item in sorted(labels, key=lambda row: row["prediction_id"]):
            row = session.scalar(
                select(Prediction)
                .where(Prediction.prediction_id == item["prediction_id"])
                .with_for_update()
            )
            if row is None:
                raise LookupError("Unknown prediction ID")
            value = item["actual_label"]
            if isinstance(value, bool) or not isinstance(value, int) or value not in (0, 1):
                raise ValueError("Actual label must be 0 or 1")
            observed = item["observed_at"]
            if isinstance(observed, str):
                observed = datetime.fromisoformat(observed)
            if observed.tzinfo is None:
                raise ValueError("Label timestamp must include a timezone")
            observed = utc(observed)
            if observed < utc(row.created_at) or observed > datetime.now(UTC) + timedelta(
                minutes=1
            ):
                raise ValueError(
                    "Label must be observed after prediction and cannot be in the future"
                )
            if row.actual_label is not None:
                if (
                    row.actual_label != value
                    or row.label_observed_at is None
                    or utc(row.label_observed_at) != observed
                ):
                    raise ValueError("Conflicting label; existing labels are immutable")
            else:
                row.actual_label, row.label_observed_at = value, observed
                updated += 1
    return {"updated": updated, "unchanged": len(labels) - updated}
