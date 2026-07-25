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
        "code": "ny-general-city-law-20-b",
        "name": "New York General City Law § 20-b — city utility taxes",
        "publisher": "New York State Senate",
        "source_type": "legal_authority",
        "url": "https://www.nysenate.gov/legislation/laws/GCT/20-B",
        "tax_level": 3,
        "state_code": "NY",
        "cadence_days": 14,
        "notes": (
            "Enabling law only. A city is not credited with a tax unless its "
            "adopted local ordinance is separately validated."
        ),
    },
    {
        "code": "ny-village-law-5-530",
        "name": "New York Village Law § 5-530 — village utility taxes",
        "publisher": "New York State Senate",
        "source_type": "legal_authority",
        "url": "https://www.nysenate.gov/legislation/laws/VIL/5-530",
        "tax_level": 3,
        "state_code": "NY",
        "cadence_days": 14,
        "notes": (
            "Enabling law and village telephony-base limitation. A village is not "
            "credited with a tax unless its adopted local ordinance is separately "
            "validated."
        ),
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

NY_LOCAL_UTILITY_RULES = [
    {
        "source": {
            "code": "local-rule-ny-johnstown-utility-grt",
            "name": "Johnstown utility gross receipts tax — Chapter 278, Article I",
            "publisher": "City of Johnstown",
            "source_type": "local_ordinance",
            "url": "https://ecode360.com/15331557",
            "tax_level": 3,
            "state_code": "NY",
            "parser": "state-rules",
            "cadence_days": 14,
            "notes": (
                "Codified one-percent utility tax, telecommunications base, "
                "filing recipient, and due dates."
            ),
        },
        "locality": "Johnstown",
        "municipality_type": "city",
        "p_code": 2560500,
        "effective_from": "1937-07-01",
        "local_citation": "Johnstown City Code Chapter 278, Article I",
        "telecom_evidence": "incorporated_tax_law_186_a",
        "additional_citation": (
            "New York Tax Law § 186-a(2), as incorporated under "
            "General City Law § 20-b"
        ),
        "filing_entity_name": "City of Johnstown — City Treasurer",
        "payment_recipient": "City Treasurer, City of Johnstown",
        "filing_frequency": "quarterly_or_small_utility_annual",
        "due_rule": (
            "Quarterly returns and payment are due September 25, December 25, "
            "March 25, and June 25. A qualifying small utility may file annually "
            "on June 25."
        ),
        "reporting_basis": (
            "Report gross income or gross operating income on the form furnished "
            "by the City Treasurer. No public downloadable return was found."
        ),
        "customer_bill_treatment": "may_itemize",
    },
    {
        "source": {
            "code": "local-rule-ny-amsterdam-utility-grt",
            "name": "Amsterdam utility services tax — Chapter 214, Article I",
            "publisher": "City of Amsterdam",
            "source_type": "local_ordinance",
            "url": "https://ecode360.com/8070007",
            "tax_level": 3,
            "state_code": "NY",
            "parser": "state-rules",
            "cadence_days": 14,
            "notes": (
                "Codified one-percent utility tax, telecommunications base, "
                "filing recipient, and due dates."
            ),
        },
        "locality": "Amsterdam",
        "municipality_type": "city",
        "p_code": 2589700,
        "effective_from": "1937-07-01",
        "local_citation": "Amsterdam City Code Chapter 214, Article I",
        "filing_entity_name": "City of Amsterdam — City Treasurer",
        "payment_recipient": "City Treasurer, City of Amsterdam",
        "filing_frequency": "quarterly_or_small_utility_annual",
        "due_rule": (
            "Quarterly returns and payment are due September 25, December 25, "
            "March 25, and June 25. A qualifying small utility may file annually "
            "on June 25."
        ),
        "reporting_basis": (
            "Report gross income or gross operating income on the form furnished "
            "by the City Treasurer. No public downloadable return was found."
        ),
        "customer_bill_treatment": "must_not_itemize",
    },
    {
        "source": {
            "code": "local-rule-ny-fort-plain-utility-grt",
            "name": "Fort Plain utility tax — Chapter 165, Article I",
            "publisher": "Village of Fort Plain",
            "source_type": "local_ordinance",
            "url": "https://ecode360.com/12375089",
            "tax_level": 3,
            "state_code": "NY",
            "parser": "state-rules",
            "cadence_days": 14,
            "notes": (
                "Codified one-percent utility tax, local-exchange base, "
                "filing recipient, and due dates."
            ),
        },
        "locality": "Fort Plain",
        "municipality_type": "village",
        "p_code": 2589900,
        "effective_from": "1973-03-01",
        "local_citation": "Fort Plain Village Code Chapter 165, Article I",
        "telecom_evidence": "incorporated_village_law_5_530",
        "filing_entity_name": "Village of Fort Plain — Village Treasurer",
        "payment_recipient": "Village Treasurer, Village of Fort Plain",
        "filing_frequency": "annual_or_elected_quarterly",
        "due_rule": (
            "The annual return and payment are due March 25. A utility may elect "
            "quarterly returns due September 25, December 25, March 25, and June 25."
        ),
        "reporting_basis": (
            "Report local-exchange-service receipts wholly consummated within the "
            "Village on the form furnished by the Village Treasurer. No public "
            "downloadable return was found."
        ),
        "customer_bill_treatment": "must_not_itemize",
    },
    {
        "source": {
            "code": "local-rule-ny-saratoga-springs-utility-grt",
            "name": "Saratoga Springs utility tax — Chapter 212, Article I",
            "publisher": "City of Saratoga Springs",
            "source_type": "local_ordinance",
            "url": "https://ecode360.com/6520973",
            "tax_level": 3,
            "state_code": "NY",
            "parser": "state-rules",
            "cadence_days": 14,
            "notes": (
                "Codified one-percent utility tax, telecommunications base, "
                "filing recipient, and due rule."
            ),
        },
        "locality": "Saratoga Springs",
        "municipality_type": "city",
        "p_code": 2651300,
        "effective_from": "1937-07-01",
        "local_citation": "Saratoga Springs City Code Chapter 212, Article I",
        "filing_entity_name": "City of Saratoga Springs — Commissioner of Finance",
        "payment_recipient": "Commissioner of Finance, City of Saratoga Springs",
        "filing_frequency": "monthly",
        "due_rule": (
            "The codified rule requires a monthly return and payment on the "
            "twenty-fifth day following the reporting month."
        ),
        "reporting_basis": (
            "Report gross income or gross operating income on the form furnished "
            "by the Commissioner of Finance. No public downloadable return was found."
        ),
        "customer_bill_treatment": "must_not_itemize",
    },
    {
        "source": {
            "code": "local-rule-ny-albany-utility-grt",
            "name": "Albany utility gross receipts tax — Chapter 333, Article IX",
            "publisher": "City of Albany",
            "source_type": "local_ordinance",
            "url": "https://ecode360.com/7684955",
            "tax_level": 3,
            "state_code": "NY",
            "parser": "state-rules",
            "cadence_days": 14,
            "notes": (
                "Codified one-percent utility tax, telecommunications base, "
                "filing recipient, and due dates."
            ),
        },
        "locality": "Albany",
        "municipality_type": "city",
        "p_code": 2502700,
        "effective_from": "1937-07-01",
        "local_citation": "Albany City Code Chapter 333, Article IX",
        "filing_entity_name": "City of Albany — City Comptroller",
        "payment_recipient": "City Comptroller, City of Albany",
        "filing_frequency": "quarterly_or_small_utility_annual",
        "due_rule": (
            "Quarterly returns and payment are due September 25, December 25, "
            "March 25, and June 25. A qualifying small utility may file annually "
            "on June 25."
        ),
        "reporting_basis": (
            "Report gross income or gross operating income on the form furnished "
            "by the City Comptroller. No public downloadable return was found."
        ),
        "customer_bill_treatment": "must_not_itemize",
    },
    {
        "source": {
            "code": "local-rule-ny-lake-george-utility-grt",
            "name": "Lake George utility tax — Chapter 195, Article I",
            "publisher": "Village of Lake George",
            "source_type": "local_ordinance",
            "url": "https://ecode360.com/9945181",
            "tax_level": 3,
            "state_code": "NY",
            "parser": "state-rules",
            "cadence_days": 14,
            "notes": (
                "Codified one-percent utility tax, local-exchange base, "
                "filing recipient, and due dates."
            ),
        },
        "locality": "Lake George",
        "municipality_type": "village",
        "p_code": 2699100,
        "effective_from": "1968-04-01",
        "local_citation": "Lake George Village Code Chapter 195, Article I",
        "filing_entity_name": "Village of Lake George — Village Treasurer",
        "payment_recipient": "Village Treasurer, Village of Lake George",
        "filing_frequency": "semiannual_or_small_utility_annual",
        "due_rule": (
            "Semiannual returns and payment are due July 1 and January 1. A "
            "qualifying small utility may file annually on October 1."
        ),
        "reporting_basis": (
            "Report local-exchange-service receipts wholly consummated within the "
            "Village on the form furnished by the Village Treasurer. No public "
            "downloadable return was found."
        ),
        "customer_bill_treatment": "must_not_itemize",
    },
    {
        "source": {
            "code": "local-rule-ny-scotia-utility-grt",
            "name": "Scotia public utilities tax — Chapter 228, Article I",
            "publisher": "Village of Scotia",
            "source_type": "local_ordinance",
            "url": "https://ecode360.com/9176130",
            "tax_level": 3,
            "state_code": "NY",
            "parser": "state-rules",
            "cadence_days": 14,
            "notes": (
                "Codified one-percent utility tax, local-exchange base, "
                "filing recipient, and due dates."
            ),
        },
        "locality": "Scotia",
        "municipality_type": "village",
        "p_code": 2654500,
        "effective_from": "1951-01-01",
        "local_citation": "Scotia Village Code Chapter 228, Article I",
        "filing_entity_name": "Village of Scotia — Clerk-Treasurer",
        "payment_recipient": "Clerk-Treasurer, Village of Scotia",
        "filing_frequency": "annual_or_elected_quarterly",
        "due_rule": (
            "The annual return and payment are due March 1. A utility may elect "
            "quarterly returns due September 25, December 25, March 25, and June 25."
        ),
        "reporting_basis": (
            "Report local-exchange-service receipts wholly consummated within the "
            "Village on the form furnished by the Clerk-Treasurer. No public "
            "downloadable return was found."
        ),
        "customer_bill_treatment": "must_not_itemize",
    },
    {
        "source": {
            "code": "local-rule-ny-clayton-utility-grt",
            "name": "Clayton utilities tax — Chapter 114, Article I",
            "publisher": "Village of Clayton",
            "source_type": "local_ordinance",
            "url": "https://ecode360.com/11989385",
            "tax_level": 3,
            "state_code": "NY",
            "parser": "state-rules",
            "cadence_days": 14,
            "notes": (
                "Codified one-percent utility tax, local-exchange base, "
                "filing recipient, and due date."
            ),
        },
        "locality": "Clayton",
        "municipality_type": "village",
        "p_code": 2573000,
        "effective_from": "1970-06-01",
        "local_citation": "Clayton Village Code Chapter 114, Article I",
        "filing_entity_name": "Village of Clayton — Village Treasurer",
        "payment_recipient": "Village Treasurer, Village of Clayton",
        "filing_frequency": "annual",
        "due_rule": "The annual return and payment are due July 25.",
        "reporting_basis": (
            "Report local-exchange-service receipts wholly consummated within the "
            "Village on the form furnished by the Village Treasurer. No public "
            "downloadable return was found."
        ),
        "customer_bill_treatment": "must_not_itemize",
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
    for rule in NY_LOCAL_UTILITY_RULES:
        _, created = get_or_create_source(session, **rule["source"])
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
