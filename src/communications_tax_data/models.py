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


class BenchmarkRateChange(Base):
    """Append-only mirror of the commercial benchmark's rate changelog."""

    __tablename__ = "ctd_benchmark_rate_change"
    __table_args__ = (
        Index("ix_ctd_benchmark_change_run", "run_timestamp"),
        Index(
            "ix_ctd_benchmark_change_rule",
            "p_code",
            "tax_type",
            "tax_level",
            "run_timestamp",
        ),
    )

    benchmark_change_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    source_timestamp: Mapped[datetime] = mapped_column(DateTime)
    run_timestamp: Mapped[datetime] = mapped_column(DateTime)
    p_code: Mapped[int] = mapped_column(BigInteger)
    tax_category: Mapped[str | None] = mapped_column(String(100))
    tax_description: Mapped[str | None] = mapped_column(String(160))
    old_effective_date: Mapped[datetime] = mapped_column(DateTime)
    new_effective_date: Mapped[datetime] = mapped_column(DateTime)
    old_rate: Mapped[Decimal] = mapped_column(Numeric(18, 9))
    new_rate: Mapped[Decimal] = mapped_column(Numeric(18, 9))
    tax_type: Mapped[int] = mapped_column(Integer)
    tax_level: Mapped[int] = mapped_column(Integer)
    synced_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class CustomerTaxNeed(Base):
    """Customer-level priority snapshot derived from actual non-zero invoice tax."""

    __tablename__ = "ctd_customer_tax_need"
    __table_args__ = (
        Index("ix_ctd_customer_need_priority", "active_customer", "last_tax_invoice"),
        Index("ix_ctd_customer_need_location", "p_code", "postal_code"),
    )

    customer_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    customer_number: Mapped[int] = mapped_column(Integer, index=True)
    p_code: Mapped[int | None] = mapped_column(BigInteger, index=True)
    postal_code: Mapped[str | None] = mapped_column(String(10), index=True)
    plus_four: Mapped[str | None] = mapped_column(String(4))
    state_code: Mapped[str | None] = mapped_column(String(8), index=True)
    country_code: Mapped[str | None] = mapped_column(String(3))
    active_customer: Mapped[bool] = mapped_column(Boolean, index=True)
    first_tax_invoice: Mapped[datetime | None] = mapped_column(DateTime)
    last_tax_invoice: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    tax_charge_rows: Mapped[int] = mapped_column(BigInteger)
    absolute_tax_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    synced_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class CustomerTaxNeedDetail(Base):
    """Billed-tax demand by customer, p_code, benchmark tax type, and level."""

    __tablename__ = "ctd_customer_tax_need_detail"
    __table_args__ = (
        Index(
            "ix_ctd_customer_need_detail_priority",
            "active_customer",
            "tax_level",
            "trailing_12m_tax_amount",
        ),
        Index(
            "ix_ctd_customer_need_detail_location",
            "p_code",
            "tax_type",
            "tax_level",
        ),
        Index(
            "ix_ctd_customer_need_detail_state",
            "state_code",
            "tax_level",
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True
    )
    detail_key: Mapped[str] = mapped_column(String(64), unique=True)
    customer_id: Mapped[int] = mapped_column(BigInteger, index=True)
    customer_number: Mapped[int] = mapped_column(Integer, index=True)
    p_code: Mapped[int] = mapped_column(BigInteger, index=True)
    postal_code: Mapped[str | None] = mapped_column(String(10), index=True)
    plus_four: Mapped[str | None] = mapped_column(String(4))
    state_code: Mapped[str | None] = mapped_column(String(8), index=True)
    country_code: Mapped[str | None] = mapped_column(String(3))
    tax_type: Mapped[int] = mapped_column(Integer, index=True)
    tax_level: Mapped[int] = mapped_column(Integer, index=True)
    tax_category: Mapped[str | None] = mapped_column(String(100))
    tax_description: Mapped[str | None] = mapped_column(String(160))
    active_customer: Mapped[bool] = mapped_column(Boolean, index=True)
    first_tax_invoice: Mapped[datetime | None] = mapped_column(DateTime)
    last_tax_invoice: Mapped[datetime | None] = mapped_column(DateTime, index=True)
    tax_charge_rows: Mapped[int] = mapped_column(BigInteger)
    lifetime_tax_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2))
    trailing_window_start: Mapped[date] = mapped_column(Date)
    trailing_12m_charge_rows: Mapped[int] = mapped_column(BigInteger)
    trailing_12m_tax_amount: Mapped[Decimal] = mapped_column(Numeric(18, 2), index=True)
    synced_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class TaxTypeCrosswalk(Base):
    """Auditable mapping from benchmark type/level semantics to CTD concepts."""

    __tablename__ = "ctd_tax_type_crosswalk"
    __table_args__ = (
        Index("ix_ctd_tax_crosswalk_type", "benchmark_tax_type", "benchmark_tax_level"),
        Index("ix_ctd_tax_crosswalk_status", "mapping_status", "ctd_tax_concept"),
    )

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)
    benchmark_signature: Mapped[str] = mapped_column(String(64), unique=True)
    benchmark_tax_type: Mapped[int] = mapped_column(Integer)
    benchmark_tax_level: Mapped[int] = mapped_column(Integer)
    benchmark_tax_category: Mapped[str | None] = mapped_column(String(100))
    benchmark_tax_description: Mapped[str | None] = mapped_column(String(160))
    ctd_tax_concept: Mapped[str | None] = mapped_column(String(100), index=True)
    service_category: Mapped[str | None] = mapped_column(String(100))
    mapping_status: Mapped[str] = mapped_column(String(20), default="proposed")
    mapping_method: Mapped[str] = mapped_column(String(60), default="normalized_description")
    confidence: Mapped[str] = mapped_column(String(20), default="candidate")
    legal_citation: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    reviewed_by: Mapped[str | None] = mapped_column(String(120))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class TaxFactBenchmarkMap(Base):
    """State-aware link from one benchmark type/level to a public legal fact."""

    __tablename__ = "ctd_tax_fact_benchmark_map"
    __table_args__ = (
        UniqueConstraint("natural_key", "effective_from", name="uq_ctd_fact_benchmark_map"),
        Index(
            "ix_ctd_fact_benchmark_map_lookup",
            "benchmark_tax_type",
            "benchmark_tax_level",
            "state_code",
            "p_code",
        ),
    )

    id: Mapped[int] = mapped_column(
        BigInteger().with_variant(Integer, "sqlite"), primary_key=True
    )
    natural_key: Mapped[str] = mapped_column(String(255), index=True)
    public_fact_natural_key: Mapped[str] = mapped_column(String(255), index=True)
    benchmark_tax_type: Mapped[int] = mapped_column(Integer, index=True)
    benchmark_tax_level: Mapped[int] = mapped_column(Integer, index=True)
    state_code: Mapped[str | None] = mapped_column(String(8), index=True)
    p_code: Mapped[int | None] = mapped_column(BigInteger, index=True)
    service_category: Mapped[str | None] = mapped_column(String(100))
    mapping_status: Mapped[str] = mapped_column(String(20), default="proposed")
    mapping_method: Mapped[str] = mapped_column(String(60))
    confidence: Mapped[str] = mapped_column(String(20), default="candidate")
    legal_citation: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    effective_from: Mapped[date] = mapped_column(Date, default=date(1900, 1, 1))
    effective_to: Mapped[date | None] = mapped_column(Date)
    reviewed_by: Mapped[str | None] = mapped_column(String(120))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class CoverageMetric(Base):
    """One denominator/numerator result from a reproducible comparison run."""

    __tablename__ = "ctd_coverage_metric"
    __table_args__ = (
        UniqueConstraint("comparison_run_id", "scope", "dimension", name="uq_ctd_metric_run"),
        Index("ix_ctd_metric_latest", "scope", "dimension", "measured_at"),
    )

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)
    comparison_run_id: Mapped[int] = mapped_column(
        ForeignKey("ctd_collection_run.id"), index=True
    )
    measured_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    as_of_date: Mapped[date] = mapped_column(Date)
    scope: Mapped[str] = mapped_column(String(40))
    dimension: Mapped[str] = mapped_column(String(60))
    numerator: Mapped[int] = mapped_column(BigInteger)
    denominator: Mapped[int] = mapped_column(BigInteger)
    percent: Mapped[Decimal | None] = mapped_column(Numeric(9, 4))
    details: Mapped[dict[str, Any] | None] = mapped_column(JSON)


class TaxFactChange(Base):
    """Append-only field-level audit trail for normalized public facts."""

    __tablename__ = "ctd_tax_fact_change"
    __table_args__ = (
        Index("ix_ctd_fact_change_fact", "tax_fact_id", "detected_at"),
        Index("ix_ctd_fact_change_run", "collection_run_id"),
    )

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)
    tax_fact_id: Mapped[int] = mapped_column(ForeignKey("ctd_tax_fact.id"), index=True)
    collection_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("ctd_collection_run.id"), index=True
    )
    change_type: Mapped[str] = mapped_column(String(20))
    natural_key: Mapped[str] = mapped_column(String(255), index=True)
    effective_from: Mapped[date] = mapped_column(Date)
    changed_fields: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    old_content_sha256: Mapped[str | None] = mapped_column(String(64))
    new_content_sha256: Mapped[str] = mapped_column(String(64))
    detected_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    tax_fact: Mapped[TaxFact] = relationship()


class FilingEntity(Base):
    """Government or administrator that receives a return and/or payment."""

    __tablename__ = "ctd_filing_entity"

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)
    entity_code: Mapped[str] = mapped_column(String(120), unique=True)
    name: Mapped[str] = mapped_column(String(255))
    payee_name: Mapped[str | None] = mapped_column(String(255))
    entity_type: Mapped[str] = mapped_column(String(60))
    tax_level: Mapped[int] = mapped_column(Integer, index=True)
    state_code: Mapped[str | None] = mapped_column(String(8), index=True)
    jurisdiction_external_key: Mapped[str | None] = mapped_column(String(160), index=True)
    website_url: Mapped[str] = mapped_column(Text)
    filing_portal_url: Mapped[str | None] = mapped_column(Text)
    payment_url: Mapped[str | None] = mapped_column(Text)
    registration_url: Mapped[str | None] = mapped_column(Text)
    mailing_address: Mapped[str | None] = mapped_column(Text)
    legal_citation: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="proposed")
    effective_from: Mapped[date] = mapped_column(Date, default=date(1900, 1, 1))
    effective_to: Mapped[date | None] = mapped_column(Date)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class FilingDocument(Base):
    """Return, instruction, worksheet, registration, or exemption document."""

    __tablename__ = "ctd_filing_document"
    __table_args__ = (
        UniqueConstraint(
            "filing_entity_id",
            "document_type",
            "form_number",
            "effective_from",
            name="uq_ctd_filing_document",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)
    filing_entity_id: Mapped[int] = mapped_column(ForeignKey("ctd_filing_entity.id"), index=True)
    document_type: Mapped[str] = mapped_column(String(40), index=True)
    form_number: Mapped[str] = mapped_column(String(80), default="")
    title: Mapped[str] = mapped_column(String(255))
    url: Mapped[str] = mapped_column(Text)
    instructions_url: Mapped[str | None] = mapped_column(Text)
    effective_from: Mapped[date] = mapped_column(Date, default=date(1900, 1, 1))
    effective_to: Mapped[date | None] = mapped_column(Date)
    status: Mapped[str] = mapped_column(String(20), default="proposed")
    source_locator: Mapped[str | None] = mapped_column(Text)
    content_sha256: Mapped[str | None] = mapped_column(String(64))
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class TaxFilingMap(Base):
    """Effective-dated rule connecting a tax identity/location to its filing entity."""

    __tablename__ = "ctd_tax_filing_map"
    __table_args__ = (
        UniqueConstraint("natural_key", "effective_from", name="uq_ctd_filing_map"),
        Index(
            "ix_ctd_filing_map_lookup",
            "benchmark_tax_type",
            "tax_level",
            "state_code",
            "p_code",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)
    natural_key: Mapped[str] = mapped_column(String(255), index=True)
    benchmark_tax_type: Mapped[int | None] = mapped_column(Integer)
    tax_level: Mapped[int] = mapped_column(Integer)
    ctd_tax_concept: Mapped[str] = mapped_column(String(100), index=True)
    state_code: Mapped[str | None] = mapped_column(String(8), index=True)
    p_code: Mapped[int | None] = mapped_column(BigInteger, index=True)
    jurisdiction_external_key: Mapped[str | None] = mapped_column(String(160), index=True)
    filing_entity_id: Mapped[int] = mapped_column(ForeignKey("ctd_filing_entity.id"), index=True)
    payment_entity_id: Mapped[int | None] = mapped_column(
        ForeignKey("ctd_filing_entity.id"), index=True
    )
    return_document_id: Mapped[int | None] = mapped_column(ForeignKey("ctd_filing_document.id"))
    exemption_document_id: Mapped[int | None] = mapped_column(
        ForeignKey("ctd_filing_document.id")
    )
    filing_frequency: Mapped[str | None] = mapped_column(String(40))
    due_rule: Mapped[str | None] = mapped_column(Text)
    reporting_basis: Mapped[str | None] = mapped_column(Text)
    payment_recipient: Mapped[str | None] = mapped_column(String(255))
    legal_citation: Mapped[str | None] = mapped_column(Text)
    mapping_status: Mapped[str] = mapped_column(String(20), default="proposed")
    effective_from: Mapped[date] = mapped_column(Date, default=date(1900, 1, 1))
    effective_to: Mapped[date | None] = mapped_column(Date)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class LocationProfile(Base):
    """CTD-owned, effective-dated jurisdiction-set identifier (p_code equivalent)."""

    __tablename__ = "ctd_location_profile"
    __table_args__ = (
        Index("ix_ctd_location_profile_postal", "postal_code", "plus_four"),
        Index("ix_ctd_location_profile_benchmark", "benchmark_p_code"),
    )

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)
    profile_code: Mapped[str] = mapped_column(String(40), unique=True)
    composition_sha256: Mapped[str] = mapped_column(String(64), index=True)
    country_iso: Mapped[str] = mapped_column(String(3), default="USA")
    state_code: Mapped[str | None] = mapped_column(String(8), index=True)
    postal_code: Mapped[str | None] = mapped_column(String(10), index=True)
    plus_four: Mapped[str | None] = mapped_column(String(4))
    benchmark_p_code: Mapped[int | None] = mapped_column(BigInteger)
    assignment_method: Mapped[str] = mapped_column(String(80))
    confidence: Mapped[str] = mapped_column(String(20))
    calculation_ready: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(20), default="candidate")
    valid_from: Mapped[date] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class LocationProfileMember(Base):
    __tablename__ = "ctd_location_profile_member"
    __table_args__ = (
        UniqueConstraint(
            "location_profile_id",
            "jurisdiction_id",
            "member_role",
            name="uq_ctd_location_profile_member",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)
    location_profile_id: Mapped[int] = mapped_column(
        ForeignKey("ctd_location_profile.id"), index=True
    )
    jurisdiction_id: Mapped[int] = mapped_column(ForeignKey("ctd_jurisdiction.id"), index=True)
    member_role: Mapped[str] = mapped_column(String(20), default="candidate")
    allocation_ratio: Mapped[Decimal | None] = mapped_column(Numeric(12, 9))
    evidence: Mapped[dict[str, Any] | None] = mapped_column(JSON)


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
