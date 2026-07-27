from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from communications_tax_data.models import TaxTypeCrosswalk

ECFR_54_706_URL = (
    "https://www.ecfr.gov/current/title-47/chapter-I/subchapter-B/part-54/subpart-H/section-54.706"
)
ECFR_54_709_URL = (
    "https://www.ecfr.gov/current/title-47/chapter-I/subchapter-B/part-54/subpart-H/section-54.709"
)
ECFR_54_712_URL = (
    "https://www.ecfr.gov/current/title-47/chapter-I/subchapter-B/part-54/subpart-H/section-54.712"
)
FCC_2026_FORM_499A_INSTRUCTIONS_URL = "https://docs.fcc.gov/public/attachments/DA-25-308A3.pdf"
FCC_2006_CONTRIBUTION_ORDER_URL = "https://docs.fcc.gov/public/attachments/FCC-06-94A1.pdf"
FUSF_PUBLIC_SOURCES = (
    ECFR_54_706_URL,
    ECFR_54_709_URL,
    ECFR_54_712_URL,
    FCC_2026_FORM_499A_INSTRUCTIONS_URL,
    FCC_2006_CONTRIBUTION_ORDER_URL,
)


@dataclass(frozen=True)
class FederalUsfVariant:
    service_category: str
    legal_citation: str
    rule_note: str


_GENERAL_CITATION = "47 USC § 254(d); 47 CFR §§ 54.706(b), 54.709"
_WIRELESS_CITATION = (
    "47 CFR § 54.706(a)(1); 2026 FCC Form 499-A Instructions §§ IV.C.4.c and IV.C.5.g"
)
_VOIP_CITATION = (
    "47 CFR § 54.706(a)(18); 2026 FCC Form 499-A Instructions §§ IV.C.4.b, IV.C.4.d, and IV.C.5.g"
)
_FIXED_LOCAL_CITATION = (
    "47 CFR §§ 54.706(a)-(b), 54.709; 2026 FCC Form 499-A Instructions § IV.C.4.b (Lines 303/404)"
)
_NON_ITEMIZED_CITATION = (
    "47 CFR §§ 54.706(b), 54.709, 54.712(a); 2026 FCC Form 499-A Instructions § IV.C.4.e (Line 403)"
)


# These are Avalara's nonzero federal-USF labels. They are not eleven separate
# federal assessments. The public authorities support one contribution
# mechanism, with service/revenue allocation and customer-billing rules.
FEDERAL_USF_VARIANTS: dict[int, FederalUsfVariant] = {
    18: FederalUsfVariant(
        "general",
        _GENERAL_CITATION,
        "General FUSF contribution-factor application.",
    ),
    55: FederalUsfVariant(
        "cellular",
        _WIRELESS_CITATION,
        "Cellular is a public-law service/revenue category; the 2026 wireless "
        "interstate-revenue safe harbor is 37.1%.",
    ),
    56: FederalUsfVariant(
        "paging",
        _WIRELESS_CITATION,
        "Paging is a public-law service/revenue category; the 2026 paging "
        "interstate-revenue safe harbor is 12.0%.",
    ),
    162: FederalUsfVariant(
        "interconnected_voip",
        _VOIP_CITATION,
        "Interconnected VoIP is expressly included; the 2026 interstate-revenue "
        "safe harbor is 64.9%.",
    ),
    277: FederalUsfVariant(
        "general_non_itemized",
        _NON_ITEMIZED_CITATION,
        "Avalara's non-billable label is a billing-treatment variant, not a "
        "separate federal mechanism. Federal rules permit, but do not require, "
        "customer line-item recovery.",
    ),
    311: FederalUsfVariant(
        "multiline_fixed_local",
        _FIXED_LOCAL_CITATION,
        "Avalara's multi-line label is a product/application subtype. The FCC "
        "sources place fixed local revenue in Lines 303/404 but do not establish "
        "a separate multi-line FUSF assessment.",
    ),
    444: FederalUsfVariant(
        "centrex_fixed_local",
        _FIXED_LOCAL_CITATION,
        "Avalara's Centrex label is a product/application subtype. The FCC "
        "sources place fixed local revenue in Lines 303/404 but do not establish "
        "a separate Centrex FUSF assessment.",
    ),
    625: FederalUsfVariant(
        "cellular_non_itemized",
        f"{_WIRELESS_CITATION}; 47 CFR § 54.712(a)",
        "Cellular applicability plus Avalara's non-billable billing treatment; "
        "not a separate federal mechanism.",
    ),
    626: FederalUsfVariant(
        "paging_non_itemized",
        f"{_WIRELESS_CITATION}; 47 CFR § 54.712(a)",
        "Paging applicability plus Avalara's non-billable billing treatment; "
        "not a separate federal mechanism.",
    ),
    627: FederalUsfVariant(
        "centrex_fixed_local_non_itemized",
        f"{_FIXED_LOCAL_CITATION}; 47 CFR § 54.712(a)",
        "Centrex product subtype plus Avalara's non-billable billing treatment; "
        "not a separate federal mechanism.",
    ),
    628: FederalUsfVariant(
        "multiline_fixed_local_non_itemized",
        f"{_FIXED_LOCAL_CITATION}; 47 CFR § 54.712(a)",
        "Multi-line product subtype plus Avalara's non-billable billing "
        "treatment; not a separate federal mechanism.",
    ),
    629: FederalUsfVariant(
        "interconnected_voip_non_itemized",
        f"{_VOIP_CITATION}; 47 CFR § 54.712(a)",
        "Interconnected-VoIP applicability plus Avalara's non-billable billing "
        "treatment; not a separate federal mechanism.",
    ),
}


def enrich_federal_usf_crosswalk(session: Session) -> int:
    """Attach public-law support without claiming Avalara's IDs are official."""
    rows = list(
        session.scalars(
            select(TaxTypeCrosswalk).where(
                TaxTypeCrosswalk.benchmark_tax_type.in_(FEDERAL_USF_VARIANTS)
            )
        )
    )
    for item in rows:
        variant = FEDERAL_USF_VARIANTS[item.benchmark_tax_type]
        item.ctd_tax_concept = "federal_universal_service_fund"
        item.service_category = variant.service_category
        item.mapping_method = "vendor_label_plus_public_rule"
        item.confidence = "supported"
        item.legal_citation = variant.legal_citation
        item.notes = (
            f"{variant.rule_note} The Avalara numeric tax-type mapping remains "
            "vendor-derived and proposed until reviewed against an Avalara data "
            "dictionary."
        )
    return len(rows)
