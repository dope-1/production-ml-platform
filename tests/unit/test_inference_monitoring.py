from datetime import UTC, datetime, timedelta
from uuid import uuid4

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from tests_data import synthetic_frame

from ml_platform.api.main import create_app
from ml_platform.core.io import fingerprint
from ml_platform.data.validation import FEATURES, SCHEMA_HASH, model_features
from ml_platform.db.models import Base, Prediction
from ml_platform.features.pipeline import make_pipeline
from ml_platform.inference.batch import score_csv
from ml_platform.inference.schema import PredictionInput, validate_features
from ml_platform.inference.service import ModelService, Snapshot
from ml_platform.inference.storage import attach_labels, log_predictions
from ml_platform.monitoring.reference import make_reference
from ml_platform.monitoring.report import build_report, population_stability
from ml_platform.monitoring.simulation import shifted
from ml_platform.training.evaluate import evaluate


@pytest.fixture(scope="module")
def serving():
    frame = synthetic_frame()
    model = make_pipeline(RandomForestClassifier(n_estimators=12, max_depth=5, random_state=42))
    model.fit(model_features(frame), frame.default)
    evidence = {
        "threshold": 0.5,
        "model_version": "1",
        "run_id": uuid4().hex,
        "schema_hash": SCHEMA_HASH,
        "dataset_version": "unit-fixture",
        "validation": evaluate(
            frame.default, model.predict_proba(model_features(frame))[:, 1], 0.5
        ),
    }
    reference = make_reference(model, frame, evidence, fingerprint("unit-test-only"))
    return Snapshot(model, evidence, reference), frame


@pytest.fixture
def engine():
    database = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(database)
    yield database
    database.dispose()


@pytest.fixture
def served_client(settings, serving, engine):
    model, _ = serving
    service = ModelService(None)
    service._snapshot = model
    settings = settings.model_copy(update={"inference_enabled": True})
    from pydantic import SecretStr

    settings.admin_key = SecretStr("test-admin-key")
    with TestClient(create_app(settings, engine=engine, model_service=service)) as client:
        yield client


def test_real_prediction_explanation_and_private_ledger(served_client, serving, engine):
    model, frame = serving
    payload = frame[FEATURES].iloc[0].to_dict()
    result = served_client.post("/api/v1/predict", json=payload)
    assert result.status_code == 200
    row = result.json()
    assert row["request_id"] == result.headers["X-Request-ID"]
    assert row["risk_score"] == pytest.approx(model.score(model_features(frame).iloc[:1])[0])
    explanation = served_client.post("/api/v1/explain", json=payload)
    assert explanation.status_code == 200
    assert explanation.json()["explanation"]["reconstructed_risk_score"] == pytest.approx(
        row["risk_score"]
    )
    with Session(engine) as session:
        stored = session.get(Prediction, row["prediction_id"])
        assert stored.model_version == "1"
        assert set(stored.feature_buckets) == set(FEATURES)
        assert all(0 <= value <= 12 for value in stored.feature_buckets.values())
        assert not hasattr(stored, "customer_id")
    assert served_client.get("/ready").status_code == 200
    assert "model_risk_score" in served_client.get("/metrics").text


@pytest.mark.parametrize(
    "change",
    [{"income": 50000}, {"limit_bal": None}, {"pay_0": 10}, {"limit_bal": 1.5}, {"pay_amt1": -1}],
)
def test_schema_fails_closed(served_client, serving, change):
    _, frame = serving
    payload = {**frame[FEATURES].iloc[0].to_dict(), **change}
    response = served_client.post("/api/v1/predict", json=payload)
    assert response.status_code == 422
    assert '"input"' not in response.text


def test_missing_fields_are_monitored_and_unknown_routes_stay_bounded(served_client):
    assert served_client.post("/api/v1/predict", json={}).status_code == 422
    report = served_client.get("/api/v1/monitoring").json()
    assert report["operational"]["missing_feature_rates"]["limit_bal"] == 1
    assert report["operational"]["error_rate"] == 1
    assert report["performance"]["status"] == "insufficient_labels"
    assert report["drift"]["status"] == "insufficient_samples"


def test_admin_and_cohort_isolation(served_client, serving):
    _, frame = serving
    payload = frame[FEATURES].iloc[0].to_dict()
    assert served_client.post("/api/v1/models/reload").status_code == 403
    assert served_client.post("/api/v1/labels", json={"labels": []}).status_code == 403
    assert (
        served_client.post(
            "/api/v1/predict", json=payload, headers={"X-Data-Cohort": "synthetic-severe"}
        ).status_code
        == 403
    )
    response = served_client.post(
        "/api/v1/predict",
        json=payload,
        headers={"X-Data-Cohort": "verification", "X-Admin-Key": "test-admin-key"},
    )
    assert response.status_code == 200
    assert served_client.get("/api/v1/monitoring").json()["prediction_count"] == 0
    assert (
        served_client.get("/api/v1/monitoring?cohort=verification").json()["prediction_count"] == 1
    )


def test_labels_idempotent_conflicts_atomic_and_chronological(serving, engine):
    model, frame = serving
    X = model_features(frame).iloc[:2]
    rows = log_predictions(engine, model, X, model.score(X), "trace", "credit-default", "live", 1)
    observed = datetime.now(UTC)
    labels = [
        {"prediction_id": r["prediction_id"], "actual_label": 1, "observed_at": observed}
        for r in rows
    ]
    assert attach_labels(engine, labels)["updated"] == 2
    assert attach_labels(engine, labels)["unchanged"] == 2
    with pytest.raises(ValueError, match="Conflicting"):
        attach_labels(engine, [{**labels[0], "actual_label": 0}])
    with pytest.raises(ValueError, match="after prediction"):
        attach_labels(engine, [{**labels[0], "observed_at": observed - timedelta(days=1)}])
    with pytest.raises(LookupError):
        attach_labels(engine, [{**labels[0], "prediction_id": "f" * 32}])
    with Session(engine) as session:
        assert session.get(Prediction, rows[0]["prediction_id"]).actual_label == 1


def test_drift_and_delayed_label_evidence(serving, engine):
    model, frame = serving
    for severity in ("none", "severe"):
        X = model_features(shifted(frame, severity, rows=800))
        rows = log_predictions(
            engine, model, X, model.score(X), "trace", "credit-default", "synthetic-" + severity, 1
        )
        report = build_report(engine, model, "credit-default", "synthetic-" + severity)
        assert report["drift"]["drift_trigger"] is (severity == "severe")
        assert report["performance"]["status"] == "insufficient_labels"
        assert not report["performance"]["performance_trigger"]
        if severity == "none":
            # Explicit synthetic adversarial labels prove the performance trigger independently.
            attach_labels(
                engine,
                [
                    {
                        "prediction_id": row["prediction_id"],
                        "actual_label": 1 - row["prediction"],
                        "observed_at": datetime.now(UTC),
                    }
                    for row in rows
                ],
            )
            degraded = build_report(engine, model, "credit-default", "synthetic-none")
            assert degraded["performance"]["performance_trigger"]
            assert degraded["performance"]["coverage"] == 1
            assert degraded["performance"]["metrics"]["roc_auc"] < 0.1
    assert build_report(engine, model, "credit-default")["prediction_count"] == 0
    with pytest.raises(ValueError, match="shorter window"):
        build_report(engine, model, "credit-default", "synthetic-none", maximum_rows=100)
    assert population_stability([0, 100, 0], [0, 100, 0]) == 0


def test_vectorized_batch_matches_model(serving, engine, tmp_path):
    model, frame = serving
    sample = frame[["customer_id", *FEATURES]].iloc[:60]
    source, destination = tmp_path / "input.csv", tmp_path / "output.csv"
    sample.to_csv(source, index=False)
    result = score_csv(source, destination, model, engine, "credit-default", chunk_size=17)
    scored = pd.read_csv(destination)
    assert result["rows"] == 60
    np.testing.assert_allclose(scored.risk_score, model.score(model_features(sample)))
    assert scored.customer_id.tolist() == sample.customer_id.tolist()
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(Prediction)) == 60
    with pytest.raises(ValueError, match="paths must differ"):
        score_csv(source, source, model, engine, "credit-default")


def test_linear_explanation_uses_explicit_log_odds(serving):
    _, frame = serving
    model = make_pipeline(LogisticRegression(max_iter=1500), scale=True)
    model.fit(model_features(frame), frame.default)
    evidence = {"run_id": "unit-linear", "dataset_version": "unit", "threshold": 0.5}
    reference = make_reference(model, frame, evidence, "unit")
    explained = Snapshot(model, evidence, reference).explain(model_features(frame).iloc[:1])
    assert explained["output_space"] == "log_odds"
    assert explained["reconstructed_risk_score"] == pytest.approx(
        model.predict_proba(model_features(frame).iloc[:1])[0, 1]
    )


def test_feature_request_and_csv_contract_match(serving):
    _, frame = serving
    payload = PredictionInput.model_validate(frame[FEATURES].iloc[0].to_dict())
    pd.testing.assert_frame_equal(payload.frame(), validate_features(frame[FEATURES].iloc[:1]))
    boolean = frame[FEATURES].iloc[:1].copy()
    boolean["pay_0"] = False
    with pytest.raises(ValueError, match="non-numeric"):
        validate_features(boolean)


def test_failed_late_batch_validation_rolls_back_all_rows(serving, engine, tmp_path):
    model, frame = serving
    sample = frame[["customer_id", *FEATURES]].iloc[:25].copy()
    sample.loc[sample.index[-1], "limit_bal"] = -1
    source, destination = tmp_path / "bad.csv", tmp_path / "existing.csv"
    sample.to_csv(source, index=False)
    destination.write_text("keep previous output")
    with pytest.raises(ValueError, match="out of range"):
        score_csv(source, destination, model, engine, "credit-default", chunk_size=10)
    assert destination.read_text() == "keep previous output"
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(Prediction)) == 0


def test_lightgbm_explanation_reconstructs_probability(serving):
    from lightgbm import LGBMClassifier

    _, frame = serving
    model = make_pipeline(LGBMClassifier(n_estimators=8, num_leaves=8, n_jobs=1, verbosity=-1))
    model.fit(model_features(frame), frame.default)
    evidence = {"run_id": "unit-lightgbm", "dataset_version": "unit", "threshold": 0.5}
    reference = make_reference(model, frame, evidence, "unit")
    result = Snapshot(model, evidence, reference).explain(model_features(frame).iloc[:1])
    assert result["output_space"] == "log_odds"
    assert result["reconstructed_risk_score"] == pytest.approx(
        model.predict_proba(model_features(frame).iloc[:1])[0, 1]
    )


def test_empty_admin_key_never_authorizes_mutations(settings, engine):
    from pydantic import SecretStr

    settings.admin_key = SecretStr("")
    with TestClient(create_app(settings, engine=engine)) as client:
        assert client.post("/api/v1/models/reload").status_code == 403


@pytest.mark.parametrize("limits", [{"max_rows": 12}, {"max_bytes": 10}])
def test_batch_resource_limits_preserve_output_and_roll_back(serving, engine, tmp_path, limits):
    model, frame = serving
    source, destination = tmp_path / "input.csv", tmp_path / "output.csv"
    frame[["customer_id", *FEATURES]].iloc[:25].to_csv(source, index=False)
    destination.write_text("previous output")
    with pytest.raises(ValueError, match="limit"):
        score_csv(source, destination, model, engine, "credit-default", chunk_size=10, **limits)
    assert destination.read_text() == "previous output"
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(Prediction)) == 0
    assert not list(tmp_path.glob("*.tmp"))
