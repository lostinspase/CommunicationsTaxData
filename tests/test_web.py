from datetime import datetime
from decimal import Decimal

from communications_tax_data.models import (
    BenchmarkRate,
    Source,
    SourceCheck,
    TaxTypeCrosswalk,
)
from communications_tax_data.taxonomy import enrich_federal_usf_crosswalk
from communications_tax_data.web import (
    dashboard_data,
    location_resolver_data,
    source_health,
    tax_types,
)


def test_dashboard_data_handles_empty_database(session):
    data = dashboard_data(session)

    assert data["metrics"]["sources"] == 0
    assert data["metrics"]["source_failures"] == 0
    assert data["metrics"]["current_facts"] == 0
    assert data["metrics"]["benchmark_tax_types"] == 0
    assert data["metrics"]["resolved_addresses"] == 0
    assert data["coverage"] == [
        {"level": 0, "name": "Federal", "public": 0, "benchmark": 0},
        {"level": 1, "name": "State", "public": 0, "benchmark": 0},
        {"level": 2, "name": "County", "public": 0, "benchmark": 0},
        {"level": 3, "name": "Municipal/special", "public": 0, "benchmark": 0},
    ]

    resolver = location_resolver_data(session)
    assert resolver["summary"]["current_assignments"] == 0
    assert resolver["summary"]["resolved_percent"] is None
    assert resolver["latest_run"] is None
    assert resolver["benchmark_comparison"]["state_comparable"] == 0


def test_source_health_reports_latest_failure(session):
    source = Source(
        code="failed-source",
        name="Failed source",
        publisher="Test",
        source_type="test",
        url="https://example.test/source",
    )
    session.add(source)
    session.flush()
    session.add(SourceCheck(source_id=source.id, error="HTTP 403"))
    session.commit()

    data = dashboard_data(session)
    rows = source_health(failed_only=True, limit=100, session=session)

    assert data["metrics"]["source_failures"] == 1
    assert rows[0]["source"] == "failed-source"
    assert rows[0]["error"] == "HTTP 403"


def test_tax_type_api_is_unique_nonzero_and_cites_fusf_variants(session):
    session.add_all(
        [
            BenchmarkRate(
                benchmark_id=1,
                p_code=1,
                tax_type=55,
                tax_level=0,
                effective_date=datetime(2026, 7, 1),
                active=True,
                tax_category="CONNECTIVITY CHARGES",
                tax_description="Fed USF Cellular",
                level_exemptible=False,
                rate=Decimal("0.388"),
                source_timestamp=datetime(2026, 7, 1),
            ),
            BenchmarkRate(
                benchmark_id=2,
                p_code=2,
                tax_type=55,
                tax_level=0,
                effective_date=datetime(2026, 7, 1),
                active=True,
                tax_category="CONNECTIVITY CHARGES",
                tax_description="Fed USF Cellular",
                level_exemptible=False,
                rate=Decimal("0.381"),
                source_timestamp=datetime(2026, 7, 1),
            ),
            BenchmarkRate(
                benchmark_id=3,
                p_code=2,
                tax_type=999,
                tax_level=0,
                effective_date=datetime(2026, 7, 1),
                active=True,
                tax_category="PLACEHOLDER",
                tax_description="Ignore zero",
                level_exemptible=False,
                rate=Decimal("0"),
                source_timestamp=datetime(2026, 7, 1),
            ),
            TaxTypeCrosswalk(
                benchmark_signature="a" * 64,
                benchmark_tax_type=55,
                benchmark_tax_level=0,
                benchmark_tax_category="CONNECTIVITY CHARGES",
                benchmark_tax_description="Fed USF Cellular",
                ctd_tax_concept="universal_service_fund",
                mapping_status="proposed",
                mapping_method="normalized_description",
                confidence="candidate",
            ),
        ]
    )
    session.flush()
    assert enrich_federal_usf_crosswalk(session) == 1

    rows = tax_types(
        mapping_status=None,
        tax_type=None,
        limit=100,
        session=session,
    )

    assert len(rows) == 1
    assert rows[0]["benchmark_tax_type"] == 55
    assert rows[0]["nonzero_rates"] == ["0.381000000", "0.388000000"]
    assert rows[0]["service_categories"] == ["cellular"]
    assert rows[0]["public_law_supported"] is True
    assert len(rows[0]["public_sources"]) == 5
