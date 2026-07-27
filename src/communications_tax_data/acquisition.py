from __future__ import annotations

from collections import defaultdict
from datetime import date
from decimal import Decimal

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from communications_tax_data.models import (
    BenchmarkJurisdiction,
    CustomerTaxNeedDetail,
    TaxFactBenchmarkMap,
    TaxFilingMap,
    TaxTypeCrosswalk,
)


def _money(value: Decimal) -> float:
    return round(float(value), 2)


def _primary_locations(session: Session) -> dict[int, BenchmarkJurisdiction]:
    result: dict[int, BenchmarkJurisdiction] = {}
    rows = session.scalars(
        select(BenchmarkJurisdiction).order_by(
            BenchmarkJurisdiction.p_code,
            BenchmarkJurisdiction.alternate,
            BenchmarkJurisdiction.benchmark_id,
        )
    )
    for row in rows:
        result.setdefault(row.p_code, row)
    return result


def acquisition_queue_data(session: Session) -> dict:
    """Rank public-source acquisition by actual trailing-12-month invoice tax."""
    demand = list(
        session.scalars(
            select(CustomerTaxNeedDetail).where(
                CustomerTaxNeedDetail.active_customer.is_(True),
                CustomerTaxNeedDetail.trailing_12m_tax_amount > 0,
                CustomerTaxNeedDetail.tax_level.in_((1, 2, 3)),
            )
        )
    )
    locations = _primary_locations(session)
    crosswalks = list(session.scalars(select(TaxTypeCrosswalk)))
    filing_maps = list(session.scalars(select(TaxFilingMap)))
    today = date.today()
    fact_maps = list(
        session.scalars(
            select(TaxFactBenchmarkMap).where(
                TaxFactBenchmarkMap.effective_from <= today,
                or_(
                    TaxFactBenchmarkMap.effective_to.is_(None),
                    TaxFactBenchmarkMap.effective_to >= today,
                ),
            )
        )
    )

    support: dict[tuple[int, int], dict[str, bool]] = defaultdict(
        lambda: {"concept": False, "legal": False, "reviewed": False}
    )
    for row in crosswalks:
        key = (row.benchmark_tax_type, row.benchmark_tax_level)
        support[key]["concept"] |= bool(row.ctd_tax_concept)
        support[key]["legal"] |= bool(row.ctd_tax_concept and row.legal_citation)
        support[key]["reviewed"] |= row.mapping_status in {
            "reviewed",
            "verified",
            "published",
            "source_verified",
        }

    def has_rule(item: CustomerTaxNeedDetail, state: str | None) -> bool:
        return any(
            mapping.benchmark_tax_type == item.tax_type
            and mapping.benchmark_tax_level == item.tax_level
            and mapping.state_code in (None, state)
            and mapping.p_code in (None, item.p_code)
            and mapping.mapping_status in {"source_verified", "reviewed", "verified", "published"}
            and bool(mapping.legal_citation)
            for mapping in fact_maps
        )

    def has_filing(item: CustomerTaxNeedDetail, state: str | None) -> bool:
        for mapping in filing_maps:
            if mapping.benchmark_tax_type not in (None, item.tax_type):
                continue
            if mapping.tax_level != item.tax_level:
                continue
            if mapping.state_code not in (None, state):
                continue
            if mapping.p_code not in (None, item.p_code):
                continue
            if mapping.mapping_status in {"source_verified", "reviewed", "verified", "published"}:
                return True
        return False

    state_groups: dict[str, dict] = {}
    local_groups: dict[int, dict] = {}
    type_groups: dict[tuple[int, int, str, str], dict] = {}
    all_customers: set[int] = set()
    all_pcodes: set[int] = set()
    local_customers: set[int] = set()
    local_pcodes: set[int] = set()
    state_amount = Decimal()
    local_amount = Decimal()

    for item in demand:
        location = locations.get(item.p_code)
        state = location.state_code if location is not None else (item.state_code or "Unknown")
        amount = item.trailing_12m_tax_amount or Decimal()
        all_customers.add(item.customer_id)
        all_pcodes.add(item.p_code)
        if item.tax_level == 1:
            state_amount += amount
        else:
            local_amount += amount
            local_customers.add(item.customer_id)
            local_pcodes.add(item.p_code)

        state_row = state_groups.setdefault(
            state,
            {
                "state": state,
                "amount": Decimal(),
                "state_amount": Decimal(),
                "local_amount": Decimal(),
                "customers": set(),
                "p_codes": set(),
                "tax_types": set(),
                "unsupported_types": set(),
                "filing_gaps": set(),
            },
        )
        state_row["amount"] += amount
        state_row["state_amount" if item.tax_level == 1 else "local_amount"] += amount
        state_row["customers"].add(item.customer_id)
        state_row["p_codes"].add(item.p_code)
        state_row["tax_types"].add((item.tax_type, item.tax_level))
        rule_mapped = has_rule(item, state)
        filing_mapped = has_filing(item, state)
        if not rule_mapped:
            state_row["unsupported_types"].add((item.tax_type, item.tax_level))
        if not filing_mapped:
            state_row["filing_gaps"].add((item.tax_type, item.tax_level))

        type_key = (
            item.tax_type,
            item.tax_level,
            item.tax_category or "",
            item.tax_description or "",
        )
        type_row = type_groups.setdefault(
            type_key,
            {
                "tax_type": item.tax_type,
                "tax_level": item.tax_level,
                "category": item.tax_category,
                "description": item.tax_description,
                "amount": Decimal(),
                "customers": set(),
                "p_codes": set(),
                "states": set(),
                "rule_covered": True,
                "filing_covered": True,
            },
        )
        type_row["amount"] += amount
        type_row["customers"].add(item.customer_id)
        type_row["p_codes"].add(item.p_code)
        type_row["states"].add(state)
        type_row["rule_covered"] &= rule_mapped
        type_row["filing_covered"] &= filing_mapped

        if item.tax_level in (2, 3):
            local_row = local_groups.setdefault(
                item.p_code,
                {
                    "p_code": item.p_code,
                    "state": state,
                    "county": location.county_name if location else None,
                    "locality": location.locality_name if location else None,
                    "postal_code": item.postal_code,
                    "amount": Decimal(),
                    "county_amount": Decimal(),
                    "municipal_amount": Decimal(),
                    "customers": set(),
                    "tax_types": set(),
                    "unsupported_types": set(),
                    "filing_gaps": set(),
                },
            )
            local_row["amount"] += amount
            local_row["county_amount" if item.tax_level == 2 else "municipal_amount"] += amount
            local_row["customers"].add(item.customer_id)
            local_row["tax_types"].add((item.tax_type, item.tax_level))
            if not rule_mapped:
                local_row["unsupported_types"].add((item.tax_type, item.tax_level))
            if not filing_mapped:
                local_row["filing_gaps"].add((item.tax_type, item.tax_level))

    states = [
        {
            **{key: value for key, value in row.items() if not isinstance(value, set)},
            "amount": _money(row["amount"]),
            "state_amount": _money(row["state_amount"]),
            "local_amount": _money(row["local_amount"]),
            "customers": len(row["customers"]),
            "p_codes": len(row["p_codes"]),
            "tax_types": len(row["tax_types"]),
            "unsupported_types": len(row["unsupported_types"]),
            "filing_gaps": len(row["filing_gaps"]),
        }
        for row in state_groups.values()
    ]
    states.sort(key=lambda row: row["amount"], reverse=True)

    localities = [
        {
            **{key: value for key, value in row.items() if not isinstance(value, set)},
            "amount": _money(row["amount"]),
            "county_amount": _money(row["county_amount"]),
            "municipal_amount": _money(row["municipal_amount"]),
            "customers": len(row["customers"]),
            "tax_types": len(row["tax_types"]),
            "unsupported_types": len(row["unsupported_types"]),
            "filing_gaps": len(row["filing_gaps"]),
        }
        for row in local_groups.values()
    ]
    localities.sort(key=lambda row: row["amount"], reverse=True)

    tax_types = []
    for row in type_groups.values():
        row_support = support[(row["tax_type"], row["tax_level"])]
        tax_types.append(
            {
                "tax_type": row["tax_type"],
                "tax_level": row["tax_level"],
                "category": row["category"],
                "description": row["description"],
                "amount": _money(row["amount"]),
                "customers": len(row["customers"]),
                "p_codes": len(row["p_codes"]),
                "states": sorted(row["states"]),
                "concept_mapped": row_support["concept"],
                "legal_support": row["rule_covered"],
                "reviewed": row_support["reviewed"],
                "filing_mapped": row["filing_covered"],
            }
        )
    tax_types.sort(key=lambda row: row["amount"], reverse=True)

    return {
        "window": {
            "label": "Trailing 365 days",
            "start": min(
                (item.trailing_window_start for item in demand),
                default=None,
            ),
        },
        "summary": {
            "customers": len(all_customers),
            "p_codes": len(all_pcodes),
            "state_tax_amount": _money(state_amount),
            "local_tax_amount": _money(local_amount),
            "local_customers": len(local_customers),
            "local_p_codes": len(local_pcodes),
            "demanded_tax_types": len({(row.tax_type, row.tax_level) for row in demand}),
        },
        "states": states,
        "localities": localities,
        "tax_types": tax_types,
    }
