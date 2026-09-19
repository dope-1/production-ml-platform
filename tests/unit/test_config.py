import pytest
from pydantic import ValidationError

from ml_platform.core.config import Settings


def test_password_is_required(monkeypatch):
    monkeypatch.delenv("ML_DB_PASSWORD", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


@pytest.mark.parametrize(
    "overrides",
    [
        {"db_port": 0},
        {"db_connect_timeout": 0},
        {"db_password": "short"},
        {"cors_origins": ["*"]},
        {"environment": "production"},
    ],
)
def test_invalid_configuration(overrides):
    values = {"db_password": "test-only-password-123", **overrides}
    with pytest.raises(ValidationError):
        Settings(_env_file=None, **values)


def test_password_hidden_and_special_characters_preserved():
    secret = "complex@:/?#password-123"
    settings = Settings(_env_file=None, db_password=secret)
    assert secret not in repr(settings)
    assert secret not in str(settings.database_url)
    assert settings.database_url.password == secret


def test_production_requires_verified_tls(tmp_path):
    ca_bundle = tmp_path / "rds-ca.pem"
    ca_bundle.write_text("test CA", encoding="utf-8")
    settings = Settings(
        _env_file=None,
        db_password="test-only-password-123",
        environment="production",
        db_sslmode="verify-full",
        db_sslrootcert=ca_bundle,
        auth_enabled=True,
        api_key="a" * 32,
        admin_key="b" * 32,
    )
    assert settings.db_sslrootcert == ca_bundle


def test_production_requires_ca_bundle(tmp_path):
    with pytest.raises(ValidationError, match="ML_DB_SSLROOTCERT"):
        Settings(
            _env_file=None,
            db_password="test-only-password-123",
            environment="production",
            db_sslmode="verify-full",
            db_sslrootcert=tmp_path / "missing.pem",
            auth_enabled=True,
            api_key="a" * 32,
            admin_key="b" * 32,
        )
