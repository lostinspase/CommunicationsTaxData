from datetime import date, datetime
from decimal import Decimal

from communications_tax_data.models import (
    AddressAssignment,
    BenchmarkRate,
    CompanyNexusDetermination,
    CustomerTaxProfile,
    FilingEntity,
    Jurisdiction,
    LocationProfile,
    ProductTaxonomyMap,
    ServiceProductDemand,
    ServiceTaxAssessment,
    Source,
    TaxabilityRule,
    TaxFact,
    TaxFilingMap,
    TaxTypeCrosswalk,
)
from communications_tax_data.product_demand import seed_product_taxonomy
from communications_tax_data.tax_determination import (
    assess_service_tax_demand,
    latest_service_tax_data,
    product_taxonomy_data,
    write_service_tax_report,
)
from communications_tax_data.web import templates


def _seed_service_determination(
    session,
    *,
    mapping_status: str = "reviewed",
    location_ready: bool = True,
    source_tax_exempt_state: bool = False,
) -> None:
    source = Source(
        code="service-tax-test",
        name="Service tax test",
        publisher="Test",
        source_type="test",
        tax_level=1,
        state_code="NY",
        url="https://example.test/tax",
    )
    jurisdiction = Jurisdiction(
        external_key="state:NY",
        tax_level=1,
        name="New York",
        state_code="NY",
        valid_from=date(1900, 1, 1),
        source_id=None,
    )
    session.add_all([source, jurisdiction])
    session.flush()
    jurisdiction.source_id = source.id
    profile = LocationProfile(
        profile_code="CTD-JUR-SERVICE-TAX",
        composition_sha256="d" * 64,
        country_iso="USA",
        state_code="NY",
        postal_code="10001",
        benchmark_p_code=123,
        assignment_method="test",
        confidence="reviewed",
        calculation_ready=location_ready,
        status="published" if location_ready else "resolved_core",
        valid_from=date(2026, 1, 1),
    )
    session.add(profile)
    session.flush()
    session.add(
        AddressAssignment(
            source_system="apeiron_service_address",
            source_address_id=9001,
            sourcing_role="service_address",
            address_fingerprint="e" * 64,
            country_iso="USA",
            state_code="NY",
            postal_code="10001",
            location_profile_id=profile.id,
            benchmark_p_code=123,
            source_id=source.id,
            assignment_method="test",
            confidence="reviewed",
            calculation_ready=location_ready,
            status="resolved_core",
        )
    )
    session.add(
        ProductTaxonomyMap(
            source_system="apeiron_product",
            source_tax_group="internet_access",
            service_category="internet_access",
            default_sourcing_role="service_address",
            mapping_status=mapping_status,
            mapping_method="test",
            confidence="reviewed" if mapping_status == "reviewed" else "candidate",
            effective_from=date(1900, 1, 1),
        )
    )
    session.add(
        CustomerTaxProfile(
            customer_id=501,
            customer_number=10001,
            source_address_id=9001,
            active_customer=True,
            source_tax_exempt=False,
            source_tax_exempt_federal=False,
            source_tax_exempt_state=source_tax_exempt_state,
            source_tax_exempt_local=False,
            evidence_status=("source_flag_only" if source_tax_exempt_state else "not_claimed"),
        )
    )
    session.add(
        ServiceProductDemand(
            demand_key="f" * 64,
            customer_id=501,
            customer_number=10001,
            source_address_id=9001,
            source_product_id=77,
            source_tax_group="internet_access",
            charge_type="recurring",
            active_customer=True,
            first_invoice_at=datetime(2026, 7, 1),
            last_invoice_at=datetime(2026, 7, 25),
            invoice_count=1,
            charge_rows=1,
            quantity=Decimal("1"),
            trailing_billed_amount=Decimal("100.00"),
            trailing_window_start=date(2025, 7, 26),
        )
    )
    session.add(
        BenchmarkRate(
            benchmark_id=1,
            p_code=123,
            tax_type=20,
            tax_level=1,
            effective_date=datetime(2026, 1, 1),
            active=True,
            tax_category="SALES TAX",
            tax_description="State sales tax",
            level_exemptible=True,
            rate=Decimal("0.05"),
            source_timestamp=datetime(2026, 7, 1),
        )
    )
    session.add(
        TaxTypeCrosswalk(
            benchmark_signature="1" * 64,
            benchmark_tax_type=20,
            benchmark_tax_level=1,
            benchmark_tax_category="SALES TAX",
            benchmark_tax_description="State sales tax",
            ctd_tax_concept="sales_tax",
            service_category="internet_access",
            mapping_status="reviewed",
            mapping_method="test",
            confidence="reviewed",
            legal_citation="Test Tax Law § 1",
        )
    )
    session.add(
        TaxFact(
            natural_key="test:ny:sales",
            jurisdiction_id=jurisdiction.id,
            source_id=source.id,
            tax_family="sales_and_use",
            tax_name="New York test sales tax",
            service_category="internet_access",
            rate=Decimal("0.05"),
            unit="percent_of_base",
            effective_from=date(2026, 1, 1),
            legal_citation="Test Tax Law § 1",
            content_sha256="2" * 64,
            status="published",
        )
    )
    session.add(
        TaxabilityRule(
            natural_key="taxability:ny:sales:internet",
            ctd_tax_concept="sales_tax",
            tax_fact_natural_key="test:ny:sales",
            tax_level=1,
            state_code="NY",
            service_category="internet_access",
            charge_type="recurring",
            taxability="taxable",
            sourcing_role="service_address",
            calculation_method="percent_of_charge",
            taxable_percentage=Decimal("1"),
            filing_required=True,
            legal_citation="Test Tax Law § 1",
            source_id=source.id,
            review_status="reviewed",
            confidence="reviewed",
            effective_from=date(2026, 1, 1),
            reviewed_by="test-reviewer",
            reviewed_at=datetime(2026, 7, 1),
        )
    )
    session.add(
        CompanyNexusDetermination(
            state_code="NY",
            tax_family="sales_and_use",
            physical_presence_status="not_present",
            economic_nexus_status="exceeded",
            obligation_status="collection_required",
            registration_status="registered",
            collection_status="collecting",
            determination_basis="Test reviewed nexus determination.",
            evidence_reference="test",
            review_status="reviewed",
            reviewed_by="test-reviewer",
            reviewed_at=datetime(2026, 7, 1),
            effective_from=date(2026, 1, 1),
        )
    )
    entity = FilingEntity(
        entity_code="ny-test-filing",
        name="New York test filing entity",
        entity_type="revenue_department",
        tax_level=1,
        state_code="NY",
        website_url="https://example.test/filing",
        status="source_verified",
    )
    session.add(entity)
    session.flush()
    session.add(
        TaxFilingMap(
            natural_key="filing:ny:test-sales",
            benchmark_tax_type=20,
            tax_level=1,
            ctd_tax_concept="sales_tax",
            state_code="NY",
            filing_entity_id=entity.id,
            mapping_status="source_verified",
            effective_from=date(2026, 1, 1),
        )
    )
    session.flush()


def test_service_determination_calculates_only_after_all_gates_pass(session, tmp_path):
    _seed_service_determination(session)

    first = assess_service_tax_demand(
        session,
        as_of=date(2026, 7, 26),
        output_dir=tmp_path,
    )
    session.flush()
    snapshot = session.query(ServiceTaxAssessment).one()

    assert first["demand_rows_assessed"] == 1
    assert first["calculation_ready"] == 1
    assert first["calculation_ready_billed_amount"] == "100.00"
    assert first["estimated_public_tax_amount"] == "5.000000"
    assert snapshot.product_mapping_ready is True
    assert snapshot.location_ready is True
    assert snapshot.taxability_ready is True
    assert snapshot.nexus_ready is True
    assert snapshot.exemption_ready is True
    assert snapshot.filing_ready is True
    assert snapshot.calculation_ready is True
    assert snapshot.route_details[0]["public_fact"] == "test:ny:sales"
    assert snapshot.route_details[0]["legal_citation"] == "Test Tax Law § 1"
    assert (tmp_path / "service-tax-assessment-summary.json").is_file()
    assert (tmp_path / "service-tax-assessment-gaps.csv").is_file()

    prior_demand = session.query(ServiceProductDemand).one()
    session.delete(prior_demand)
    session.flush()
    session.add(
        ServiceProductDemand(
            demand_key="f" * 64,
            customer_id=501,
            customer_number=10001,
            source_address_id=9001,
            source_product_id=77,
            source_tax_group="internet_access",
            charge_type="recurring",
            active_customer=True,
            first_invoice_at=datetime(2026, 7, 1),
            last_invoice_at=datetime(2026, 7, 25),
            invoice_count=1,
            charge_rows=1,
            quantity=Decimal("1"),
            trailing_billed_amount=Decimal("100.00"),
            trailing_window_start=date(2025, 7, 27),
        )
    )
    session.flush()
    second = assess_service_tax_demand(session, as_of=date(2026, 7, 27))
    session.flush()
    latest = session.query(ServiceTaxAssessment).order_by(ServiceTaxAssessment.id.desc()).first()
    assert second["new_demand_rows"] == 0
    assert second["changed_assessments"] == 0
    assert latest.previous_assessment_id == snapshot.id

    data = latest_service_tax_data(session, manual_only=False)
    assert data["summary"]["calculation_ready_billed_percent"] == 100.0
    assert data["assessments"][0]["source_address_id"] == 9001
    assert "customer_id" not in data["assessments"][0]
    assert "customer_number" not in data["assessments"][0]
    assert data["assessments"][0]["routes"] == []
    evidence = latest_service_tax_data(session, manual_only=False, include_routes=True)
    assert evidence["assessments"][0]["routes"][0]["public_fact"] == "test:ny:sales"
    assert product_taxonomy_data(session)[0]["source_tax_group"] == "internet_access"
    rendered = templates.get_template("tax_determination.html").render(**data)
    assert "Tax Determination v1" in rendered
    assert "internet_access" in rendered


def test_service_determination_keeps_independent_review_gates(session):
    _seed_service_determination(
        session,
        mapping_status="proposed",
        location_ready=False,
        source_tax_exempt_state=True,
    )

    assess_service_tax_demand(session, as_of=date(2026, 7, 26))
    session.flush()
    snapshot = session.query(ServiceTaxAssessment).one()

    assert snapshot.product_mapping_ready is False
    assert snapshot.location_ready is False
    assert snapshot.taxability_ready is True
    assert snapshot.nexus_ready is True
    assert snapshot.exemption_ready is False
    assert snapshot.calculation_ready is False
    assert "PRODUCT_MAPPING_UNREVIEWED" in snapshot.gap_codes
    assert "TAX_BOUNDARY_UNVERIFIED" in snapshot.gap_codes
    assert "EXEMPTION_EVIDENCE_UNVERIFIED" in snapshot.gap_codes


def test_sales_use_route_requires_reviewed_nexus_and_registration(session):
    _seed_service_determination(session)
    session.query(CompanyNexusDetermination).delete()
    session.flush()

    assess_service_tax_demand(session, as_of=date(2026, 7, 26))
    snapshot = session.query(ServiceTaxAssessment).one()

    assert snapshot.taxability_ready is True
    assert snapshot.nexus_ready is False
    assert snapshot.filing_ready is True
    assert snapshot.calculation_ready is False
    assert "NEXUS_DETERMINATION_MISSING" in snapshot.gap_codes


def test_taxonomy_seeding_preserves_human_review(session):
    first = seed_product_taxonomy(session, ["voice-trunk", "mystery-service"])
    session.flush()
    voice = (
        session.query(ProductTaxonomyMap)
        .filter(ProductTaxonomyMap.source_tax_group == "voice-trunk")
        .one()
    )
    voice.mapping_status = "reviewed"
    voice.reviewed_by = "tax-counsel"
    session.flush()

    second = seed_product_taxonomy(session, ["voice-trunk", "mystery-service"])
    session.flush()

    assert first["taxonomy_inserted"] == 2
    assert second["taxonomy_inserted"] == 0
    assert voice.service_category == "interconnected_voip"
    assert voice.mapping_status == "reviewed"
    assert voice.reviewed_by == "tax-counsel"
    mystery = (
        session.query(ProductTaxonomyMap)
        .filter(ProductTaxonomyMap.source_tax_group == "mystery-service")
        .one()
    )
    assert mystery.service_category is None
    assert mystery.confidence == "unmapped"


def test_gap_report_sorts_rows_with_and_without_source_addresses(tmp_path):
    common = {
        "new_demand": True,
        "assessment_changed": True,
        "trailing_billed_amount": "10.00",
        "calculation_ready": False,
    }
    rows = [
        {**common, "source_address_id": 20},
        {**common, "source_address_id": ""},
    ]

    _, gaps_path = write_service_tax_report(
        tmp_path,
        run_id=1,
        counts={},
        report_rows=rows,
    )

    lines = gaps_path.read_text().splitlines()
    assert lines[1].endswith(",")
    assert lines[2].endswith(",20")
