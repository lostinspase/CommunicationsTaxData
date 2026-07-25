from datetime import date, datetime
from decimal import Decimal

from communications_tax_data.acquisition import acquisition_queue_data
from communications_tax_data.models import (
    BenchmarkJurisdiction,
    CustomerTaxNeedDetail,
    FilingEntity,
    TaxFactBenchmarkMap,
    TaxFilingMap,
)


def _demand(
    *,
    detail_key: str,
    tax_type: int,
    tax_level: int,
    description: str,
    amount: str,
) -> CustomerTaxNeedDetail:
    return CustomerTaxNeedDetail(
        detail_key=detail_key,
        customer_id=1,
        customer_number=1001,
        p_code=123,
        postal_code="12095",
        plus_four=None,
        state_code="NY",
        country_code="US",
        tax_type=tax_type,
        tax_level=tax_level,
        tax_category="TEST",
        tax_description=description,
        active_customer=True,
        first_tax_invoice=datetime(2026, 1, 1),
        last_tax_invoice=datetime(2026, 7, 1),
        tax_charge_rows=10,
        lifetime_tax_amount=Decimal(amount),
        trailing_window_start=date(2025, 7, 25),
        trailing_12m_charge_rows=10,
        trailing_12m_tax_amount=Decimal(amount),
    )


def test_acquisition_queue_ranks_billed_local_demand_and_reports_gaps(session):
    session.add(
        BenchmarkJurisdiction(
            benchmark_id=1,
            p_code=123,
            alternate=False,
            country_iso="USA",
            state_code="NY",
            county_name="Fulton",
            locality_name="Johnstown",
            zip_begin="12095",
            zip_end="12095",
            source_timestamp=datetime(2026, 7, 1),
        )
    )
    session.add_all(
        [
            _demand(
                detail_key="a" * 64,
                tax_type=313,
                tax_level=2,
                description="NY Sales Tax",
                amount="100",
            ),
            _demand(
                detail_key="b" * 64,
                tax_type=14,
                tax_level=3,
                description="Statutory Gross Receipts Tax",
                amount="20",
            ),
        ]
    )
    session.add(
        TaxFactBenchmarkMap(
            natural_key="ny:313:2:123",
            public_fact_natural_key="ny:dor:sales-use-local:2:fulton",
            benchmark_tax_type=313,
            benchmark_tax_level=2,
            state_code="NY",
            p_code=123,
            mapping_status="source_verified",
            mapping_method="official_reporting_jurisdiction",
            confidence="source_verified",
            legal_citation="New York Tax Law Article 29",
            effective_from=date(1900, 1, 1),
        )
    )
    entity = FilingEntity(
        entity_code="ny-dtf-test",
        name="New York State Department of Taxation and Finance",
        entity_type="tax_authority",
        tax_level=1,
        state_code="NY",
        website_url="https://www.tax.ny.gov/",
        status="source_verified",
    )
    session.add(entity)
    session.flush()
    session.add(
        TaxFilingMap(
            natural_key="ny:313:2:filing",
            benchmark_tax_type=313,
            tax_level=2,
            ctd_tax_concept="new_york_sales_and_use_tax",
            state_code="NY",
            p_code=None,
            filing_entity_id=entity.id,
            mapping_status="source_verified",
            effective_from=date(1900, 1, 1),
        )
    )
    session.flush()

    data = acquisition_queue_data(session)

    assert data["summary"]["local_tax_amount"] == 120.0
    assert data["summary"]["local_p_codes"] == 1
    assert data["states"][0]["state"] == "NY"
    assert data["states"][0]["unsupported_types"] == 1
    assert data["states"][0]["filing_gaps"] == 1
    assert data["localities"][0]["locality"] == "Johnstown"
    by_type = {row["tax_type"]: row for row in data["tax_types"]}
    assert by_type[313]["legal_support"] is True
    assert by_type[313]["filing_mapped"] is True
    assert by_type[14]["legal_support"] is False
    assert by_type[14]["filing_mapped"] is False
