from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)


class Base(DeclarativeBase):
    pass


class Source(Base):
    __tablename__ = "ctd_source"

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)
    code: Mapped[str] = mapped_column(String(120), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(255))
    publisher: Mapped[str] = mapped_column(String(255))
    source_type: Mapped[str] = mapped_column(String(40))
    tax_level: Mapped[int | None] = mapped_column(Integer)
    state_code: Mapped[str | None] = mapped_column(String(2), index=True)
    url: Mapped[str] = mapped_column(Text)
    parser: Mapped[str | None] = mapped_column(String(120))
    cadence_days: Mapped[int] = mapped_column(Integer, default=30)
    authoritative: Mapped[bool] = mapped_column(Boolean, default=True)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    notes: Mapped[str | None] = mapped_column(Text)
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_changed_at: Mapped[datetime | None] = mapped_column(DateTime)
    current_sha256: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)

    checks: Mapped[list[SourceCheck]] = relationship(back_populates="source")


class CollectionRun(Base):
    __tablename__ = "ctd_collection_run"

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)
    collector: Mapped[str] = mapped_column(String(80), index=True)
    status: Mapped[str] = mapped_column(String(20), default="running", index=True)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime)
    source_count: Mapped[int] = mapped_column(Integer, default=0)
    records_seen: Mapped[int] = mapped_column(Integer, default=0)
    records_inserted: Mapped[int] = mapped_column(Integer, default=0)
    records_updated: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSON)


class SourceCheck(Base):
    __tablename__ = "ctd_source_check"
    __table_args__ = (Index("ix_ctd_source_check_source_checked", "source_id", "checked_at"),)

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("ctd_source.id"), index=True)
    run_id: Mapped[int | None] = mapped_column(ForeignKey("ctd_collection_run.id"), index=True)
    checked_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    status_code: Mapped[int | None] = mapped_column(Integer)
    content_sha256: Mapped[str | None] = mapped_column(String(64))
    etag: Mapped[str | None] = mapped_column(String(255))
    last_modified: Mapped[str | None] = mapped_column(String(255))
    changed: Mapped[bool] = mapped_column(Boolean, default=False)
    bytes_received: Mapped[int | None] = mapped_column(BigInteger)
    elapsed_ms: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)

    source: Mapped[Source] = relationship(back_populates="checks")


class Jurisdiction(Base):
    __tablename__ = "ctd_jurisdiction"
    __table_args__ = (
        UniqueConstraint("external_key", "valid_from", name="uq_ctd_jurisdiction_key_from"),
        Index("ix_ctd_jurisdiction_location", "country_iso", "state_code", "tax_level"),
    )

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)
    external_key: Mapped[str] = mapped_column(String(160), index=True)
    country_iso: Mapped[str] = mapped_column(String(3), default="USA")
    tax_level: Mapped[int] = mapped_column(Integer, index=True)
    name: Mapped[str] = mapped_column(String(255))
    state_code: Mapped[str | None] = mapped_column(String(2), index=True)
    county_name: Mapped[str | None] = mapped_column(String(120))
    locality_name: Mapped[str | None] = mapped_column(String(160))
    fips_code: Mapped[str | None] = mapped_column(String(16), index=True)
    parent_external_key: Mapped[str | None] = mapped_column(String(160))
    valid_from: Mapped[date] = mapped_column(Date, default=date(1900, 1, 1))
    valid_to: Mapped[date | None] = mapped_column(Date)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("ctd_source.id"))
    metadata_json: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class PostalAssignment(Base):
    __tablename__ = "ctd_postal_assignment"
    __table_args__ = (
        UniqueConstraint(
            "postal_code",
            "plus4_low",
            "plus4_high",
            "jurisdiction_id",
            "valid_from",
            name="uq_ctd_postal_assignment",
        ),
        Index("ix_ctd_postal_assignment_lookup", "postal_code", "valid_from", "valid_to"),
    )

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)
    postal_code: Mapped[str] = mapped_column(String(10))
    plus4_low: Mapped[str | None] = mapped_column(String(4))
    plus4_high: Mapped[str | None] = mapped_column(String(4))
    jurisdiction_id: Mapped[int] = mapped_column(ForeignKey("ctd_jurisdiction.id"))
    allocation_ratio: Mapped[Decimal | None] = mapped_column(Numeric(12, 9))
    confidence: Mapped[str] = mapped_column(String(20), default="statistical")
    assignment_method: Mapped[str] = mapped_column(String(80))
    valid_from: Mapped[date] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    source_id: Mapped[int] = mapped_column(ForeignKey("ctd_source.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class TaxFact(Base):
    __tablename__ = "ctd_tax_fact"
    __table_args__ = (
        UniqueConstraint("natural_key", "effective_from", name="uq_ctd_tax_fact_key_from"),
        Index(
            "ix_ctd_tax_fact_current",
            "jurisdiction_id",
            "tax_family",
            "effective_from",
            "effective_to",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)
    natural_key: Mapped[str] = mapped_column(String(255), index=True)
    jurisdiction_id: Mapped[int] = mapped_column(ForeignKey("ctd_jurisdiction.id"), index=True)
    source_id: Mapped[int] = mapped_column(ForeignKey("ctd_source.id"), index=True)
    tax_family: Mapped[str] = mapped_column(String(60), index=True)
    tax_name: Mapped[str] = mapped_column(String(255), index=True)
    service_category: Mapped[str] = mapped_column(String(100), default="general")
    tax_type_code: Mapped[str | None] = mapped_column(String(80))
    rate: Mapped[Decimal | None] = mapped_column(Numeric(18, 9))
    flat_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    unit: Mapped[str] = mapped_column(String(40), default="percent_of_base")
    max_base: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    min_base: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    base_rule: Mapped[str | None] = mapped_column(Text)
    effective_from: Mapped[date] = mapped_column(Date, index=True)
    effective_to: Mapped[date | None] = mapped_column(Date, index=True)
    legal_citation: Mapped[str | None] = mapped_column(Text)
    source_locator: Mapped[str | None] = mapped_column(Text)
    content_sha256: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(20), default="published")
    observed_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    raw_payload: Mapped[dict[str, Any] | None] = mapped_column(JSON)


class BenchmarkJurisdiction(Base):
    __tablename__ = "ctd_benchmark_jurisdiction"
    __table_args__ = (Index("ix_ctd_benchmark_jurisdiction_zip", "country_iso", "zip_begin"),)

    benchmark_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    p_code: Mapped[int] = mapped_column(BigInteger, index=True)
    alternate: Mapped[bool] = mapped_column(Boolean)
    country_iso: Mapped[str] = mapped_column(String(3))
    state_code: Mapped[str] = mapped_column(String(2), index=True)
    county_name: Mapped[str] = mapped_column(String(60))
    locality_name: Mapped[str] = mapped_column(String(80))
    zip_begin: Mapped[str] = mapped_column(String(10))
    zip_end: Mapped[str] = mapped_column(String(10))
    source_timestamp: Mapped[datetime] = mapped_column(DateTime)
    synced_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class BenchmarkRate(Base):
    __tablename__ = "ctd_benchmark_rate"
    __table_args__ = (
        UniqueConstraint("p_code", "tax_type", "tax_level", "effective_date", "level_exemptible"),
        Index("ix_ctd_benchmark_rate_active", "active", "p_code", "tax_level"),
    )

    benchmark_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    p_code: Mapped[int] = mapped_column(BigInteger, index=True)
    tax_type: Mapped[int] = mapped_column(Integer)
    tax_level: Mapped[int] = mapped_column(Integer)
    effective_date: Mapped[datetime] = mapped_column(DateTime)
    active: Mapped[bool] = mapped_column(Boolean)
    tax_category: Mapped[str | None] = mapped_column(String(100))
    tax_description: Mapped[str | None] = mapped_column(String(160))
    level_exemptible: Mapped[bool] = mapped_column(Boolean)
    rate: Mapped[Decimal | None] = mapped_column(Numeric(18, 9))
    max_base: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    county_override_tax: Mapped[Decimal | None] = mapped_column(Numeric(18, 9))
    state_override_tax: Mapped[Decimal | None] = mapped_column(Numeric(18, 9))
    state_override_on: Mapped[bool | None] = mapped_column(Boolean)
    county_override_on: Mapped[bool | None] = mapped_column(Boolean)
    source_timestamp: Mapped[datetime] = mapped_column(DateTime)
    synced_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class CoverageException(Base):
    __tablename__ = "ctd_coverage_exception"
    __table_args__ = (
        Index("ix_ctd_exception_open", "status", "severity", "exception_type"),
        Index("ix_ctd_exception_benchmark", "benchmark_rate_id", "benchmark_jurisdiction_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)
    comparison_run_id: Mapped[int] = mapped_column(ForeignKey("ctd_collection_run.id"), index=True)
    exception_type: Mapped[str] = mapped_column(String(60), index=True)
    severity: Mapped[str] = mapped_column(String(20), index=True)
    status: Mapped[str] = mapped_column(String(20), default="open")
    state_code: Mapped[str | None] = mapped_column(String(2), index=True)
    jurisdiction_label: Mapped[str | None] = mapped_column(String(255))
    benchmark_rate_id: Mapped[int | None] = mapped_column(BigInteger)
    benchmark_jurisdiction_id: Mapped[int | None] = mapped_column(BigInteger)
    public_tax_fact_id: Mapped[int | None] = mapped_column(ForeignKey("ctd_tax_fact.id"))
    summary: Mapped[str] = mapped_column(Text)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    detected_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime)
