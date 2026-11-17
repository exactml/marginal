"""Open the OIC database and bring its schema up to date."""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine, create_engine, event

__all__ = ["alembic_config", "open_engine", "upgrade"]

MIGRATIONS = Path(__file__).parent / "migrations"


def open_engine(url: str) -> Engine:
    """An engine for `url`. On SQLite: WAL mode, and foreign keys enforced."""
    engine = create_engine(url)
    if engine.dialect.name == "sqlite":

        @event.listens_for(engine, "connect")
        def _sqlite_pragmas(dbapi_connection, _record) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()

    return engine


def alembic_config(url: str) -> Config:
    config = Config()
    config.set_main_option("script_location", str(MIGRATIONS))
    # ConfigParser treats % as interpolation; a password may contain one.
    config.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return config


def upgrade(url: str, revision: str = "head") -> None:
    """Apply migrations up to `revision`."""
    command.upgrade(alembic_config(url), revision)
