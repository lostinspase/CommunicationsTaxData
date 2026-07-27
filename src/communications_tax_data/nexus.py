from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import Engine, create_engine, delete, func, or_, select, text
from sqlalchemy.orm import Session

from communications_tax_data.collectors.base import CollectionStats, finish_run, start_run
from communications_tax_data.config import get_settings
from communications_tax_data.models import (
    BenchmarkJurisdiction,
    BenchmarkRate,
    CollectionRun,
    CompanyNexusDetermination,
    ExemptionFormArtifact,
    ExemptionFormStateCheck,
    NexusAssessment,
    NexusRule,
    SalesTaxProvider,
    Source,
    StateNexusExposure,
    TaxabilityRule,
    utcnow,
)
from communications_tax_data.state_authorities import STATE_AUTHORITIES

SST_NEXUS_SOURCE = "https://www.streamlinedsalestax.org/state-tables"
SALES_USE_CONCEPTS = {"sales_tax", "use_tax", "sales_and_use_tax"}
NEXUS_COLLECTION_STATUSES = {"collection_required", "registered", "collecting"}
NEXUS_NOT_REQUIRED_STATUSES = {"not_required"}
TPP_TAX_GROUPS = {"equipment-included", "equipment-lease", "equipment-sale"}


def _rule(
    amount: int | None,
    *,
    basis: str,
    text_value: str,
    lookback: str = "current_or_previous_calendar_year",
    transactions: int | None = None,
    operator: str = "amount_only",
    amount_inclusive: bool = False,
    transaction_inclusive: bool = True,
    effective: date = date(2018, 1, 1),
    service_treatment: str = "requires_taxability_review",
    statewide: bool = True,
    source_url: str = SST_NEXUS_SOURCE,
) -> dict[str, Any]:
    return {
        "threshold_amount": amount,
        "threshold_amount_inclusive": amount_inclusive,
        "transaction_threshold": transactions,
        "transaction_threshold_inclusive": transaction_inclusive,
        "threshold_operator": operator,
        "threshold_basis": basis,
        "threshold_rule_text": text_value,
        "lookback_period": lookback,
        "service_revenue_treatment": service_treatment,
        "remote_seller_effective_date": effective,
        "statewide_sales_tax": statewide,
        "source_url": source_url,
    }


# Screening normalization of the Streamlined Governing Board's current remote-seller
# table as of 2026-07-27. These records remain "screening" until state-specific legal
# review publishes the exact statutory numerator and sourcing treatment.
NEXUS_RULE_DATA: dict[str, dict[str, Any]] = {
    "AL": _rule(
        250_000,
        basis="tpp_only",
        text_value="More than $250,000 of TPP sales in the prior calendar year.",
    ),
    "AK": _rule(
        100_000,
        basis="gross_remote_sales",
        text_value="$100,000 or more of statewide gross remote sales; local regime only.",
        amount_inclusive=True,
        statewide=False,
        effective=date(2025, 1, 1),
    ),
    "AZ": _rule(
        100_000,
        basis="gross_retail_sales_or_income",
        text_value="More than $100,000 of annual Arizona gross retail sales or income.",
        effective=date(2021, 1, 1),
    ),
    "AR": _rule(
        100_000,
        basis="sales",
        text_value="Sales exceed $100,000 or 200 transactions in the current or preceding year.",
        transactions=200,
        operator="or",
    ),
    "CA": _rule(
        500_000,
        basis="tpp_only",
        text_value=(
            "Total combined sales of TPP exceed $500,000 in the current or preceding calendar year."
        ),
        source_url="https://cdtfa.ca.gov/industry/wayfair/",
    ),
    "CO": _rule(
        100_000,
        basis="taxable_sales",
        text_value="Taxable sales exceed $100,000 in the current or preceding calendar year.",
    ),
    "CT": _rule(
        100_000,
        basis="gross_receipts_retail",
        text_value="$100,000 or more of gross receipts and 200 or more retail transactions.",
        transactions=200,
        operator="and",
        amount_inclusive=True,
    ),
    "DE": _rule(
        None, basis="no_general_sales_tax", text_value="No state sales or use tax.", statewide=False
    ),
    "FL": _rule(
        100_000,
        basis="taxable_tpp_only",
        text_value="Taxable TPP sales exceed $100,000 in the previous calendar year.",
        lookback="previous_calendar_year",
    ),
    "GA": _rule(
        100_000,
        basis="retail_sales",
        text_value=(
            "Gross revenue exceeds $100,000 or 200 retail sales in the current or "
            "previous calendar year."
        ),
        transactions=200,
        operator="or",
    ),
    "HI": _rule(
        100_000,
        basis="gross_income",
        text_value="$100,000 or more of gross income or 200 transactions.",
        transactions=200,
        operator="or",
        amount_inclusive=True,
        service_treatment="included_in_gross_income",
    ),
    "ID": _rule(
        100_000, basis="sales", text_value="Sales exceed $100,000 in the current or previous year."
    ),
    "IL": _rule(
        100_000,
        basis="tpp_only",
        text_value="$100,000 or more of cumulative gross receipts from Illinois TPP sales.",
        amount_inclusive=True,
        effective=date(2026, 1, 1),
    ),
    "IN": _rule(
        100_000,
        basis="gross_sales",
        text_value=(
            "Gross revenue from sales exceeds $100,000 in the current or previous calendar year."
        ),
        effective=date(2024, 1, 1),
    ),
    "IA": _rule(
        100_000,
        basis="gross_sales",
        text_value="$100,000 of gross revenue from sales in the current or previous calendar year.",
        amount_inclusive=True,
    ),
    "KS": _rule(
        100_000,
        basis="gross_receipts",
        text_value=(
            "Cumulative gross receipts exceed $100,000 in the current or preceding calendar year."
        ),
        effective=date(2021, 7, 1),
    ),
    "KY": _rule(
        100_000,
        basis="gross_receipts",
        text_value=(
            "$100,000 or more of gross receipts or 200 sales in the current or previous "
            "calendar year."
        ),
        transactions=200,
        operator="or",
        amount_inclusive=True,
    ),
    "LA": _rule(
        100_000,
        basis="goods_or_services",
        text_value="More than $100,000 of goods or services delivered into Louisiana.",
        service_treatment="included_if_delivered",
    ),
    "ME": _rule(
        100_000,
        basis="tpp_digital_taxable_services",
        text_value=(
            "More than $100,000 or 200 transactions of TPP, electronic products, or "
            "taxable services."
        ),
        transactions=200,
        operator="or",
    ),
    "MD": _rule(
        100_000,
        basis="gross_revenue",
        text_value=(
            "Gross revenue exceeds $100,000 or 200 transactions in the current or "
            "previous calendar year."
        ),
        transactions=200,
        operator="or",
    ),
    "MA": _rule(
        100_000,
        basis="massachusetts_sales",
        text_value="Massachusetts sales exceed $100,000 in the current or previous calendar year.",
    ),
    "MI": _rule(
        100_000,
        basis="taxable_and_nontaxable_sales",
        text_value=(
            "Taxable and nontaxable sales exceed $100,000 or 200 transactions in the "
            "previous calendar year."
        ),
        lookback="previous_calendar_year",
        transactions=200,
        operator="or",
        source_url="https://www.michigan.gov/en/taxes/business-taxes/sales-use-tax/resources/sales-and-use-tax-information-for-remote-sellers",
    ),
    "MN": _rule(
        100_000,
        basis="retail_sales_excluding_resale",
        text_value="More than $100,000 or 200 retail transactions in any 12 consecutive months.",
        lookback="rolling_12_months",
        transactions=200,
        operator="or",
    ),
    "MS": _rule(
        250_000,
        basis="sales",
        text_value="Sales exceed $250,000 in the prior 12 months.",
        lookback="rolling_12_months",
    ),
    "MO": _rule(
        100_000,
        basis="taxable_sales",
        text_value=(
            "Taxable gross receipts exceed $100,000 in the current or previous calendar year."
        ),
    ),
    "MT": _rule(
        None,
        basis="no_general_sales_tax",
        text_value="No state general sales tax.",
        statewide=False,
    ),
    "NE": _rule(
        100_000,
        basis="retail_sales",
        text_value=(
            "Retail sales exceed $100,000 or 200 transactions in the current or prior "
            "calendar year."
        ),
        transactions=200,
        operator="or",
    ),
    "NV": _rule(
        100_000,
        basis="retail_sales",
        text_value=(
            "Retail sales exceed $100,000 or 200 retail transactions in the current or prior year."
        ),
        transactions=200,
        operator="or",
    ),
    "NH": _rule(
        None,
        basis="no_general_sales_tax",
        text_value="No state general sales tax.",
        statewide=False,
    ),
    "NJ": _rule(
        100_000,
        basis="tpp_digital_taxable_services",
        text_value=(
            "Gross revenue exceeds $100,000 or 200 transactions of TPP, specified "
            "digital products, or taxable services."
        ),
        transactions=200,
        operator="or",
        source_url="https://www.nj.gov/treasury/taxation/remotesellers.shtml",
    ),
    "NM": _rule(
        100_000,
        basis="taxable_gross_receipts",
        text_value="At least $100,000 of taxable gross receipts in the previous calendar year.",
        lookback="previous_calendar_year",
        amount_inclusive=True,
    ),
    "NY": _rule(
        500_000,
        basis="tpp_only",
        text_value=(
            "More than $500,000 of gross receipts and more than 100 TPP sales in the "
            "preceding four sales-tax quarters."
        ),
        lookback="preceding_four_sales_tax_quarters",
        transactions=100,
        operator="and",
        transaction_inclusive=False,
        source_url="https://www.tax.ny.gov/pubs_and_bulls/publications/sales/nexus.htm",
    ),
    "NC": _rule(
        100_000,
        basis="gross_sales",
        text_value="Gross sales exceed $100,000 in the current or previous calendar year.",
        effective=date(2024, 7, 1),
    ),
    "ND": _rule(
        100_000,
        basis="taxable_sales",
        text_value="$100,000 of taxable sales in the current or previous calendar year.",
        amount_inclusive=True,
    ),
    "OH": _rule(
        100_000,
        basis="retail_sales",
        text_value=(
            "Retail receipts exceed $100,000 or 200 transactions in the current or "
            "preceding calendar year."
        ),
        transactions=200,
        operator="or",
    ),
    "OK": _rule(
        100_000,
        basis="taxable_products",
        text_value=(
            "$100,000 or more of taxable product sales in the current or previous calendar year."
        ),
        amount_inclusive=True,
        effective=date(2023, 1, 1),
    ),
    "OR": _rule(
        None,
        basis="no_general_sales_tax",
        text_value="No state general sales tax.",
        statewide=False,
    ),
    "PA": _rule(
        100_000,
        basis="gross_sales",
        text_value="More than $100,000 of gross sales in the previous 12 months.",
        lookback="rolling_12_months",
        source_url="https://www.pa.gov/agencies/revenue/resources/tax-types-and-information/sales-use-and-hotel-occupancy-tax/online-retailers",
    ),
    "RI": _rule(
        100_000,
        basis="gross_revenue",
        text_value=(
            "$100,000 or more of gross revenue or 200 transactions in the previous calendar year."
        ),
        lookback="previous_calendar_year",
        transactions=200,
        operator="or",
        amount_inclusive=True,
    ),
    "SC": _rule(
        100_000,
        basis="gross_sales",
        text_value=(
            "Gross revenue from South Carolina sales exceeds $100,000 in the current or "
            "previous calendar year."
        ),
    ),
    "SD": _rule(
        100_000,
        basis="gross_sales",
        text_value=(
            "Gross revenue from sales exceeds $100,000 in the current or previous calendar year."
        ),
        effective=date(2023, 7, 1),
    ),
    "TN": _rule(
        100_000,
        basis="retail_sales",
        text_value="Retail sales exceed $100,000 during the previous 12 months.",
        lookback="rolling_12_months",
        effective=date(2020, 10, 1),
    ),
    "TX": _rule(
        500_000,
        basis="total_revenue",
        text_value="$500,000 or more of total Texas revenue in the preceding 12 calendar months.",
        lookback="preceding_12_calendar_months",
        amount_inclusive=True,
        service_treatment="included_in_total_revenue",
        source_url="https://comptroller.texas.gov/taxes/sales/remote-sellers-marketplace-faq.php",
    ),
    "UT": _rule(
        100_000,
        basis="gross_sales",
        text_value="More than $100,000 of gross revenue in the current or previous calendar year.",
        service_treatment="included_if_covered_sale",
        effective=date(2025, 7, 1),
        source_url="https://tax.utah.gov/business/sales-tax/other-sales-tax/out-of-state-remote-sellers/",
    ),
    "VT": _rule(
        100_000,
        basis="sales",
        text_value="At least $100,000 of sales or 200 transactions in a preceding 12-month period.",
        lookback="rolling_12_months",
        transactions=200,
        operator="or",
        amount_inclusive=True,
    ),
    "VA": _rule(
        100_000,
        basis="retail_sales",
        text_value=(
            "More than $100,000 of retail sales or 200 retail transactions in the "
            "current or previous calendar year."
        ),
        transactions=200,
        operator="or",
    ),
    "WA": _rule(
        100_000,
        basis="gross_income",
        text_value="Gross income exceeds $100,000 in the current or preceding calendar year.",
        service_treatment="included_in_gross_income",
        effective=date(2020, 1, 1),
    ),
    "WV": _rule(
        100_000,
        basis="sales",
        text_value=(
            "$100,000 or more of sales or 200 transactions in the current or preceding "
            "calendar year."
        ),
        transactions=200,
        operator="or",
        amount_inclusive=True,
    ),
    "WI": _rule(
        100_000,
        basis="gross_sales",
        text_value="Gross sales exceed $100,000 in the current or previous calendar year.",
    ),
    "WY": _rule(
        100_000,
        basis="tpp_admissions_services",
        text_value=(
            "More than $100,000 from TPP, admissions, or services in the current or previous year."
        ),
        service_treatment="included",
        effective=date(2024, 7, 1),
    ),
}


def seed_nexus_rules(session: Session, *, verified_at: datetime | None = None) -> dict[str, int]:
    """Seed the 50-state screening matrix without overwriting reviewed decisions."""
    verified_at = verified_at or utcnow()
    source_row = session.scalar(select(Source).where(Source.code == "sst-economic-nexus"))
    if source_row is None:
        source_row = Source(
            code="sst-economic-nexus",
            name="Remote Seller State Guidance Table",
            publisher="Streamlined Sales Tax Governing Board",
            source_type="nexus_threshold_index",
            tax_level=1,
            url=SST_NEXUS_SOURCE,
            cadence_days=7,
            authoritative=False,
            notes=(
                "Official multistate screening index linking state guidance. Each rule "
                "requires state-specific legal review before publication."
            ),
        )
        session.add(source_row)
        session.flush()
    existing_rules = {
        (row.state_code, row.tax_family, row.trigger_type, row.effective_from): row
        for row in session.scalars(select(NexusRule))
    }
    inserted = 0
    for state_code, values in NEXUS_RULE_DATA.items():
        effective_from = values["remote_seller_effective_date"] or date(1900, 1, 1)
        key = (state_code, "sales_and_use", "economic", effective_from)
        if key in existing_rules:
            continue
        session.add(
            NexusRule(
                state_code=state_code,
                tax_family="sales_and_use",
                trigger_type="economic",
                source_id=source_row.id,
                legal_citation=(
                    "Streamlined Sales Tax Governing Board remote-seller table; "
                    "state-specific legal review required before publication."
                ),
                review_status="screening",
                effective_from=effective_from,
                last_verified_at=verified_at,
                **values,
            )
        )
        inserted += 1

    existing_company = {
        (row.state_code, row.tax_family, row.effective_from)
        for row in session.scalars(select(CompanyNexusDetermination))
    }
    company_inserted = 0
    for state_code, physical in (("PA", "asserted"), ("TX", "asserted"), ("CA", "possible")):
        key = (state_code, "sales_and_use", date(2026, 7, 27))
        if key in existing_company:
            continue
        session.add(
            CompanyNexusDetermination(
                state_code=state_code,
                tax_family="sales_and_use",
                physical_presence_status=physical,
                economic_nexus_status="not_assessed",
                obligation_status="review_required",
                registration_status="not_recorded",
                collection_status="not_recorded",
                determination_basis=(
                    "Physical nexus described by Apeiron management; property, employee, "
                    "contractor, network, registration, and collection evidence remains open."
                ),
                evidence_reference="Management statement recorded 2026-07-27",
                review_status="proposed",
                effective_from=date(2026, 7, 27),
            )
        )
        company_inserted += 1

    providers = {item.provider_code: item for item in session.scalars(select(SalesTaxProvider))}
    provider_inserted = 0
    for code, name, url in (
        ("accuratetax", "AccurateTax", "https://www.accuratetax.com/"),
        ("avalara", "Avalara", "https://www.avalara.com/"),
        ("avior", "Avior", "https://www.avior.com/"),
        ("sovos", "Sovos", "https://sovos.com/"),
        ("taxcloud", "TaxCloud", "https://taxcloud.com/"),
    ):
        if code in providers:
            continue
        session.add(
            SalesTaxProvider(
                provider_code=code,
                provider_name=name,
                status="candidate",
                certified_service_provider=True,
                calculation_api=True,
                returns_filing=True,
                exemption_support=True,
                website_url=url,
                capabilities={
                    "intended_scope": "type_1_sales_and_use",
                    "excludes": [
                        "state_usf",
                        "911_988",
                        "puc_assessments",
                        "communications_gross_receipts",
                        "uut_and_franchise",
                    ],
                },
                notes=(
                    "Candidate SST Certified Service Provider; no provider selected or configured."
                ),
            )
        )
        provider_inserted += 1
    session.flush()
    return {
        "rules_inserted": inserted,
        "company_determinations_inserted": company_inserted,
        "providers_inserted": provider_inserted,
    }


def sync_nexus_exposures(
    session: Session,
    *,
    as_of: date | None = None,
    benchmark_engine: Engine | None = None,
) -> dict[str, Any]:
    """Load previous/current calendar-year gross billed screens by service state."""
    assessment_date = as_of or date.today()
    period_start = date(assessment_date.year - 1, 1, 1)
    period_end = date(assessment_date.year + 1, 1, 1)
    owns_engine = benchmark_engine is None
    engine = benchmark_engine or create_engine(
        get_settings().benchmark_url(), pool_pre_ping=True, future=True
    )
    run = start_run(session, "nexus-exposure-sync")
    counts: dict[str, Any] = {"as_of": str(assessment_date), "state_periods": 0}
    try:
        session.execute(
            delete(StateNexusExposure).where(
                StateNexusExposure.measurement_method == "gross_billed_screen",
                StateNexusExposure.period_start >= period_start,
            )
        )
        sql = text(
            """
            SELECT YEAR(b.invoice_at) AS calendar_year,
                   UPPER(LEFT(TRIM(a.state), 8)) AS state_code,
                   SUM(ABS(b.amount)) AS gross_billed_amount,
                   SUM(CASE WHEN b.tax_group IN
                        ('equipment-included','equipment-lease','equipment-sale')
                            THEN ABS(b.amount) ELSE 0 END) AS tpp_candidate_amount,
                   SUM(CASE WHEN b.tax_group = '__unmapped__'
                            THEN 0
                            WHEN b.tax_group IN
                        ('equipment-included','equipment-lease','equipment-sale')
                            THEN 0 ELSE ABS(b.amount) END) AS service_candidate_amount,
                   SUM(CASE WHEN b.tax_group = '__unmapped__'
                            THEN ABS(b.amount) ELSE 0 END) AS unclassified_amount,
                   COUNT(DISTINCT b.invoice_id) AS invoice_count,
                   COUNT(DISTINCT b.customer_id) AS customer_count
            FROM (
                SELECT s.customer_id, s.invoice_id, i.stop AS invoice_at,
                       COALESCE(NULLIF(LOWER(TRIM(p.tax_group)), ''), '__unmapped__')
                           AS tax_group,
                       s.total AS amount
                FROM apeiron_apeironrecurringchargessummary s
                JOIN apeiron_apeironinvoice i ON i.id = s.invoice_id
                LEFT JOIN apeiron_apeironorderitem oi ON oi.id = s.order_item_id
                LEFT JOIN apeiron_apeironproduct p ON p.id = oi.product_id
                WHERE i.stop >= :period_start AND i.stop < :period_end
                UNION ALL
                SELECT s.customer_id, s.invoice_id, i.stop,
                       COALESCE(NULLIF(LOWER(TRIM(p.tax_group)), ''), '__unmapped__'),
                       s.total
                FROM apeiron_apeironnonrecurringchargessummary s
                JOIN apeiron_apeironinvoice i ON i.id = s.invoice_id
                LEFT JOIN apeiron_apeironorderitem oi ON oi.id = s.order_item_id
                LEFT JOIN apeiron_apeironproduct p ON p.id = oi.product_id
                WHERE i.stop >= :period_start AND i.stop < :period_end
                UNION ALL
                SELECT s.customer_id, s.invoice_id, i.stop,
                       COALESCE(NULLIF(LOWER(TRIM(p.tax_group)), ''),
                                'cellular-data-usage'), s.total
                FROM apeiron_apeirondatachargessummary s
                JOIN apeiron_apeironinvoice i ON i.id = s.invoice_id
                LEFT JOIN apeiron_apeironproduct p ON p.id = s.product_id
                WHERE i.stop >= :period_start AND i.stop < :period_end
                UNION ALL
                SELECT s.customer_id, s.invoice_id, i.stop, 'voice-usage', s.total
                FROM apeiron_apeironusagechargessummary s
                JOIN apeiron_apeironinvoice i ON i.id = s.invoice_id
                WHERE i.stop >= :period_start AND i.stop < :period_end
                UNION ALL
                SELECT s.customer_id, s.invoice_id, i.stop, 'sms', s.total
                FROM apeiron_apeironmsgchargessummary s
                JOIN apeiron_apeironinvoice i ON i.id = s.invoice_id
                WHERE i.stop >= :period_start AND i.stop < :period_end
            ) b
            JOIN apeiron_apeironcustomer c ON c.user_id = b.customer_id
            LEFT JOIN apeiron_apeironaddress a ON a.id = c.service_address_id
            WHERE c.closed = 0 AND c.test_account = 0 AND c.generate_invoices = 1
            GROUP BY YEAR(b.invoice_at), UPPER(LEFT(TRIM(a.state), 8))
            ORDER BY calendar_year, state_code
            """
        )
        with engine.connect() as connection:
            rows = connection.execute(
                sql, {"period_start": period_start, "period_end": period_end}
            ).mappings()
            for row in rows:
                state_code = (row["state_code"] or "").strip().upper()
                if len(state_code) != 2:
                    state_code = "UN"
                year = int(row["calendar_year"])
                end = date(year, 12, 31)
                if year == assessment_date.year:
                    end = assessment_date
                session.add(
                    StateNexusExposure(
                        state_code=state_code,
                        period_start=date(year, 1, 1),
                        period_end=end,
                        as_of_date=assessment_date,
                        gross_billed_amount=row["gross_billed_amount"] or 0,
                        tpp_candidate_amount=row["tpp_candidate_amount"] or 0,
                        service_candidate_amount=row["service_candidate_amount"] or 0,
                        unclassified_amount=row["unclassified_amount"] or 0,
                        invoice_count=row["invoice_count"] or 0,
                        customer_count=row["customer_count"] or 0,
                        limitations=(
                            "Gross absolute billed charges by current service-address state. "
                            "Not reduced for resale, exemptions, returns, marketplace sales, "
                            "product taxability, or state-specific sourcing. Invoice count is "
                            "not a reviewed statutory transaction count."
                        ),
                        collection_run_id=run.id,
                    )
                )
                counts["state_periods"] += 1
        session.flush()
        finish_run(
            run,
            CollectionStats(
                sources=1,
                seen=counts["state_periods"],
                inserted=counts["state_periods"],
                details=counts,
            ),
        )
        counts["collection_run_id"] = run.id
        return counts
    except Exception as exc:
        finish_run(
            run,
            CollectionStats(details=counts),
            status="failed",
            error=f"{type(exc).__name__}: {exc}",
        )
        raise
    finally:
        if owns_engine:
            engine.dispose()


def _current_rows(session: Session, model, as_of: date):
    return list(
        session.scalars(
            select(model).where(
                model.effective_from <= as_of,
                or_(model.effective_to.is_(None), model.effective_to >= as_of),
            )
        )
    )


def current_company_nexus(
    session: Session, as_of: date
) -> dict[tuple[str, str], CompanyNexusDetermination]:
    result: dict[tuple[str, str], CompanyNexusDetermination] = {}
    for item in sorted(
        _current_rows(session, CompanyNexusDetermination, as_of),
        key=lambda row: (row.effective_from, row.id),
        reverse=True,
    ):
        result.setdefault((item.state_code, item.tax_family), item)
    return result


def nexus_gate_status(
    determination: CompanyNexusDetermination | None,
) -> tuple[str, bool]:
    if determination is None:
        return "missing", False
    if (
        determination.obligation_status in NEXUS_NOT_REQUIRED_STATUSES
        and determination.review_status in {"reviewed", "published", "source_verified"}
    ):
        return "not_required", True
    if (
        determination.obligation_status in NEXUS_COLLECTION_STATUSES
        and determination.registration_status in {"registered", "active"}
        and determination.collection_status in {"collecting", "collection_required"}
        and determination.review_status in {"reviewed", "published", "source_verified"}
    ):
        return "collecting", True
    return "review_required", False


def _basis_amount(rule: NexusRule, exposure: StateNexusExposure | None) -> Decimal | None:
    if exposure is None:
        return None
    if rule.threshold_basis in {"tpp_only", "taxable_tpp_only"}:
        return Decimal(exposure.tpp_candidate_amount)
    if rule.threshold_basis in {
        "gross_remote_sales",
        "gross_sales",
        "gross_receipts",
        "gross_revenue",
        "gross_income",
        "total_revenue",
        "taxable_and_nontaxable_sales",
        "goods_or_services",
        "tpp_admissions_services",
    }:
        return Decimal(exposure.gross_billed_amount)
    # Retail/taxable-sales bases require taxability, resale, and exemption decisions
    # that the gross billed screen intentionally does not fabricate.
    return None


def _triggered(value: Decimal | None, threshold: Decimal | None, inclusive: bool) -> bool | None:
    if value is None or threshold is None:
        return None
    return value >= threshold if inclusive else value > threshold


def assess_nexus(session: Session, *, as_of: date | None = None) -> dict[str, Any]:
    """Create a daily 50-state screen while preserving legal-review gaps."""
    assessment_date = as_of or date.today()
    seed_nexus_rules(session)
    run = start_run(session, "nexus-assessment-v1")
    rules = {
        row.state_code: row
        for row in sorted(
            _current_rows(session, NexusRule, assessment_date),
            key=lambda item: (item.effective_from, item.id),
        )
    }
    determinations = current_company_nexus(session, assessment_date)
    exposure_rows = list(
        session.scalars(
            select(StateNexusExposure)
            .where(StateNexusExposure.as_of_date <= assessment_date)
            .order_by(
                StateNexusExposure.state_code,
                StateNexusExposure.period_start.desc(),
                StateNexusExposure.id.desc(),
            )
        )
    )
    exposures: dict[str, StateNexusExposure] = {}
    for item in exposure_rows:
        exposures.setdefault(item.state_code, item)
    previous: dict[str, NexusAssessment] = {}
    for item in session.scalars(
        select(NexusAssessment).order_by(
            NexusAssessment.state_code,
            NexusAssessment.assessment_date.desc(),
            NexusAssessment.id.desc(),
        )
    ):
        previous.setdefault(item.state_code, item)
    counts: defaultdict[str, int] = defaultdict(int)
    try:
        for profile in STATE_AUTHORITIES:
            state = profile.state_code
            rule = rules.get(state)
            exposure = exposures.get(state)
            determination = determinations.get((state, "sales_and_use"))
            gaps: set[str] = set()
            basis_amount = _basis_amount(rule, exposure) if rule else None
            gross_amount = Decimal(exposure.gross_billed_amount) if exposure else None
            amount_trigger = (
                _triggered(
                    basis_amount,
                    Decimal(rule.threshold_amount) if rule and rule.threshold_amount else None,
                    rule.threshold_amount_inclusive if rule else False,
                )
                if rule
                else None
            )
            transaction_trigger = None
            if rule and rule.transaction_threshold is not None and exposure is not None:
                transaction_trigger = (
                    exposure.invoice_count >= rule.transaction_threshold
                    if rule.transaction_threshold_inclusive
                    else exposure.invoice_count > rule.transaction_threshold
                )
                gaps.add("TRANSACTION_COUNT_IS_INVOICE_PROXY")
            gate_status, gate_ready = nexus_gate_status(determination)
            if rule is None:
                status = "rule_missing"
                gaps.add("NEXUS_RULE_MISSING")
            elif not rule.statewide_sales_tax and rule.threshold_amount is None:
                status = "no_statewide_sales_tax"
            elif not rule.statewide_sales_tax:
                status = "local_sales_tax_review"
                gaps.add("LOCAL_REMOTE_SELLER_REGIME")
            elif gate_ready:
                status = gate_status
            elif determination and determination.physical_presence_status in {
                "asserted",
                "possible",
            }:
                status = "physical_presence_review"
                gaps.add("PHYSICAL_PRESENCE_EVIDENCE_REVIEW")
                gaps.add("REGISTRATION_STATUS_NOT_VERIFIED")
            elif amount_trigger is True or transaction_trigger is True:
                status = "economic_nexus_candidate"
                gaps.add("ECONOMIC_NEXUS_LEGAL_REVIEW")
            elif exposure is None:
                status = "exposure_missing"
                gaps.add("STATE_EXPOSURE_MISSING")
            elif rule.threshold_amount is not None and basis_amount is None:
                status = "threshold_basis_review"
                gaps.add("STATUTORY_THRESHOLD_BASIS_UNRESOLVED")
            else:
                status = "monitor"
            if determination is None and status not in {
                "no_statewide_sales_tax",
                "local_sales_tax_review",
            }:
                gaps.add("COMPANY_NEXUS_DETERMINATION_MISSING")
            threshold_percent = None
            if rule and rule.threshold_amount and basis_amount is not None:
                threshold_percent = (
                    basis_amount / Decimal(rule.threshold_amount) * Decimal("100")
                ).quantize(Decimal("0.0001"))
            details = {
                "physical_presence_status": (
                    determination.physical_presence_status if determination else "not_assessed"
                ),
                "economic_nexus_status": (
                    determination.economic_nexus_status if determination else "not_assessed"
                ),
                "obligation_status": (
                    determination.obligation_status if determination else "not_assessed"
                ),
                "registration_status": (
                    determination.registration_status if determination else "not_recorded"
                ),
                "collection_status": (
                    determination.collection_status if determination else "not_recorded"
                ),
                "threshold_basis": rule.threshold_basis if rule else None,
                "lookback_period": rule.lookback_period if rule else None,
                "invoice_count": exposure.invoice_count if exposure else None,
                "customer_count": exposure.customer_count if exposure else None,
                "exposure_period": (
                    [str(exposure.period_start), str(exposure.period_end)] if exposure else None
                ),
                "screening_only": True,
            }
            digest = hashlib.sha256(
                json.dumps(
                    {
                        "status": status,
                        "basis_amount": str(basis_amount) if basis_amount is not None else None,
                        "gross": str(gross_amount) if gross_amount is not None else None,
                        "amount_trigger": amount_trigger,
                        "transaction_trigger": transaction_trigger,
                        "gaps": sorted(gaps),
                        "details": details,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                ).encode()
            ).hexdigest()
            prior = previous.get(state)
            changed = prior is None or prior.assessment_sha256 != digest
            session.add(
                NexusAssessment(
                    assessment_run_id=run.id,
                    assessment_date=assessment_date,
                    state_code=state,
                    tax_family="sales_and_use",
                    nexus_rule_id=rule.id if rule else None,
                    company_determination_id=determination.id if determination else None,
                    exposure_id=exposure.id if exposure else None,
                    previous_assessment_id=prior.id if prior else None,
                    status=status,
                    threshold_basis_amount=basis_amount,
                    gross_screen_amount=gross_amount,
                    threshold_percent=threshold_percent,
                    amount_threshold_triggered=amount_trigger,
                    transaction_threshold_triggered=transaction_trigger,
                    assessment_changed=changed,
                    gap_codes=sorted(gaps),
                    details=details,
                    assessment_sha256=digest,
                )
            )
            counts[status] += 1
        session.flush()
        result = {"assessment_date": str(assessment_date), "states": 50, **dict(counts)}
        finish_run(
            run,
            CollectionStats(seen=50, inserted=50, details=result),
        )
        result["collection_run_id"] = run.id
        return result
    except Exception as exc:
        finish_run(
            run,
            CollectionStats(details=dict(counts)),
            status="failed",
            error=f"{type(exc).__name__}: {exc}",
        )
        raise


def nexus_dashboard_data(session: Session) -> dict[str, Any]:
    latest_run = session.scalar(
        select(NexusAssessment.assessment_run_id)
        .order_by(NexusAssessment.assessment_run_id.desc())
        .limit(1)
    )
    assessments = (
        list(
            session.scalars(
                select(NexusAssessment)
                .where(NexusAssessment.assessment_run_id == latest_run)
                .order_by(NexusAssessment.state_code)
            )
        )
        if latest_run is not None
        else []
    )
    rules = {item.id: item for item in session.scalars(select(NexusRule))}
    determinations = {item.id: item for item in session.scalars(select(CompanyNexusDetermination))}
    exposures = {item.id: item for item in session.scalars(select(StateNexusExposure))}
    names = {item.state_code: item.state_name for item in STATE_AUTHORITIES}
    taxability_counts = {
        state: (rules_count, categories)
        for state, rules_count, categories in session.execute(
            select(
                TaxabilityRule.state_code,
                func.count(),
                func.count(func.distinct(TaxabilityRule.service_category)),
            )
            .where(
                TaxabilityRule.state_code.is_not(None),
                TaxabilityRule.review_status.in_(("reviewed", "published")),
            )
            .group_by(TaxabilityRule.state_code)
        )
    }
    type1_by_state: dict[str, dict[int, int]] = defaultdict(dict)
    for state, level, count in session.execute(
        select(
            BenchmarkJurisdiction.state_code,
            BenchmarkRate.tax_level,
            func.count(func.distinct(BenchmarkRate.benchmark_id)),
        )
        .select_from(BenchmarkRate)
        .join(
            BenchmarkJurisdiction,
            BenchmarkJurisdiction.p_code == BenchmarkRate.p_code,
        )
        .where(
            BenchmarkRate.tax_type == 1,
            BenchmarkRate.active.is_(True),
            BenchmarkRate.rate.is_not(None),
            BenchmarkRate.rate != 0,
        )
        .group_by(BenchmarkJurisdiction.state_code, BenchmarkRate.tax_level)
    ):
        type1_by_state[state][level] = count
    rows = []
    for item in assessments:
        rule = rules.get(item.nexus_rule_id or -1)
        determination = determinations.get(item.company_determination_id or -1)
        exposure = exposures.get(item.exposure_id or -1)
        reviewed_rules, reviewed_categories = taxability_counts.get(item.state_code, (0, 0))
        type1 = type1_by_state.get(item.state_code, {})
        rows.append(
            {
                "state_code": item.state_code,
                "state_name": names.get(item.state_code, item.state_code),
                "status": item.status,
                "physical_presence": (
                    determination.physical_presence_status if determination else "not_assessed"
                ),
                "obligation_status": (
                    determination.obligation_status if determination else "not_assessed"
                ),
                "registration_status": (
                    determination.registration_status if determination else "not_recorded"
                ),
                "collection_status": (
                    determination.collection_status if determination else "not_recorded"
                ),
                "gross_screen_amount": (
                    float(item.gross_screen_amount)
                    if item.gross_screen_amount is not None
                    else None
                ),
                "basis_amount": (
                    float(item.threshold_basis_amount)
                    if item.threshold_basis_amount is not None
                    else None
                ),
                "invoice_count": exposure.invoice_count if exposure else None,
                "period": (f"{exposure.period_start}–{exposure.period_end}" if exposure else None),
                "threshold_amount": (
                    float(rule.threshold_amount) if rule and rule.threshold_amount else None
                ),
                "threshold_percent": (
                    float(item.threshold_percent) if item.threshold_percent is not None else None
                ),
                "threshold_basis": rule.threshold_basis if rule else None,
                "threshold_rule": rule.threshold_rule_text if rule else None,
                "lookback_period": rule.lookback_period if rule else None,
                "source_url": rule.source_url if rule else None,
                "review_status": rule.review_status if rule else None,
                "taxability_rules": reviewed_rules,
                "taxability_categories": reviewed_categories,
                "type1_levels": sorted(type1),
                "type1_rows": sum(type1.values()),
                "gaps": item.gap_codes or [],
            }
        )
    provider_rows = [
        {
            "code": item.provider_code,
            "name": item.provider_name,
            "status": item.status,
            "csp": item.certified_service_provider,
            "website_url": item.website_url,
        }
        for item in session.scalars(
            select(SalesTaxProvider).order_by(SalesTaxProvider.provider_name)
        )
    ]
    sales_tax_import = session.scalar(
        select(CollectionRun)
        .where(
            CollectionRun.collector == "fast-sales-tax-zip-rate-import",
            CollectionRun.status == "success",
        )
        .order_by(CollectionRun.finished_at.desc(), CollectionRun.id.desc())
        .limit(1)
    )
    form_counts = {
        state or "MULTI": count
        for state, count in session.execute(
            select(ExemptionFormArtifact.state_code, func.count()).group_by(
                ExemptionFormArtifact.state_code
            )
        )
    }
    latest_form_check = session.scalar(
        select(func.max(ExemptionFormStateCheck.checked_on)).where(
            ExemptionFormStateCheck.provider_code == "fastsalestax"
        )
    )
    form_checks = (
        {
            item.state_code: item
            for item in session.scalars(
                select(ExemptionFormStateCheck).where(
                    ExemptionFormStateCheck.provider_code == "fastsalestax",
                    ExemptionFormStateCheck.checked_on == latest_form_check,
                )
            )
        }
        if latest_form_check
        else {}
    )
    for row in rows:
        form_check = form_checks.get(row["state_code"])
        row["exemption_forms"] = form_counts.get(row["state_code"], 0)
        row["exemption_form_status"] = form_check.status if form_check else "not_checked"
        row["exemption_form_notice"] = form_check.notice if form_check else None
    return {
        "run_id": latest_run,
        "assessment_date": assessments[0].assessment_date if assessments else None,
        "summary": {
            "states": len(rows),
            "established_or_collecting": sum(
                row["status"] in {"collecting", "registered"} for row in rows
            ),
            "economic_candidates": sum(row["status"] == "economic_nexus_candidate" for row in rows),
            "physical_reviews": sum(row["status"] == "physical_presence_review" for row in rows),
            "basis_reviews": sum(row["status"] == "threshold_basis_review" for row in rows),
            "no_statewide_sales_tax": sum(
                row["status"] == "no_statewide_sales_tax" for row in rows
            ),
            "reviewed_taxability_states": sum(row["taxability_rules"] > 0 for row in rows),
            "exemption_forms": sum(form_counts.values()),
            "form_source_anomalies": sum(
                item.status == "source_anomaly" for item in form_checks.values()
            ),
        },
        "states": rows,
        "providers": provider_rows,
        "sales_tax_file": sales_tax_import.details if sales_tax_import else None,
        "policy": {
            "sales_use_gate": (
                "A taxable Type 1 route is calculation-ready only after a reviewed nexus "
                "determination and active registration/collection status."
            ),
            "telecom_separate": (
                "USF, 911/988, PUC, gross-receipts, UUT, franchise, and other provider "
                "obligations remain separate from the general sales/use nexus screen."
            ),
            "screening_limit": (
                "Revenue is an invoice-based screening proxy; statutory bases, resale, "
                "exemptions, sourcing, and transaction definitions require review."
            ),
        },
    }
