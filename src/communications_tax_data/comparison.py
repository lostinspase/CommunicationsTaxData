from __future__ import annotations

import csv
import hashlib
import json
import re
from collections import Counter
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from communications_tax_data.collectors.base import CollectionStats, finish_run, start_run
from communications_tax_data.models import (
    BenchmarkJurisdiction,
    BenchmarkRate,
    CoverageException,
    CoverageMetric,
    CustomerTaxNeed,
    PostalAssignment,
    Source,
    TaxFact,
    TaxFactBenchmarkMap,
    TaxFilingMap,
    TaxTypeCrosswalk,
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


def _signature(
    tax_type: int,
    tax_level: int,
    tax_category: str | None,
    tax_description: str | None,
) -> str:
    payload = "|".join(
        [
            str(tax_type),
            str(tax_level),
            (tax_category or "").strip().casefold(),
            (tax_description or "").strip().casefold(),
        ]
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _metric(
    *,
    run_id: int,
    as_of: date,
    scope: str,
    dimension: str,
    numerator: int,
    denominator: int,
    details: dict | None = None,
) -> CoverageMetric:
    percent = None
    if denominator:
        percent = (Decimal(numerator) * 100 / Decimal(denominator)).quantize(Decimal("0.0001"))
    return CoverageMetric(
        comparison_run_id=run_id,
        as_of_date=as_of,
        scope=scope,
        dimension=dimension,
        numerator=numerator,
        denominator=denominator,
        percent=percent,
        details=details,
    )


def _filing_map_applies(
    filing_map: TaxFilingMap,
    benchmark: BenchmarkRate,
    state_code: str | None,
) -> bool:
    if (
        filing_map.benchmark_tax_type is not None
        and filing_map.benchmark_tax_type != benchmark.tax_type
    ):
        return False
    if filing_map.tax_level != benchmark.tax_level:
        return False
    if filing_map.state_code and filing_map.state_code != state_code:
        return False
    return filing_map.p_code is None or filing_map.p_code == benchmark.p_code


def _fact_map_applies(
    fact_map: TaxFactBenchmarkMap,
    benchmark: BenchmarkRate,
    state_code: str | None,
) -> bool:
    return (
        fact_map.benchmark_tax_type == benchmark.tax_type
        and fact_map.benchmark_tax_level == benchmark.tax_level
        and fact_map.state_code in (None, state_code)
        and fact_map.p_code in (None, benchmark.p_code)
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
    public_by_natural_key: dict[str, list[TaxFact]] = {}
    for fact in public_facts:
        public_by_natural_key.setdefault(fact.natural_key, []).append(fact)
    fact_maps = list(
        session.scalars(
            select(TaxFactBenchmarkMap).where(
                TaxFactBenchmarkMap.effective_from <= today,
                or_(
                    TaxFactBenchmarkMap.effective_to.is_(None),
                    TaxFactBenchmarkMap.effective_to >= today,
                ),
                TaxFactBenchmarkMap.mapping_status.in_(
                    ("source_verified", "reviewed", "verified", "published")
                ),
            )
        )
    )

    primary_locations = {}
    for location in session.scalars(
        select(BenchmarkJurisdiction).where(BenchmarkJurisdiction.alternate.is_(False))
    ):
        primary_locations.setdefault(location.p_code, location)

    exceptions: list[CoverageException] = []
    active_rates = sorted(
        session.scalars(
            select(BenchmarkRate).where(
                BenchmarkRate.active.is_(True),
                BenchmarkRate.rate.is_not(None),
                BenchmarkRate.rate != Decimal("0"),
            )
        ),
        key=lambda item: (item.tax_type, item.benchmark_id),
    )
    rates_by_tax_type: dict[int, list[BenchmarkRate]] = {}
    for item in active_rates:
        rates_by_tax_type.setdefault(item.tax_type, []).append(item)
    matched_tax_types: set[int] = set()
    for tax_type, type_rates in rates_by_tax_type.items():
        federal_rates = [item for item in type_rates if item.tax_level == 0]
        benchmark = federal_rates[0] if federal_rates else type_rates[0]
        location = primary_locations.get(benchmark.p_code)
        state = location.state_code if location else None
        label = None
        if location:
            label = ", ".join(
                part
                for part in [location.locality_name, location.county_name, location.state_code]
                if part
            )
        kind = next(
            (candidate for item in type_rates if (candidate := _keywords(item.tax_description))),
            None,
        )
        candidates = list(federal_by_kind.get(kind, []) if federal_rates and kind else [])
        for item in type_rates:
            item_location = primary_locations.get(item.p_code)
            item_state = item_location.state_code if item_location else None
            for mapping in fact_maps:
                if _fact_map_applies(mapping, item, item_state):
                    candidates.extend(
                        public_by_natural_key.get(mapping.public_fact_natural_key, [])
                    )
        candidates = list({fact.id: fact for fact in candidates}.values())
        benchmark_values = sorted({item.rate for item in type_rates if item.rate is not None})
        rate_matches = [
            fact
            for fact in candidates
            if (
                (fact.rate is not None and fact.rate in benchmark_values)
                or (fact.flat_amount is not None and fact.flat_amount in benchmark_values)
            )
        ]
        if rate_matches:
            matched_tax_types.add(tax_type)
            continue
        if candidates:
            exception_type = "RATE_MISMATCH"
            summary = (
                f"Public {kind} facts exist but no current rate equals any nonzero "
                f"Avalara rate for tax type {tax_type}."
            )
        else:
            exception_type = "MISSING_PUBLIC_RATE"
            summary = (
                f"No normalized public fact matches Avalara tax type {tax_type} "
                f"({benchmark.tax_description or 'no description'})."
            )
        exceptions.append(
            CoverageException(
                comparison_run_id=run.id,
                exception_type=exception_type,
                severity=("high" if min(item.tax_level for item in type_rates) <= 1 else "medium"),
                state_code=state,
                jurisdiction_label=label,
                benchmark_rate_id=benchmark.benchmark_id,
                public_tax_fact_id=candidates[0].id if candidates else None,
                summary=summary,
                details={
                    "tax_type": tax_type,
                    "tax_levels": sorted({item.tax_level for item in type_rates}),
                    "tax_categories": sorted(
                        {item.tax_category for item in type_rates if item.tax_category}
                    ),
                    "tax_descriptions": sorted(
                        {item.tax_description for item in type_rates if item.tax_description}
                    ),
                    "benchmark_nonzero_rates": [str(value) for value in benchmark_values],
                    "benchmark_rate_rows": len(type_rates),
                    "benchmark_pcodes": len({item.p_code for item in type_rates}),
                    "candidate_rates": [
                        str(item.rate if item.rate is not None else item.flat_amount)
                        for item in candidates
                    ],
                    "method": (
                        "One exception per distinct nonzero Avalara tax_type. "
                        "Repeated p_code rows are diagnostic detail only."
                    ),
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

    crosswalks_by_type: dict[int, list[TaxTypeCrosswalk]] = {}
    for item in session.scalars(select(TaxTypeCrosswalk)):
        crosswalks_by_type.setdefault(item.benchmark_tax_type, []).append(item)
    filing_maps = list(
        session.scalars(
            select(TaxFilingMap).where(
                TaxFilingMap.effective_from <= today,
                or_(
                    TaxFilingMap.effective_to.is_(None),
                    TaxFilingMap.effective_to >= today,
                ),
                TaxFilingMap.mapping_status.in_(
                    ("source_verified", "reviewed", "verified", "published")
                ),
            )
        )
    )
    customers = list(session.scalars(select(CustomerTaxNeed)))
    recent_cutoff = today - timedelta(days=365)
    customer_scopes = {
        "customer_historical": customers,
        "customer_active": [item for item in customers if item.active_customer],
        "customer_recent_12m": [
            item
            for item in customers
            if item.last_tax_invoice and item.last_tax_invoice.date() >= recent_cutoff
        ],
        "customer_active_recent_12m": [
            item
            for item in customers
            if item.active_customer
            and item.last_tax_invoice
            and item.last_tax_invoice.date() >= recent_cutoff
        ],
    }
    rates_by_pcode: dict[int, list[BenchmarkRate]] = {}
    for item in active_rates:
        rates_by_pcode.setdefault(item.p_code, []).append(item)

    coverage_metrics: list[CoverageMetric] = []
    priority_summary: dict[str, dict[str, float | int | None]] = {}

    def add_metric(
        scope: str,
        dimension: str,
        numerator: int,
        denominator: int,
        details: dict | None = None,
    ) -> None:
        item = _metric(
            run_id=run.id,
            as_of=today,
            scope=scope,
            dimension=dimension,
            numerator=numerator,
            denominator=denominator,
            details=details,
        )
        coverage_metrics.append(item)
        priority_summary.setdefault(scope, {})[dimension] = (
            float(item.percent) if item.percent is not None else None
        )

    add_metric(
        "benchmark_total",
        "tax_type_strict_rate",
        len(matched_tax_types),
        len(rates_by_tax_type),
        {
            "method": (
                "Distinct active Avalara tax_type values with a nonzero rate only. "
                "A type is credited when a current normalized public fact in the same "
                "semantic family has one of the type's benchmark rates. Repeated p_code "
                "rows do not affect the percentage."
            )
        },
    )
    add_metric(
        "benchmark_total",
        "statistical_postal_rows",
        postal_matched,
        postal_seen,
        {
            "confidence": "statistical",
            "warning": "Census ZCTA coverage is not ZIP+4 or rooftop sourcing.",
        },
    )
    all_tax_types = set(rates_by_tax_type)
    candidate_tax_types = {
        tax_type
        for tax_type in all_tax_types
        if any(item.ctd_tax_concept for item in crosswalks_by_type.get(tax_type, []))
    }
    reviewed_tax_types = {
        tax_type
        for tax_type in all_tax_types
        if any(
            item.mapping_status in {"reviewed", "verified", "published"}
            for item in crosswalks_by_type.get(tax_type, [])
        )
    }
    public_law_supported_tax_types = {
        tax_type
        for tax_type in all_tax_types
        if any(
            item.ctd_tax_concept and item.legal_citation
            for item in crosswalks_by_type.get(tax_type, [])
        )
    }
    public_law_supported_tax_types.update(
        item.benchmark_tax_type for item in fact_maps if item.legal_citation
    )
    add_metric(
        "benchmark_total",
        "tax_type_candidate_crosswalk",
        len(candidate_tax_types),
        len(all_tax_types),
        {"warning": "Candidate semantic grouping is not a reviewed taxability mapping."},
    )
    add_metric(
        "benchmark_total",
        "tax_type_reviewed_crosswalk",
        len(reviewed_tax_types),
        len(all_tax_types),
    )
    add_metric(
        "benchmark_total",
        "tax_type_public_law_support",
        len(public_law_supported_tax_types),
        len(all_tax_types),
        {
            "method": (
                "A distinct nonzero Avalara tax_type has a CTD concept and a public "
                "legal citation. This does not make Avalara's proprietary numeric ID "
                "an official government identifier."
            )
        },
    )

    active_missing_filing: dict[tuple[int, int, str | None], BenchmarkRate] = {}
    for scope, scope_customers in customer_scopes.items():
        pcodes = {item.p_code for item in scope_customers if item.p_code is not None}
        postal_codes = {
            item.postal_code for item in scope_customers if item.postal_code is not None
        }
        scope_rates = [
            benchmark for p_code in pcodes for benchmark in rates_by_pcode.get(p_code, [])
        ]
        scope_tax_types = {item.tax_type for item in scope_rates}
        route_rate_results: dict[int, list[bool]] = {}
        route_law_results: dict[int, list[bool]] = {}
        for benchmark in scope_rates:
            state = (
                primary_locations[benchmark.p_code].state_code
                if benchmark.p_code in primary_locations
                else None
            )
            applicable_maps = [
                mapping for mapping in fact_maps if _fact_map_applies(mapping, benchmark, state)
            ]
            mapped_facts = [
                fact
                for mapping in applicable_maps
                for fact in public_by_natural_key.get(mapping.public_fact_natural_key, [])
            ]
            mapped_rate = any(
                benchmark.rate in (fact.rate, fact.flat_amount) for fact in mapped_facts
            )
            if benchmark.tax_level == 0 and benchmark.tax_type in matched_tax_types:
                mapped_rate = True
            route_rate_results.setdefault(benchmark.tax_type, []).append(mapped_rate)
            route_law_results.setdefault(benchmark.tax_type, []).append(
                bool(applicable_maps)
                or any(
                    item.ctd_tax_concept and item.legal_citation
                    for item in crosswalks_by_type.get(benchmark.tax_type, [])
                )
            )
        scope_matched_tax_types = {
            tax_type for tax_type, results in route_rate_results.items() if results and all(results)
        }
        scope_candidate_tax_types = scope_tax_types & candidate_tax_types
        scope_reviewed_tax_types = scope_tax_types & reviewed_tax_types
        scope_public_law_tax_types = {
            tax_type for tax_type, results in route_law_results.items() if results and all(results)
        }
        filing_results: dict[int, list[bool]] = {}
        for benchmark in scope_rates:
            state = (
                primary_locations[benchmark.p_code].state_code
                if benchmark.p_code in primary_locations
                else None
            )
            mapped = any(
                _filing_map_applies(filing_map, benchmark, state) for filing_map in filing_maps
            )
            filing_results.setdefault(benchmark.tax_type, []).append(mapped)
            if not mapped and scope == "customer_active":
                active_missing_filing.setdefault(
                    (benchmark.tax_type, benchmark.tax_level, state), benchmark
                )
        fully_mapped_filing_tax_types = {
            tax_type for tax_type, results in filing_results.items() if results and all(results)
        }

        add_metric(
            scope,
            "customer_pcode_available",
            sum(item.p_code is not None for item in scope_customers),
            len(scope_customers),
            {"source": "Apeiron customer service-address benchmark p_code"},
        )
        add_metric(
            scope,
            "customer_zip_statistical",
            sum(item.postal_code in known_zctas for item in scope_customers),
            len(scope_customers),
            {
                "confidence": "statistical",
                "warning": "Recognition of a ZIP is not jurisdiction assignment.",
            },
        )
        add_metric(
            scope,
            "distinct_zip_statistical",
            sum(item in known_zctas for item in postal_codes),
            len(postal_codes),
            {"confidence": "statistical"},
        )
        add_metric(
            scope,
            "tax_type_strict_rate",
            len(scope_matched_tax_types),
            len(scope_tax_types),
            {
                "method": (
                    "Distinct active nonzero tax_type values present at the customer "
                    "scope; repeated rate and p_code rows are ignored."
                )
            },
        )
        add_metric(
            scope,
            "tax_type_candidate_crosswalk",
            len(scope_candidate_tax_types),
            len(scope_tax_types),
            {"warning": "Candidate semantic grouping is not legally reviewed."},
        )
        add_metric(
            scope,
            "tax_type_reviewed_crosswalk",
            len(scope_reviewed_tax_types),
            len(scope_tax_types),
        )
        add_metric(
            scope,
            "tax_type_public_law_support",
            len(scope_public_law_tax_types),
            len(scope_tax_types),
        )
        add_metric(
            scope,
            "filing_entity_tax_types",
            len(fully_mapped_filing_tax_types),
            len(scope_tax_types),
            {
                "method": (
                    "A tax type is covered only when every relevant benchmark "
                    "tax-level/state route in the scope has a current filing map."
                )
            },
        )

    for (tax_type, tax_level, state), benchmark in active_missing_filing.items():
        location = primary_locations.get(benchmark.p_code)
        exceptions.append(
            CoverageException(
                comparison_run_id=run.id,
                exception_type="MISSING_FILING_MAP",
                severity="high" if tax_level <= 1 else "medium",
                state_code=state,
                jurisdiction_label=(
                    ", ".join(
                        part
                        for part in [
                            location.locality_name if location else None,
                            location.county_name if location else None,
                            state,
                        ]
                        if part
                    )
                    or None
                ),
                benchmark_rate_id=benchmark.benchmark_id,
                summary=(
                    f"No reviewed filing/payment entity map for Avalara tax type "
                    f"{tax_type}, level {tax_level}, state {state or 'federal/unknown'}."
                ),
                details={
                    "tax_type": tax_type,
                    "tax_level": tax_level,
                    "tax_category": benchmark.tax_category,
                    "tax_description": benchmark.tax_description,
                    "scope": "customer_active",
                    "required_artifacts": [
                        "filing entity/payee",
                        "return or filing portal",
                        "payment destination",
                        "exemption form where applicable",
                    ],
                },
            )
        )

    session.add_all(coverage_metrics)

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
    stats.seen = len(rates_by_tax_type) + postal_seen
    stats.inserted = len(new_exceptions)
    stats.updated = retained + resolved
    counts = Counter(item.exception_type for item in exceptions)
    stats.details = {
        "active_nonzero_benchmark_tax_types": len(rates_by_tax_type),
        "active_nonzero_benchmark_rate_rows_diagnostic": len(active_rates),
        "matched_benchmark_tax_types": len(matched_tax_types),
        "benchmark_tax_type_match_percent": (
            round(100 * len(matched_tax_types) / len(rates_by_tax_type), 3)
            if rates_by_tax_type
            else None
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
        "coverage_metric_rows": len(coverage_metrics),
        "customer_priority_coverage": priority_summary,
        "reviewed_filing_maps": len(filing_maps),
        "source_verified_fact_maps": len(fact_maps),
        "methodology": (
            "Tax coverage uses distinct active Avalara tax_type values with nonzero "
            "rates. Zero-rate types and repeated p_code rows are excluded. Non-federal "
            "types require a normalized public-law mapping before they count as matched."
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
    latest_metric_run = session.scalar(
        select(CoverageMetric.comparison_run_id)
        .order_by(CoverageMetric.comparison_run_id.desc())
        .limit(1)
    )
    metric_rows = (
        list(
            session.scalars(
                select(CoverageMetric)
                .where(CoverageMetric.comparison_run_id == latest_metric_run)
                .order_by(CoverageMetric.scope, CoverageMetric.dimension)
            )
        )
        if latest_metric_run is not None
        else []
    )
    summary = {
        "generated_at": utcnow().isoformat() + "Z",
        "total_open_exceptions": len(rows),
        "by_type": dict(Counter(row.exception_type for row in rows)),
        "by_severity": dict(Counter(row.severity for row in rows)),
        "by_state": dict(Counter(row.state_code or "FEDERAL/UNKNOWN" for row in rows)),
        "coverage_run_id": latest_metric_run,
        "coverage_metrics": {
            scope: {
                item.dimension: {
                    "numerator": item.numerator,
                    "denominator": item.denominator,
                    "percent": float(item.percent) if item.percent is not None else None,
                    "details": item.details,
                }
                for item in metric_rows
                if item.scope == scope
            }
            for scope in sorted({item.scope for item in metric_rows})
        },
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
