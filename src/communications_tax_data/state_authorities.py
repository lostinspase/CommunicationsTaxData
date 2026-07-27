from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class StateAuthorityProfile:
    state_code: str
    state_name: str
    commission_name: str
    commission_url: str
    revenue_name: str
    revenue_url: str
    sales_tax_framework: str = "sales_and_use"
    framework_note: str = (
        "General sales/use framework. Communications taxability requires "
        "product-level authority review."
    )
    sst_membership: str = "nonmember"


_FULL_SST = {
    "AR",
    "GA",
    "IN",
    "IA",
    "KS",
    "KY",
    "MI",
    "MN",
    "NE",
    "NV",
    "NJ",
    "NC",
    "ND",
    "OH",
    "OK",
    "RI",
    "SD",
    "UT",
    "VT",
    "WA",
    "WV",
    "WI",
    "WY",
}


def _sst(state_code: str) -> str:
    if state_code in _FULL_SST:
        return "full"
    if state_code == "TN":
        return "associate"
    return "nonmember"


def _profile(
    state_code: str,
    state_name: str,
    commission_name: str,
    commission_url: str,
    revenue_name: str,
    revenue_url: str,
    *,
    sales_tax_framework: str = "sales_and_use",
    framework_note: str | None = None,
) -> StateAuthorityProfile:
    values = {
        "state_code": state_code,
        "state_name": state_name,
        "commission_name": commission_name,
        "commission_url": commission_url,
        "revenue_name": revenue_name,
        "revenue_url": revenue_url,
        "sales_tax_framework": sales_tax_framework,
        "sst_membership": _sst(state_code),
    }
    if framework_note is not None:
        values["framework_note"] = framework_note
    return StateAuthorityProfile(**values)


STATE_AUTHORITIES = (
    _profile(
        "AL",
        "Alabama",
        "Alabama Public Service Commission",
        "https://psc.alabama.gov/",
        "Alabama Department of Revenue",
        "https://www.revenue.alabama.gov/sales-use/",
    ),
    _profile(
        "AK",
        "Alaska",
        "Regulatory Commission of Alaska",
        "https://rca.alaska.gov/RCAWeb/home.aspx",
        "Alaska Department of Revenue — Tax Division",
        "https://tax.alaska.gov/",
        sales_tax_framework="no_statewide_general_sales_tax",
        framework_note=(
            "No statewide general sales tax. Local sales taxes and "
            "communications-specific state/local charges require separate review."
        ),
    ),
    _profile(
        "AZ",
        "Arizona",
        "Arizona Corporation Commission",
        "https://www.azcc.gov/",
        "Arizona Department of Revenue",
        "https://azdor.gov/business/transaction-privilege-tax/tax-rate-table",
        sales_tax_framework="transaction_privilege_tax",
        framework_note=(
            "Transaction privilege tax rather than a conventional seller-collected "
            "sales tax; communications classifications require separate review."
        ),
    ),
    _profile(
        "AR",
        "Arkansas",
        "Arkansas Public Service Commission",
        "https://apsc.arkansas.gov/",
        "Arkansas Department of Finance and Administration",
        "https://www.dfa.arkansas.gov/office/taxes/excise-tax-administration/sales-use-tax/",
    ),
    _profile(
        "CA",
        "California",
        "California Public Utilities Commission",
        "https://www.cpuc.ca.gov/",
        "California Department of Tax and Fee Administration",
        "https://www.cdtfa.ca.gov/taxes-and-fees/sales-use-tax-rates.htm",
        framework_note=(
            "Sales/use tax generally follows tangible-personal-property rules. "
            "Telecommunications service, devices, prepaid products, and CPUC/CDTFA "
            "surcharges must be analyzed separately."
        ),
    ),
    _profile(
        "CO",
        "Colorado",
        "Colorado Public Utilities Commission",
        "https://puc.colorado.gov/",
        "Colorado Department of Revenue",
        "https://tax.colorado.gov/sales-tax",
    ),
    _profile(
        "CT",
        "Connecticut",
        "Connecticut Public Utilities Regulatory Authority",
        "https://portal.ct.gov/pura",
        "Connecticut Department of Revenue Services",
        "https://portal.ct.gov/drs/sales-tax/tax-information",
    ),
    _profile(
        "DE",
        "Delaware",
        "Delaware Public Service Commission",
        "https://depsc.delaware.gov/",
        "Delaware Division of Revenue",
        "https://revenue.delaware.gov/business-tax-forms/gross-receipts-tax-forms/",
        sales_tax_framework="gross_receipts_no_general_sales_tax",
        framework_note=(
            "No general sales tax. Delaware gross-receipts and "
            "communications-specific obligations require separate review."
        ),
    ),
    _profile(
        "FL",
        "Florida",
        "Florida Public Service Commission",
        "https://www.floridapsc.com/",
        "Florida Department of Revenue",
        "https://floridarevenue.com/taxes/taxesfees/Pages/sales_tax.aspx",
        sales_tax_framework="sales_use_and_communications_services_tax",
        framework_note=(
            "Florida administers a separate communications services tax in "
            "addition to general sales/use tax."
        ),
    ),
    _profile(
        "GA",
        "Georgia",
        "Georgia Public Service Commission",
        "https://psc.ga.gov/",
        "Georgia Department of Revenue",
        "https://dor.georgia.gov/taxes/sales-use-tax",
    ),
    _profile(
        "HI",
        "Hawaii",
        "Hawaii Public Utilities Commission",
        "https://puc.hawaii.gov/",
        "Hawaii Department of Taxation",
        "https://tax.hawaii.gov/geninfo/get/",
        sales_tax_framework="general_excise_tax",
        framework_note=(
            "General excise tax is imposed on business activity rather than as a "
            "conventional retail sales tax."
        ),
    ),
    _profile(
        "ID",
        "Idaho",
        "Idaho Public Utilities Commission",
        "https://puc.idaho.gov/",
        "Idaho State Tax Commission",
        "https://tax.idaho.gov/taxes/sales-use/",
    ),
    _profile(
        "IL",
        "Illinois",
        "Illinois Commerce Commission",
        "https://www.icc.illinois.gov/",
        "Illinois Department of Revenue",
        "https://tax.illinois.gov/research/taxrates.html",
    ),
    _profile(
        "IN",
        "Indiana",
        "Indiana Utility Regulatory Commission",
        "https://www.in.gov/iurc/",
        "Indiana Department of Revenue",
        "https://www.in.gov/dor/business-tax/sales-tax/",
    ),
    _profile(
        "IA",
        "Iowa",
        "Iowa Utilities Commission",
        "https://iuc.iowa.gov/",
        "Iowa Department of Revenue",
        "https://revenue.iowa.gov/taxes/tax-guidance/sales-use-excise-tax",
    ),
    _profile(
        "KS",
        "Kansas",
        "Kansas Corporation Commission",
        "https://www.kcc.ks.gov/",
        "Kansas Department of Revenue",
        "https://www.ksrevenue.gov/bustaxtypessales.html",
    ),
    _profile(
        "KY",
        "Kentucky",
        "Kentucky Public Service Commission",
        "https://psc.ky.gov/",
        "Kentucky Department of Revenue",
        "https://revenue.ky.gov/Business/Sales-Use-Tax/Pages/default.aspx",
    ),
    _profile(
        "LA",
        "Louisiana",
        "Louisiana Public Service Commission",
        "https://lpsc.louisiana.gov/",
        "Louisiana Department of Revenue",
        (
            "https://revenue.louisiana.gov/tax-education-and-faqs/faqs/"
            "sales-tax/what-is-the-sales-tax-rate-in-louisiana/"
        ),
    ),
    _profile(
        "ME",
        "Maine",
        "Maine Public Utilities Commission",
        "https://www.maine.gov/mpuc/",
        "Maine Revenue Services",
        "https://www.maine.gov/revenue/taxes/sales-use-service-provider-tax",
        sales_tax_framework="sales_use_and_service_provider_tax",
        framework_note=(
            "Maine sales/use and service-provider tax regimes must be considered "
            "separately for communications products."
        ),
    ),
    _profile(
        "MD",
        "Maryland",
        "Maryland Public Service Commission",
        "https://www.psc.state.md.us/",
        "Comptroller of Maryland",
        (
            "https://services.marylandcomptroller.gov/taxes/en/sales-and-use-tax"
            "?id=kb_article_view&sysparm_article=KB0010107"
        ),
    ),
    _profile(
        "MA",
        "Massachusetts",
        "Massachusetts Department of Public Utilities",
        "https://www.mass.gov/orgs/department-of-public-utilities",
        "Massachusetts Department of Revenue",
        "https://www.mass.gov/sales-and-use-tax",
    ),
    _profile(
        "MI",
        "Michigan",
        "Michigan Public Service Commission",
        "https://www.michigan.gov/mpsc",
        "Michigan Department of Treasury",
        "https://www.michigan.gov/taxes/business-taxes/sales-use-tax",
    ),
    _profile(
        "MN",
        "Minnesota",
        "Minnesota Public Utilities Commission",
        "https://mn.gov/puc/",
        "Minnesota Department of Revenue",
        "https://www.revenue.state.mn.us/sales-and-use-tax",
    ),
    _profile(
        "MS",
        "Mississippi",
        "Mississippi Public Service Commission",
        "https://www.psc.ms.gov/",
        "Mississippi Department of Revenue",
        "https://www.dor.ms.gov/business/sales-tax-rates",
    ),
    _profile(
        "MO",
        "Missouri",
        "Missouri Public Service Commission",
        "https://psc.mo.gov/",
        "Missouri Department of Revenue",
        "https://dor.mo.gov/taxation/business/tax-types/sales-use/",
    ),
    _profile(
        "MT",
        "Montana",
        "Montana Public Service Commission",
        "https://psc.mt.gov/",
        "Montana Department of Revenue",
        "https://mtrevenue.gov/taxes/",
        sales_tax_framework="no_general_sales_tax",
        framework_note=(
            "No general statewide sales tax. Selective and "
            "communications-specific taxes still require review."
        ),
    ),
    _profile(
        "NE",
        "Nebraska",
        "Nebraska Public Service Commission",
        "https://psc.nebraska.gov/",
        "Nebraska Department of Revenue",
        "https://revenue.nebraska.gov/businesses/sales-and-use-tax",
    ),
    _profile(
        "NV",
        "Nevada",
        "Public Utilities Commission of Nevada",
        "https://puc.nv.gov/",
        "Nevada Department of Taxation",
        "https://tax.nv.gov/FAQs/Sales_Tax_Information___FAQ_s/",
    ),
    _profile(
        "NH",
        "New Hampshire",
        "New Hampshire Public Utilities Commission",
        "https://www.puc.nh.gov/",
        "New Hampshire Department of Revenue Administration",
        "https://www.revenue.nh.gov/taxes-glance",
        sales_tax_framework="no_general_sales_tax",
        framework_note=(
            "No general sales tax. New Hampshire communications-specific taxes "
            "and commission obligations require separate review."
        ),
    ),
    _profile(
        "NJ",
        "New Jersey",
        "New Jersey Board of Public Utilities",
        "https://www.nj.gov/bpu/",
        "New Jersey Division of Taxation",
        "https://www.nj.gov/treasury/taxation/salesandusetax.shtml",
    ),
    _profile(
        "NM",
        "New Mexico",
        "New Mexico Public Regulation Commission",
        "https://www.prc.nm.gov/",
        "New Mexico Taxation and Revenue Department",
        "https://www.tax.newmexico.gov/businesses/gross-receipts-tax/",
        sales_tax_framework="gross_receipts_tax",
        framework_note=(
            "Gross receipts tax rather than a conventional retail sales tax; "
            "communications deductions and sourcing require separate review."
        ),
    ),
    _profile(
        "NY",
        "New York",
        "New York Public Service Commission",
        "https://dps.ny.gov/",
        "New York Department of Taxation and Finance",
        "https://www.tax.ny.gov/bus/st/stidx.htm",
    ),
    _profile(
        "NC",
        "North Carolina",
        "North Carolina Utilities Commission",
        "https://www.ncuc.gov/",
        "North Carolina Department of Revenue",
        "https://www.ncdor.gov/taxes-forms/sales-and-use-tax",
    ),
    _profile(
        "ND",
        "North Dakota",
        "North Dakota Public Service Commission",
        "https://www.psc.nd.gov/",
        "North Dakota Office of State Tax Commissioner",
        "https://www.tax.nd.gov/business/sales-and-use-tax",
    ),
    _profile(
        "OH",
        "Ohio",
        "Public Utilities Commission of Ohio",
        "https://puco.ohio.gov/",
        "Ohio Department of Taxation",
        "https://thefinder.tax.ohio.gov/streamlinesalestaxweb/default.aspx",
    ),
    _profile(
        "OK",
        "Oklahoma",
        "Oklahoma Corporation Commission",
        "https://oklahoma.gov/occ.html",
        "Oklahoma Tax Commission",
        "https://oklahoma.gov/tax/businesses/sales-use-tax.html",
    ),
    _profile(
        "OR",
        "Oregon",
        "Oregon Public Utility Commission",
        "https://www.oregon.gov/puc/",
        "Oregon Department of Revenue",
        "https://www.oregon.gov/dor/programs/businesses/pages/default.aspx",
        sales_tax_framework="no_general_sales_tax",
        framework_note=(
            "No general sales tax. Communications surcharges, emergency-service "
            "charges, and business taxes require separate review."
        ),
    ),
    _profile(
        "PA",
        "Pennsylvania",
        "Pennsylvania Public Utility Commission",
        "https://www.puc.pa.gov/",
        "Pennsylvania Department of Revenue",
        (
            "https://www.pa.gov/agencies/revenue/resources/"
            "tax-types-and-information/sales-use-and-hotel-occupancy-tax"
        ),
        sales_tax_framework="sales_use_and_telecommunications_gross_receipts",
        framework_note=(
            "Enumerated communications services can be subject to sales/use tax, "
            "and providers can separately owe telecommunications gross-receipts tax."
        ),
    ),
    _profile(
        "RI",
        "Rhode Island",
        "Rhode Island Public Utilities Commission",
        "https://ripuc.ri.gov/",
        "Rhode Island Division of Taxation",
        "https://tax.ri.gov/tax-sections/sales-excise-taxes/sales-use-tax",
    ),
    _profile(
        "SC",
        "South Carolina",
        "Public Service Commission of South Carolina",
        "https://www.psc.sc.gov/",
        "South Carolina Department of Revenue",
        "https://dor.sc.gov/tax/sales",
    ),
    _profile(
        "SD",
        "South Dakota",
        "South Dakota Public Utilities Commission",
        "https://puc.sd.gov/",
        "South Dakota Department of Revenue",
        "https://dor.sd.gov/businesses/taxes/sales-use-tax/",
    ),
    _profile(
        "TN",
        "Tennessee",
        "Tennessee Public Utility Commission",
        "https://www.tn.gov/tpuc.html",
        "Tennessee Department of Revenue",
        "https://www.tn.gov/revenue/taxes/sales-and-use-tax.html",
    ),
    _profile(
        "TX",
        "Texas",
        "Public Utility Commission of Texas",
        "https://www.puc.texas.gov/",
        "Texas Comptroller of Public Accounts",
        "https://comptroller.texas.gov/taxes/sales/",
    ),
    _profile(
        "UT",
        "Utah",
        "Public Service Commission of Utah",
        "https://psc.utah.gov/",
        "Utah State Tax Commission",
        "https://tax.utah.gov/sales",
    ),
    _profile(
        "VT",
        "Vermont",
        "Vermont Public Utility Commission",
        "https://puc.vermont.gov/",
        "Vermont Department of Taxes",
        "https://tax.vermont.gov/business-and-corp/sales-and-use-tax",
    ),
    _profile(
        "VA",
        "Virginia",
        "Virginia State Corporation Commission",
        "https://www.scc.virginia.gov/",
        "Virginia Department of Taxation",
        "https://www.tax.virginia.gov/retail-sales-and-use-tax",
    ),
    _profile(
        "WA",
        "Washington",
        "Washington Utilities and Transportation Commission",
        "https://www.utc.wa.gov/",
        "Washington Department of Revenue",
        "https://dor.wa.gov/taxes-rates/retail-sales-tax",
        sales_tax_framework="retail_sales_and_business_occupation",
        framework_note=(
            "Retail sales/use and business-and-occupation tax classifications must "
            "be considered separately for communications."
        ),
    ),
    _profile(
        "WV",
        "West Virginia",
        "Public Service Commission of West Virginia",
        "https://www.psc.state.wv.us/",
        "West Virginia State Tax Department",
        "https://tax.wv.gov/Business/SalesAndUseTax/Pages/SalesAndUseTax.aspx",
    ),
    _profile(
        "WI",
        "Wisconsin",
        "Public Service Commission of Wisconsin",
        "https://psc.wi.gov/",
        "Wisconsin Department of Revenue",
        "https://www.revenue.wi.gov/Pages/FAQS/pcs-taxrates.aspx",
    ),
    _profile(
        "WY",
        "Wyoming",
        "Wyoming Public Service Commission",
        "https://psc.wyo.gov/",
        "Wyoming Department of Revenue",
        "https://excise-tax-div.wyo.gov/salesuselodging-tax/tax-rates",
    ),
)

STATE_AUTHORITY_BY_CODE = {profile.state_code: profile for profile in STATE_AUTHORITIES}
