from __future__ import annotations

import json
import logging
from pathlib import Path

import typer
import uvicorn

from communications_tax_data.benchmark import sync_benchmark
from communications_tax_data.bootstrap import bootstrap_from_sqlite
from communications_tax_data.catalog import seed_catalog
from communications_tax_data.collectors import (
    CensusRelationshipCollector,
    FederalCollector,
    SourceMonitor,
    SstRateCollector,
)
from communications_tax_data.comparison import compare_coverage, write_exception_report
from communications_tax_data.config import get_settings
from communications_tax_data.db import create_schema, get_engine, session_scope
from communications_tax_data.filing import seed_federal_filing_map
from communications_tax_data.location_profiles import build_customer_location_profiles

app = typer.Typer(no_args_is_help=True, help="Apeiron public tax-data collection agent.")


def _setup_logging() -> None:
    logging.basicConfig(
        level=get_settings().log_level.upper(),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


@app.command("init")
def init_database() -> None:
    """Create the CTD tables in the configured database."""
    create_schema()
    typer.echo("Database schema is ready.")


@app.command("seed-catalog")
def seed_source_catalog() -> None:
    """Seed official federal, Census, SST, and state tax source records."""
    create_schema()
    with session_scope() as session:
        inserted, updated = seed_catalog(session)
    typer.echo(f"Source catalog: {inserted} inserted, {updated} refreshed.")


@app.command("collect")
def collect(
    collector: str = typer.Option(
        "all", help="all, federal, sst, census, or monitor"
    ),
    force_monitor: bool = typer.Option(False, help="Check all monitored sources now."),
) -> None:
    """Run one or all public-source collectors."""
    _setup_logging()
    create_schema()
    choices = {
        "federal": FederalCollector,
        "sst": SstRateCollector,
        "census": CensusRelationshipCollector,
        "monitor": SourceMonitor,
    }
    names = list(choices) if collector == "all" else [collector]
    if any(name not in choices for name in names):
        raise typer.BadParameter(f"Unknown collector {collector!r}")
    with session_scope() as session:
        for name in names:
            instance = choices[name]()
            stats = (
                instance.collect(session, force=force_monitor)
                if name == "monitor"
                else instance.collect(session)
            )
            session.commit()
            typer.echo(
                f"{name}: {stats.sources} sources, {stats.seen} seen, "
                f"{stats.inserted} inserted, {stats.updated} updated"
            )


@app.command("benchmark-sync")
def benchmark_sync() -> None:
    """Refresh benchmark snapshots from the read-only Apeiron replica."""
    _setup_logging()
    create_schema()
    with session_scope() as session:
        counts = sync_benchmark(session)
    typer.echo(json.dumps(counts, indent=2))


@app.command("seed-filing-map")
def seed_filing_map() -> None:
    """Seed source-verified federal filing entities, forms, and payment links."""
    create_schema()
    with session_scope() as session:
        counts = seed_federal_filing_map(session)
    typer.echo(json.dumps(counts, indent=2))


@app.command("build-location-profiles")
def build_location_profiles() -> None:
    """Build non-calculation-ready CTD identifiers for priority customer locations."""
    create_schema()
    with session_scope() as session:
        counts = build_customer_location_profiles(session)
    typer.echo(json.dumps(counts, indent=2))


@app.command("bootstrap")
def bootstrap(
    source: Path = typer.Option(
        Path("communications_tax_data.sqlite3"),
        exists=True,
        dir_okay=False,
        readable=True,
        help="Verified local SQLite seed to copy.",
    ),
    replace: bool = typer.Option(
        False,
        "--replace",
        help="Replace rows in CTD-prefixed target tables. Other tables are untouched.",
    ),
    batch_size: int = typer.Option(1000, min=1, max=10000),
) -> None:
    """Atomically bootstrap CTD tables from a verified local SQLite seed."""
    create_schema()
    counts = bootstrap_from_sqlite(
        get_engine(),
        source,
        replace=replace,
        batch_size=batch_size,
        progress=lambda table, count: typer.echo(f"{table}: {count:,} rows"),
    )
    typer.echo(f"Bootstrap complete: {sum(counts.values()):,} rows across {len(counts)} tables.")


@app.command("compare")
def compare() -> None:
    """Compare normalized public facts and postal coverage with the benchmark."""
    create_schema()
    with session_scope() as session:
        result = compare_coverage(session)
    typer.echo(json.dumps(result, indent=2))


@app.command("report")
def report(output_dir: Path = typer.Option(Path("reports"))) -> None:
    """Write the current exception summary JSON and detail CSV."""
    create_schema()
    with session_scope() as session:
        summary_path, csv_path = write_exception_report(session, output_dir)
    typer.echo(f"Wrote {summary_path} and {csv_path}")


@app.command("serve")
def serve(
    host: str = typer.Option("127.0.0.1"),
    port: int = typer.Option(8080),
    reload: bool = typer.Option(False),
) -> None:
    """Serve the coverage dashboard and JSON API."""
    create_schema()
    uvicorn.run(
        "communications_tax_data.web:app",
        host=host,
        port=port,
        reload=reload,
    )


if __name__ == "__main__":
    app()
