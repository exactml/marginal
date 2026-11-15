"""Alembic environment for the OIC store."""

from alembic import context

from marginal.oic.store.database import open_engine
from marginal.oic.store.tables import metadata


def _run(connection) -> None:
    # Batch mode lets later migrations alter tables on SQLite too.
    context.configure(connection=connection, target_metadata=metadata, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


engine = open_engine(context.config.get_main_option("sqlalchemy.url"))
with engine.connect() as connection:
    _run(connection)
engine.dispose()
