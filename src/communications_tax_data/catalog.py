from __future__ import annotations

from sqlalchemy.orm import Session

from communications_tax_data.collectors.base import get_or_create_source
from communications_tax_data.state_authorities import STATE_AUTHORITIES

CORE_SOURCES = [
    {
        "code": "irs-form-720-current",
        "name": "Current Form 720 and instructions",
        "publisher": "Internal Revenue Service",
        "source_type": "filing_document",
        "url": "https://www.irs.gov/forms-pubs/about-form-720",
        "tax_level": 0,
        "cadence_days": 30,
        "notes": "Federal communications excise return and current revision links.",
    },
    {
        "code": "irs-publication-510-current",
        "name": "Publication 510 communications-tax exemption guidance",
        "publisher": "Internal Revenue Service",
        "source_type": "exemption_guidance",
        "url": "https://www.irs.gov/publications/p510",
        "tax_level": 0,
        "cadence_days": 30,
    },
    {
        "code": "usac-forms-499-current",
        "name": "Current FCC Forms 499-A and 499-Q",
        "publisher": "Universal Service Administrative Company",
        "source_type": "filing_document",
        "url": "https://www.usac.org/service-providers/resources/forms/",
        "tax_level": 0,
        "cadence_days": 14,
    },
    {
        "code": "usac-non-usac-payment-administrators",
        "name": "TRS, LNPA, NANPA, and ITSP payment administrators",
        "publisher": "Universal Service Administrative Company",
        "source_type": "payment_directory",
        "url": (
            "https://www.usac.org/service-providers/making-payments/non-usac-payments/"
            "invoice-from-third-parties/"
        ),
        "tax_level": 0,
        "cadence_days": 30,
    },
    {
        "code": "fcc-cores-regulatory-fees",
        "name": "FCC CORES regulatory-fee filing and payment",
        "publisher": "Federal Communications Commission",
        "source_type": "filing_portal",
        "url": "https://apps.fcc.gov/cores/userLogin.do",
        "tax_level": 0,
        "cadence_days": 30,
        "notes": (
            "CORES login is monitored directly; the FCC regulatory-fee instruction "
            "page remains attached to the filing document."
        ),
    },
    {
        "code": "fcc-911-fee-reports",
        "name": "Annual 911 fee reports",
        "publisher": "Federal Communications Commission",
        "source_type": "report_directory",
        "url": "https://www.fcc.gov/general/911-fee-reports",
        "tax_level": 1,
        "cadence_days": 30,
        "notes": (
            "Annual state/territory 911 fee reports; not a substitute for current "
            "local statutes."
        ),
    },
    {
        "code": "fcc-usf-quarterly-filings",
        "name": "FCC contribution factors and quarterly filings",
        "publisher": "Federal Communications Commission",
        "source_type": "notice_directory",
        "url": (
            "https://www.fcc.gov/general/contribution-factor-quarterly-filings-"
            "universal-service-fund-usf-management-support"
        ),
        "tax_level": 0,
        "cadence_days": 14,
    },
    {
        "code": "ecfr-fusf-contributors",
        "name": "47 CFR 54.706 — FUSF contributors and covered services",
        "publisher": "Electronic Code of Federal Regulations",
        "source_type": "legal_authority",
        "url": (
            "https://www.ecfr.gov/current/title-47/chapter-I/subchapter-B/"
            "part-54/subpart-H/section-54.706"
        ),
        "tax_level": 0,
        "cadence_days": 14,
    },
    {
        "code": "ecfr-fusf-computation",
        "name": "47 CFR 54.709 — FUSF contribution computation",
        "publisher": "Electronic Code of Federal Regulations",
        "source_type": "legal_authority",
        "url": (
            "https://www.ecfr.gov/current/title-47/chapter-I/subchapter-B/"
            "part-54/subpart-H/section-54.709"
        ),
        "tax_level": 0,
        "cadence_days": 14,
    },
    {
        "code": "ecfr-fusf-customer-recovery",
        "name": "47 CFR 54.712 — recovery of FUSF costs from end users",
        "publisher": "Electronic Code of Federal Regulations",
        "source_type": "legal_authority",
        "url": (
            "https://www.ecfr.gov/current/title-47/chapter-I/subchapter-B/"
            "part-54/subpart-H/section-54.712"
        ),
        "tax_level": 0,
        "cadence_days": 14,
    },
    {
        "code": "fcc-form-499a-2026-instructions",
        "name": "2026 FCC Form 499-A instructions and revenue categories",
        "publisher": "Federal Communications Commission",
        "source_type": "taxability_guidance",
        "url": "https://docs.fcc.gov/public/attachments/DA-25-308A3.pdf",
        "tax_level": 0,
        "cadence_days": 30,
    },
    {
        "code": "fcc-2006-usf-contribution-order",
        "name": "2006 USF contribution methodology order",
        "publisher": "Federal Communications Commission",
        "source_type": "legal_authority",
        "url": "https://docs.fcc.gov/public/attachments/FCC-06-94A1.pdf",
        "tax_level": 0,
        "cadence_days": 90,
    },
    {
        "code": "sst-taxability-matrices",
        "name": "Streamlined Sales Tax state taxability matrices",
        "publisher": "Streamlined Sales Tax Governing Board",
        "source_type": "taxability_matrix",
        "url": "https://sst.streamlinedsalestax.org/TM/query",
        "tax_level": 1,
        "cadence_days": 30,
        "notes": "Sales/use tax only; communications-specific service mappings remain required.",
    },
    {
        "code": "sst-state-detail",
        "name": "Streamlined Sales Tax member state status",
        "publisher": "Streamlined Sales Tax Governing Board",
        "source_type": "state_program_directory",
        "url": "https://www.streamlinedsalestax.org/Shared-Pages/State-Detail",
        "tax_level": 1,
        "cadence_days": 30,
        "notes": "Official full-member and associate-member status.",
    },
    {
        "code": "census-tiger-2025",
        "name": "2025 TIGER/Line shapefiles",
        "publisher": "U.S. Census Bureau",
        "source_type": "boundary_directory",
        "url": "https://www2.census.gov/geo/tiger/TIGER2025/",
        "tax_level": 3,
        "cadence_days": 90,
        "authoritative": False,
        "notes": "Legal/statistical boundaries as of 2025-01-01; not USPS ZIP+4 or 911 districts.",
    },
]

STATE_RULE_SOURCES = [
    {
        "code": "state-rule-ca-cpuc-surcharge",
        "name": "California telecommunications surcharge rates",
        "publisher": "California Public Utilities Commission",
        "source_type": "state_puc_rate",
        "url": (
            "https://www.cpuc.ca.gov/industries-and-topics/internet-and-phone/"
            "telecommunications-surcharges-and-user-fees/surcharge-rates"
        ),
        "tax_level": 1,
        "state_code": "CA",
        "parser": "state-rules",
        "cadence_days": 7,
        "notes": "Effective-dated flat Public Purpose Program surcharge and allocations.",
    },
    {
        "code": "state-rule-ca-cpuc-user-fee",
        "name": "California telecommunications user fee rates",
        "publisher": "California Public Utilities Commission",
        "source_type": "state_puc_rate",
        "url": "https://www.cpuc.ca.gov/userfeerates",
        "tax_level": 1,
        "state_code": "CA",
        "parser": "state-rules",
        "cadence_days": 7,
        "notes": "Effective-dated percentage of gross intrastate telecommunications revenue.",
    },
    {
        "code": "state-rule-ca-cdtfa-mobile",
        "name": "California mobile phone and service-plan sales/use tax guidance",
        "publisher": "California Department of Tax and Fee Administration",
        "source_type": "state_revenue_taxability",
        "url": "https://www.cdtfa.ca.gov/industry/mobile-phone-vendors/industry-topics.htm",
        "tax_level": 1,
        "state_code": "CA",
        "parser": "state-rules",
        "cadence_days": 14,
        "notes": "Product treatment for devices, service/data plans, and prepaid MTS.",
    },
    {
        "code": "state-rule-pa-telecom-grt",
        "name": "Pennsylvania telecommunications gross receipts tax",
        "publisher": "Pennsylvania Department of Revenue",
        "source_type": "state_revenue_rate",
        "url": (
            "https://www.pa.gov/agencies/revenue/resources/tax-types-and-information/"
            "corporation-taxes/gross-receipts-tax"
        ),
        "tax_level": 1,
        "state_code": "PA",
        "parser": "state-rules",
        "cadence_days": 14,
        "notes": "Telecommunications 50-mill rate, sourcing summary, return, and due date.",
    },
    {
        "code": "state-rule-pa-sales-use-rate",
        "name": "Pennsylvania sales/use tax rates",
        "publisher": "Pennsylvania Department of Revenue",
        "source_type": "state_revenue_rate",
        "url": (
            "https://www.pa.gov/agencies/revenue/resources/tax-types-and-information/"
            "sales-use-and-hotel-occupancy-tax"
        ),
        "tax_level": 1,
        "state_code": "PA",
        "parser": "state-rules",
        "cadence_days": 14,
        "notes": "State rate and Philadelphia/Allegheny local additions.",
    },
    {
        "code": "state-rule-pa-telecom-taxability",
        "name": "Pennsylvania Sales Tax Bulletin 2005-03 — telecommunications",
        "publisher": "Pennsylvania Department of Revenue",
        "source_type": "state_revenue_taxability",
        "url": (
            "https://www.pa.gov/content/dam/copapwp-pagov/en/revenue/documents/"
            "taxlawpoliciesbulletinsnotices/taxbulletins/sut/documents/"
            "st_bulletin_2005-03.pdf"
        ),
        "tax_level": 1,
        "state_code": "PA",
        "parser": "state-rules",
        "cadence_days": 30,
        "notes": "Enhanced/non-enhanced telecommunications classifications and sourcing.",
    },
    {
        "code": "state-rule-ny-sales-rates",
        "name": "New York sales and use tax rates by jurisdiction — Publication 718",
        "publisher": "New York State Department of Taxation and Finance",
        "source_type": "state_revenue_rate",
        "url": "https://www.tax.ny.gov/pdf/publications/sales/pub718.pdf",
        "tax_level": 2,
        "state_code": "NY",
        "parser": "state-rules",
        "cadence_days": 7,
        "notes": (
            "Current combined state/local rates and official return reporting codes; "
            "reporting codes, not ZIP codes, identify the filing jurisdiction."
        ),
    },
    {
        "code": "state-rule-ny-telecom-taxability",
        "name": "New York sales-tax quick reference — telecommunications",
        "publisher": "New York State Department of Taxation and Finance",
        "source_type": "state_revenue_taxability",
        "url": (
            "https://www.tax.ny.gov/pubs_and_bulls/tg_bulletins/st/"
            "quick_reference_guide_for_taxable_and_exempt_property_and_services.htm"
        ),
        "tax_level": 1,
        "state_code": "NY",
        "parser": "state-rules",
        "cadence_days": 14,
        "notes": "Official taxable-services classification for intrastate telecommunications.",
    },
    {
        "code": "state-rule-ny-wireless-postpaid",
        "name": "New York postpaid wireless communications surcharge — Publication 451",
        "publisher": "New York State Department of Taxation and Finance",
        "source_type": "state_revenue_rate",
        "url": "https://www.tax.ny.gov/forms/publications/2025/wcs/pub451.htm",
        "tax_level": 2,
        "state_code": "NY",
        "parser": "state-rules",
        "cadence_days": 7,
        "notes": "State and county/New York City per-device monthly surcharge rates.",
    },
    {
        "code": "state-rule-ny-wireless-prepaid",
        "name": "New York prepaid wireless communications surcharge — Publication 452",
        "publisher": "New York State Department of Taxation and Finance",
        "source_type": "state_revenue_rate",
        "url": "https://www.tax.ny.gov/forms/publications/2025/wcs/pub452.htm",
        "tax_level": 2,
        "state_code": "NY",
        "parser": "state-rules",
        "cadence_days": 7,
        "notes": "State and county/New York City per-retail-sale surcharge rates.",
    },
    {
        "code": "state-rule-ny-telecom-excise",
        "name": "New York telecommunications excise tax rates and base",
        "publisher": "New York State Department of Taxation and Finance",
        "source_type": "state_revenue_rate",
        "url": (
            "https://www.tax.ny.gov/data/stats/ter/fiscal-year26/"
            "corporation-tax.htm"
        ),
        "tax_level": 1,
        "state_code": "NY",
        "parser": "state-rules",
        "cadence_days": 30,
        "notes": "Tax Law § 186-e nonmobile and mobile provider gross-receipts rates.",
    },
]


def seed_catalog(session: Session) -> tuple[int, int]:
    inserted = 0
    updated = 0
    for item in CORE_SOURCES:
        _, created = get_or_create_source(session, parser=None, **item)
        inserted += int(created)
        updated += int(not created)
    for item in STATE_RULE_SOURCES:
        _, created = get_or_create_source(session, **item)
        inserted += int(created)
        updated += int(not created)
    for profile in STATE_AUTHORITIES:
        state = profile.state_code
        _, created = get_or_create_source(
            session,
            code=f"state-puc-{state.lower()}",
            name=profile.commission_name,
            publisher=profile.commission_name,
            source_type="state_communications_regulator",
            url=profile.commission_url,
            tax_level=1,
            state_code=state,
            parser=None,
            cadence_days=14,
            authoritative=True,
            notes=(
                "Official regulator landing page. Health monitoring does not imply "
                "that its orders, dockets, tariffs, or surcharge rules are normalized."
            ),
        )
        inserted += int(created)
        updated += int(not created)
        _, created = get_or_create_source(
            session,
            code=f"state-dor-{state.lower()}",
            name=profile.revenue_name,
            publisher=profile.revenue_name,
            source_type="state_tax_landing",
            url=profile.revenue_url,
            tax_level=1,
            state_code=state,
            parser=None,
            cadence_days=30,
            authoritative=True,
            notes=(
                "Official revenue/tax landing page. Health monitoring does not imply "
                "that communications taxability, rates, sourcing, forms, or exemptions "
                "are normalized."
            ),
        )
        inserted += int(created)
        updated += int(not created)
    return inserted, updated
