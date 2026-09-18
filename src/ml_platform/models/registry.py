"""Single-controller registry operations; MLflow remains the source of model versions.

FileLock serializes commands sharing control_dir. A pending write-ahead audit
record blocks new mutations after a crash until explicit reconciliation.
"""

import json
import os
import re
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import mlflow
import mlflow.sklearn
from filelock import FileLock
from mlflow import MlflowClient
from mlflow.exceptions import MlflowException

from ml_platform.core.io import digest, read_json, write_json
from ml_platform.core.training_config import GateConfig
from ml_platform.data.validation import SCHEMA_HASH
from ml_platform.models.gate import evaluate_gate


class RegistryReader:
    """Read-only access to the same trusted backend through a host or Docker URI.

    The shared controller directory is mounted read-only in serving containers;
    pending operations block loads. It is never re-bound to the container URI.
    """

    def __init__(self, tracking_uri: str, name: str, control_dir: Path) -> None:
        mlflow.set_tracking_uri(tracking_uri)
        self.client = MlflowClient(tracking_uri=tracking_uri)
        self.tracking_uri, self.name, self.directory = tracking_uri, name, control_dir
        identity = read_json(control_dir / "identity.json")
        if identity["model_name"] != name:
            raise ValueError("Controller belongs to a different registered model")

    def _ensure_no_pending(self) -> None:
        if (self.directory / "pending.json").exists():
            raise RuntimeError("Unresolved registry operation; run registry reconcile first")

    def alias(self, name: str = "production") -> str | None:
        try:
            return str(self.client.get_model_version_by_alias(self.name, name).version)
        except MlflowException as exc:
            if exc.error_code == "RESOURCE_DOES_NOT_EXIST":
                return None
            # MLflow 2 represents a missing alias on an existing model this way.
            if (
                exc.error_code == "INVALID_PARAMETER_VALUE"
                and "alias" in str(exc).lower()
                and "not found" in str(exc).lower()
            ):
                return None
            raise

    def evidence(self, version: str) -> dict[str, Any]:
        record = self.client.get_model_version(self.name, version)
        if record.status != "READY" or not record.run_id:
            raise ValueError("Model version is not ready or has no controlled run")
        run = self.client.get_run(record.run_id)
        if (
            run.info.status != "FINISHED"
            or run.data.tags.get("pipeline") != "controlled-training-v1"
        ):
            raise ValueError("Only finished controlled training runs may be used")
        if (
            record.source.rstrip("/")
            != self.client.get_run(record.run_id).info.artifact_uri.rstrip("/") + "/model"
        ):
            raise ValueError("Registry model source does not match controlled run artifact")
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(
                self.client.download_artifacts(record.run_id, "evidence/candidate.json", temporary)
            )
            if digest(path) != run.data.tags.get("candidate_evidence_sha256"):
                raise ValueError("Candidate evidence checksum mismatch")
            report = read_json(path)
        if report["run_id"] != record.run_id or report["schema_hash"] != SCHEMA_HASH:
            raise ValueError("Candidate identity/schema mismatch")
        active_features = Path(__file__).resolve().parents[1] / "features/pipeline.py"
        if report.get("feature_implementation_sha256") != digest(active_features):
            raise ValueError("Feature implementation differs from the training artifact")
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(self.client.download_artifacts(record.run_id, "model", temporary))
            actual = {
                p.relative_to(folder).as_posix(): digest(p)
                for p in folder.rglob("*")
                if p.is_file()
            }
            if actual != report["artifact_hashes"]:
                raise ValueError("Model artifact integrity check failed")
        return report

    def load_production(self) -> tuple[Any, dict[str, Any]]:
        self._ensure_no_pending()
        version = self.alias()
        if version is None:
            raise ValueError("No approved production model")
        return self.load_version(version, require_approved=True)

    def load_version(
        self, version: str, require_approved: bool = True
    ) -> tuple[Any, dict[str, Any]]:
        self._ensure_no_pending()
        record = self.client.get_model_version(self.name, version)
        if require_approved and record.tags.get("approved") != "true":
            raise ValueError("Production alias references an unapproved model")
        evidence = self.evidence(version)
        # Download once more and check these exact bytes before deserialization.
        with tempfile.TemporaryDirectory() as temporary:
            folder = Path(self.client.download_artifacts(record.run_id, "model", temporary))
            hashes = {
                p.relative_to(folder).as_posix(): digest(p)
                for p in folder.rglob("*")
                if p.is_file()
            }
            if hashes != evidence["artifact_hashes"]:
                raise ValueError("Model changed during loading")
            model = mlflow.sklearn.load_model(str(folder))
        return model, {**evidence, "model_version": version}


class Registry(RegistryReader):
    def __init__(self, tracking_uri: str, name: str, control_dir: Path) -> None:
        # MLflow 2's mlflow-artifacts resolver reads process-global configuration,
        # even when the tracking client has an explicit URI. Cold CLI processes
        # must configure both. This controller supports one backend per process.
        mlflow.set_tracking_uri(tracking_uri)
        self.client = MlflowClient(tracking_uri=tracking_uri)
        self.tracking_uri = tracking_uri
        self.name = name
        # One directory per registry: source identity prevents accidental reuse
        # against a different backend. Keep it on a persistent local volume.
        self.directory = control_dir
        self.directory.mkdir(parents=True, exist_ok=True)
        self.lock = FileLock(str(self.directory / "registry.lock"), timeout=30)
        with self.lock:
            identity = {"tracking_uri": tracking_uri, "model_name": name}
            path = self.directory / "identity.json"
            if path.exists() and read_json(path) != identity:
                raise ValueError("Control directory belongs to a different registry")
            write_json(path, identity)

    def _event(self, action: str, **details: Any) -> None:
        event = {
            "id": uuid4().hex,
            "timestamp": datetime.now(UTC).isoformat(),
            "model_name": self.name,
            "action": action,
            **details,
        }
        with (self.directory / "audit.jsonl").open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, sort_keys=True, allow_nan=False) + "\n")
            stream.flush()
            os.fsync(stream.fileno())

    def _ensure_no_pending(self) -> None:
        if (self.directory / "pending.json").exists():
            raise RuntimeError("Unresolved registry operation; run registry reconcile first")

    def register(self, run_id: str) -> str:
        if not re.fullmatch(r"[a-f0-9]{32}", run_id):
            raise ValueError("Invalid run identifier")
        with self.lock:
            self._ensure_no_pending()
            run = self.client.get_run(run_id)
            if (
                run.data.tags.get("pipeline") != "controlled-training-v1"
                or run.info.status != "FINISHED"
            ):
                raise ValueError("Run has no completed training evidence")
            try:
                self.client.get_registered_model(self.name)
            except MlflowException as exc:
                if exc.error_code != "RESOURCE_DOES_NOT_EXIST":
                    raise
                self.client.create_registered_model(self.name)
            matches = self.client.search_model_versions(f"name='{self.name}'")
            for item in matches:
                if item.run_id == run_id:
                    version = str(item.version)
                    self.evidence(version)
                    # Recover create-version success followed by evidence/alias
                    # failure without creating a second version or demoting one.
                    if item.tags.get("lifecycle") in (None, "candidate"):
                        self.client.set_model_version_tag(
                            self.name, version, "lifecycle", "candidate"
                        )
                        self.client.set_registered_model_alias(self.name, "candidate", version)
                        self._event("registration_resumed", version=version, run_id=run_id)
                    return version
            record = self.client.create_model_version(
                self.name, run.info.artifact_uri + "/model", run_id=run_id
            )
            version = str(record.version)
            self.evidence(version)
            self.client.set_model_version_tag(self.name, version, "lifecycle", "candidate")
            self.client.set_registered_model_alias(self.name, "candidate", version)
            self._event("registered", version=version, run_id=run_id)
            return version

    def _apply(self, version: str, previous: str | None, action: str, reason: str) -> None:
        pending = {"version": version, "previous": previous, "action": action, "reason": reason}
        write_json(self.directory / "pending.json", pending)
        self._event("intent", operation=pending)
        self.client.set_registered_model_alias(self.name, "production", version)
        self.client.set_model_version_tag(self.name, version, "approved", "true")
        self.client.set_model_version_tag(self.name, version, "lifecycle", "approved")
        self._event(action, **{k: v for k, v in pending.items() if k != "action"})
        (self.directory / "pending.json").unlink()

    def promote(self, version: str, policy: GateConfig) -> dict[str, Any]:
        with self.lock:
            self._ensure_no_pending()
            candidate = self.evidence(version)
            current = self.alias()
            champion = self.evidence(current) if current else None
            result = evaluate_gate(candidate, champion, policy)
            self._event(
                "evaluated", version=version, previous=current, policy=policy.model_dump(), **result
            )
            if current == version:
                return {
                    "decision": "UNCHANGED",
                    "reasons": ["Already production"],
                    "version": version,
                }
            if result["decision"] == "PROMOTE":
                self._apply(version, current, "promoted", "; ".join(result["reasons"]))
            else:
                self.client.set_model_version_tag(self.name, version, "lifecycle", "rejected")
                self._event("rejected", version=version, **result)
            return {**result, "version": version}

    def rollback(self, version: str, policy: GateConfig, reason: str) -> dict[str, Any]:
        if len(reason.strip()) < 10:
            raise ValueError("Provide a meaningful rollback reason (at least 10 characters)")
        with self.lock:
            self._ensure_no_pending()
            if self.client.get_model_version(self.name, version).tags.get("approved") != "true":
                raise ValueError("Rollback target was never approved")
            report = self.evidence(version)
            result = evaluate_gate(report, None, policy)
            if result["decision"] != "PROMOTE":
                self._event("rollback_rejected", version=version, **result)
                return result
            current = self.alias()
            if current == version:
                return {"decision": "UNCHANGED", "version": version}
            self._apply(version, current, "rolled_back", reason)
            return {"decision": "ROLLED_BACK", "version": version, "previous": current}

    def reconcile(self) -> dict[str, Any]:
        with self.lock:
            path = self.directory / "pending.json"
            if not path.exists():
                return {"status": "clean"}
            pending = read_json(path)
            actual = self.alias()
            if actual is not None and actual == pending["version"]:
                self.evidence(actual)
                self.client.set_model_version_tag(self.name, actual, "approved", "true")
                self.client.set_model_version_tag(self.name, actual, "lifecycle", "approved")
                state = "applied"
            elif actual == pending["previous"]:
                state = "not_applied"
            else:
                raise RuntimeError(
                    "Alias changed outside this controller; manual investigation required"
                )
            self._event("reconciled", status=state, operation=pending)
            path.unlink()
            return {"status": state, "production": actual}
