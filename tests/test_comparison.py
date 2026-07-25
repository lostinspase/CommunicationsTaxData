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
    TaxFactBenchmarkMap,
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
    assert result["matched_benchmark_tax_types"] == 1
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
    assert result["customer_priority_coverage"]["customer_active"][
        "tax_type_strict_rate"
    ] == 100.0
    metrics = {
        item.dimension: item
        for item in session.query(CoverageMetric)
        .filter(CoverageMetric.scope == "customer_active")
        .all()
    }
    assert metrics["customer_zip_statistical"].denominator == 1
    assert metrics["tax_type_strict_rate"].denominator == 1


def test_tax_coverage_counts_unique_nonzero_tax_types_only(session):
    session.add_all(
        [
            BenchmarkRate(
                benchmark_id=101,
                p_code=1,
                tax_type=900,
                tax_level=1,
                effective_date=datetime(2026, 7, 1),
                active=True,
                tax_category="TEST",
                tax_description="One repeated tax type",
                level_exemptible=False,
                rate=Decimal("0.01"),
                source_timestamp=datetime(2026, 7, 1),
            ),
            BenchmarkRate(
                benchmark_id=102,
                p_code=2,
                tax_type=900,
                tax_level=2,
                effective_date=datetime(2026, 7, 1),
                active=True,
                tax_category="TEST",
                tax_description="One repeated tax type",
                level_exemptible=False,
                rate=Decimal("0.02"),
                source_timestamp=datetime(2026, 7, 1),
            ),
            BenchmarkRate(
                benchmark_id=103,
                p_code=2,
                tax_type=901,
                tax_level=1,
                effective_date=datetime(2026, 7, 1),
                active=True,
                tax_category="TEST",
                tax_description="Zero placeholder",
                level_exemptible=False,
                rate=Decimal("0"),
                source_timestamp=datetime(2026, 7, 1),
            ),
        ]
    )
    session.commit()

    result = compare_coverage(session, as_of=date(2026, 7, 24))
    metric = session.query(CoverageMetric).filter_by(
        comparison_run_id=result["run_id"],
        scope="benchmark_total",
        dimension="tax_type_strict_rate",
    ).one()

    assert result["active_nonzero_benchmark_tax_types"] == 1
    assert result["active_nonzero_benchmark_rate_rows_diagnostic"] == 2
    assert metric.denominator == 1
    assert session.query(CoverageException).filter_by(
        exception_type="MISSING_PUBLIC_RATE",
        status="open",
    ).count() == 1


def test_state_aware_fact_map_matches_rate_without_covering_other_states(session):
    jurisdiction = Jurisdiction(
        external_key="state:NY",
        country_iso="USA",
        tax_level=1,
        name="New York",
        state_code="NY",
        valid_from=date(1900, 1, 1),
    )
    source = Source(
        code="ny-test",
        name="New York test source",
        publisher="NYS DTF",
        source_type="state_revenue_rate",
        state_code="NY",
        url="https://www.tax.ny.gov/",
    )
    session.add_all([jurisdiction, source])
    session.flush()
    session.add(
        TaxFact(
            natural_key="ny:dor:state-sales-use-rate",
            jurisdiction_id=jurisdiction.id,
            source_id=source.id,
            tax_family="sales_and_use",
            tax_name="New York State sales and use tax",
            service_category="state_taxable_sales_and_services",
            rate=Decimal("0.04"),
            effective_from=date(1971, 6, 1),
            legal_citation="New York Tax Law § 1105",
            content_sha256="c" * 64,
        )
    )
    session.add(
        TaxFactBenchmarkMap(
            natural_key="ny:avalara:313:1",
            public_fact_natural_key="ny:dor:state-sales-use-rate",
            benchmark_tax_type=313,
            benchmark_tax_level=1,
            state_code="NY",
            p_code=None,
            mapping_status="source_verified",
            mapping_method="source_and_rate_semantics",
            confidence="source_verified",
            legal_citation="New York Tax Law § 1105(b)",
            effective_from=date(1900, 1, 1),
        )
    )
    session.add(
        BenchmarkJurisdiction(
            benchmark_id=300,
            p_code=300,
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
    session.add(
        BenchmarkRate(
            benchmark_id=300,
            p_code=300,
            tax_type=313,
            tax_level=1,
            effective_date=datetime(2026, 7, 1),
            active=True,
            tax_category="SALES AND USE TAXES",
            tax_description="NY Sales Tax",
            level_exemptible=False,
            rate=Decimal("0.04"),
            source_timestamp=datetime(2026, 7, 1),
        )
    )
    session.commit()

    result = compare_coverage(session, as_of=date(2026, 7, 24))

    assert result["matched_benchmark_tax_types"] == 1
    metric = session.query(CoverageMetric).filter_by(
        comparison_run_id=result["run_id"],
        scope="benchmark_total",
        dimension="tax_type_public_law_support",
    ).one()
    assert metric.numerator == 1
    assert metric.denominator == 1
