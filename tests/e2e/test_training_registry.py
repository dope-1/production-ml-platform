import json
from pathlib import Path
from uuid import uuid4

import mlflow
import pytest
from tests_data import synthetic_frame

from ml_platform.core.training_config import GateConfig, TrainingConfig
from ml_platform.data.splitting import prepare_dataset
from ml_platform.data.validation import model_features
from ml_platform.models.registry import Registry
from ml_platform.training.train import train


@pytest.fixture(scope="module")
def trained(tmp_path_factory):
    root = tmp_path_factory.mktemp("real-mlflow")
    source = root / "fixture.csv"
    frame = synthetic_frame()
    frame.to_csv(source, index=False)
    dataset = prepare_dataset(source, root / "datasets", 42)
    uri = "sqlite:///" + (root / "mlflow.db").as_posix()
    # Real MLflow SQL backend, artifact files, six trained models, no fake registry.
    mlflow.set_tracking_uri(uri)
    mlflow.create_experiment("fixture-tests", artifact_location=(root / "artifacts").as_uri())
    config = TrainingConfig(
        experiment="fixture-tests",
        shap_samples=5,
        latency_repeats=5,
        cv_folds=2,
        gate=GateConfig(min_group_positives=2),
    )
    report = train(dataset, config, uri, root / "reports")
    return uri, report, frame


@pytest.fixture
def registry(trained, tmp_path):
    uri, report, frame = trained
    registry = Registry(uri, "test-" + uuid4().hex, tmp_path / "control")
    version = registry.register(report["run_id"])
    # Fixture-specific policy tests lifecycle independently of statistical deployment suitability.
    policy = GateConfig(
        minimum_roc_auc=0,
        minimum_pr_auc=0,
        minimum_recall=0,
        maximum_brier=1,
        max_sex_recall_gap=1,
        max_latency_ms=10000,
        max_cv_std=1,
        max_model_bytes=100_000_000,
    )
    return registry, version, policy, frame


def test_real_train_register_promote_load_reject_and_rollback(registry):
    registry, first, policy, frame = registry
    assert registry.register(registry.evidence(first)["run_id"]) == first
    assert registry.promote(first, policy)["decision"] == "PROMOTE"
    model, evidence = registry.load_production()
    assert evidence["model_version"] == first
    p = model.predict_proba(model_features(frame).iloc[:4])[:, 1]
    assert ((p >= 0) & (p <= 1)).all()
    record = registry.client.get_model_version(registry.name, first)
    # Create a real second version of the identical artifact to prove no-improvement rejection.
    second = str(
        registry.client.create_model_version(
            registry.name, record.source, run_id=record.run_id
        ).version
    )
    assert registry.promote(second, policy)["decision"] == "REJECT"
    assert registry.alias() == first
    with pytest.raises(ValueError, match="never approved"):
        registry.rollback(second, policy, "Unapproved target must fail")
    # Explicit test policy permits equality, allowing a real rollback transition.
    equal_allowed = policy.model_copy(update={"minimum_improvement": 0})
    assert registry.promote(second, equal_allowed)["decision"] == "PROMOTE"
    assert (
        registry.rollback(first, policy, "Exercise verified rollback transition")["decision"]
        == "ROLLED_BACK"
    )
    assert registry.alias() == first
    actions = [
        json.loads(line)["action"]
        for line in (registry.directory / "audit.jsonl").read_text().splitlines()
    ]
    assert {"registered", "promoted", "rejected", "rolled_back"}.issubset(actions)


def test_integrity_checks_before_deserialization(registry):
    registry, version, policy, _ = registry
    record = registry.client.get_model_version(registry.name, version)
    path = Path(registry.client.download_artifacts(record.run_id, "model/model.pkl"))
    original = path.read_bytes()
    try:
        path.write_bytes(original + b"tampering")
        with pytest.raises(ValueError, match="integrity"):
            registry.promote(version, policy)
        assert registry.alias() is None
    finally:
        path.write_bytes(original)


def test_pending_alias_mutation_requires_reconciliation(registry, monkeypatch):
    registry, version, policy, _ = registry
    original = registry._event

    def fail_after_alias(action, **details):
        if action == "promoted":
            raise OSError("Simulated audit storage failure")
        return original(action, **details)

    monkeypatch.setattr(registry, "_event", fail_after_alias)
    with pytest.raises(OSError):
        registry.promote(version, policy)
    with pytest.raises(RuntimeError, match="Unresolved"):
        registry.promote(version, policy)
    monkeypatch.setattr(registry, "_event", original)
    assert registry.reconcile()["status"] == "applied"
    assert registry.alias() == version


def test_partial_registration_reuses_existing_version(registry):
    registry, version, _, _ = registry
    record = registry.client.get_model_version(registry.name, version)
    registry.client.delete_registered_model_alias(registry.name, "candidate")
    registry.client.delete_model_version_tag(registry.name, version, "lifecycle")
    assert registry.register(record.run_id) == version
    assert registry.alias("candidate") == version
    assert len(registry.client.search_model_versions(f"name='{registry.name}'")) == 1


def test_verified_reference_and_read_only_serving(registry, tmp_path):
    from ml_platform.core.io import write_json
    from ml_platform.inference.service import ModelService
    from ml_platform.models.registry import RegistryReader
    from ml_platform.monitoring.reference import publish_reference

    registry, version, policy, frame = registry
    registry.promote(version, policy)
    source = tmp_path / "source.csv"
    frame.to_csv(source, index=False)
    dataset = prepare_dataset(source, tmp_path / "dataset", 42)
    checksum = publish_reference(registry, dataset)
    assert len(checksum) == 64
    reader = RegistryReader(registry.tracking_uri, registry.name, registry.directory)
    service = ModelService(reader)
    snapshot = service.reload()
    assert snapshot.version == version
    assert snapshot.score(model_features(frame).iloc[:2]).shape == (2,)
    # A failed reload keeps exactly the previous verified snapshot.
    write_json(registry.directory / "pending.json", {"version": version})
    with pytest.raises(RuntimeError, match="Unresolved"):
        service.reload()
    assert service.current() is snapshot


def test_real_retraining_retains_champion_without_improvement(registry, tmp_path):
    from datetime import UTC, datetime, timedelta

    from ml_platform.core.io import digest, read_json
    from ml_platform.retraining.workflow import retrain

    registry, version, policy, frame = registry
    registry.promote(version, policy)
    source = tmp_path / "base.csv"
    frame.to_csv(source, index=False)
    dataset = prepare_dataset(source, tmp_path / "base", 42)
    new = frame.iloc[:160].copy()
    new.customer_id += 10000
    new.bill_amt6 += 23456
    new["prediction_timestamp"] = (datetime.now(UTC) - timedelta(days=2)).isoformat()
    new["label_observed_at"] = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    labeled = tmp_path / "new-labels.csv"
    new.to_csv(labeled, index=False)
    config = TrainingConfig(
        experiment="fixture-retraining",
        model_name=registry.name,
        cv_folds=2,
        shap_samples=5,
        latency_repeats=5,
        gate=policy.model_copy(update={"minimum_improvement": 0.1}),
    )
    result = retrain(registry, dataset, labeled, config, tmp_path / "jobs")
    assert result["decision"] == "REJECT"
    assert registry.alias() == version
    assert result["version"] != version
    assert result["candidate_validation"]["roc_auc"] >= 0.5
    assert digest(Path(result["dataset"]) / "test.csv") == digest(dataset / "test.csv")
    checkpoint = read_json(tmp_path / "jobs" / result["job_id"] / "trained.json")
    assert checkpoint["test"]["status"] == "not_evaluated_in_retraining"
    assert retrain(registry, dataset, labeled, config, tmp_path / "jobs")["idempotent_replay"]
    actions = [
        json.loads(line)["action"]
        for line in (registry.directory / "audit.jsonl").read_text().splitlines()
    ]
    assert "retraining_completed" in actions
