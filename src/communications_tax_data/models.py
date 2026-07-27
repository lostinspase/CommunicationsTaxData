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

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)
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

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)
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
    comparison_run_id: Mapped[int] = mapped_column(ForeignKey("ctd_collection_run.id"), index=True)
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


class ProductTaxonomyMap(Base):
    """Effective-dated mapping from an Apeiron tax group to a CTD service class."""

    __tablename__ = "ctd_product_taxonomy_map"
    __table_args__ = (
        UniqueConstraint(
            "source_system",
            "source_tax_group",
            "effective_from",
            name="uq_ctd_product_taxonomy_map",
        ),
        Index(
            "ix_ctd_product_taxonomy_current",
            "source_system",
            "source_tax_group",
            "effective_from",
            "effective_to",
        ),
        Index(
            "ix_ctd_product_taxonomy_review",
            "mapping_status",
            "service_category",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)
    source_system: Mapped[str] = mapped_column(String(80), default="apeiron_product")
    source_tax_group: Mapped[str] = mapped_column(String(100))
    service_category: Mapped[str | None] = mapped_column(String(100), index=True)
    default_sourcing_role: Mapped[str | None] = mapped_column(String(40))
    mapping_status: Mapped[str] = mapped_column(String(30), default="proposed", index=True)
    mapping_method: Mapped[str] = mapped_column(String(60), default="internal_tax_group_candidate")
    confidence: Mapped[str] = mapped_column(String(20), default="candidate")
    source_reference: Mapped[str | None] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    effective_from: Mapped[date] = mapped_column(Date, default=date(1900, 1, 1))
    effective_to: Mapped[date | None] = mapped_column(Date)
    reviewed_by: Mapped[str | None] = mapped_column(String(120))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class ProductCatalogItem(Base):
    """Replaceable snapshot of tax-relevant Apeiron product attributes."""

    __tablename__ = "ctd_product_catalog_item"
    __table_args__ = (Index("ix_ctd_product_catalog_tax_group", "source_tax_group", "active"),)

    source_product_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    sku: Mapped[str] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(String(255))
    active: Mapped[bool] = mapped_column(Boolean, index=True)
    product_type: Mapped[str | None] = mapped_column(String(200))
    source_tax_type: Mapped[str | None] = mapped_column(String(200))
    source_tax_group: Mapped[str] = mapped_column(String(100), index=True)
    billing_type: Mapped[str | None] = mapped_column(String(32))
    charge_frequency: Mapped[str | None] = mapped_column(String(32))
    report_category: Mapped[str | None] = mapped_column(String(100))
    product_platform: Mapped[str | None] = mapped_column(String(100))
    interstate_percent: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    intrastate_percent: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    voice_percent: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    sms_percent: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    wireless_data_percent: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    transport_percent: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    synced_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class CustomerTaxProfile(Base):
    """Privacy-limited snapshot of source tax flags used as an exemption warning."""

    __tablename__ = "ctd_customer_tax_profile"
    __table_args__ = (
        Index("ix_ctd_customer_tax_profile_address", "source_address_id"),
        Index("ix_ctd_customer_tax_profile_active", "active_customer", "customer_number"),
    )

    customer_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    customer_number: Mapped[int] = mapped_column(Integer, index=True)
    source_address_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    active_customer: Mapped[bool] = mapped_column(Boolean, index=True)
    source_tax_exempt: Mapped[bool] = mapped_column(Boolean, default=False)
    source_tax_exempt_federal: Mapped[bool] = mapped_column(Boolean, default=False)
    source_tax_exempt_state: Mapped[bool] = mapped_column(Boolean, default=False)
    source_tax_exempt_local: Mapped[bool] = mapped_column(Boolean, default=False)
    evidence_status: Mapped[str] = mapped_column(String(30), default="source_flag_only")
    synced_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class CustomerExemption(Base):
    """Structured exemption evidence; document contents remain outside CTD."""

    __tablename__ = "ctd_customer_exemption"
    __table_args__ = (
        UniqueConstraint(
            "customer_id",
            "exemption_type",
            "tax_level",
            "state_code",
            "jurisdiction_external_key",
            "service_category",
            "valid_from",
            name="uq_ctd_customer_exemption_scope",
        ),
        Index(
            "ix_ctd_customer_exemption_current",
            "customer_id",
            "status",
            "valid_from",
            "valid_to",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)
    customer_id: Mapped[int] = mapped_column(BigInteger, index=True)
    exemption_type: Mapped[str] = mapped_column(String(60))
    tax_level: Mapped[int | None] = mapped_column(Integer, index=True)
    state_code: Mapped[str | None] = mapped_column(String(8), index=True)
    jurisdiction_external_key: Mapped[str | None] = mapped_column(String(160), index=True)
    service_category: Mapped[str | None] = mapped_column(String(100), index=True)
    document_reference: Mapped[str | None] = mapped_column(String(255))
    certificate_reference: Mapped[str | None] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(30), default="proposed", index=True)
    valid_from: Mapped[date] = mapped_column(Date)
    valid_to: Mapped[date | None] = mapped_column(Date)
    verified_by: Mapped[str | None] = mapped_column(String(120))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class ServiceProductDemand(Base):
    """Trailing-period billed product demand used to prioritize tax determinations."""

    __tablename__ = "ctd_service_product_demand"
    __table_args__ = (
        Index(
            "ix_ctd_service_product_demand_priority",
            "active_customer",
            "trailing_billed_amount",
        ),
        Index(
            "ix_ctd_service_product_demand_address",
            "source_address_id",
            "source_tax_group",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)
    demand_key: Mapped[str] = mapped_column(String(64), unique=True)
    customer_id: Mapped[int] = mapped_column(BigInteger, index=True)
    customer_number: Mapped[int] = mapped_column(Integer, index=True)
    source_address_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    source_product_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    source_tax_group: Mapped[str] = mapped_column(String(100), index=True)
    charge_type: Mapped[str] = mapped_column(String(40), index=True)
    active_customer: Mapped[bool] = mapped_column(Boolean, index=True)
    first_invoice_at: Mapped[datetime] = mapped_column(DateTime)
    last_invoice_at: Mapped[datetime] = mapped_column(DateTime, index=True)
    invoice_count: Mapped[int] = mapped_column(BigInteger)
    charge_rows: Mapped[int] = mapped_column(BigInteger)
    quantity: Mapped[Decimal] = mapped_column(Numeric(24, 6), default=Decimal("0"))
    trailing_billed_amount: Mapped[Decimal] = mapped_column(Numeric(24, 2), index=True)
    trailing_window_start: Mapped[date] = mapped_column(Date)
    synced_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class TaxabilityRule(Base):
    """Reviewed service-level applicability and calculation rule for one tax concept."""

    __tablename__ = "ctd_taxability_rule"
    __table_args__ = (
        UniqueConstraint("natural_key", "effective_from", name="uq_ctd_taxability_rule"),
        Index(
            "ix_ctd_taxability_rule_lookup",
            "ctd_tax_concept",
            "tax_level",
            "state_code",
            "service_category",
        ),
        Index("ix_ctd_taxability_rule_review", "review_status", "effective_to"),
    )

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)
    natural_key: Mapped[str] = mapped_column(String(255), index=True)
    ctd_tax_concept: Mapped[str] = mapped_column(String(100), index=True)
    tax_fact_natural_key: Mapped[str | None] = mapped_column(String(255), index=True)
    tax_level: Mapped[int] = mapped_column(Integer, index=True)
    state_code: Mapped[str | None] = mapped_column(String(8), index=True)
    p_code: Mapped[int | None] = mapped_column(BigInteger, index=True)
    jurisdiction_external_key: Mapped[str | None] = mapped_column(String(160), index=True)
    service_category: Mapped[str] = mapped_column(String(100), index=True)
    charge_type: Mapped[str | None] = mapped_column(String(40))
    taxability: Mapped[str] = mapped_column(String(30), index=True)
    sourcing_role: Mapped[str] = mapped_column(String(40), default="service_address")
    calculation_method: Mapped[str] = mapped_column(String(40), default="manual")
    taxable_percentage: Mapped[Decimal | None] = mapped_column(Numeric(9, 6))
    base_rule: Mapped[str | None] = mapped_column(Text)
    filing_required: Mapped[bool] = mapped_column(Boolean, default=True)
    legal_citation: Mapped[str] = mapped_column(Text)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("ctd_source.id"), index=True)
    review_status: Mapped[str] = mapped_column(String(30), default="proposed", index=True)
    confidence: Mapped[str] = mapped_column(String(20), default="candidate")
    effective_from: Mapped[date] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)
    reviewed_by: Mapped[str | None] = mapped_column(String(120))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class NexusRule(Base):
    """Effective-dated state rule used to screen remote-seller nexus exposure.

    A threshold rule is evidence about state law, not a determination that Apeiron
    has nexus.  The normalized basis fields deliberately preserve distinctions such
    as gross sales, taxable sales, retail sales, and tangible personal property.
    """

    __tablename__ = "ctd_nexus_rule"
    __table_args__ = (
        UniqueConstraint(
            "state_code",
            "tax_family",
            "trigger_type",
            "effective_from",
            name="uq_ctd_nexus_rule",
        ),
        Index(
            "ix_ctd_nexus_rule_current",
            "state_code",
            "tax_family",
            "effective_from",
            "effective_to",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)
    state_code: Mapped[str] = mapped_column(String(8), index=True)
    tax_family: Mapped[str] = mapped_column(String(60), default="sales_and_use", index=True)
    trigger_type: Mapped[str] = mapped_column(String(40), default="economic")
    statewide_sales_tax: Mapped[bool] = mapped_column(Boolean, default=True)
    threshold_amount: Mapped[Decimal | None] = mapped_column(Numeric(18, 2))
    threshold_amount_inclusive: Mapped[bool] = mapped_column(Boolean, default=False)
    transaction_threshold: Mapped[int | None] = mapped_column(Integer)
    transaction_threshold_inclusive: Mapped[bool] = mapped_column(Boolean, default=True)
    threshold_operator: Mapped[str] = mapped_column(String(20), default="amount_only")
    threshold_basis: Mapped[str] = mapped_column(String(60))
    threshold_rule_text: Mapped[str] = mapped_column(Text)
    lookback_period: Mapped[str] = mapped_column(String(60))
    service_revenue_treatment: Mapped[str] = mapped_column(
        String(40), default="requires_taxability_review"
    )
    remote_seller_effective_date: Mapped[date | None] = mapped_column(Date)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("ctd_source.id"), index=True)
    source_url: Mapped[str] = mapped_column(Text)
    legal_citation: Mapped[str | None] = mapped_column(Text)
    review_status: Mapped[str] = mapped_column(String(30), default="screening", index=True)
    effective_from: Mapped[date] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class CompanyNexusDetermination(Base):
    """Human-reviewable Apeiron nexus, registration, and collection decision."""

    __tablename__ = "ctd_company_nexus_determination"
    __table_args__ = (
        UniqueConstraint(
            "state_code",
            "tax_family",
            "effective_from",
            name="uq_ctd_company_nexus_determination",
        ),
        Index(
            "ix_ctd_company_nexus_current",
            "state_code",
            "tax_family",
            "effective_from",
            "effective_to",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)
    state_code: Mapped[str] = mapped_column(String(8), index=True)
    tax_family: Mapped[str] = mapped_column(String(60), default="sales_and_use", index=True)
    physical_presence_status: Mapped[str] = mapped_column(
        String(30), default="not_assessed", index=True
    )
    economic_nexus_status: Mapped[str] = mapped_column(
        String(30), default="not_assessed", index=True
    )
    obligation_status: Mapped[str] = mapped_column(String(30), default="not_assessed", index=True)
    registration_status: Mapped[str] = mapped_column(String(30), default="not_recorded", index=True)
    collection_status: Mapped[str] = mapped_column(String(30), default="not_started", index=True)
    registration_reference: Mapped[str | None] = mapped_column(String(160))
    collection_start_date: Mapped[date | None] = mapped_column(Date)
    determination_basis: Mapped[str | None] = mapped_column(Text)
    evidence_reference: Mapped[str | None] = mapped_column(Text)
    review_status: Mapped[str] = mapped_column(String(30), default="proposed", index=True)
    reviewed_by: Mapped[str | None] = mapped_column(String(120))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime)
    effective_from: Mapped[date] = mapped_column(Date)
    effective_to: Mapped[date | None] = mapped_column(Date)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class StateNexusExposure(Base):
    """Calendar-period state revenue screen; not a legal threshold numerator."""

    __tablename__ = "ctd_state_nexus_exposure"
    __table_args__ = (
        UniqueConstraint(
            "state_code",
            "period_start",
            "period_end",
            "measurement_method",
            name="uq_ctd_state_nexus_exposure",
        ),
        Index(
            "ix_ctd_state_nexus_exposure_period",
            "period_start",
            "period_end",
            "state_code",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)
    state_code: Mapped[str] = mapped_column(String(8), index=True)
    period_start: Mapped[date] = mapped_column(Date, index=True)
    period_end: Mapped[date] = mapped_column(Date, index=True)
    as_of_date: Mapped[date] = mapped_column(Date)
    gross_billed_amount: Mapped[Decimal] = mapped_column(Numeric(24, 2), default=Decimal("0"))
    tpp_candidate_amount: Mapped[Decimal] = mapped_column(Numeric(24, 2), default=Decimal("0"))
    service_candidate_amount: Mapped[Decimal] = mapped_column(Numeric(24, 2), default=Decimal("0"))
    unclassified_amount: Mapped[Decimal] = mapped_column(Numeric(24, 2), default=Decimal("0"))
    invoice_count: Mapped[int] = mapped_column(BigInteger, default=0)
    customer_count: Mapped[int] = mapped_column(BigInteger, default=0)
    measurement_method: Mapped[str] = mapped_column(String(80), default="gross_billed_screen")
    source_system: Mapped[str] = mapped_column(String(80), default="apeiron_invoice_summary")
    limitations: Mapped[str] = mapped_column(Text)
    collection_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("ctd_collection_run.id"), index=True
    )
    calculated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class NexusAssessment(Base):
    """Append-only daily nexus screen by state and tax family."""

    __tablename__ = "ctd_nexus_assessment"
    __table_args__ = (
        UniqueConstraint(
            "assessment_run_id",
            "state_code",
            "tax_family",
            name="uq_ctd_nexus_assessment_run_state",
        ),
        Index(
            "ix_ctd_nexus_assessment_daily",
            "assessment_date",
            "status",
            "state_code",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)
    assessment_run_id: Mapped[int] = mapped_column(ForeignKey("ctd_collection_run.id"), index=True)
    assessment_date: Mapped[date] = mapped_column(Date, index=True)
    state_code: Mapped[str] = mapped_column(String(8), index=True)
    tax_family: Mapped[str] = mapped_column(String(60), default="sales_and_use", index=True)
    nexus_rule_id: Mapped[int | None] = mapped_column(ForeignKey("ctd_nexus_rule.id"))
    company_determination_id: Mapped[int | None] = mapped_column(
        ForeignKey("ctd_company_nexus_determination.id")
    )
    exposure_id: Mapped[int | None] = mapped_column(ForeignKey("ctd_state_nexus_exposure.id"))
    previous_assessment_id: Mapped[int | None] = mapped_column(
        ForeignKey("ctd_nexus_assessment.id"), index=True
    )
    status: Mapped[str] = mapped_column(String(30), index=True)
    threshold_basis_amount: Mapped[Decimal | None] = mapped_column(Numeric(24, 2))
    gross_screen_amount: Mapped[Decimal | None] = mapped_column(Numeric(24, 2))
    threshold_percent: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    amount_threshold_triggered: Mapped[bool | None] = mapped_column(Boolean)
    transaction_threshold_triggered: Mapped[bool | None] = mapped_column(Boolean)
    assessment_changed: Mapped[bool] = mapped_column(Boolean, default=False)
    gap_codes: Mapped[list[str] | None] = mapped_column(JSON)
    details: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    assessment_sha256: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class SalesTaxProvider(Base):
    """Non-secret configuration and readiness record for a Type 1 tax API."""

    __tablename__ = "ctd_sales_tax_provider"

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)
    provider_code: Mapped[str] = mapped_column(String(80), unique=True)
    provider_name: Mapped[str] = mapped_column(String(160))
    status: Mapped[str] = mapped_column(String(30), default="candidate", index=True)
    certified_service_provider: Mapped[bool] = mapped_column(Boolean, default=False)
    calculation_api: Mapped[bool] = mapped_column(Boolean, default=False)
    returns_filing: Mapped[bool] = mapped_column(Boolean, default=False)
    exemption_support: Mapped[bool] = mapped_column(Boolean, default=False)
    configured_nexus_states: Mapped[list[str] | None] = mapped_column(JSON)
    capabilities: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    website_url: Mapped[str] = mapped_column(Text)
    notes: Mapped[str | None] = mapped_column(Text)
    last_health_check_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class SalesTaxZipRate(Base):
    """Deduplicated ZIP-level combined sales/use rate candidate from a licensed file."""

    __tablename__ = "ctd_sales_tax_zip_rate"
    __table_args__ = (
        UniqueConstraint(
            "release_code",
            "postal_code",
            "state_code",
            "county_name",
            "city_name",
            "total_sales_tax",
            "total_use_tax",
            name="uq_ctd_sales_tax_zip_rate",
        ),
        Index(
            "ix_ctd_sales_tax_zip_lookup",
            "postal_code",
            "state_code",
            "release_date",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)
    release_code: Mapped[str] = mapped_column(String(80), index=True)
    release_date: Mapped[date] = mapped_column(Date, index=True)
    release_date_basis: Mapped[str] = mapped_column(String(40), default="filename_inferred")
    postal_code: Mapped[str] = mapped_column(String(10), index=True)
    state_code: Mapped[str] = mapped_column(String(8), index=True)
    county_name: Mapped[str] = mapped_column(String(160))
    city_name: Mapped[str] = mapped_column(String(160))
    total_sales_tax: Mapped[Decimal] = mapped_column(Numeric(18, 9))
    total_use_tax: Mapped[Decimal] = mapped_column(Numeric(18, 9))
    occurrence_count: Mapped[int] = mapped_column(Integer, default=1)
    source_archive: Mapped[str] = mapped_column(Text)
    source_sha256: Mapped[str] = mapped_column(String(64), index=True)
    limitations: Mapped[str] = mapped_column(Text)
    imported_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ExemptionFormArtifact(Base):
    """Metadata for an exemption form downloaded from an authorized source."""

    __tablename__ = "ctd_exemption_form_artifact"
    __table_args__ = (
        UniqueConstraint(
            "provider_code",
            "source_url_sha256",
            name="uq_ctd_exemption_form_source",
        ),
        Index(
            "ix_ctd_exemption_form_state",
            "state_code",
            "form_type",
            "status",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)
    provider_code: Mapped[str] = mapped_column(String(80), index=True)
    state_code: Mapped[str | None] = mapped_column(String(8), index=True)
    jurisdiction_scope: Mapped[str] = mapped_column(String(40), default="state")
    form_type: Mapped[str] = mapped_column(String(60), default="sales_use_exemption")
    form_number: Mapped[str] = mapped_column(String(100), default="")
    title: Mapped[str] = mapped_column(String(500))
    source_page_url: Mapped[str] = mapped_column(Text)
    download_url: Mapped[str] = mapped_column(Text)
    source_url_sha256: Mapped[str] = mapped_column(String(64))
    local_path: Mapped[str | None] = mapped_column(Text)
    mime_type: Mapped[str | None] = mapped_column(String(120))
    bytes_received: Mapped[int | None] = mapped_column(BigInteger)
    content_sha256: Mapped[str | None] = mapped_column(String(64), index=True)
    status: Mapped[str] = mapped_column(String(30), default="cataloged", index=True)
    source_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    retrieved_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class ExemptionFormStateCheck(Base):
    """Daily state-level inventory result from an exemption-form source."""

    __tablename__ = "ctd_exemption_form_state_check"
    __table_args__ = (
        UniqueConstraint(
            "provider_code",
            "state_code",
            "checked_on",
            name="uq_ctd_exemption_form_state_check",
        ),
        Index(
            "ix_ctd_exemption_form_state_check_current",
            "checked_on",
            "status",
            "state_code",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)
    provider_code: Mapped[str] = mapped_column(String(80), index=True)
    state_code: Mapped[str] = mapped_column(String(8), index=True)
    checked_on: Mapped[date] = mapped_column(Date, index=True)
    form_count: Mapped[int] = mapped_column(Integer, default=0)
    downloaded_count: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(50), index=True)
    notice: Mapped[str | None] = mapped_column(Text)
    source_page_url: Mapped[str] = mapped_column(Text)
    source_metadata: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    checked_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


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
    exemption_document_id: Mapped[int | None] = mapped_column(ForeignKey("ctd_filing_document.id"))
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


class AddressAssignment(Base):
    """Effective-dated assignment of an internal address to a CTD jurisdiction set.

    Raw street addresses are deliberately not copied into CTD.  The source row ID and
    a fingerprint support change detection while the profile contains only public
    jurisdiction identities.
    """

    __tablename__ = "ctd_address_assignment"
    __table_args__ = (
        UniqueConstraint(
            "source_system",
            "source_address_id",
            "sourcing_role",
            "valid_from",
            name="uq_ctd_address_assignment_version",
        ),
        Index(
            "ix_ctd_address_assignment_current",
            "source_system",
            "source_address_id",
            "sourcing_role",
            "valid_to",
        ),
        Index("ix_ctd_address_assignment_profile", "location_profile_id", "valid_to"),
        Index("ix_ctd_address_assignment_status", "status", "calculation_ready"),
    )

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)
    source_system: Mapped[str] = mapped_column(String(80))
    source_address_id: Mapped[int] = mapped_column(BigInteger)
    sourcing_role: Mapped[str] = mapped_column(String(40), default="service_address")
    address_fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    country_iso: Mapped[str] = mapped_column(String(3), default="USA")
    state_code: Mapped[str | None] = mapped_column(String(8), index=True)
    postal_code: Mapped[str | None] = mapped_column(String(10), index=True)
    plus_four: Mapped[str | None] = mapped_column(String(4))
    latitude: Mapped[Decimal | None] = mapped_column(Numeric(18, 12))
    longitude: Mapped[Decimal | None] = mapped_column(Numeric(18, 12))
    location_profile_id: Mapped[int | None] = mapped_column(
        ForeignKey("ctd_location_profile.id"), index=True
    )
    benchmark_p_code: Mapped[int | None] = mapped_column(BigInteger, index=True)
    source_id: Mapped[int | None] = mapped_column(ForeignKey("ctd_source.id"), index=True)
    assignment_method: Mapped[str] = mapped_column(String(80))
    confidence: Mapped[str] = mapped_column(String(20))
    calculation_ready: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(30), default="unmatched")
    evidence: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    valid_from: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    valid_to: Mapped[datetime | None] = mapped_column(DateTime)
    resolved_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow, onupdate=utcnow)


class LocationAssessment(Base):
    """Daily address-level jurisdiction, tax-rule, and filing-gap snapshot."""

    __tablename__ = "ctd_location_assessment"
    __table_args__ = (
        UniqueConstraint(
            "assessment_run_id",
            "source_system",
            "source_address_id",
            name="uq_ctd_location_assessment_run_address",
        ),
        Index(
            "ix_ctd_location_assessment_address",
            "source_system",
            "source_address_id",
            "assessment_date",
        ),
        Index(
            "ix_ctd_location_assessment_daily_gaps",
            "assessment_date",
            "assessment_complete",
            "is_new_address",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)
    assessment_run_id: Mapped[int] = mapped_column(ForeignKey("ctd_collection_run.id"), index=True)
    assessment_date: Mapped[date] = mapped_column(Date, index=True)
    source_system: Mapped[str] = mapped_column(String(80))
    source_address_id: Mapped[int] = mapped_column(BigInteger)
    address_assignment_id: Mapped[int] = mapped_column(
        ForeignKey("ctd_address_assignment.id"), index=True
    )
    location_profile_id: Mapped[int | None] = mapped_column(
        ForeignKey("ctd_location_profile.id"), index=True
    )
    previous_assessment_id: Mapped[int | None] = mapped_column(
        ForeignKey("ctd_location_assessment.id"), index=True
    )
    state_code: Mapped[str | None] = mapped_column(String(8), index=True)
    postal_code: Mapped[str | None] = mapped_column(String(10), index=True)
    plus_four: Mapped[str | None] = mapped_column(String(4))
    benchmark_p_code: Mapped[int | None] = mapped_column(BigInteger, index=True)
    resolver_status: Mapped[str] = mapped_column(String(30), index=True)
    resolver_confidence: Mapped[str] = mapped_column(String(20))
    location_calculation_ready: Mapped[bool] = mapped_column(Boolean, default=False)
    assessment_complete: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_new_address: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_new_profile: Mapped[bool] = mapped_column(Boolean, default=False)
    profile_changed: Mapped[bool] = mapped_column(Boolean, default=False)
    assessment_changed: Mapped[bool] = mapped_column(Boolean, default=False)
    level_0_status: Mapped[str] = mapped_column(String(20))
    level_1_status: Mapped[str] = mapped_column(String(20))
    level_2_status: Mapped[str] = mapped_column(String(20))
    level_3_status: Mapped[str] = mapped_column(String(20))
    gap_count: Mapped[int] = mapped_column(Integer, default=0)
    manual_gap_levels: Mapped[list[int] | None] = mapped_column(JSON)
    level_details: Mapped[dict[str, Any]] = mapped_column(JSON)
    assessment_sha256: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


class ServiceTaxAssessment(Base):
    """Daily shadow determination for one billed product/address demand row."""

    __tablename__ = "ctd_service_tax_assessment"
    __table_args__ = (
        UniqueConstraint(
            "assessment_run_id",
            "demand_key",
            name="uq_ctd_service_tax_assessment_run_demand",
        ),
        Index(
            "ix_ctd_service_tax_assessment_daily",
            "assessment_date",
            "determination_complete",
            "state_code",
        ),
        Index(
            "ix_ctd_service_tax_assessment_product",
            "source_tax_group",
            "service_category",
            "assessment_date",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True)
    assessment_run_id: Mapped[int] = mapped_column(ForeignKey("ctd_collection_run.id"), index=True)
    assessment_date: Mapped[date] = mapped_column(Date, index=True)
    demand_key: Mapped[str] = mapped_column(String(64), index=True)
    service_product_demand_id: Mapped[int] = mapped_column(BigInteger, index=True)
    previous_assessment_id: Mapped[int | None] = mapped_column(
        ForeignKey("ctd_service_tax_assessment.id"), index=True
    )
    address_assignment_id: Mapped[int | None] = mapped_column(
        ForeignKey("ctd_address_assignment.id"), index=True
    )
    customer_id: Mapped[int] = mapped_column(BigInteger, index=True)
    source_address_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    source_product_id: Mapped[int | None] = mapped_column(BigInteger, index=True)
    source_tax_group: Mapped[str] = mapped_column(String(100), index=True)
    service_category: Mapped[str | None] = mapped_column(String(100), index=True)
    charge_type: Mapped[str] = mapped_column(String(40))
    state_code: Mapped[str | None] = mapped_column(String(8), index=True)
    location_profile_id: Mapped[int | None] = mapped_column(
        ForeignKey("ctd_location_profile.id"), index=True
    )
    benchmark_p_code: Mapped[int | None] = mapped_column(BigInteger, index=True)
    trailing_billed_amount: Mapped[Decimal] = mapped_column(Numeric(24, 2))
    product_mapping_ready: Mapped[bool] = mapped_column(Boolean, default=False)
    location_ready: Mapped[bool] = mapped_column(Boolean, default=False)
    taxability_ready: Mapped[bool] = mapped_column(Boolean, default=False)
    nexus_ready: Mapped[bool] = mapped_column(Boolean, default=False)
    exemption_ready: Mapped[bool] = mapped_column(Boolean, default=True)
    filing_ready: Mapped[bool] = mapped_column(Boolean, default=False)
    calculation_ready: Mapped[bool] = mapped_column(Boolean, default=False)
    determination_complete: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    is_new_demand: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    assessment_changed: Mapped[bool] = mapped_column(Boolean, default=False)
    candidate_route_count: Mapped[int] = mapped_column(Integer, default=0)
    resolved_route_count: Mapped[int] = mapped_column(Integer, default=0)
    taxable_route_count: Mapped[int] = mapped_column(Integer, default=0)
    estimated_public_tax_amount: Mapped[Decimal | None] = mapped_column(Numeric(24, 6))
    gap_codes: Mapped[list[str] | None] = mapped_column(JSON)
    route_details: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON)
    assessment_sha256: Mapped[str] = mapped_column(String(64), index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)


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
