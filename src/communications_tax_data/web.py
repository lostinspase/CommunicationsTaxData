from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from fastapi import Depends, FastAPI, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from communications_tax_data import __version__
from communications_tax_data.db import get_engine
from communications_tax_data.models import (
    BenchmarkJurisdiction,
    BenchmarkRate,
    BenchmarkRateChange,
    CollectionRun,
    CoverageException,
    CoverageMetric,
    CustomerTaxNeed,
    FilingDocument,
    FilingEntity,
    Jurisdiction,
    LocationProfile,
    PostalAssignment,
    Source,
    SourceCheck,
    TaxFact,
    TaxFactChange,
    TaxFilingMap,
    TaxTypeCrosswalk,
)
from communications_tax_data.taxonomy import FUSF_PUBLIC_SOURCES

PACKAGE_DIR = Path(__file__).parent
templates = Jinja2Templates(directory=PACKAGE_DIR / "templates")


def get_session():
    with Session(get_engine()) as session:
        yield session


app = FastAPI(title="Apeiron Communications Tax Data", version=__version__)


@app.get("/api/health")
def health(session: Session = Depends(get_session)):
    session.execute(select(1))
    return {"status": "ok", "version": __version__}


def dashboard_data(session: Session) -> dict:
    today = date.today()
    latest_source_check_ids = select(func.max(SourceCheck.id)).group_by(SourceCheck.source_id)
    current_fact_filter = (
        TaxFact.effective_from <= today,
        or_(TaxFact.effective_to.is_(None), TaxFact.effective_to >= today),
    )
    metrics = {
        "sources": session.scalar(select(func.count()).select_from(Source)) or 0,
        "source_failures": session.scalar(
            select(func.count())
            .select_from(SourceCheck)
            .where(
                SourceCheck.id.in_(latest_source_check_ids),
                SourceCheck.error.is_not(None),
            )
        )
        or 0,
        "current_facts": session.scalar(
            select(func.count()).select_from(TaxFact).where(*current_fact_filter)
        )
        or 0,
        "jurisdictions": session.scalar(select(func.count()).select_from(Jurisdiction)) or 0,
        "postal_assignments": session.scalar(select(func.count()).select_from(PostalAssignment))
        or 0,
        "benchmark_tax_types": session.scalar(
            select(func.count(func.distinct(BenchmarkRate.tax_type))).where(
                BenchmarkRate.active.is_(True),
                BenchmarkRate.rate.is_not(None),
                BenchmarkRate.rate != 0,
            )
        )
        or 0,
        "benchmark_postal": session.scalar(
            select(func.count()).select_from(BenchmarkJurisdiction)
        )
        or 0,
        "open_exceptions": session.scalar(
            select(func.count())
            .select_from(CoverageException)
            .where(CoverageException.status == "open")
        )
        or 0,
        "priority_customers": session.scalar(
            select(func.count())
            .select_from(CustomerTaxNeed)
            .where(CustomerTaxNeed.active_customer.is_(True))
        )
        or 0,
        "benchmark_changes": session.scalar(
            select(func.count()).select_from(BenchmarkRateChange)
        )
        or 0,
        "filing_maps": session.scalar(
            select(func.count()).select_from(TaxFilingMap)
        )
        or 0,
    }
    level_names = {0: "Federal", 1: "State", 2: "County", 3: "Municipal/special", 4: "Other"}
    public_rows = dict(
        session.execute(
            select(Jurisdiction.tax_level, func.count(TaxFact.id))
            .join(TaxFact, TaxFact.jurisdiction_id == Jurisdiction.id)
            .where(*current_fact_filter)
            .group_by(Jurisdiction.tax_level)
        ).all()
    )
    benchmark_rows = dict(
        session.execute(
            select(
                BenchmarkRate.tax_level,
                func.count(func.distinct(BenchmarkRate.tax_type)),
            )
            .where(
                BenchmarkRate.active.is_(True),
                BenchmarkRate.rate.is_not(None),
                BenchmarkRate.rate != 0,
            )
            .group_by(BenchmarkRate.tax_level)
        ).all()
    )
    coverage = [
        {
            "level": level,
            "name": level_names.get(level, str(level)),
            "public": public_rows.get(level, 0),
            "benchmark": benchmark_rows.get(level, 0),
        }
        for level in sorted(set(public_rows) | set(benchmark_rows) | {0, 1, 2, 3})
    ]
    exceptions = [
        {"type": kind, "count": count}
        for kind, count in session.execute(
            select(CoverageException.exception_type, func.count())
            .where(CoverageException.status == "open")
            .group_by(CoverageException.exception_type)
            .order_by(func.count().desc())
        )
    ]
    runs = list(
        session.scalars(
            select(CollectionRun).order_by(CollectionRun.started_at.desc()).limit(10)
        )
    )
    latest_metric_run = session.scalar(select(func.max(CoverageMetric.comparison_run_id)))
    priority_metrics = []
    if latest_metric_run is not None:
        priority_metrics = [
            {
                "dimension": item.dimension,
                "numerator": item.numerator,
                "denominator": item.denominator,
                "percent": float(item.percent) if item.percent is not None else None,
                "details": item.details,
            }
            for item in session.scalars(
                select(CoverageMetric)
                .where(
                    CoverageMetric.comparison_run_id == latest_metric_run,
                    CoverageMetric.scope == "customer_active",
                    CoverageMetric.dimension.in_(
                        (
                            "customer_zip_statistical",
                            "tax_type_strict_rate",
                            "tax_type_public_law_support",
                            "tax_type_reviewed_crosswalk",
                            "filing_entity_tax_types",
                        )
                    ),
                )
                .order_by(CoverageMetric.dimension)
            )
        ]
    return {
        "metrics": metrics,
        "coverage": coverage,
        "priority_metrics": priority_metrics,
        "exceptions": exceptions,
        "runs": runs,
    }


@app.get("/", response_class=HTMLResponse)
def dashboard(request: Request, session: Session = Depends(get_session)):
    return templates.TemplateResponse(
        request=request,
        name="dashboard.html",
        context=dashboard_data(session),
    )


@app.get("/api/coverage")
def coverage(session: Session = Depends(get_session)):
    return dashboard_data(session)


@app.get("/api/exceptions")
def exceptions(
    state: str | None = None,
    exception_type: str | None = None,
    limit: int = Query(100, ge=1, le=1000),
    session: Session = Depends(get_session),
):
    query = select(CoverageException).where(CoverageException.status == "open")
    if state:
        query = query.where(CoverageException.state_code == state.upper())
    if exception_type:
        query = query.where(CoverageException.exception_type == exception_type)
    rows = list(session.scalars(query.order_by(CoverageException.id).limit(limit)))
    return [
        {
            "id": row.id,
            "type": row.exception_type,
            "severity": row.severity,
            "state": row.state_code,
            "jurisdiction": row.jurisdiction_label,
            "summary": row.summary,
            "details": row.details,
        }
        for row in rows
    ]


@app.get("/api/source-health")
def source_health(
    failed_only: bool = False,
    limit: int = Query(100, ge=1, le=1000),
    session: Session = Depends(get_session),
):
    latest_check_ids = select(func.max(SourceCheck.id)).group_by(SourceCheck.source_id)
    query = (
        select(Source, SourceCheck)
        .join(SourceCheck, SourceCheck.source_id == Source.id)
        .where(SourceCheck.id.in_(latest_check_ids))
    )
    if failed_only:
        query = query.where(SourceCheck.error.is_not(None))
    rows = session.execute(query.order_by(Source.code).limit(limit))
    return [
        {
            "source": source.code,
            "name": source.name,
            "state": source.state_code,
            "url": source.url,
            "last_checked_at": check.checked_at,
            "status_code": check.status_code,
            "changed": check.changed,
            "error": check.error,
        }
        for source, check in rows
    ]


@app.get("/api/coverage-metrics")
def coverage_metrics(
    scope: str | None = None,
    latest_only: bool = True,
    limit: int = Query(500, ge=1, le=5000),
    session: Session = Depends(get_session),
):
    query = select(CoverageMetric)
    if latest_only:
        latest_run = session.scalar(select(func.max(CoverageMetric.comparison_run_id)))
        if latest_run is None:
            return []
        query = query.where(CoverageMetric.comparison_run_id == latest_run)
    if scope:
        query = query.where(CoverageMetric.scope == scope)
    rows = session.scalars(
        query.order_by(
            CoverageMetric.comparison_run_id.desc(),
            CoverageMetric.scope,
            CoverageMetric.dimension,
        ).limit(limit)
    )
    return [
        {
            "run_id": row.comparison_run_id,
            "measured_at": row.measured_at,
            "as_of": row.as_of_date,
            "scope": row.scope,
            "dimension": row.dimension,
            "numerator": row.numerator,
            "denominator": row.denominator,
            "percent": str(row.percent) if row.percent is not None else None,
            "details": row.details,
        }
        for row in rows
    ]


@app.get("/api/priority-locations")
def priority_locations(
    active_only: bool = True,
    recent_days: int | None = Query(None, ge=1, le=3650),
    state: str | None = None,
    limit: int = Query(1000, ge=1, le=5000),
    session: Session = Depends(get_session),
):
    query = select(CustomerTaxNeed)
    if active_only:
        query = query.where(CustomerTaxNeed.active_customer.is_(True))
    if recent_days is not None:
        cutoff = date.today() - timedelta(days=recent_days)
        query = query.where(CustomerTaxNeed.last_tax_invoice >= cutoff)
    if state:
        query = query.where(CustomerTaxNeed.state_code == state.upper())
    rows = session.scalars(
        query.order_by(
            CustomerTaxNeed.state_code,
            CustomerTaxNeed.p_code,
            CustomerTaxNeed.customer_number,
        ).limit(limit)
    )
    return [
        {
            "customer_number": row.customer_number,
            "customer_id": row.customer_id,
            "active": row.active_customer,
            "state": row.state_code,
            "postal_code": row.postal_code,
            "plus_four": row.plus_four,
            "benchmark_p_code": row.p_code,
            "first_tax_invoice": row.first_tax_invoice,
            "last_tax_invoice": row.last_tax_invoice,
            "tax_charge_rows": row.tax_charge_rows,
            "absolute_tax_amount": str(row.absolute_tax_amount),
        }
        for row in rows
    ]


@app.get("/api/tax-types")
def tax_types(
    mapping_status: str | None = None,
    tax_type: int | None = None,
    limit: int = Query(1000, ge=1, le=5000),
    session: Session = Depends(get_session),
):
    rate_query = select(BenchmarkRate).where(
        BenchmarkRate.active.is_(True),
        BenchmarkRate.rate.is_not(None),
        BenchmarkRate.rate != 0,
    )
    if tax_type is not None:
        rate_query = rate_query.where(BenchmarkRate.tax_type == tax_type)
    rate_rows = list(session.scalars(rate_query))
    active_types = {row.tax_type for row in rate_rows}
    query = select(TaxTypeCrosswalk).where(
        TaxTypeCrosswalk.benchmark_tax_type.in_(active_types)
    )
    if mapping_status:
        query = query.where(TaxTypeCrosswalk.mapping_status == mapping_status)
    crosswalks_by_type: dict[int, list[TaxTypeCrosswalk]] = {}
    for row in session.scalars(query):
        crosswalks_by_type.setdefault(row.benchmark_tax_type, []).append(row)
    if mapping_status:
        active_types &= set(crosswalks_by_type)
    rates_by_type: dict[int, list[BenchmarkRate]] = {}
    for row in rate_rows:
        if row.tax_type in active_types:
            rates_by_type.setdefault(row.tax_type, []).append(row)

    result = []
    for benchmark_tax_type in sorted(rates_by_type)[:limit]:
        benchmark_rows = rates_by_type[benchmark_tax_type]
        crosswalk_rows = crosswalks_by_type.get(benchmark_tax_type, [])
        concepts = sorted(
            {row.ctd_tax_concept for row in crosswalk_rows if row.ctd_tax_concept}
        )
        result.append(
            {
                "benchmark_tax_type": benchmark_tax_type,
                "tax_levels": sorted({row.tax_level for row in benchmark_rows}),
                "benchmark_categories": sorted(
                    {
                        row.tax_category
                        for row in benchmark_rows
                        if row.tax_category
                    }
                ),
                "benchmark_descriptions": sorted(
                    {
                        row.tax_description
                        for row in benchmark_rows
                        if row.tax_description
                    }
                ),
                "nonzero_rates": [
                    str(value)
                    for value in sorted(
                        {row.rate for row in benchmark_rows if row.rate is not None}
                    )
                ],
                "ctd_tax_concepts": concepts,
                "service_categories": sorted(
                    {
                        row.service_category
                        for row in crosswalk_rows
                        if row.service_category
                    }
                ),
                "mapping_statuses": sorted(
                    {row.mapping_status for row in crosswalk_rows}
                ),
                "mapping_methods": sorted(
                    {row.mapping_method for row in crosswalk_rows}
                ),
                "confidence": sorted({row.confidence for row in crosswalk_rows}),
                "public_law_supported": any(
                    row.ctd_tax_concept and row.legal_citation
                    for row in crosswalk_rows
                ),
                "citations": sorted(
                    {
                        row.legal_citation
                        for row in crosswalk_rows
                        if row.legal_citation
                    }
                ),
                "public_sources": (
                    list(FUSF_PUBLIC_SOURCES)
                    if "federal_universal_service_fund" in concepts
                    else []
                ),
                "notes": sorted(
                    {row.notes for row in crosswalk_rows if row.notes}
                ),
            }
        )
    return result


@app.get("/api/filing-map")
def filing_map(
    state: str | None = None,
    tax_type: int | None = None,
    limit: int = Query(1000, ge=1, le=5000),
    session: Session = Depends(get_session),
):
    today = date.today()
    query = select(TaxFilingMap).where(
        TaxFilingMap.effective_from <= today,
        or_(TaxFilingMap.effective_to.is_(None), TaxFilingMap.effective_to >= today),
    )
    if state:
        query = query.where(TaxFilingMap.state_code == state.upper())
    if tax_type is not None:
        query = query.where(TaxFilingMap.benchmark_tax_type == tax_type)
    maps = list(
        session.scalars(
            query.order_by(
                TaxFilingMap.tax_level,
                TaxFilingMap.state_code,
                TaxFilingMap.benchmark_tax_type,
            ).limit(limit)
        )
    )
    entity_ids = {
        entity_id
        for item in maps
        for entity_id in (item.filing_entity_id, item.payment_entity_id)
        if entity_id is not None
    }
    document_ids = {
        document_id
        for item in maps
        for document_id in (item.return_document_id, item.exemption_document_id)
        if document_id is not None
    }
    entities = {
        item.id: item
        for item in session.scalars(
            select(FilingEntity).where(FilingEntity.id.in_(entity_ids))
        )
    }
    documents = {
        item.id: item
        for item in session.scalars(
            select(FilingDocument).where(FilingDocument.id.in_(document_ids))
        )
    }
    return [
        {
            "benchmark_tax_type": row.benchmark_tax_type,
            "tax_level": row.tax_level,
            "ctd_tax_concept": row.ctd_tax_concept,
            "state": row.state_code,
            "p_code": row.p_code,
            "jurisdiction": row.jurisdiction_external_key,
            "filing_entity": entities[row.filing_entity_id].name,
            "filing_portal": entities[row.filing_entity_id].filing_portal_url,
            "payment_entity": (
                entities[row.payment_entity_id].name
                if row.payment_entity_id in entities
                else row.payment_recipient
            ),
            "payment_url": (
                entities[row.payment_entity_id].payment_url
                if row.payment_entity_id in entities
                else None
            ),
            "return": (
                {
                    "form": documents[row.return_document_id].form_number,
                    "title": documents[row.return_document_id].title,
                    "url": documents[row.return_document_id].url,
                    "instructions": documents[row.return_document_id].instructions_url,
                }
                if row.return_document_id in documents
                else None
            ),
            "exemption": (
                {
                    "form": documents[row.exemption_document_id].form_number,
                    "title": documents[row.exemption_document_id].title,
                    "url": documents[row.exemption_document_id].url,
                }
                if row.exemption_document_id in documents
                else None
            ),
            "frequency": row.filing_frequency,
            "due_rule": row.due_rule,
            "reporting_basis": row.reporting_basis,
            "citation": row.legal_citation,
            "status": row.mapping_status,
            "last_verified_at": row.last_verified_at,
        }
        for row in maps
    ]


@app.get("/api/changes")
def changes(
    change_source: str = Query("public", pattern="^(public|benchmark)$"),
    limit: int = Query(100, ge=1, le=1000),
    session: Session = Depends(get_session),
):
    if change_source == "benchmark":
        rows = session.scalars(
            select(BenchmarkRateChange)
            .order_by(BenchmarkRateChange.benchmark_change_id.desc())
            .limit(limit)
        )
        return [
            {
                "benchmark_change_id": row.benchmark_change_id,
                "detected_at": row.source_timestamp,
                "source_run_at": row.run_timestamp,
                "p_code": row.p_code,
                "tax_type": row.tax_type,
                "tax_level": row.tax_level,
                "tax_category": row.tax_category,
                "tax_description": row.tax_description,
                "old_effective_date": row.old_effective_date,
                "new_effective_date": row.new_effective_date,
                "old_rate": str(row.old_rate),
                "new_rate": str(row.new_rate),
            }
            for row in rows
        ]
    rows = session.scalars(
        select(TaxFactChange).order_by(TaxFactChange.id.desc()).limit(limit)
    )
    return [
        {
            "id": row.id,
            "detected_at": row.detected_at,
            "run_id": row.collection_run_id,
            "change_type": row.change_type,
            "tax_fact_id": row.tax_fact_id,
            "natural_key": row.natural_key,
            "effective_from": row.effective_from,
            "changed_fields": row.changed_fields,
            "old_hash": row.old_content_sha256,
            "new_hash": row.new_content_sha256,
        }
        for row in rows
    ]


@app.get("/api/location-profiles")
def location_profiles(
    postal_code: str | None = None,
    calculation_ready: bool | None = None,
    limit: int = Query(1000, ge=1, le=5000),
    session: Session = Depends(get_session),
):
    query = select(LocationProfile)
    if postal_code:
        query = query.where(LocationProfile.postal_code == postal_code)
    if calculation_ready is not None:
        query = query.where(LocationProfile.calculation_ready.is_(calculation_ready))
    rows = session.scalars(
        query.order_by(LocationProfile.postal_code, LocationProfile.plus_four).limit(limit)
    )
    return [
        {
            "ctd_profile_code": row.profile_code,
            "postal_code": row.postal_code,
            "plus_four": row.plus_four,
            "state": row.state_code,
            "benchmark_p_code": row.benchmark_p_code,
            "assignment_method": row.assignment_method,
            "confidence": row.confidence,
            "calculation_ready": row.calculation_ready,
            "status": row.status,
            "valid_from": row.valid_from,
            "valid_to": row.valid_to,
        }
        for row in rows
    ]


@app.get("/api/rates")
def rates(
    state: str | None = None,
    tax_family: str | None = None,
    as_of: date | None = Query(None),
    limit: int = Query(100, ge=1, le=1000),
    session: Session = Depends(get_session),
):
    effective_date = as_of or date.today()
    query = (
        select(TaxFact, Jurisdiction)
        .join(Jurisdiction, Jurisdiction.id == TaxFact.jurisdiction_id)
        .where(
            TaxFact.effective_from <= effective_date,
            or_(TaxFact.effective_to.is_(None), TaxFact.effective_to >= effective_date),
        )
    )
    if state:
        query = query.where(Jurisdiction.state_code == state.upper())
    if tax_family:
        query = query.where(TaxFact.tax_family == tax_family)
    rows = session.execute(query.order_by(Jurisdiction.state_code, TaxFact.tax_name).limit(limit))
    return [
        {
            "id": fact.id,
            "jurisdiction": jurisdiction.name,
            "level": jurisdiction.tax_level,
            "state": jurisdiction.state_code,
            "tax_family": fact.tax_family,
            "tax_name": fact.tax_name,
            "service_category": fact.service_category,
            "rate": str(fact.rate) if fact.rate is not None else None,
            "flat_amount": str(fact.flat_amount) if fact.flat_amount is not None else None,
            "effective_from": fact.effective_from,
            "effective_to": fact.effective_to,
            "citation": fact.legal_citation,
            "source": fact.source_locator,
        }
        for fact, jurisdiction in rows
    ]
