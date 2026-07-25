from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from communications_tax_data.comparison import compare_coverage
from communications_tax_data.models import (
    BenchmarkJurisdiction,
    BenchmarkRate,
    CoverageException,
    CoverageMetric,
    CustomerTaxNeed,
    Jurisdiction,
    PostalAssignment,
    Source,
    TaxFact,
)


def test_strict_comparison_matches_known_federal_rate_and_flags_unknown(session):
    federal = Jurisdiction(
        external_key="usa:federal",
        country_iso="USA",
        tax_level=0,
        name="United States",
        valid_from=date(1900, 1, 1),
    )
    session.add(federal)
    source = Source(
        code="test-fcc",
        name="Test FCC",
        publisher="FCC",
        source_type="federal_rate",
        url="https://example.test/fcc",
    )
    session.add(source)
    session.flush()
    session.add(
        TaxFact(
            natural_key="fcc:fusf:2026:q3",
            jurisdiction_id=federal.id,
            source_id=source.id,
            tax_family="connectivity",
            tax_name="Federal Universal Service Fund contribution factor",
            service_category="interstate",
            rate=Decimal("0.388"),
            effective_from=date(2026, 7, 1),
            effective_to=date(2026, 9, 30),
            content_sha256="a" * 64,
        )
    )
    location = BenchmarkJurisdiction(
        benchmark_id=1,
        p_code=0,
        alternate=False,
        country_iso="USA",
        state_code="",
        county_name="",
        locality_name="",
        zip_begin="00000",
        zip_end="00000",
        source_timestamp=datetime(2026, 7, 1),
    )
    session.add(location)
    session.add_all(
        [
            BenchmarkRate(
                benchmark_id=1,
                p_code=0,
                tax_type=18,
                tax_level=0,
                effective_date=datetime(2026, 7, 1),
                active=True,
                tax_category="CONNECTIVITY CHARGES",
                tax_description="Federal Universal Service Fund",
                level_exemptible=False,
                rate=Decimal("0.388"),
                source_timestamp=datetime(2026, 7, 1),
            ),
            BenchmarkRate(
                benchmark_id=2,
                p_code=0,
                tax_type=999,
                tax_level=0,
                effective_date=datetime(2026, 7, 1),
                active=True,
                tax_category="REGULATORY",
                tax_description="Unknown Fee",
                level_exemptible=False,
                rate=Decimal("0.01"),
                source_timestamp=datetime(2026, 7, 1),
            ),
        ]
    )
    session.commit()
    result = compare_coverage(session, as_of=date(2026, 7, 24))
    assert result["matched_benchmark_rates"] == 1
    assert session.query(CoverageException).count() == 1
    assert session.query(CoverageException).one().exception_type == "MISSING_PUBLIC_RATE"

    second = compare_coverage(session, as_of=date(2026, 7, 24))

    assert second["new_exceptions"] == 0
    assert second["retained_exceptions"] == 1
    assert session.query(CoverageException).count() == 1


def test_customer_priority_metrics_keep_zip_and_rate_denominators_separate(session):
    jurisdiction = Jurisdiction(
        external_key="usa:federal",
        country_iso="USA",
        tax_level=0,
        name="United States",
        valid_from=date(1900, 1, 1),
    )
    source = Source(
        code="test-source",
        name="Test source",
        publisher="Test",
        source_type="test",
        url="https://example.test",
    )
    session.add_all([jurisdiction, source])
    session.flush()
    session.add(
        TaxFact(
            natural_key="fcc:fusf:2026:q3",
            jurisdiction_id=jurisdiction.id,
            source_id=source.id,
            tax_family="connectivity",
            tax_name="Federal Universal Service Fund contribution factor",
            service_category="interstate",
            rate=Decimal("0.388"),
            effective_from=date(2026, 7, 1),
            effective_to=date(2026, 9, 30),
            content_sha256="a" * 64,
        )
    )
    session.add(
        PostalAssignment(
            postal_code="10001",
            jurisdiction_id=jurisdiction.id,
            allocation_ratio=Decimal("1"),
            confidence="statistical",
            assignment_method="test",
            valid_from=date(2020, 1, 1),
            source_id=source.id,
        )
    )
    session.add(
        BenchmarkJurisdiction(
            benchmark_id=20,
            p_code=123,
            alternate=False,
            country_iso="USA",
            state_code="NY",
            county_name="New York",
            locality_name="New York",
            zip_begin="10001",
            zip_end="10001",
            source_timestamp=datetime(2026, 7, 1),
        )
    )
    session.add(
        BenchmarkRate(
            benchmark_id=20,
            p_code=123,
            tax_type=18,
            tax_level=0,
            effective_date=datetime(2026, 7, 1),
            active=True,
            tax_category="CONNECTIVITY CHARGES",
            tax_description="Federal Universal Service Fund",
            level_exemptible=False,
            rate=Decimal("0.388"),
            source_timestamp=datetime(2026, 7, 1),
        )
    )
    session.add(
        CustomerTaxNeed(
            customer_id=1,
            customer_number=10001,
            p_code=123,
            postal_code="10001",
            plus_four=None,
            state_code="NY",
            country_code="US",
            active_customer=True,
            first_tax_invoice=datetime(2026, 1, 1),
            last_tax_invoice=datetime(2026, 7, 1),
            tax_charge_rows=1,
            absolute_tax_amount=Decimal("1"),
        )
    )
    session.commit()

    result = compare_coverage(session, as_of=date(2026, 7, 24))

    assert result["customer_priority_coverage"]["customer_active"][
        "customer_zip_statistical"
    ] == 100.0
    assert result["customer_priority_coverage"]["customer_active"]["strict_rate_rows"] == 100.0
    assert result["customer_priority_coverage"]["customer_active"][
        "pcode_fully_strict_rate"
    ] == 100.0
    metrics = {
        item.dimension: item
        for item in session.query(CoverageMetric)
        .filter(CoverageMetric.scope == "customer_active")
        .all()
    }
    assert metrics["customer_zip_statistical"].denominator == 1
    assert metrics["strict_rate_rows"].denominator == 1
