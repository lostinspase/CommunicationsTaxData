from __future__ import annotations

import csv
import hashlib
import re
import zipfile
from collections import Counter
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import delete
from sqlalchemy.orm import Session

from communications_tax_data.collectors.base import CollectionStats, finish_run, start_run
from communications_tax_data.models import SalesTaxZipRate, utcnow

EXPECTED_FIELDS = (
    "ZIP_CODE",
    "STATE_ABBREV",
    "COUNTY_NAME",
    "CITY_NAME",
    "TOTAL_SALES_TAX",
    "TOTAL_USE_TAX",
)
LIMITATIONS = (
    "Five-digit ZIP candidate only. The basic file repeats rows associated with ZIP+4 "
    "coverage but does not disclose the plus-four ranges. It cannot select among split-ZIP "
    "jurisdictions and does not contain component rates, jurisdiction IDs, product "
    "taxability, nexus, communications surcharges, or a legally stated effective date."
)


def _release_from_name(path: Path) -> tuple[str, date]:
    match = re.search(r"_(\d{2})_(\d{2})(?:\D|$)", path.stem)
    if not match:
        raise ValueError("Could not infer release month/year; expected a name such as *_07_26.zip")
    month, year = (int(value) for value in match.groups())
    if month < 1 or month > 12:
        raise ValueError(f"Invalid release month in {path.name}")
    release_date = date(2000 + year, month, 1)
    return f"{release_date:%Y-%m}", release_date


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def import_sales_tax_zip_file(
    session: Session,
    archive_path: Path,
    *,
    batch_size: int = 2000,
) -> dict[str, Any]:
    """Import a FastSalesTax basic rate archive as deduplicated ZIP candidates."""
    path = archive_path.expanduser().resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    if batch_size < 1:
        raise ValueError("batch_size must be positive")
    release_code, release_date = _release_from_name(path)
    source_hash = _sha256(path)
    run = start_run(session, "fast-sales-tax-zip-rate-import")
    counts: dict[str, Any] = {
        "release_code": release_code,
        "release_date": str(release_date),
        "source_archive": path.name,
        "source_sha256": source_hash,
        "raw_rows": 0,
        "distinct_candidates": 0,
        "postal_codes": 0,
        "states_and_territories": 0,
        "split_postal_codes": 0,
        "sales_use_rate_differences": 0,
    }
    try:
        candidates: Counter[tuple[str, str, str, str, str, str]] = Counter()
        with zipfile.ZipFile(path) as archive:
            members = [item for item in archive.infolist() if not item.is_dir()]
            if len(members) != 1:
                raise ValueError("Expected exactly one data file in the archive")
            with archive.open(members[0]) as raw:
                import io

                reader = csv.DictReader(io.TextIOWrapper(raw, encoding="utf-8-sig"), delimiter="\t")
                if tuple(reader.fieldnames or ()) != EXPECTED_FIELDS:
                    raise ValueError(f"Unexpected columns: {reader.fieldnames}")
                for row in reader:
                    key = (
                        (row["ZIP_CODE"] or "").strip().zfill(5),
                        (row["STATE_ABBREV"] or "").strip().upper(),
                        (row["COUNTY_NAME"] or "").strip(),
                        (row["CITY_NAME"] or "").strip(),
                        str(Decimal(row["TOTAL_SALES_TAX"] or "0")),
                        str(Decimal(row["TOTAL_USE_TAX"] or "0")),
                    )
                    candidates[key] += 1
                    counts["raw_rows"] += 1

        session.execute(delete(SalesTaxZipRate).where(SalesTaxZipRate.release_code == release_code))
        now = utcnow()
        rows = []
        postal_candidates: dict[str, int] = Counter()
        states: set[str] = set()
        for key, occurrence_count in candidates.items():
            postal_code, state_code, county, city, sales_rate, use_rate = key
            rows.append(
                {
                    "release_code": release_code,
                    "release_date": release_date,
                    "release_date_basis": "filename_inferred",
                    "postal_code": postal_code,
                    "state_code": state_code,
                    "county_name": county,
                    "city_name": city,
                    "total_sales_tax": Decimal(sales_rate),
                    "total_use_tax": Decimal(use_rate),
                    "occurrence_count": occurrence_count,
                    "source_archive": path.name,
                    "source_sha256": source_hash,
                    "limitations": LIMITATIONS,
                    "imported_at": now,
                }
            )
            postal_candidates[postal_code] += 1
            states.add(state_code)
            counts["sales_use_rate_differences"] += int(sales_rate != use_rate)
            if len(rows) >= batch_size:
                session.execute(SalesTaxZipRate.__table__.insert(), rows)
                rows = []
        if rows:
            session.execute(SalesTaxZipRate.__table__.insert(), rows)
        session.flush()
        counts["distinct_candidates"] = len(candidates)
        counts["postal_codes"] = len(postal_candidates)
        counts["states_and_territories"] = len(states)
        counts["split_postal_codes"] = sum(value > 1 for value in postal_candidates.values())
        finish_run(
            run,
            CollectionStats(
                sources=1,
                seen=counts["raw_rows"],
                inserted=counts["distinct_candidates"],
                details=counts,
            ),
        )
        counts["collection_run_id"] = run.id
        return counts
    except Exception as exc:
        finish_run(
            run,
            CollectionStats(seen=counts["raw_rows"], details=counts),
            status="failed",
            error=f"{type(exc).__name__}: {exc}",
        )
        raise
