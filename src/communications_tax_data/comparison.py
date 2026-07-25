from __future__ import annotations

import csv
import json
import re
from collections import Counter
from datetime import date
from pathlib import Path

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from communications_tax_data.collectors.base import CollectionStats, finish_run, start_run
from communications_tax_data.models import (
    BenchmarkJurisdiction,
    BenchmarkRate,
    CoverageException,
    PostalAssignment,
    Source,
    TaxFact,
    utcnow,
)


def _valid_zip(value: str) -> bool:
    return bool(re.fullmatch(r"\d{5}", value or "")) and value not in {"00000", "00001"}


def _keywords(description: str | None) -> str | None:
    value = (description or "").lower()
    if "universal service" in value or "usf" in value:
        return "usf"
    if "relay" in value or re.search(r"\btrs\b", value):
        return "trs"
    if "excise" in value:
        return "excise"
    return None


def _public_kind(fact: TaxFact) -> str | None:
    value = f"{fact.tax_name} {fact.tax_family}".lower()
    if "universal service" in value:
        return "usf"
    if "trs" in value or "relay" in value:
        return "trs"
    if "excise" in value:
        return "excise"
    return None


def _exception_key(item: CoverageException) -> tuple:
    return (
        item.exception_type,
        item.benchmark_rate_id,
        item.benchmark_jurisdiction_id,
        item.public_tax_fact_id,
        item.state_code,
        item.jurisdiction_label,
        item.summary,
    )


def compare_coverage(session: Session, *, as_of: date | None = None) -> dict:
    run = start_run(session, "coverage-comparison")
    stats = CollectionStats()
    now = utcnow()
    today = as_of or date.today()
    public_facts = list(
        session.scalars(
            select(TaxFact).where(
                TaxFact.effective_from <= today,
                or_(TaxFact.effective_to.is_(None), TaxFact.effective_to >= today),
            )
        )
    )
    federal_by_kind: dict[str, list[TaxFact]] = {}
    for fact in public_facts:
        kind = _public_kind(fact)
        if kind:
            federal_by_kind.setdefault(kind, []).append(fact)

    primary_locations = {}
    for location in session.scalars(
        select(BenchmarkJurisdiction).where(BenchmarkJurisdiction.alternate.is_(False))
    ):
        primary_locations.setdefault(location.p_code, location)

    exceptions: list[CoverageException] = []
    active_rates = list(
        session.scalars(select(BenchmarkRate).where(BenchmarkRate.active.is_(True)))
    )
    matched_rates = 0
    for benchmark in active_rates:
        location = primary_locations.get(benchmark.p_code)
        state = location.state_code if location else None
        label = None
        if location:
            label = ", ".join(
                part
                for part in [location.locality_name, location.county_name, location.state_code]
                if part
            )
        kind = _keywords(benchmark.tax_description)
        candidates = federal_by_kind.get(kind, []) if benchmark.tax_level == 0 and kind else []
        rate_matches = [
            fact for fact in candidates if fact.rate is not None and fact.rate == benchmark.rate
        ]
        if rate_matches:
            matched_rates += 1
            continue
        if candidates:
            exception_type = "RATE_MISMATCH"
            summary = (
                f"Public {kind} fact exists but no current rate equals benchmark "
                f"{benchmark.rate}."
            )
        else:
            exception_type = "MISSING_PUBLIC_RATE"
            summary = (
                f"No normalized public fact matches benchmark tax "
                f"{benchmark.tax_description or benchmark.tax_type}."
            )
        exceptions.append(
            CoverageException(
                comparison_run_id=run.id,
                exception_type=exception_type,
                severity="high" if benchmark.tax_level <= 1 else "medium",
                state_code=state,
                jurisdiction_label=label,
                benchmark_rate_id=benchmark.benchmark_id,
                public_tax_fact_id=candidates[0].id if candidates else None,
                summary=summary,
                details={
                    "tax_level": benchmark.tax_level,
                    "tax_type": benchmark.tax_type,
                    "tax_category": benchmark.tax_category,
                    "tax_description": benchmark.tax_description,
                    "benchmark_rate": str(benchmark.rate) if benchmark.rate is not None else None,
                    "candidate_rates": [str(item.rate) for item in candidates],
                },
            )
        )

    known_zctas = set(session.scalars(select(PostalAssignment.postal_code).distinct()))
    postal_seen = 0
    postal_matched = 0
    for location in session.scalars(
        select(BenchmarkJurisdiction).where(BenchmarkJurisdiction.country_iso == "USA")
    ):
        if not _valid_zip(location.zip_begin) or not _valid_zip(location.zip_end):
            continue
        postal_seen += 1
        low, high = int(location.zip_begin), int(location.zip_end)
        # Ranges in the commercial data are compact encodings. Avoid unbounded expansion.
        candidates = (
            [f"{value:05d}" for value in range(low, high + 1)] if 0 <= high - low <= 500 else []
        )
        if any(value in known_zctas for value in candidates):
            postal_matched += 1
            continue
        exceptions.append(
            CoverageException(
                comparison_run_id=run.id,
                exception_type="MISSING_POSTAL_ASSIGNMENT",
                severity="high",
                state_code=location.state_code,
                jurisdiction_label=", ".join(
                    part
                    for part in [location.locality_name, location.county_name, location.state_code]
                    if part
                ),
                benchmark_jurisdiction_id=location.benchmark_id,
                summary=(
                    f"No Census ZCTA relationship covers benchmark ZIP range "
                    f"{location.zip_begin}-{location.zip_end}."
                ),
                details={
                    "p_code": location.p_code,
                    "zip_begin": location.zip_begin,
                    "zip_end": location.zip_end,
                    "benchmark_is_alternate": location.alternate,
                    "caveat": "Census ZCTA coverage is statistical, not rooftop/ZIP+4 coverage.",
                },
            )
        )

    for source in session.scalars(
        select(Source).where(Source.active.is_(True), Source.parser.is_(None))
    ):
        if source.source_type not in {"state_tax_landing", "report_directory", "taxability_matrix"}:
            continue
        exceptions.append(
            CoverageException(
                comparison_run_id=run.id,
                exception_type="UNIMPLEMENTED_SOURCE_PARSER",
                severity="medium",
                state_code=source.state_code,
                jurisdiction_label=source.state_code,
                summary=f"Source is monitored but not normalized: {source.name}.",
                details={"source_code": source.code, "url": source.url},
            )
        )

    existing_open = list(
        session.scalars(
            select(CoverageException)
            .where(CoverageException.status == "open")
            .order_by(CoverageException.id)
        )
    )
    existing_by_key = {_exception_key(item): item for item in existing_open}
    new_exceptions: list[CoverageException] = []
    retained = 0
    for candidate in exceptions:
        existing = existing_by_key.pop(_exception_key(candidate), None)
        if existing is None:
            new_exceptions.append(candidate)
            continue
        existing.comparison_run_id = run.id
        existing.severity = candidate.severity
        existing.details = candidate.details
        existing.resolved_at = None
        retained += 1
    resolved = len(existing_by_key)
    for stale in existing_by_key.values():
        stale.status = "superseded"
        stale.resolved_at = now
    session.add_all(new_exceptions)
    session.flush()
    stats.seen = len(active_rates) + postal_seen
    stats.inserted = len(new_exceptions)
    stats.updated = retained + resolved
    counts = Counter(item.exception_type for item in exceptions)
    stats.details = {
        "active_benchmark_rates": len(active_rates),
        "matched_benchmark_rates": matched_rates,
        "benchmark_rate_match_percent": (
            round(100 * matched_rates / len(active_rates), 3) if active_rates else None
        ),
        "benchmark_postal_rows": postal_seen,
        "statistically_covered_postal_rows": postal_matched,
        "postal_match_percent": (
            round(100 * postal_matched / postal_seen, 3) if postal_seen else None
        ),
        "public_current_facts": len(public_facts),
        "exceptions": dict(counts),
        "new_exceptions": len(new_exceptions),
        "retained_exceptions": retained,
        "resolved_exceptions": resolved,
        "methodology": (
            "Rate matching is intentionally strict. Non-federal facts require a normalized "
            "jurisdiction/taxability mapping before they count as matched."
        ),
    }
    finish_run(run, stats)
    return {"run_id": run.id, **stats.details}


def write_exception_report(session: Session, output_dir: Path) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = list(
        session.scalars(
            select(CoverageException)
            .where(CoverageException.status == "open")
            .order_by(
                CoverageException.severity,
                CoverageException.exception_type,
                CoverageException.id,
            )
        )
    )
    summary = {
        "generated_at": utcnow().isoformat() + "Z",
        "total_open_exceptions": len(rows),
        "by_type": dict(Counter(row.exception_type for row in rows)),
        "by_severity": dict(Counter(row.severity for row in rows)),
        "by_state": dict(Counter(row.state_code or "FEDERAL/UNKNOWN" for row in rows)),
        "limitations": [
            "Census ZCTAs approximate USPS ZIP Codes and do not provide ZIP+4 or rooftop sourcing.",
            (
                "SST files cover sales/use rates for member states; they do not establish "
                "communications taxability."
            ),
            (
                "A benchmark fact is not counted as covered until tax identity, jurisdiction, "
                "rate, and effective date match."
            ),
        ],
    }
    json_path = output_dir / "coverage-summary.json"
    json_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    csv_path = output_dir / "coverage-exceptions.csv"
    with csv_path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(
            [
                "exception_type",
                "severity",
                "state",
                "jurisdiction",
                "summary",
                "benchmark_rate_id",
                "benchmark_jurisdiction_id",
                "public_tax_fact_id",
                "details_json",
            ]
        )
        for row in rows:
            writer.writerow(
                [
                    row.exception_type,
                    row.severity,
                    row.state_code,
                    row.jurisdiction_label,
                    row.summary,
                    row.benchmark_rate_id,
                    row.benchmark_jurisdiction_id,
                    row.public_tax_fact_id,
                    json.dumps(row.details, sort_keys=True),
                ]
            )
    return json_path, csv_path
