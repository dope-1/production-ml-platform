import os
import subprocess

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from ml_platform.api.main import create_app
from ml_platform.core.config import Settings
from ml_platform.db.session import create_db_engine

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("TEST_DATABASE") != "1", reason="Set TEST_DATABASE=1 with real PostgreSQL"
    ),
]


def test_real_postgres_migration_and_readiness():
    subprocess.run(["alembic", "upgrade", "head"], check=True)
    settings = Settings()
    engine = create_db_engine(settings)
    try:
        with engine.connect() as connection:
            assert (
                connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
                == "0002"
            )
    finally:
        engine.dispose()
    with TestClient(create_app(settings)) as client:
        assert client.get("/ready").status_code == 200
