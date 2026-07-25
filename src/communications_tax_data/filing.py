from __future__ import annotations

import re
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from communications_tax_data.models import (
    BenchmarkJurisdiction,
    BenchmarkRate,
    FilingDocument,
    FilingEntity,
    TaxFact,
    TaxFactBenchmarkMap,
    TaxFilingMap,
    utcnow,
)
from communications_tax_data.taxonomy import enrich_federal_usf_crosswalk

FORM_720_URL = "https://www.irs.gov/forms-pubs/about-form-720"
FORM_720_INSTRUCTIONS_URL = "https://www.irs.gov/instructions/i720"
PUBLICATION_510_URL = "https://www.irs.gov/publications/p510"
USAC_FORMS_URL = "https://www.usac.org/service-providers/resources/forms/"
USAC_FILING_URL = (
    "https://www.usac.org/service-providers/contributing-to-the-usf/how-to-use-e-file/"
)
USAC_PAYMENT_URL = "https://www.usac.org/service-providers/making-payments/"
USAC_THIRD_PARTY_URL = (
    "https://www.usac.org/service-providers/making-payments/non-usac-payments/"
    "invoice-from-third-parties/"
)
FCC_CORES_URL = "https://apps.fcc.gov/cores/userLogin.do"
FCC_FEE_URL = "https://www.fcc.gov/licensing-databases/fees/cores-payment-system"
NY_WCS_FORMS_URL = "https://www.tax.ny.gov/forms/wireless_communications.htm"
NY_WCS1_URL = "https://www.tax.ny.gov/pdf/current_forms/wcs/wcs1.pdf"
NY_WCS1_INSTRUCTIONS_URL = "https://www.tax.ny.gov/pdf/current_forms/wcs/wcs1i.pdf"
NY_SALES_FORMS_URL = "https://www.tax.ny.gov/forms/prvforms/sales_tax_2025_2026.htm"
NY_CT186E_URL = "https://www.tax.ny.gov/pdf/current_forms/ct/ct186e.pdf"
NY_CT186E_INSTRUCTIONS_URL = "https://www.tax.ny.gov/pdf/current_forms/ct/ct186ei.pdf"
PA_GRT_URL = (
    "https://www.pa.gov/agencies/revenue/resources/tax-types-and-information/"
    "corporation-taxes/gross-receipts-tax"
)
PA_SALES_URL = (
    "https://www.pa.gov/agencies/revenue/resources/tax-types-and-information/"
    "sales-use-and-hotel-occupancy-tax"
)


def _entity(session: Session, code: str, **values) -> tuple[FilingEntity, bool]:
    item = session.scalar(select(FilingEntity).where(FilingEntity.entity_code == code))
    created = item is None
    if item is None:
        item = FilingEntity(entity_code=code, **values)
        session.add(item)
    else:
        for key, value in values.items():
            setattr(item, key, value)
    item.last_verified_at = utcnow()
    session.flush()
    return item, created


def _document(
    session: Session,
    *,
    entity: FilingEntity,
    document_type: str,
    form_number: str,
    effective_from: date,
    **values,
) -> tuple[FilingDocument, bool]:
    item = session.scalar(
        select(FilingDocument).where(
            FilingDocument.filing_entity_id == entity.id,
            FilingDocument.document_type == document_type,
            FilingDocument.form_number == form_number,
            FilingDocument.effective_from == effective_from,
        )
    )
    created = item is None
    if item is None:
        item = FilingDocument(
            filing_entity_id=entity.id,
            document_type=document_type,
            form_number=form_number,
            effective_from=effective_from,
            **values,
        )
        session.add(item)
    else:
        for key, value in values.items():
            setattr(item, key, value)
    item.last_verified_at = utcnow()
    session.flush()
    return item, created


def _filing_map(
    session: Session,
    *,
    natural_key: str,
    effective_from: date,
    **values,
) -> tuple[TaxFilingMap, bool]:
    item = session.scalar(
        select(TaxFilingMap).where(
            TaxFilingMap.natural_key == natural_key,
            TaxFilingMap.effective_from == effective_from,
        )
    )
    created = item is None
    if item is None:
        item = TaxFilingMap(
            natural_key=natural_key,
            effective_from=effective_from,
            **values,
        )
        session.add(item)
    else:
        for key, value in values.items():
            setattr(item, key, value)
    item.last_verified_at = utcnow()
    return item, created


def _fact_benchmark_map(
    session: Session,
    *,
    natural_key: str,
    effective_from: date,
    **values,
) -> tuple[TaxFactBenchmarkMap, bool]:
    item = session.scalar(
        select(TaxFactBenchmarkMap).where(
            TaxFactBenchmarkMap.natural_key == natural_key,
            TaxFactBenchmarkMap.effective_from == effective_from,
        )
    )
    created = item is None
    if item is None:
        item = TaxFactBenchmarkMap(
            natural_key=natural_key,
            effective_from=effective_from,
            **values,
        )
        session.add(item)
    else:
        for key, value in values.items():
            setattr(item, key, value)
    return item, created


def _slug(value: str | None) -> str:
    cleaned = re.sub(r"\s+county$", "", value or "", flags=re.IGNORECASE)
    return re.sub(r"[^a-z0-9]+", "-", cleaned.casefold()).strip("-")


def seed_federal_filing_map(session: Session) -> dict[str, int]:
    """Seed public-source-verified federal entities, forms, and benchmark links."""
    counts = {
        "entities_inserted": 0,
        "documents_inserted": 0,
        "maps_inserted": 0,
        "federal_usf_crosswalks_enriched": 0,
    }
    common = {
        "tax_level": 0,
        "state_code": None,
        "jurisdiction_external_key": "usa:federal",
        "status": "source_verified",
        "effective_from": date(1900, 1, 1),
    }
    irs, created = _entity(
        session,
        "us-irs-excise",
        name="Internal Revenue Service — Excise Tax",
        payee_name="United States Treasury",
        entity_type="tax_authority",
        website_url=FORM_720_URL,
        filing_portal_url="https://www.irs.gov/e-file-providers/e-file-form-720",
        payment_url="https://www.irs.gov/payments",
        registration_url=None,
        mailing_address=(
            "Department of the Treasury, Internal Revenue Service, "
            "Ogden, UT 84201-0009"
        ),
        legal_citation="26 USC §§ 4251 and 4291; Form 720, IRS No. 22",
        **common,
    )
    counts["entities_inserted"] += int(created)
    usac, created = _entity(
        session,
        "us-usac-499",
        name="Universal Service Administrative Company — FCC Forms 499",
        payee_name="Universal Service Administrative Company",
        entity_type="designated_administrator",
        website_url=USAC_FORMS_URL,
        filing_portal_url=USAC_FILING_URL,
        payment_url=USAC_PAYMENT_URL,
        registration_url=USAC_FILING_URL,
        mailing_address=None,
        legal_citation="47 CFR §§ 54.706 and 54.711",
        **common,
    )
    counts["entities_inserted"] += int(created)
    trs_admin, created = _entity(
        session,
        "us-trs-administrator",
        name="Interstate Telecommunications Relay Services Fund Administrator",
        payee_name="Rolka Loube",
        entity_type="designated_administrator",
        website_url=USAC_THIRD_PARTY_URL,
        filing_portal_url=None,
        payment_url=USAC_THIRD_PARTY_URL,
        registration_url=None,
        mailing_address=None,
        legal_citation="47 CFR § 64.604(c)(5)(iii)",
        **common,
    )
    counts["entities_inserted"] += int(created)
    fcc, created = _entity(
        session,
        "us-fcc-regulatory-fees",
        name="Federal Communications Commission — Regulatory Fees",
        payee_name="Federal Communications Commission",
        entity_type="regulator",
        website_url=FCC_FEE_URL,
        filing_portal_url=FCC_CORES_URL,
        payment_url=FCC_CORES_URL,
        registration_url=FCC_CORES_URL,
        mailing_address=None,
        legal_citation="47 USC § 159; 47 CFR part 1, subpart G",
        **common,
    )
    counts["entities_inserted"] += int(created)

    form720, created = _document(
        session,
        entity=irs,
        document_type="return",
        form_number="720",
        title="Quarterly Federal Excise Tax Return",
        url=FORM_720_URL,
        instructions_url=FORM_720_INSTRUCTIONS_URL,
        effective_from=date(2026, 6, 1),
        status="source_verified",
        source_locator=FORM_720_INSTRUCTIONS_URL,
    )
    counts["documents_inserted"] += int(created)
    pub510, created = _document(
        session,
        entity=irs,
        document_type="exemption_guidance",
        form_number="Publication 510",
        title="Excise Taxes — communications-tax exemption certificates",
        url=PUBLICATION_510_URL,
        instructions_url=None,
        effective_from=date(2025, 12, 1),
        status="source_verified",
        source_locator=PUBLICATION_510_URL,
    )
    counts["documents_inserted"] += int(created)
    form499a, created = _document(
        session,
        entity=usac,
        document_type="return",
        form_number="FCC 499-A",
        title="Annual Telecommunications Reporting Worksheet",
        url=USAC_FORMS_URL,
        instructions_url=USAC_FORMS_URL,
        effective_from=date(2026, 1, 1),
        status="source_verified",
        source_locator=USAC_FORMS_URL,
    )
    counts["documents_inserted"] += int(created)
    _, created = _document(
        session,
        entity=usac,
        document_type="return",
        form_number="FCC 499-Q",
        title="Quarterly Telecommunications Reporting Worksheet",
        url=USAC_FORMS_URL,
        instructions_url=USAC_FORMS_URL,
        effective_from=date(2026, 1, 1),
        status="source_verified",
        source_locator=USAC_FORMS_URL,
    )
    counts["documents_inserted"] += int(created)
    cores, created = _document(
        session,
        entity=fcc,
        document_type="filing_portal",
        form_number="CORES",
        title="Commission Registration System regulatory-fee filing and payment",
        url=FCC_CORES_URL,
        instructions_url=FCC_FEE_URL,
        effective_from=date(2025, 1, 1),
        status="source_verified",
        source_locator=FCC_FEE_URL,
    )
    counts["documents_inserted"] += int(created)

    base_map = {
        "tax_level": 0,
        "state_code": None,
        "p_code": None,
        "jurisdiction_external_key": "usa:federal",
        "mapping_status": "source_verified",
    }
    _, created = _filing_map(
        session,
        natural_key="federal:avalara:6:excise",
        effective_from=date(2006, 8, 1),
        benchmark_tax_type=6,
        ctd_tax_concept="federal_communications_excise",
        filing_entity_id=irs.id,
        payment_entity_id=irs.id,
        return_document_id=form720.id,
        exemption_document_id=pub510.id,
        filing_frequency="quarterly",
        due_rule="Form 720 is generally due by the last day of the month after the quarter.",
        reporting_basis="Form 720, Part I, IRS No. 22; deposits may be semimonthly.",
        payment_recipient="United States Treasury",
        legal_citation="26 USC §§ 4251 and 4291; Form 720 instructions",
        **base_map,
    )
    counts["maps_inserted"] += int(created)

    usf_types = (7, 18, 55, 56, 83, 162, 163, 277, 311, 444, 625, 626, 627, 628, 629)
    for tax_type in usf_types:
        _, created = _filing_map(
            session,
            natural_key=f"federal:avalara:{tax_type}:usf",
            effective_from=date(1900, 1, 1),
            benchmark_tax_type=tax_type,
            ctd_tax_concept="federal_universal_service_fund",
            filing_entity_id=usac.id,
            payment_entity_id=usac.id,
            return_document_id=form499a.id,
            exemption_document_id=None,
            filing_frequency="annual_and_quarterly",
            due_rule=(
                "FCC Form 499-A is due April 1; Form 499-Q is due February 1, "
                "May 1, August 1, and November 1 for non-de-minimis filers."
            ),
            reporting_basis="FCC Forms 499-A/Q revenue reporting; USAC bills contributions.",
            payment_recipient="Universal Service Administrative Company",
            legal_citation="47 CFR §§ 54.706 and 54.711",
            **base_map,
        )
        counts["maps_inserted"] += int(created)

    trs_types = (23, 31, 62, 63, 88, 217, 232, 234, 235, 585, 586, 587, 588)
    for tax_type in trs_types:
        _, created = _filing_map(
            session,
            natural_key=f"federal:avalara:{tax_type}:trs",
            effective_from=date(1900, 1, 1),
            benchmark_tax_type=tax_type,
            ctd_tax_concept="federal_telecommunications_relay_service",
            filing_entity_id=usac.id,
            payment_entity_id=trs_admin.id,
            return_document_id=form499a.id,
            exemption_document_id=None,
            filing_frequency="annual_and_invoiced",
            due_rule="Revenue is reported on FCC Form 499-A; the TRS administrator invoices.",
            reporting_basis="FCC Form 499-A TRS contribution base.",
            payment_recipient="Interstate TRS Fund Administrator (Rolka Loube)",
            legal_citation="47 CFR § 64.604(c)(5)(iii)",
            **base_map,
        )
        counts["maps_inserted"] += int(created)

    regulatory_types = (72, 169, 170, 226, 274, 429, 430)
    for tax_type in regulatory_types:
        _, created = _filing_map(
            session,
            natural_key=f"federal:avalara:{tax_type}:regulatory",
            effective_from=date(1900, 1, 1),
            benchmark_tax_type=tax_type,
            ctd_tax_concept="fcc_regulatory_fee",
            filing_entity_id=fcc.id,
            payment_entity_id=fcc.id,
            return_document_id=cores.id,
            exemption_document_id=None,
            filing_frequency="annual",
            due_rule="Annual regulatory-fee window and deadline are set by FCC order.",
            reporting_basis="File and pay the assessed regulatory fee in FCC CORES.",
            payment_recipient="Federal Communications Commission",
            legal_citation="47 USC § 159; 47 CFR part 1, subpart G",
            **base_map,
        )
        counts["maps_inserted"] += int(created)

    counts["federal_usf_crosswalks_enriched"] = enrich_federal_usf_crosswalk(session)
    return counts


def seed_state_filing_and_benchmark_maps(session: Session) -> dict[str, int]:
    """Seed source-verified CA/NY/PA benchmark links and state filing recipients."""
    from communications_tax_data.catalog import NY_LOCAL_UTILITY_RULES

    counts = {
        "entities_inserted": 0,
        "documents_inserted": 0,
        "filing_maps_inserted": 0,
        "fact_maps_inserted": 0,
        "fact_maps_removed": 0,
    }
    fact_keys = set(session.scalars(select(TaxFact.natural_key)))

    def map_fact(
        *,
        state: str,
        tax_type: int,
        tax_level: int,
        fact_key: str,
        citation: str,
        service_category: str,
        p_code: int | None = None,
        method: str = "source_and_rate_semantics",
        notes: str | None = None,
    ) -> None:
        if fact_key not in fact_keys:
            return
        suffix = str(p_code) if p_code is not None else "statewide"
        _, created = _fact_benchmark_map(
            session,
            natural_key=(
                f"{state.lower()}:avalara:{tax_type}:{tax_level}:{suffix}:{fact_key}"
            ),
            effective_from=date(1900, 1, 1),
            public_fact_natural_key=fact_key,
            benchmark_tax_type=tax_type,
            benchmark_tax_level=tax_level,
            state_code=state,
            p_code=p_code,
            service_category=service_category,
            mapping_status="source_verified",
            mapping_method=method,
            confidence="source_verified",
            legal_citation=citation,
            notes=notes,
        )
        counts["fact_maps_inserted"] += int(created)

    for tax_type in (622, 624):
        map_fact(
            state="CA",
            tax_type=tax_type,
            tax_level=1,
            fact_key="ca:cpuc:public-purpose-program-flat-surcharge",
            citation="California Public Utilities Code §§ 285 and 285.5",
            service_category="telephone_access_line",
        )
    for tax_type in (306, 604):
        map_fact(
            state="CA",
            tax_type=tax_type,
            tax_level=1,
            fact_key="ca:cpuc:telecommunications-user-fee",
            citation="California Public Utilities Code §§ 401–443",
            service_category="intrastate_telecommunications_revenue",
        )
    map_fact(
        state="PA",
        tax_type=14,
        tax_level=1,
        fact_key="pa:dor:telecommunications-gross-receipts-tax",
        citation="72 P.S. § 8101(a)",
        service_category="telecommunications_provider_gross_receipts",
    )
    for tax_type in (1, 49):
        map_fact(
            state="PA",
            tax_type=tax_type,
            tax_level=1,
            fact_key="pa:dor:telecommunications-sales-use-taxability",
            citation="72 P.S. § 7202; 61 Pa. Code § 60.20",
            service_category="telecommunications_service",
        )
    map_fact(
        state="NY",
        tax_type=313,
        tax_level=1,
        fact_key="ny:dor:state-sales-use-rate",
        citation="New York Tax Law § 1105(b)",
        service_category="intrastate_telecommunications_service",
    )
    map_fact(
        state="NY",
        tax_type=313,
        tax_level=1,
        fact_key="ny:dor:intrastate-telecommunications-sales-taxability",
        citation="New York Tax Law § 1105(b)",
        service_category="intrastate_telecommunications_service",
        method="source_taxability_semantics",
    )
    for fact_key, category in (
        ("ny:dor:wireless-surcharge:postpaid:state", "postpaid_wireless"),
        ("ny:dor:wireless-surcharge:prepaid:state", "prepaid_wireless"),
    ):
        map_fact(
            state="NY",
            tax_type=263,
            tax_level=1,
            fact_key=fact_key,
            citation="New York Tax Law § 186-f",
            service_category=category,
        )
    legacy_mobile_map = session.scalar(
        select(TaxFactBenchmarkMap).where(
            TaxFactBenchmarkMap.natural_key
            == (
                "ny:avalara:14:1:statewide:"
                "ny:dor:telecommunications-excise:mobile"
            )
        )
    )
    if legacy_mobile_map is not None:
        session.delete(legacy_mobile_map)
        counts["fact_maps_removed"] += 1
    for tax_type, fact_key, category in (
        (
            14,
            "ny:dor:telecommunications-excise:nonmobile",
            "nonmobile_telecommunications_provider_gross_receipts",
        ),
        (
            275,
            "ny:dor:telecommunications-excise:mobile",
            "mobile_telecommunications_provider_gross_receipts",
        ),
    ):
        map_fact(
            state="NY",
            tax_type=tax_type,
            tax_level=1,
            fact_key=fact_key,
            citation="New York Tax Law § 186-e",
            service_category=category,
        )

    primary_locations: dict[int, BenchmarkJurisdiction] = {}
    for row in session.scalars(
        select(BenchmarkJurisdiction)
        .where(BenchmarkJurisdiction.state_code == "NY")
        .order_by(
            BenchmarkJurisdiction.p_code,
            BenchmarkJurisdiction.alternate,
            BenchmarkJurisdiction.benchmark_id,
        )
    ):
        primary_locations.setdefault(row.p_code, row)
    active_local = {
        (row.p_code, row.tax_type, row.tax_level)
        for row in session.scalars(
            select(BenchmarkRate)
            .join(
                BenchmarkJurisdiction,
                BenchmarkJurisdiction.p_code == BenchmarkRate.p_code,
            )
            .where(
                BenchmarkJurisdiction.state_code == "NY",
                BenchmarkJurisdiction.alternate.is_(False),
                BenchmarkRate.active.is_(True),
                BenchmarkRate.rate.is_not(None),
                BenchmarkRate.rate != 0,
                BenchmarkRate.tax_level.in_((2, 3)),
                BenchmarkRate.tax_type.in_((263, 313, 315)),
            )
        )
    }
    nyc_counties = {"bronx", "kings", "new-york", "queens", "richmond"}
    for p_code, tax_type, tax_level in active_local:
        location = primary_locations[p_code]
        county_slug = _slug(location.county_name)
        locality_slug = _slug(location.locality_name)
        if county_slug in nyc_counties:
            county_slug = "new-york-city"
        if tax_type == 263 and tax_level == 2:
            for flavor in ("postpaid", "prepaid"):
                fact_key = (
                    f"ny:dor:wireless-surcharge:{flavor}:local:"
                    f"{3 if county_slug == 'new-york-city' else 2}:{county_slug}"
                )
                map_fact(
                    state="NY",
                    tax_type=tax_type,
                    tax_level=tax_level,
                    fact_key=fact_key,
                    citation="New York Tax Law § 186-f",
                    service_category=f"{flavor}_wireless",
                    p_code=p_code,
                    method="benchmark_pcode_to_official_county",
                )
        elif tax_type in (313, 315):
            city_key = f"ny:dor:sales-use-local:3:{locality_slug}"
            county_key = (
                f"ny:dor:sales-use-local:"
                f"{3 if county_slug == 'new-york-city' else 2}:{county_slug}"
            )
            fact_key = city_key if city_key in fact_keys else county_key
            map_fact(
                state="NY",
                tax_type=tax_type,
                tax_level=tax_level,
                fact_key=fact_key,
                citation="New York Tax Law Article 29; Publication 718",
                service_category="locally_taxable_telecommunications_service",
                p_code=p_code,
                method="benchmark_pcode_to_official_reporting_jurisdiction",
                notes=(
                    "Commercial p_code is used only to identify the current target. "
                    "Publication 718 reporting jurisdiction and code are authoritative."
                ),
            )

    for config in NY_LOCAL_UTILITY_RULES:
        fact_key = (
            f"ny:local:{_slug(config['locality'])}:utility-gross-receipts"
        )
        enabling_citation = (
            "New York Village Law § 5-530"
            if config["municipality_type"] == "village"
            else "New York General City Law § 20-b"
        )
        legal_citation = f"{config['local_citation']}; {enabling_citation}"
        if config.get("additional_citation"):
            legal_citation += f"; {config['additional_citation']}"
        map_fact(
            state="NY",
            tax_type=14,
            tax_level=3,
            fact_key=fact_key,
            citation=legal_citation,
            service_category="local_telecommunications_utility_gross_receipts",
            p_code=config["p_code"],
            method="benchmark_pcode_to_adopted_local_ordinance",
            notes=(
                "The p_code identifies the benchmark location only. The adopted "
                "municipal ordinance is the rate and tax-base authority; modern "
                "VoIP, wireless, and bundle classifications still require specific "
                "product analysis."
            ),
        )

    entity_common = {
        "entity_type": "tax_authority",
        "tax_level": 1,
        "jurisdiction_external_key": None,
        "status": "source_verified",
        "effective_from": date(1900, 1, 1),
    }
    ny_dtf, created = _entity(
        session,
        "ny-dtf",
        name="New York State Department of Taxation and Finance",
        payee_name="New York State Department of Taxation and Finance",
        state_code="NY",
        website_url="https://www.tax.ny.gov/",
        filing_portal_url="https://www.tax.ny.gov/online/",
        payment_url="https://www.tax.ny.gov/pay/",
        registration_url="https://www.tax.ny.gov/bus/doingbus.htm",
        mailing_address=None,
        legal_citation="New York Tax Law §§ 1105, 1136, 186-e, and 186-f",
        **entity_common,
    )
    counts["entities_inserted"] += int(created)
    pa_dor, created = _entity(
        session,
        "pa-dor",
        name="Pennsylvania Department of Revenue",
        payee_name="Commonwealth of Pennsylvania",
        state_code="PA",
        website_url="https://www.pa.gov/agencies/revenue",
        filing_portal_url="https://mypath.pa.gov/",
        payment_url="https://mypath.pa.gov/",
        registration_url="https://mypath.pa.gov/",
        mailing_address=None,
        legal_citation="72 P.S. §§ 7202 and 8101",
        **entity_common,
    )
    counts["entities_inserted"] += int(created)

    wcs1, created = _document(
        session,
        entity=ny_dtf,
        document_type="return",
        form_number="WCS-1",
        title="Wireless Communications Surcharge Return",
        url=NY_WCS1_URL,
        instructions_url=NY_WCS1_INSTRUCTIONS_URL,
        effective_from=date(2025, 9, 1),
        status="source_verified",
        source_locator=NY_WCS_FORMS_URL,
    )
    counts["documents_inserted"] += int(created)
    st100, created = _document(
        session,
        entity=ny_dtf,
        document_type="return",
        form_number="ST-100 / Schedule T",
        title="New York State and Local Quarterly Sales and Use Tax Return",
        url=NY_SALES_FORMS_URL,
        instructions_url=NY_SALES_FORMS_URL,
        effective_from=date(2025, 12, 1),
        status="source_verified",
        source_locator=NY_SALES_FORMS_URL,
    )
    counts["documents_inserted"] += int(created)
    ct186e, created = _document(
        session,
        entity=ny_dtf,
        document_type="return",
        form_number="CT-186-E",
        title="Telecommunications Tax Return and Utility Services Tax Return",
        url=NY_CT186E_URL,
        instructions_url=NY_CT186E_INSTRUCTIONS_URL,
        effective_from=date(2026, 1, 1),
        status="source_verified",
        source_locator=NY_CT186E_INSTRUCTIONS_URL,
    )
    counts["documents_inserted"] += int(created)
    rct111, created = _document(
        session,
        entity=pa_dor,
        document_type="return",
        form_number="RCT-111",
        title="Gross Receipts Tax — Telecommunications",
        url=PA_GRT_URL,
        instructions_url=PA_GRT_URL,
        effective_from=date(2026, 1, 1),
        status="source_verified",
        source_locator=PA_GRT_URL,
    )
    counts["documents_inserted"] += int(created)
    pa3, created = _document(
        session,
        entity=pa_dor,
        document_type="return",
        form_number="PA-3",
        title="Sales, Use and Hotel Occupancy Tax Return",
        url=PA_SALES_URL,
        instructions_url=PA_SALES_URL,
        effective_from=date(2026, 1, 1),
        status="source_verified",
        source_locator=PA_SALES_URL,
    )
    counts["documents_inserted"] += int(created)

    def filing(
        *,
        state: str,
        tax_type: int,
        tax_level: int,
        concept: str,
        entity: FilingEntity,
        document: FilingDocument,
        frequency: str,
        due_rule: str,
        basis: str,
        citation: str,
    ) -> None:
        _, created = _filing_map(
            session,
            natural_key=(
                f"{state.lower()}:avalara:{tax_type}:{tax_level}:{concept}:filing"
            ),
            effective_from=date(1900, 1, 1),
            benchmark_tax_type=tax_type,
            tax_level=tax_level,
            ctd_tax_concept=concept,
            state_code=state,
            p_code=None,
            jurisdiction_external_key=f"state:{state}",
            filing_entity_id=entity.id,
            payment_entity_id=entity.id,
            return_document_id=document.id,
            exemption_document_id=None,
            filing_frequency=frequency,
            due_rule=due_rule,
            reporting_basis=basis,
            payment_recipient=entity.payee_name,
            legal_citation=citation,
            mapping_status="source_verified",
        )
        counts["filing_maps_inserted"] += int(created)

    for level in (1, 2):
        filing(
            state="NY",
            tax_type=263,
            tax_level=level,
            concept="new_york_wireless_communications_surcharge",
            entity=ny_dtf,
            document=wcs1,
            frequency="quarterly",
            due_rule="Due on the twentieth day after the end of each calendar quarter.",
            basis=(
                "WCS-1 reports state and locality device/transaction counts and "
                "surcharges by place of primary use or prepaid sale location."
            ),
            citation="New York Tax Law § 186-f; Form WCS-1 instructions",
        )
    for tax_type, levels in ((313, (1, 2, 3)), (315, (3,))):
        for level in levels:
            filing(
                state="NY",
                tax_type=tax_type,
                tax_level=level,
                concept="new_york_sales_and_use_tax",
                entity=ny_dtf,
                document=st100,
                frequency="assigned_filing_period",
                due_rule=(
                    "Generally due within 20 days after the assigned monthly, "
                    "quarterly, or annual filing period."
                ),
                basis="Report taxable telecommunications and local jurisdiction amounts.",
                citation="New York Tax Law §§ 1105(b) and 1136",
            )
    filing(
        state="NY",
        tax_type=14,
        tax_level=1,
        concept="new_york_telecommunications_excise",
        entity=ny_dtf,
        document=ct186e,
        frequency="annual",
        due_rule="File for each applicable corporation-tax year.",
        basis="Provider gross receipts under Tax Law § 186-e.",
        citation="New York Tax Law § 186-e; Form CT-186-E instructions",
    )
    filing(
        state="NY",
        tax_type=275,
        tax_level=1,
        concept="new_york_mobile_telecommunications_excise",
        entity=ny_dtf,
        document=ct186e,
        frequency="annual",
        due_rule="File for each applicable corporation-tax year.",
        basis=(
            "Provider gross receipts from mobile telecommunications when the "
            "customer's place of primary use is in New York."
        ),
        citation="New York Tax Law § 186-e; Form CT-186-E instructions",
    )
    filing(
        state="PA",
        tax_type=14,
        tax_level=1,
        concept="pennsylvania_telecommunications_gross_receipts_tax",
        entity=pa_dor,
        document=rct111,
        frequency="annual",
        due_rule="Annual RCT-111 is due March 15 for the prior calendar year.",
        basis="Covered telecommunications gross receipts sourced to Pennsylvania.",
        citation="72 P.S. § 8101(a); RCT-111",
    )
    for tax_type in (1, 49):
        filing(
            state="PA",
            tax_type=tax_type,
            tax_level=1,
            concept="pennsylvania_sales_and_use_tax",
            entity=pa_dor,
            document=pa3,
            frequency="assigned_filing_period",
            due_rule="File by the deadline assigned to the account in myPATH.",
            basis="Taxable telecommunications receipts sourced to Pennsylvania.",
            citation="72 P.S. § 7202; 61 Pa. Code § 60.20",
        )

    for config in NY_LOCAL_UTILITY_RULES:
        locality_slug = _slug(config["locality"])
        jurisdiction_external_key = (
            f"ny:utility-gross-receipts:3:{locality_slug}"
        )
        enabling_citation = (
            "New York Village Law § 5-530"
            if config["municipality_type"] == "village"
            else "New York General City Law § 20-b"
        )
        legal_citation = f"{config['local_citation']}; {enabling_citation}"
        if config.get("additional_citation"):
            legal_citation += f"; {config['additional_citation']}"
        entity, created = _entity(
            session,
            f"ny-local-{locality_slug}-utility-tax",
            name=config["filing_entity_name"],
            payee_name=config["payment_recipient"],
            entity_type="municipal_tax_authority",
            tax_level=3,
            state_code="NY",
            jurisdiction_external_key=jurisdiction_external_key,
            website_url=config["source"]["url"],
            filing_portal_url=None,
            payment_url=None,
            registration_url=None,
            mailing_address=None,
            legal_citation=legal_citation,
            status="recipient_verified",
            effective_from=date.fromisoformat(config["effective_from"]),
        )
        counts["entities_inserted"] += int(created)
        _, created = _filing_map(
            session,
            natural_key=(
                f"ny:avalara:14:3:{config['p_code']}:"
                f"{locality_slug}:utility-grt:filing"
            ),
            effective_from=date.fromisoformat(config["effective_from"]),
            benchmark_tax_type=14,
            tax_level=3,
            ctd_tax_concept="new_york_municipal_utility_gross_receipts_tax",
            state_code="NY",
            p_code=config["p_code"],
            jurisdiction_external_key=jurisdiction_external_key,
            filing_entity_id=entity.id,
            payment_entity_id=entity.id,
            return_document_id=None,
            exemption_document_id=None,
            filing_frequency=config["filing_frequency"],
            due_rule=config["due_rule"],
            reporting_basis=config["reporting_basis"],
            payment_recipient=config["payment_recipient"],
            legal_citation=legal_citation,
            mapping_status="recipient_verified",
        )
        counts["filing_maps_inserted"] += int(created)
    return counts
