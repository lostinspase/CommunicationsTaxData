from __future__ import annotations

from sqlalchemy.orm import Session

from communications_tax_data.collectors.base import get_or_create_source

STATE_DOR_URLS = {
    "AL": "https://www.revenue.alabama.gov/sales-use/",
    "AK": "https://tax.alaska.gov/",
    "AZ": "https://azdor.gov/business/transaction-privilege-tax/tax-rate-table",
    "AR": "https://www.dfa.arkansas.gov/office/taxes/excise-tax-administration/sales-use-tax/",
    "CA": "https://www.cdtfa.ca.gov/taxes-and-fees/sales-use-tax-rates.htm",
    "CO": "https://tax.colorado.gov/sales-tax",
    "CT": "https://portal.ct.gov/drs/sales-tax/tax-information",
    "DE": "https://revenue.delaware.gov/business-tax-forms/gross-receipts-tax-forms/",
    "DC": "https://otr.cfo.dc.gov/page/sales-use-tax",
    "FL": "https://floridarevenue.com/taxes/taxesfees/Pages/sales_tax.aspx",
    "GA": "https://dor.georgia.gov/taxes/sales-use-tax",
    "HI": "https://tax.hawaii.gov/geninfo/get/",
    "ID": "https://tax.idaho.gov/taxes/sales-use/",
    "IL": "https://tax.illinois.gov/research/taxrates.html",
    "IN": "https://www.in.gov/dor/business-tax/sales-tax/",
    "IA": "https://revenue.iowa.gov/taxes/tax-guidance/sales-use-excise-tax",
    "KS": "https://www.ksrevenue.gov/bustaxtypessales.html",
    "KY": "https://revenue.ky.gov/Business/Sales-Use-Tax/Pages/default.aspx",
    "LA": (
        "https://revenue.louisiana.gov/tax-education-and-faqs/faqs/sales-tax/"
        "what-is-the-sales-tax-rate-in-louisiana/"
    ),
    "ME": "https://www.maine.gov/revenue/taxes/sales-use-service-provider-tax",
    "MD": (
        "https://services.marylandcomptroller.gov/taxes/en/sales-and-use-tax"
        "?id=kb_article_view&sysparm_article=KB0010107"
    ),
    "MA": "https://www.mass.gov/sales-and-use-tax",
    "MI": "https://www.michigan.gov/taxes/business-taxes/sales-use-tax",
    "MN": "https://www.revenue.state.mn.us/sales-and-use-tax",
    "MS": "https://www.dor.ms.gov/business/sales-tax-rates",
    "MO": "https://dor.mo.gov/taxation/business/tax-types/sales-use/",
    "MT": "https://mtrevenue.gov/taxes/",
    "NE": "https://revenue.nebraska.gov/businesses/sales-and-use-tax",
    "NV": "https://tax.nv.gov/FAQs/Sales_Tax_Information___FAQ_s/",
    "NH": "https://www.revenue.nh.gov/taxes-glance",
    "NJ": "https://www.nj.gov/treasury/taxation/salesandusetax.shtml",
    "NM": "https://www.tax.newmexico.gov/businesses/gross-receipts-tax/",
    "NY": "https://www.tax.ny.gov/bus/st/stidx.htm",
    "NC": "https://www.ncdor.gov/taxes-forms/sales-and-use-tax",
    "ND": "https://www.tax.nd.gov/business/sales-and-use-tax",
    "OH": "https://thefinder.tax.ohio.gov/streamlinesalestaxweb/default.aspx",
    "OK": "https://oklahoma.gov/tax/businesses/sales-use-tax.html",
    "OR": "https://www.oregon.gov/dor/programs/businesses/pages/default.aspx",
    "PA": "https://www.pa.gov/agencies/revenue/resources/tax-types-and-information/sales-use-and-hotel-occupancy-tax",
    "RI": "https://tax.ri.gov/tax-sections/sales-excise-taxes/sales-use-tax",
    "SC": "https://dor.sc.gov/tax/sales",
    "SD": "https://dor.sd.gov/businesses/taxes/sales-use-tax/",
    "TN": "https://www.tn.gov/revenue/taxes/sales-and-use-tax.html",
    "TX": "https://comptroller.texas.gov/taxes/sales/",
    "UT": "https://tax.utah.gov/sales",
    "VT": "https://tax.vermont.gov/business-and-corp/sales-and-use-tax",
    "VA": "https://www.tax.virginia.gov/retail-sales-and-use-tax",
    "WA": "https://dor.wa.gov/taxes-rates/retail-sales-tax",
    "WV": "https://tax.wv.gov/Business/SalesAndUseTax/Pages/SalesAndUseTax.aspx",
    "WI": "https://www.revenue.wi.gov/Pages/FAQS/pcs-taxrates.aspx",
    "WY": "https://excise-tax-div.wyo.gov/salesuselodging-tax/tax-rates",
}

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


def seed_catalog(session: Session) -> tuple[int, int]:
    inserted = 0
    updated = 0
    for item in CORE_SOURCES:
        _, created = get_or_create_source(session, parser=None, **item)
        inserted += int(created)
        updated += int(not created)
    for state, url in STATE_DOR_URLS.items():
        _, created = get_or_create_source(
            session,
            code=f"state-dor-{state.lower()}",
            name=f"{state} official sales/use tax source",
            publisher=f"{state} state tax authority",
            source_type="state_tax_landing",
            url=url,
            tax_level=1,
            state_code=state,
            parser=None,
            cadence_days=30,
            authoritative=True,
            notes=(
                "Discovery/monitoring record. A state-specific parser is required for normalized "
                "non-SST rates and communications taxability."
            ),
        )
        inserted += int(created)
        updated += int(not created)
    return inserted, updated
