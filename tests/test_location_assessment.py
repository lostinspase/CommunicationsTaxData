from datetime import date, datetime
from decimal import Decimal

from communications_tax_data.location_assessment import (
    assess_service_locations,
    latest_location_assessment_data,
)
from communications_tax_data.models import (
    AddressAssignment,
    BenchmarkRate,
    FilingEntity,
    Jurisdiction,
    LocationAssessment,
    LocationProfile,
    LocationProfileMember,
    Source,
    TaxFact,
    TaxFactBenchmarkMap,
    TaxFilingMap,
)


def _seed_assessment_address(session) -> AddressAssignment:
    source = Source(
        code="assessment-source",
        name="Assessment source",
        publisher="Test",
        source_type="test",
        url="https://example.test",
    )
    jurisdictions = [
        Jurisdiction(
            external_key="state:NY",
            tax_level=1,
            name="New York",
            state_code="NY",
            valid_from=date(1900, 1, 1),
        ),
        Jurisdiction(
            external_key="census:county:36035",
            tax_level=2,
            name="Fulton County",
            state_code="NY",
            valid_from=date(2020, 1, 1),
        ),
        Jurisdiction(
            external_key="census:place:3638781",
            tax_level=3,
            name="Johnstown city",
            state_code="NY",
            valid_from=date(2020, 1, 1),
        ),
    ]
    session.add_all([source, *jurisdictions])
    session.flush()
    profile = LocationProfile(
        profile_code="CTD-JUR-ASSESSMENT",
        composition_sha256="a" * 64,
        country_iso="USA",
        state_code="NY",
        assignment_method="test",
        confidence="address_range",
        calculation_ready=False,
        status="resolved_core",
        valid_from=date(2026, 7, 1),
    )
    session.add(profile)
    session.flush()
    for role, jurisdiction in zip(
        ("state", "county", "incorporated_place"), jurisdictions, strict=True
    ):
        session.add(
            LocationProfileMember(
                location_profile_id=profile.id,
                jurisdiction_id=jurisdiction.id,
                member_role=role,
            )
        )
    assignment = AddressAssignment(
        source_system="apeiron_service_address",
        source_address_id=7001,
        sourcing_role="service_address",
        address_fingerprint="b" * 64,
        country_iso="USA",
        state_code="NY",
        postal_code="12095",
        plus_four="1000",
        location_profile_id=profile.id,
        benchmark_p_code=123,
        source_id=source.id,
        assignment_method="census_address_range",
        confidence="address_range",
        calculation_ready=False,
        status="resolved_core",
        evidence={"collection_run_id": 1},
    )
    session.add(assignment)
    for level, tax_type in enumerate((10, 20, 30, 40)):
        session.add(
            BenchmarkRate(
                benchmark_id=level + 1,
                p_code=123,
                tax_type=tax_type,
                tax_level=level,
                effective_date=datetime(2026, 7, 1),
                active=True,
                tax_category="TEST",
                tax_description=f"Level {level}",
                level_exemptible=False,
                rate=Decimal("0.01"),
                source_timestamp=datetime(2026, 7, 1),
            )
        )
    for level, tax_type in ((0, 10), (1, 20)):
        natural_key = f"public:level:{level}"
        session.add(
            TaxFact(
                natural_key=natural_key,
                jurisdiction_id=jurisdictions[0].id,
                source_id=source.id,
                tax_family="test",
                tax_name=f"Level {level}",
                rate=Decimal("0.01"),
                effective_from=date(2026, 1, 1),
                legal_citation="Test law",
                content_sha256=str(level) * 64,
                status="published",
            )
        )
        session.add(
            TaxFactBenchmarkMap(
                natural_key=f"map:{level}:{tax_type}",
                public_fact_natural_key=natural_key,
                benchmark_tax_type=tax_type,
                benchmark_tax_level=level,
                state_code=None if level == 0 else "NY",
                p_code=None,
                mapping_status="source_verified",
                mapping_method="test",
                confidence="source_verified",
                legal_citation="Test law",
                effective_from=date(2026, 1, 1),
            )
        )
    entity = FilingEntity(
        entity_code="federal-test",
        name="Federal test entity",
        entity_type="tax_authority",
        tax_level=0,
        website_url="https://example.test/filing",
        status="source_verified",
    )
    session.add(entity)
    session.flush()
    session.add(
        TaxFilingMap(
            natural_key="filing:0:10",
            benchmark_tax_type=10,
            tax_level=0,
            ctd_tax_concept="test",
            filing_entity_id=entity.id,
            mapping_status="source_verified",
            effective_from=date(2026, 1, 1),
        )
    )
    session.flush()
    return assignment


def test_daily_assessment_tracks_new_and_unchanged_addresses_by_level(session, tmp_path):
    _seed_assessment_address(session)

    first = assess_service_locations(
        session,
        as_of=date(2026, 7, 26),
        output_dir=tmp_path,
    )
    session.flush()
    snapshot = session.query(LocationAssessment).one()

    assert first["addresses_assessed"] == 1
    assert first["new_addresses"] == 1
    assert first["new_jurisdiction_profiles"] == 1
    assert first["manual_coverage_required"] == 1
    assert snapshot.level_0_status == "complete"
    assert snapshot.level_1_status == "partial"
    assert snapshot.level_2_status == "partial"
    assert snapshot.level_3_status == "partial"
    assert snapshot.level_details["0"]["public_rule_covered_count"] == 1
    assert snapshot.level_details["0"]["filing_covered_count"] == 1
    assert snapshot.level_details["2"]["missing_public_rule_tax_types"] == [30]
    assert "TAX_BOUNDARY_UNVERIFIED" in snapshot.level_details["3"]["gap_codes"]
    assert (tmp_path / "location-assessment-summary.json").is_file()
    csv_text = (tmp_path / "location-assessment-gaps.csv").read_text()
    assert "7001" in csv_text
    assert "MISSING_PUBLIC_RULES" in csv_text

    second = assess_service_locations(session, as_of=date(2026, 7, 27))
    session.flush()
    latest = session.query(LocationAssessment).order_by(LocationAssessment.id.desc()).first()
    assert second["new_addresses"] == 0
    assert second["new_jurisdiction_profiles"] == 0
    assert second["changed_assessments"] == 0
    assert latest.previous_assessment_id == snapshot.id
    assert latest.is_new_address is False
    assert latest.assessment_changed is False

    data = latest_location_assessment_data(session)
    assert data["summary"]["addresses_assessed"] == 1
    assert data["summary"]["new_addresses"] == 0
    assert data["levels"][0]["complete"] == 1
    assert data["levels"][1]["manual_required"] == 1
    assert data["addresses"][0]["source_address_id"] == 7001
    assert "street" not in data["addresses"][0]
    assert "customer_id" not in data["addresses"][0]
