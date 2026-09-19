from sqlalchemy import Engine, create_engine, text

from ml_platform.core.config import Settings


def create_db_engine(settings: Settings) -> Engine:
    connect_args: dict[str, str | int] = {
        "connect_timeout": settings.db_connect_timeout,
        "sslmode": settings.db_sslmode,
        "options": f"-c statement_timeout={settings.db_statement_timeout_ms}",
    }
    if settings.db_sslrootcert is not None:
        connect_args["sslrootcert"] = str(settings.db_sslrootcert)
    return create_engine(
        settings.database_url,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=5,
        pool_timeout=settings.db_connect_timeout,
        connect_args=connect_args,
    )


def check_database(engine: Engine) -> None:
    with engine.connect() as connection:
        connection.execute(text("SELECT 1"))
