import importlib.util
import json
from pathlib import Path

import pytest
from dotenv import dotenv_values

from ml_platform.core.config import Settings


def load_script(name):
    path = Path(__file__).resolve().parents[2] / "scripts" / (name + ".py")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_key_upgrade_preserves_existing_db_and_admin_and_is_repeatable(tmp_path, monkeypatch):
    for name in ("ML_DB_PASSWORD", "ML_API_KEY", "ML_ADMIN_KEY", "ML_AUTH_ENABLED"):
        monkeypatch.delenv(name, raising=False)
    path = tmp_path / ".env"
    password, admin = "special@:/?#password-123", "keep-this-admin-" + "a" * 32
    path.write_text(
        f"# keep this comment\nML_DB_PASSWORD='{password}'\nML_ADMIN_KEY='{admin}'\n"
        "ML_API_KEY=\nML_AUTH_ENABLED=false\nUNRELATED=value\n"
    )
    configure = load_script("upgrade_milestone9").configure_keys
    configure(path)
    first = path.read_bytes()
    configured = Settings(_env_file=path)
    assert configured.auth_enabled
    assert configured.db_password.get_secret_value() == password
    assert configured.admin_key.get_secret_value() == admin
    assert len(configured.api_key.get_secret_value()) >= 32
    assert "UNRELATED=value" in path.read_text() and "# keep this comment" in path.read_text()
    configure(path)
    assert path.read_bytes() == first
    assert not list(tmp_path.glob(".env-update-*"))


def test_file_secrets_are_not_overwritten(tmp_path):
    path = tmp_path / ".env"
    path.write_text(
        "ML_DB_PASSWORD=existing-database-secret\nML_API_KEY_FILE=/run/secrets/api\n"
        "ML_ADMIN_KEY_FILE=/run/secrets/admin\n"
    )
    load_script("upgrade_milestone9").configure_keys(path)
    values = dotenv_values(path)
    assert "ML_API_KEY" not in values and "ML_ADMIN_KEY" not in values
    assert values["ML_AUTH_ENABLED"] == "true"


def test_scans_fail_on_findings_or_unavailable_service(tmp_path, monkeypatch):
    script = load_script("security_scan")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(script.os, "chdir", lambda path: None)
    called = []

    class Result:
        returncode = 1

    def run(command, **kwargs):
        called.append(command)
        return Result()

    monkeypatch.setattr(script.subprocess, "run", run)
    with pytest.raises(SystemExit, match="Security checks failed"):
        script.main()
    assert len(called) == 2
    assert "--strict" in called[1] and "--ignore-vuln" not in called[1]


def test_container_check_rejects_root_or_public_binding(monkeypatch):
    script = load_script("verify_milestone9")
    detail = {
        "Config": {"User": "root", "Cmd": []},
        "Mounts": [],
        "HostConfig": {
            "ReadonlyRootfs": False,
            "CapDrop": [],
            "SecurityOpt": [],
            "PortBindings": {"8000/tcp": [{"HostIp": "0.0.0.0"}]},
        },
    }

    def output(command, **kwargs):
        return json.dumps([detail]) if command[1] == "inspect" else "test-container"

    monkeypatch.setattr(script.subprocess, "check_output", output)
    with pytest.raises(RuntimeError, match="non_root"):
        script.container_checks()
