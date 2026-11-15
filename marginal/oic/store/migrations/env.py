"""Alembic environment for the OIC store."""

from alembic import context
from sqlalchemy import create_engine

from marginal.oic.store.tables import metadata


def _run(connection) -> None:
    # Batch mode lets later migrations alter tables on SQLite too.
    context.configure(connection=connection, target_metadata=metadata, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


# A plain engine, not `open_engine`: SQLite batch mode copies, drops and renames
# a table, and that drop fails on referenced tables if foreign keys are enforced.
engine = create_engine(context.config.get_main_option("sqlalchemy.url"))
with engine.connect() as connection:
    _run(connection)
engine.dispose()
