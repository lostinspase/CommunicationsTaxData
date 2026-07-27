from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from sqlalchemy import URL, Engine, create_engine, func, select

from communications_tax_data.models import Base


def bootstrap_from_sqlite(
    target_engine: Engine,
    source_path: Path,
    *,
    replace: bool = False,
    batch_size: int = 1000,
    progress: Callable[[str, int], None] | None = None,
) -> dict[str, int]:
    """Atomically copy a verified SQLite seed into the namespaced CTD tables."""
    source_path = source_path.expanduser().resolve()
    if not source_path.is_file():
        raise FileNotFoundError(source_path)
    if batch_size < 1:
        raise ValueError("batch_size must be at least 1")
    source_engine = create_engine(URL.create("sqlite+pysqlite", database=str(source_path)))
    tables = list(Base.metadata.sorted_tables)
    counts: dict[str, int] = {}
    try:
        with source_engine.connect() as source, target_engine.begin() as target:
            populated = {
                table.name: target.scalar(select(func.count()).select_from(table)) or 0
                for table in tables
            }
            if any(populated.values()) and not replace:
                details = ", ".join(f"{name}={count}" for name, count in populated.items() if count)
                raise ValueError(
                    f"Target CTD tables are not empty ({details}); pass replace=True explicitly"
                )
            if replace:
                for table in reversed(tables):
                    target.execute(table.delete())
            for table in tables:
                result = source.execute(select(table)).mappings()
                copied = 0
                while batch := result.fetchmany(batch_size):
                    target.execute(table.insert(), [dict(row) for row in batch])
                    copied += len(batch)
                counts[table.name] = copied
                if progress:
                    progress(table.name, copied)
        return counts
    finally:
        source_engine.dispose()
