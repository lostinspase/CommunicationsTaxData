from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from communications_tax_data.config import get_settings
from communications_tax_data.models import (
    CollectionRun,
    Source,
    SourceCheck,
    TaxFact,
    TaxFactChange,
    utcnow,
)


@dataclass
class CollectionStats:
    sources: int = 0
    seen: int = 0
    inserted: int = 0
    updated: int = 0
    details: dict[str, Any] = field(default_factory=dict)


def http_client() -> httpx.Client:
    settings = get_settings()
    return httpx.Client(
        timeout=settings.http_timeout_seconds,
        follow_redirects=True,
        headers={"User-Agent": settings.user_agent},
    )


def get_with_retry(
    client: httpx.Client,
    url: str,
    *,
    attempts: int = 4,
    retry_statuses: frozenset[int] = frozenset({429, 500, 502, 503, 504}),
) -> httpx.Response:
    """GET an authoritative source with bounded retry handling for transient failures."""
    if attempts < 1:
        raise ValueError("attempts must be at least 1")
    response: httpx.Response | None = None
    for attempt in range(attempts):
        response = client.get(url)
        if response.status_code not in retry_statuses or attempt == attempts - 1:
            return response
        retry_after = response.headers.get("retry-after", "").strip()
        delay = min(float(retry_after), 30.0) if retry_after.isdigit() else 2.0**attempt
        time.sleep(delay)
    assert response is not None
    return response


def get_or_create_source(
    session: Session,
    *,
    code: str,
    name: str,
    publisher: str,
    source_type: str,
    url: str,
    tax_level: int | None = None,
    state_code: str | None = None,
    parser: str | None = None,
    cadence_days: int = 30,
    authoritative: bool = True,
    notes: str | None = None,
) -> tuple[Source, bool]:
    source = session.scalar(select(Source).where(Source.code == code))
    created = source is None
    if source is None:
        source = Source(code=code, name=name, publisher=publisher, source_type=source_type, url=url)
        session.add(source)
    source.name = name
    source.publisher = publisher
    source.source_type = source_type
    source.url = url
    source.tax_level = tax_level
    source.state_code = state_code
    source.parser = parser
    source.cadence_days = cadence_days
    source.authoritative = authoritative
    source.notes = notes
    source.active = True
    session.flush()
    return source, created


def record_response(
    session: Session,
    *,
    source: Source,
    run: CollectionRun | None,
    response: httpx.Response,
    started: float,
) -> str:
    digest = hashlib.sha256(response.content).hexdigest()
    changed = source.current_sha256 is not None and source.current_sha256 != digest
    now = utcnow()
    session.add(
        SourceCheck(
            source_id=source.id,
            run_id=run.id if run else None,
            checked_at=now,
            status_code=response.status_code,
            content_sha256=digest,
            etag=response.headers.get("etag"),
            last_modified=response.headers.get("last-modified"),
            changed=changed,
            bytes_received=len(response.content),
            elapsed_ms=round((time.monotonic() - started) * 1000),
        )
    )
    source.last_checked_at = now
    if changed or source.current_sha256 is None:
        source.last_changed_at = now
    source.current_sha256 = digest
    return digest


def record_error(
    session: Session,
    *,
    source: Source,
    run: CollectionRun | None,
    error: Exception,
    started: float,
) -> None:
    now = utcnow()
    session.add(
        SourceCheck(
            source_id=source.id,
            run_id=run.id if run else None,
            checked_at=now,
            error=f"{type(error).__name__}: {error}",
            elapsed_ms=round((time.monotonic() - started) * 1000),
        )
    )
    source.last_checked_at = now


def start_run(session: Session, collector: str) -> CollectionRun:
    run = CollectionRun(collector=collector, status="running")
    session.add(run)
    session.flush()
    return run


def finish_run(
    run: CollectionRun,
    stats: CollectionStats,
    *,
    status: str = "success",
    error: str | None = None,
) -> None:
    run.status = status
    run.finished_at = utcnow()
    run.source_count = stats.sources
    run.records_seen = stats.seen
    run.records_inserted = stats.inserted
    run.records_updated = stats.updated
    run.details = stats.details or None
    run.error = error


def _audit_value(value: Any) -> Any:
    if isinstance(value, (date, Decimal)):
        return str(value)
    return value


def record_fact_change(
    session: Session,
    *,
    fact: TaxFact,
    run: CollectionRun | None,
    created: bool,
    old_values: dict[str, Any] | None = None,
) -> None:
    """Append an explicit normalized-fact change without storing source content."""
    fields = (
        "rate",
        "flat_amount",
        "unit",
        "max_base",
        "min_base",
        "base_rule",
        "effective_to",
        "legal_citation",
        "source_locator",
        "status",
    )
    before = old_values or {}
    changed_fields: dict[str, dict[str, Any]] = {}
    for field_name in fields:
        old = before.get(field_name)
        new = getattr(fact, field_name)
        if created or old != new:
            changed_fields[field_name] = {
                "old": _audit_value(old),
                "new": _audit_value(new),
            }
    old_hash = before.get("content_sha256")
    if not created and not changed_fields and old_hash == fact.content_sha256:
        return
    session.add(
        TaxFactChange(
            tax_fact=fact,
            collection_run_id=run.id if run else None,
            change_type="insert" if created else "update",
            natural_key=fact.natural_key,
            effective_from=fact.effective_from,
            changed_fields=changed_fields or None,
            old_content_sha256=old_hash,
            new_content_sha256=fact.content_sha256,
        )
    )
