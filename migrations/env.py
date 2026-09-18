from alembic import context

from ml_platform.core.config import Settings
from ml_platform.db.models import Base
from ml_platform.db.session import create_db_engine

engine = create_db_engine(Settings())
with engine.connect() as connection:
    context.configure(connection=connection, target_metadata=Base.metadata)
    with context.begin_transaction():
        context.run_migrations()
engine.dispose()
