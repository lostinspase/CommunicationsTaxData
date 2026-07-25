from datetime import date, datetime
from decimal import Decimal

from communications_tax_data.location_profiles import build_customer_location_profiles
from communications_tax_data.models import (
    CustomerTaxNeed,
    Jurisdiction,
    LocationProfile,
    LocationProfileMember,
    PostalAssignment,
    Source,
)


def test_location_profile_is_stable_and_not_calculation_ready(session):
    source = Source(
        code="census-test",
        name="Census test",
        publisher="Census",
        source_type="geographic_relationship",
        url="https://example.test",
    )
    jurisdiction = Jurisdiction(
        external_key="census:county:36061",
        tax_level=2,
        name="New York County",
        state_code="NY",
        valid_from=date(2020, 1, 1),
    )
    session.add_all([source, jurisdiction])
    session.flush()
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
        CustomerTaxNeed(
            customer_id=1,
            customer_number=10001,
            p_code=123,
            postal_code="10001",
            plus_four="0001",
            state_code="NY",
            country_code="US",
            active_customer=True,
            first_tax_invoice=datetime(2025, 1, 1),
            last_tax_invoice=datetime(2026, 7, 1),
            tax_charge_rows=10,
            absolute_tax_amount=Decimal("100"),
        )
    )
    session.flush()

    first = build_customer_location_profiles(session, as_of=date(2026, 7, 25))
    session.flush()
    profile = session.query(LocationProfile).one()

    assert first["profiles_inserted"] == 1
    assert profile.profile_code.startswith("CTD-")
    assert profile.benchmark_p_code == 123
    assert profile.confidence == "statistical"
    assert profile.calculation_ready is False
    assert session.query(LocationProfileMember).count() == 1

    second = build_customer_location_profiles(session, as_of=date(2026, 7, 25))
    session.flush()
    assert second["profiles_refreshed"] == 1
    assert session.query(LocationProfile).count() == 1
    assert session.query(LocationProfileMember).count() == 1
