from __future__ import annotations

from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from communications_tax_data.models import (
    FilingDocument,
    FilingEntity,
    TaxFilingMap,
    utcnow,
)

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


def seed_federal_filing_map(session: Session) -> dict[str, int]:
    """Seed public-source-verified federal entities, forms, and benchmark links."""
    counts = {"entities_inserted": 0, "documents_inserted": 0, "maps_inserted": 0}
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

    return counts
