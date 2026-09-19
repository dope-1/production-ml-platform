import hashlib
import io
import json
import tarfile

import pytest
from test_milestone9_scripts import load_script


def digest(data):
    return hashlib.sha256(data).hexdigest()


def make_backup(tmp_path, member_name="mlflow/mlflow.db"):
    backup = tmp_path / "security-backup"
    registry = backup / "registry"
    registry.mkdir(parents=True)
    (registry / "identity.json").write_text(json.dumps({"model_name": "credit-default"}))
    (registry / "audit.jsonl").write_text('{"action":"promoted"}\n')
    (backup / "metadata.json").write_text(json.dumps({"before": {"model_version": "1"}}))
    with tarfile.open(backup / "mlflow.tar.gz", "w:gz") as archive:
        for name, data in [(member_name, b"database"), ("mlflow/artifacts/model", b"model")]:
            item = tarfile.TarInfo(name)
            item.size = len(data)
            archive.addfile(item, io.BytesIO(data))
    return backup


def make_ca(tmp_path):
    data = b"-----BEGIN CERTIFICATE-----\ntest\n-----END CERTIFICATE-----\n"
    path = tmp_path / "global-bundle.pem"
    path.write_bytes(data)
    return path, digest(data)


def test_stage_release_separates_image_and_mlflow_data(tmp_path):
    script = load_script("prepare_aws_release")
    backup = make_backup(tmp_path)
    ca, ca_hash = make_ca(tmp_path)
    output = tmp_path / "release"

    manifest = script.stage_release(
        backup, ca, ca_hash, output, "local-api:verified", "1", "credit-default"
    )

    assert (output / "image/Dockerfile").is_file()
    assert (output / "image/registry-control/identity.json").is_file()
    assert (output / "mlflow/mlflow.db").read_bytes() == b"database"
    assert not (output / "image/mlflow.db").exists()
    assert manifest["model_version"] == "1"
    assert manifest["rds_ca_bundle_sha256"] == ca_hash


def test_stage_release_rejects_wrong_ca_hash(tmp_path):
    script = load_script("prepare_aws_release")
    ca, _ = make_ca(tmp_path)
    with pytest.raises(ValueError, match="SHA-256"):
        script.stage_release(
            make_backup(tmp_path), ca, "0" * 64, tmp_path / "release", "api", "1", "credit-default"
        )


def test_stage_release_rejects_archive_traversal(tmp_path):
    script = load_script("prepare_aws_release")
    ca, ca_hash = make_ca(tmp_path)
    with pytest.raises(ValueError, match="Unsafe backup member"):
        script.stage_release(
            make_backup(tmp_path, "mlflow/../outside"),
            ca,
            ca_hash,
            tmp_path / "release",
            "api",
            "1",
            "credit-default",
        )


def test_stage_release_rejects_pending_registry(tmp_path):
    script = load_script("prepare_aws_release")
    backup = make_backup(tmp_path)
    (backup / "registry/pending.json").write_text("{}")
    ca, ca_hash = make_ca(tmp_path)
    with pytest.raises(ValueError, match="pending"):
        script.stage_release(
            backup, ca, ca_hash, tmp_path / "release", "api", "1", "credit-default"
        )
