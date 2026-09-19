import io
import tarfile

import pytest
from test_milestone9_scripts import load_script


def test_backup_validation_requires_database_and_reads_artifacts(tmp_path):
    path = tmp_path / "backup.tar.gz"
    with tarfile.open(path, "w:gz") as archive:
        for name, data in [
            ("mlflow/mlflow.db", b"database"),
            ("mlflow/artifacts/model.pkl", b"model"),
        ]:
            member = tarfile.TarInfo(name)
            member.size = len(data)
            archive.addfile(member, io.BytesIO(data))
    load_script("upgrade_security").verify_archive(path)


@pytest.mark.parametrize("name,data", [("mlflow/other.db", b"database"), ("mlflow/mlflow.db", b"")])
def test_backup_without_existing_database_is_rejected(tmp_path, name, data):
    path = tmp_path / "backup.tar.gz"
    with tarfile.open(path, "w:gz") as archive:
        member = tarfile.TarInfo(name)
        member.size = len(data)
        archive.addfile(member, io.BytesIO(data))
    with pytest.raises(ValueError, match="missing"):
        load_script("upgrade_security").verify_archive(path)


def test_truncated_backup_is_rejected(tmp_path):
    path = tmp_path / "backup.tar.gz"
    path.write_bytes(b"\x1f\x8b\x08")
    with pytest.raises((EOFError, tarfile.ReadError)):
        load_script("upgrade_security").verify_archive(path)


def test_backup_uses_stable_container_image_reference(monkeypatch):
    script = load_script("upgrade_security")
    commands = []

    def capture(*args):
        commands.append(args)
        return "sha256:old-id" if args[-2] == "{{.Image}}" else "project-mlflow:latest"

    monkeypatch.setattr(script, "capture", capture)
    assert script.container_image_details("mlflow-container") == (
        "sha256:old-id",
        "project-mlflow:latest",
    )
    assert commands == [
        ("docker", "inspect", "--format", "{{.Image}}", "mlflow-container"),
        ("docker", "inspect", "--format", "{{.Config.Image}}", "mlflow-container"),
    ]
