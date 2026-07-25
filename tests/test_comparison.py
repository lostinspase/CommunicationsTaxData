from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from communications_tax_data.comparison import compare_coverage
from communications_tax_data.models import (
    BenchmarkJurisdiction,
    BenchmarkRate,
    CoverageException,
    Jurisdiction,
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
