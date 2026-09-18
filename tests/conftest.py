import pytest
from fastapi.testclient import TestClient

from ml_platform.api.main import create_app
from ml_platform.core.config import Settings


@pytest.fixture
def settings():
    return Settings(
        _env_file=None,
        environment="testing",
        db_password="test-only-password-123",
        db_port=1,
        db_connect_timeout=1,
    )


@pytest.fixture
def client(settings):
    with TestClient(create_app(settings)) as client:
        yield client
