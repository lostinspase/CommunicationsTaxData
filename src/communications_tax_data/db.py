from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import Engine, create_engine, event, inspect, text
from sqlalchemy.orm import Session

from communications_tax_data.config import get_settings
from communications_tax_data.models import Base


@lru_cache
def get_engine() -> Engine:
    engine = create_engine(
        get_settings().primary_url(),
        pool_pre_ping=True,
        future=True,
    )
    if engine.dialect.name == "sqlite":

        @event.listens_for(engine, "connect")
        def _sqlite_foreign_keys(dbapi_connection, _connection_record) -> None:
            cursor = dbapi_connection.cursor()
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.close()

    return engine


def create_schema(engine: Engine | None = None) -> None:
    target = engine or get_engine()
    Base.metadata.create_all(target)
    _apply_compatible_schema_upgrades(target)


def _apply_compatible_schema_upgrades(engine: Engine) -> None:
    """Apply small additive upgrades for deployments created before migrations existed."""
    inspector = inspect(engine)
    table_name = "ctd_service_tax_assessment"
    if table_name not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns(table_name)}
    if "nexus_ready" not in columns:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "ALTER TABLE ctd_service_tax_assessment "
                    "ADD COLUMN nexus_ready BOOLEAN NOT NULL DEFAULT 0"
                )
            )


@contextmanager
def session_scope(engine: Engine | None = None) -> Iterator[Session]:
    session = Session(engine or get_engine(), expire_on_commit=False)
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
