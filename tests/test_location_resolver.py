import json
from datetime import datetime

from communications_tax_data.location_resolver import (
    GeographyMember,
    Resolution,
    ResolverAddress,
    resolve_priority_locations,
)
from communications_tax_data.models import (
    AddressAssignment,
    BenchmarkJurisdiction,
    CollectionRun,
    LocationProfile,
    LocationProfileMember,
)


def _resolution(_address: ResolverAddress) -> Resolution:
    return Resolution(
        status="resolved_core",
        method="census_address_range",
        confidence="address_range",
        members=(
            GeographyMember(
                role="state",
                external_key="state:PA",
                name="Pennsylvania",
                tax_level=1,
                state_code="PA",
                fips_code="42",
                parent_external_key=None,
                geography_kind="state",
            ),
            GeographyMember(
                role="county",
                external_key="census:county:42101",
                name="Philadelphia County",
                tax_level=2,
                state_code="PA",
                fips_code="42101",
                parent_external_key="state:PA",
                geography_kind="county",
            ),
            GeographyMember(
                role="incorporated_place",
                external_key="census:place:4260000",
                name="Philadelphia city",
                tax_level=3,
                state_code="PA",
                fips_code="4260000",
                parent_external_key="state:PA",
                geography_kind="incorporated_place",
            ),
        ),
        evidence={"match_count": 1, "tiger_line_id": "123"},
    )


def _address(source_id: int, street: str) -> ResolverAddress:
    return ResolverAddress(
        source_address_id=source_id,
        street=street,
        city="Philadelphia",
        state_code="PA",
        postal_code="19103",
        plus_four="1234",
        benchmark_p_code=9001,
    )


def test_resolver_reuses_jurisdiction_set_and_keeps_assignments_effective_dated(session):
    session.add(
        BenchmarkJurisdiction(
            benchmark_id=1,
            p_code=9001,
            alternate=False,
            country_iso="USA",
            state_code="PA",
            county_name="Philadelphia",
            locality_name="Philadelphia",
            zip_begin="19103",
            zip_end="19103",
            source_timestamp=datetime(2026, 7, 1),
        )
    )
    session.flush()
    addresses = [_address(101, "100 Market St"), _address(102, "200 Market St")]

    first = resolve_priority_locations(session, addresses=addresses, geocoder=_resolution)
    session.flush()

    assert first["resolved_core"] == 2
    assert first["profiles_inserted"] == 1
    assert first["profiles_reused"] == 1
    assert first["assignments_inserted"] == 2
    assert first["benchmark_state_match"] == 2
    assert first["benchmark_county_match"] == 2
    assert first["benchmark_locality_match"] == 2
    assert session.query(LocationProfile).count() == 1
    assert session.query(LocationProfileMember).count() == 3
    profile = session.query(LocationProfile).one()
    assert profile.profile_code.startswith("CTD-JUR-")
    assert profile.calculation_ready is False
    assert session.query(AddressAssignment).count() == 2
    for assignment in session.query(AddressAssignment):
        assert assignment.location_profile_id == profile.id
        assert assignment.calculation_ready is False
        evidence = json.dumps(assignment.evidence)
        assert "Market St" not in evidence
        assert "matchedAddress" not in evidence

    second = resolve_priority_locations(session, addresses=addresses, geocoder=_resolution)
    session.flush()
    assert second["addresses_skipped_unchanged"] == 2
    assert session.query(AddressAssignment).count() == 2

    changed = resolve_priority_locations(
        session,
        addresses=[_address(101, "101 Market St")],
        geocoder=_resolution,
    )
    session.flush()
    assert changed["assignments_superseded"] == 1
    versions = (
        session.query(AddressAssignment)
        .filter(AddressAssignment.source_address_id == 101)
        .order_by(AddressAssignment.valid_from)
        .all()
    )
    assert len(versions) == 2
    assert versions[0].valid_to is not None
    assert versions[1].valid_to is None
    assert versions[0].address_fingerprint != versions[1].address_fingerprint

    latest = (
        session.query(CollectionRun)
        .filter(CollectionRun.collector == "location-resolver-v1")
        .order_by(CollectionRun.id.desc())
        .first()
    )
    assert latest.details["assignments_superseded"] == 1


def test_resolver_records_insufficient_input_without_creating_profile(session):
    session.add(
        BenchmarkJurisdiction(
            benchmark_id=2,
            p_code=9002,
            alternate=False,
            country_iso="USA",
            state_code="PA",
            county_name="Some County",
            locality_name="Somewhere",
            zip_begin="19000",
            zip_end="19000",
            source_timestamp=datetime(2026, 7, 1),
        )
    )
    session.flush()
    address = ResolverAddress(
        source_address_id=55,
        street=None,
        city="Nowhere",
        state_code="PA",
        postal_code="19000",
        benchmark_p_code=9002,
    )

    def insufficient(_address: ResolverAddress) -> Resolution:
        return Resolution(
            status="insufficient_input",
            method="census_geocoder_not_called",
            confidence="none",
            evidence={"has_street": False},
        )

    result = resolve_priority_locations(
        session,
        addresses=[address],
        geocoder=insufficient,
    )
    session.flush()

    assert result["insufficient_input"] == 1
    assert result["benchmark_state_mismatch"] == 0
    assert result["benchmark_county_mismatch"] == 0
    assert result["benchmark_locality_mismatch"] == 0
    assert session.query(LocationProfile).count() == 0
    assignment = session.query(AddressAssignment).one()
    assert assignment.status == "insufficient_input"
    assert assignment.location_profile_id is None
