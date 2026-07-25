from __future__ import annotations

from datetime import date
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
    CollectionRun,
    CoverageException,
    Jurisdiction,
    PostalAssignment,
    Source,
    TaxFact,
)

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
    current_fact_filter = (
        TaxFact.effective_from <= today,
        or_(TaxFact.effective_to.is_(None), TaxFact.effective_to >= today),
    )
    metrics = {
        "sources": session.scalar(select(func.count()).select_from(Source)) or 0,
        "current_facts": session.scalar(
            select(func.count()).select_from(TaxFact).where(*current_fact_filter)
        )
        or 0,
        "jurisdictions": session.scalar(select(func.count()).select_from(Jurisdiction)) or 0,
        "postal_assignments": session.scalar(select(func.count()).select_from(PostalAssignment))
        or 0,
        "benchmark_rates": session.scalar(
            select(func.count()).select_from(BenchmarkRate).where(BenchmarkRate.active.is_(True))
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
            select(BenchmarkRate.tax_level, func.count())
            .where(BenchmarkRate.active.is_(True))
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
    return {"metrics": metrics, "coverage": coverage, "exceptions": exceptions, "runs": runs}


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
