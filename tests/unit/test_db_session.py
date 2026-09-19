from ml_platform.core.config import Settings
from ml_platform.db import session


def test_create_db_engine_passes_ca_bundle(monkeypatch, tmp_path):
    ca_bundle = tmp_path / "rds-ca.pem"
    ca_bundle.write_text("test CA", encoding="utf-8")
    settings = Settings(
        _env_file=None,
        db_password="test-only-password-123",
        db_sslmode="verify-full",
        db_sslrootcert=ca_bundle,
    )
    captured = {}
    sentinel = object()

    def fake_create_engine(url, **kwargs):
        captured["url"] = url
        captured.update(kwargs)
        return sentinel

    monkeypatch.setattr(session, "create_engine", fake_create_engine)

    assert session.create_db_engine(settings) is sentinel
    assert captured["connect_args"]["sslrootcert"] == str(ca_bundle)
