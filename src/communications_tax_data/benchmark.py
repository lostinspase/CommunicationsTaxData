from __future__ import annotations

from collections.abc import Iterable

from sqlalchemy import Engine, create_engine, delete, text
from sqlalchemy.orm import Session

from communications_tax_data.config import get_settings
from communications_tax_data.models import (
    BenchmarkJurisdiction,
    BenchmarkRate,
    CollectionRun,
    utcnow,
)

US_COUNTRIES = ("USA", "PRI", "GUM", "VIR", "ASM", "MNP")


def _chunks(rows: Iterable[dict], size: int = 2000):
    batch = []
    for row in rows:
        batch.append(dict(row))
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


def sync_benchmark(session: Session) -> dict[str, int]:
    """Refresh local benchmark tables from the read-only Apeiron replica."""
    benchmark_engine: Engine = create_engine(
        get_settings().benchmark_url(),
        pool_pre_ping=True,
        future=True,
    )
    run = CollectionRun(collector="avalara-benchmark-sync", status="running")
    session.add(run)
    session.flush()
    counts = {"jurisdictions": 0, "rates": 0}
    try:
        session.execute(delete(BenchmarkRate))
        session.execute(delete(BenchmarkJurisdiction))
        session.flush()
        with benchmark_engine.connect().execution_options(stream_results=True) as connection:
            address_sql = text(
                """
                SELECT id AS benchmark_id, p_code, alternate, country_iso,
                       state AS state_code, county AS county_name,
                       city_locality AS locality_name, zip_begin, zip_end,
                       `timestamp` AS source_timestamp
                FROM apeiron_avalara_alladr
                WHERE country_iso IN ('USA','PRI','GUM','VIR','ASM','MNP')
                ORDER BY id
                """
            )
            for batch in _chunks(connection.execute(address_sql).mappings()):
                now = utcnow()
                for row in batch:
                    row["synced_at"] = now
                session.execute(BenchmarkJurisdiction.__table__.insert(), batch)
                counts["jurisdictions"] += len(batch)
                session.flush()
            rate_sql = text(
                """
                SELECT id AS benchmark_id, p_code, tax_type, tax_level, effective_date,
                       active, tax_category, tax_description, level_exemptible, rate,
                       max_base, county_override_tax, state_override_tax,
                       state_override_on, county_override_on,
                       `timestamp` AS source_timestamp
                FROM apeiron_avalarataxrate
                ORDER BY id
                """
            )
            for batch in _chunks(connection.execute(rate_sql).mappings()):
                now = utcnow()
                for row in batch:
                    row["synced_at"] = now
                session.execute(BenchmarkRate.__table__.insert(), batch)
                counts["rates"] += len(batch)
                session.flush()
        run.status = "success"
        run.source_count = 2
        run.records_seen = counts["jurisdictions"] + counts["rates"]
        run.records_inserted = run.records_seen
        run.details = counts
        run.finished_at = utcnow()
        return counts
    except Exception as exc:
        run.status = "failed"
        run.error = f"{type(exc).__name__}: {exc}"
        run.finished_at = utcnow()
        raise
    finally:
        benchmark_engine.dispose()
