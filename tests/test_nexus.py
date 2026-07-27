from datetime import date
from decimal import Decimal

from communications_tax_data.models import ExemptionFormStateCheck, StateNexusExposure
from communications_tax_data.nexus import (
    assess_nexus,
    nexus_dashboard_data,
    seed_nexus_rules,
)


def test_nexus_seed_and_assessment_cover_all_states(session):
    seeded = seed_nexus_rules(session)
    assert seeded["rules_inserted"] == 50
    assert seeded["company_determinations_inserted"] == 3
    assert seeded["providers_inserted"] == 5

    session.add_all(
        [
            StateNexusExposure(
                state_code="UT",
                period_start=date(2025, 1, 1),
                period_end=date(2025, 12, 31),
                as_of_date=date(2026, 7, 27),
                gross_billed_amount=Decimal("827360.01"),
                tpp_candidate_amount=Decimal("0"),
                service_candidate_amount=Decimal("827360.01"),
                unclassified_amount=Decimal("0"),
                invoice_count=24,
                customer_count=4,
                limitations="Test screening proxy.",
            ),
            StateNexusExposure(
                state_code="NY",
                period_start=date(2025, 1, 1),
                period_end=date(2025, 12, 31),
                as_of_date=date(2026, 7, 27),
                gross_billed_amount=Decimal("790524.52"),
                tpp_candidate_amount=Decimal("36379.23"),
                service_candidate_amount=Decimal("754145.29"),
                unclassified_amount=Decimal("0"),
                invoice_count=1000,
                customer_count=20,
                limitations="Test screening proxy.",
            ),
            StateNexusExposure(
                state_code="CA",
                period_start=date(2025, 1, 1),
                period_end=date(2025, 12, 31),
                as_of_date=date(2026, 7, 27),
                gross_billed_amount=Decimal("443222.07"),
                tpp_candidate_amount=Decimal("12000.00"),
                service_candidate_amount=Decimal("431222.07"),
                unclassified_amount=Decimal("0"),
                invoice_count=1466,
                customer_count=40,
                limitations="Test screening proxy.",
            ),
        ]
    )
    session.flush()
    session.add(
        ExemptionFormStateCheck(
            provider_code="fastsalestax",
            state_code="CA",
            checked_on=date(2026, 7, 27),
            form_count=16,
            downloaded_count=16,
            status="available",
            source_page_url="https://www.fastsalestax.com/forms/exemption",
        )
    )
    session.flush()

    result = assess_nexus(session, as_of=date(2026, 7, 27))
    data = nexus_dashboard_data(session)

    assert result["states"] == 50
    assert len(data["states"]) == 50
    by_state = {row["state_code"]: row for row in data["states"]}
    assert by_state["UT"]["status"] == "economic_nexus_candidate"
    assert by_state["UT"]["threshold_percent"] == 827.36
    assert by_state["NY"]["status"] == "monitor"
    assert by_state["CA"]["status"] == "physical_presence_review"
    assert by_state["CA"]["basis_amount"] == 12000.0
    assert by_state["CA"]["exemption_form_status"] == "available"
    assert by_state["DE"]["status"] == "no_statewide_sales_tax"
    assert data["summary"]["states"] == 50


def test_nexus_seed_is_idempotent(session):
    first = seed_nexus_rules(session)
    second = seed_nexus_rules(session)

    assert first["rules_inserted"] == 50
    assert second == {
        "rules_inserted": 0,
        "company_determinations_inserted": 0,
        "providers_inserted": 0,
    }
