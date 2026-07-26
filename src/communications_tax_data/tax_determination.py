from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter, defaultdict
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from communications_tax_data.collectors.base import CollectionStats, finish_run, start_run
from communications_tax_data.models import (
    AddressAssignment,
    BenchmarkRate,
    CustomerExemption,
    CustomerTaxProfile,
    Jurisdiction,
    LocationProfileMember,
    ProductCatalogItem,
    ProductTaxonomyMap,
    ServiceProductDemand,
    ServiceTaxAssessment,
    TaxabilityRule,
    TaxFact,
    TaxFilingMap,
    TaxTypeCrosswalk,
    utcnow,
)
from communications_tax_data.product_demand import SOURCE_SYSTEM

REVIEWED_STATUSES = {"reviewed", "verified", "published", "source_verified"}
PRODUCT_REVIEWED_STATUSES = {"reviewed", "published"}
TAXABILITY_REVIEWED_STATUSES = {"reviewed", "published"}
EXEMPTION_REVIEWED_STATUSES = {"reviewed", "verified", "published"}


def assess_service_tax_demand(
    session: Session,
    *,
    as_of: date | None = None,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    """Create a daily, product-aware shadow tax determination snapshot."""
    assessment_date = as_of or date.today()
    run = start_run(session, "service-tax-determination-v1")
    demands = list(
        session.scalars(
            select(ServiceProductDemand)
            .where(ServiceProductDemand.active_customer.is_(True))
            .order_by(
                ServiceProductDemand.customer_id,
                ServiceProductDemand.source_tax_group,
                ServiceProductDemand.charge_type,
                ServiceProductDemand.source_product_id,
            )
        )
    )
    mappings = _current_product_mappings(session, assessment_date)
    profiles = {item.customer_id: item for item in session.scalars(select(CustomerTaxProfile))}
    exemptions_by_customer: dict[int, list[CustomerExemption]] = defaultdict(list)
    for item in session.scalars(
        select(CustomerExemption).where(
            CustomerExemption.status.in_(EXEMPTION_REVIEWED_STATUSES),
            CustomerExemption.valid_from <= assessment_date,
            or_(
                CustomerExemption.valid_to.is_(None),
                CustomerExemption.valid_to >= assessment_date,
            ),
        )
    ):
        exemptions_by_customer[item.customer_id].append(item)

    assignments_by_address_role = {
        (item.source_address_id, item.sourcing_role): item
        for item in session.scalars(
            select(AddressAssignment).where(AddressAssignment.valid_to.is_(None))
        )
    }
    service_assignments = {
        source_address_id: item
        for (source_address_id, role), item in assignments_by_address_role.items()
        if role == "service_address"
    }
    profile_ids = {
        item.location_profile_id
        for item in assignments_by_address_role.values()
        if item.location_profile_id is not None
    }
    member_keys_by_profile: dict[int, set[str]] = defaultdict(set)
    if profile_ids:
        for profile_id, external_key in session.execute(
            select(
                LocationProfileMember.location_profile_id,
                Jurisdiction.external_key,
            )
            .join(Jurisdiction, Jurisdiction.id == LocationProfileMember.jurisdiction_id)
            .where(LocationProfileMember.location_profile_id.in_(profile_ids))
        ):
            member_keys_by_profile[profile_id].add(external_key)

    federal_routes: dict[tuple[int, int], BenchmarkRate] = {}
    routes_by_pcode: dict[int, dict[tuple[int, int], BenchmarkRate]] = defaultdict(dict)
    for rate in session.scalars(
        select(BenchmarkRate).where(
            BenchmarkRate.active.is_(True),
            BenchmarkRate.rate.is_not(None),
            BenchmarkRate.rate != Decimal("0"),
        )
    ):
        key = (rate.tax_level, rate.tax_type)
        if rate.tax_level == 0:
            federal_routes.setdefault(key, rate)
        else:
            routes_by_pcode[rate.p_code].setdefault(key, rate)

    crosswalks_by_route: dict[tuple[int, int], list[TaxTypeCrosswalk]] = defaultdict(list)
    for item in session.scalars(select(TaxTypeCrosswalk)):
        crosswalks_by_route[(item.benchmark_tax_level, item.benchmark_tax_type)].append(item)

    rules = list(
        session.scalars(
            select(TaxabilityRule).where(
                TaxabilityRule.review_status.in_(TAXABILITY_REVIEWED_STATUSES),
                TaxabilityRule.effective_from <= assessment_date,
                or_(
                    TaxabilityRule.effective_to.is_(None),
                    TaxabilityRule.effective_to >= assessment_date,
                ),
            )
        )
    )
    facts_by_key: dict[str, TaxFact] = {}
    for item in session.scalars(
        select(TaxFact)
        .where(
            TaxFact.status == "published",
            TaxFact.effective_from <= assessment_date,
            or_(TaxFact.effective_to.is_(None), TaxFact.effective_to >= assessment_date),
        )
        .order_by(TaxFact.effective_from.desc(), TaxFact.id.desc())
    ):
        facts_by_key.setdefault(item.natural_key, item)
    filing_maps = list(
        session.scalars(
            select(TaxFilingMap).where(
                TaxFilingMap.mapping_status.in_(REVIEWED_STATUSES),
                TaxFilingMap.effective_from <= assessment_date,
                or_(
                    TaxFilingMap.effective_to.is_(None),
                    TaxFilingMap.effective_to >= assessment_date,
                ),
            )
        )
    )
    previous_by_demand: dict[str, ServiceTaxAssessment] = {}
    for prior in session.scalars(
        select(ServiceTaxAssessment).order_by(
            ServiceTaxAssessment.demand_key,
            ServiceTaxAssessment.assessment_date.desc(),
            ServiceTaxAssessment.id.desc(),
        )
    ):
        previous_by_demand.setdefault(prior.demand_key, prior)

    counts: dict[str, Any] = {
        "assessment_date": str(assessment_date),
        "demand_rows_assessed": len(demands),
        "source_addresses": len(
            {item.source_address_id for item in demands if item.source_address_id is not None}
        ),
        "new_demand_rows": 0,
        "changed_assessments": 0,
        "determination_complete": 0,
        "product_mapping_ready": 0,
        "location_ready": 0,
        "taxability_ready": 0,
        "exemption_ready": 0,
        "filing_ready": 0,
        "calculation_ready": 0,
        "trailing_billed_amount": "0.00",
        "calculation_ready_billed_amount": "0.00",
        "estimated_public_tax_amount": "0.000000",
        "gap_codes": {},
    }
    total_billed = Decimal("0")
    ready_billed = Decimal("0")
    estimated_public_tax = Decimal("0")
    gap_counter: Counter[str] = Counter()
    report_rows: list[dict[str, Any]] = []
    inserted = 0
    try:
        for demand in demands:
            mapping = mappings.get(demand.source_tax_group)
            service_assignment = service_assignments.get(demand.source_address_id or -1)
            required_role = (
                mapping.default_sourcing_role
                if mapping and mapping.default_sourcing_role
                else "service_address"
            )
            required_assignment = assignments_by_address_role.get(
                (demand.source_address_id or -1, required_role)
            )
            benchmark_assignment = required_assignment or service_assignment
            state_code = benchmark_assignment.state_code if benchmark_assignment else None
            p_code = benchmark_assignment.benchmark_p_code if benchmark_assignment else None
            member_keys = (
                member_keys_by_profile.get(benchmark_assignment.location_profile_id or -1, set())
                if benchmark_assignment
                else set()
            )
            route_rates = dict(federal_routes)
            if p_code is not None:
                route_rates.update(routes_by_pcode.get(p_code, {}))
            result = _assess_demand(
                demand=demand,
                mapping=mapping,
                required_sourcing_role=required_role,
                required_assignment=required_assignment,
                benchmark_assignment=benchmark_assignment,
                state_code=state_code,
                p_code=p_code,
                member_keys=member_keys,
                route_rates=route_rates,
                crosswalks_by_route=crosswalks_by_route,
                rules=rules,
                facts_by_key=facts_by_key,
                filing_maps=filing_maps,
                customer_profile=profiles.get(demand.customer_id),
                exemptions=exemptions_by_customer.get(demand.customer_id, []),
            )
            digest_payload = {
                key: value
                for key, value in result.items()
                if key not in {"estimated_public_tax_amount"}
            }
            digest_payload["estimated_public_tax_amount"] = (
                str(result["estimated_public_tax_amount"])
                if result["estimated_public_tax_amount"] is not None
                else None
            )
            digest_payload.update(
                {
                    "source_address_id": demand.source_address_id,
                    "source_product_id": demand.source_product_id,
                    "trailing_billed_amount": str(demand.trailing_billed_amount),
                    "quantity": str(demand.quantity),
                    "last_invoice_at": demand.last_invoice_at.isoformat(),
                }
            )
            digest = hashlib.sha256(
                json.dumps(digest_payload, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest()
            previous = previous_by_demand.get(demand.demand_key)
            is_new = previous is None
            changed = is_new or previous.assessment_sha256 != digest
            snapshot = ServiceTaxAssessment(
                assessment_run_id=run.id,
                assessment_date=assessment_date,
                demand_key=demand.demand_key,
                service_product_demand_id=demand.id,
                previous_assessment_id=previous.id if previous else None,
                customer_id=demand.customer_id,
                source_address_id=demand.source_address_id,
                source_product_id=demand.source_product_id,
                source_tax_group=demand.source_tax_group,
                service_category=result["service_category"],
                charge_type=demand.charge_type,
                state_code=state_code,
                location_profile_id=(
                    benchmark_assignment.location_profile_id if benchmark_assignment else None
                ),
                benchmark_p_code=p_code,
                trailing_billed_amount=demand.trailing_billed_amount,
                product_mapping_ready=result["product_mapping_ready"],
                location_ready=result["location_ready"],
                taxability_ready=result["taxability_ready"],
                exemption_ready=result["exemption_ready"],
                filing_ready=result["filing_ready"],
                calculation_ready=result["calculation_ready"],
                determination_complete=result["determination_complete"],
                is_new_demand=is_new,
                assessment_changed=changed,
                candidate_route_count=result["candidate_route_count"],
                resolved_route_count=result["resolved_route_count"],
                taxable_route_count=result["taxable_route_count"],
                estimated_public_tax_amount=result["estimated_public_tax_amount"],
                gap_codes=result["gap_codes"],
                route_details=result["route_details"],
                assessment_sha256=digest,
            )
            session.add(snapshot)
            inserted += 1
            amount = Decimal(demand.trailing_billed_amount or 0)
            total_billed += amount
            if result["calculation_ready"]:
                ready_billed += amount
            if result["estimated_public_tax_amount"] is not None:
                estimated_public_tax += result["estimated_public_tax_amount"]
            counts["new_demand_rows"] += int(is_new)
            counts["changed_assessments"] += int(changed)
            for gate in (
                "determination_complete",
                "product_mapping_ready",
                "location_ready",
                "taxability_ready",
                "exemption_ready",
                "filing_ready",
                "calculation_ready",
            ):
                counts[gate] += int(result[gate])
            gap_counter.update(result["gap_codes"])
            report_rows.append(
                _report_row(
                    demand=demand,
                    result=result,
                    state_code=state_code,
                    p_code=p_code,
                    is_new=is_new,
                    changed=changed,
                )
            )
        session.flush()
        counts["trailing_billed_amount"] = str(total_billed.quantize(Decimal("0.01")))
        counts["calculation_ready_billed_amount"] = str(ready_billed.quantize(Decimal("0.01")))
        counts["estimated_public_tax_amount"] = str(
            estimated_public_tax.quantize(Decimal("0.000001"))
        )
        counts["gap_codes"] = dict(gap_counter.most_common())
        finish_run(
            run,
            CollectionStats(seen=len(demands), inserted=inserted, details=counts),
        )
        counts["collection_run_id"] = run.id
        if output_dir is not None:
            summary_path, gaps_path = write_service_tax_report(
                output_dir,
                run_id=run.id,
                counts=counts,
                report_rows=report_rows,
            )
            counts["summary_report"] = str(summary_path)
            counts["gap_report"] = str(gaps_path)
        return counts
    except Exception as exc:
        finish_run(
            run,
            CollectionStats(seen=len(demands), inserted=inserted, details=counts),
            status="failed",
            error=f"{type(exc).__name__}: {exc}",
        )
        raise


def _current_product_mappings(
    session: Session, assessment_date: date
) -> dict[str, ProductTaxonomyMap]:
    result: dict[str, ProductTaxonomyMap] = {}
    for item in session.scalars(
        select(ProductTaxonomyMap)
        .where(
            ProductTaxonomyMap.source_system == SOURCE_SYSTEM,
            ProductTaxonomyMap.effective_from <= assessment_date,
            or_(
                ProductTaxonomyMap.effective_to.is_(None),
                ProductTaxonomyMap.effective_to >= assessment_date,
            ),
        )
        .order_by(
            ProductTaxonomyMap.source_tax_group,
            ProductTaxonomyMap.effective_from.desc(),
            ProductTaxonomyMap.id.desc(),
        )
    ):
        result.setdefault(item.source_tax_group, item)
    return result


def _assess_demand(
    *,
    demand: ServiceProductDemand,
    mapping: ProductTaxonomyMap | None,
    required_sourcing_role: str,
    required_assignment: AddressAssignment | None,
    benchmark_assignment: AddressAssignment | None,
    state_code: str | None,
    p_code: int | None,
    member_keys: set[str],
    route_rates: dict[tuple[int, int], BenchmarkRate],
    crosswalks_by_route: dict[tuple[int, int], list[TaxTypeCrosswalk]],
    rules: list[TaxabilityRule],
    facts_by_key: dict[str, TaxFact],
    filing_maps: list[TaxFilingMap],
    customer_profile: CustomerTaxProfile | None,
    exemptions: list[CustomerExemption],
) -> dict[str, Any]:
    gaps: set[str] = set()
    service_category = mapping.service_category if mapping else None
    product_mapping_ready = bool(
        mapping and service_category and mapping.mapping_status in PRODUCT_REVIEWED_STATUSES
    )
    if mapping is None or service_category is None:
        gaps.add("PRODUCT_TAX_GROUP_UNMAPPED")
    elif not product_mapping_ready:
        gaps.add("PRODUCT_MAPPING_UNREVIEWED")

    if benchmark_assignment is None:
        gaps.add("LOCATION_ASSIGNMENT_MISSING")
    if required_assignment is None:
        gaps.add("MISSING_REQUIRED_SOURCING_ASSIGNMENT")
    elif not required_assignment.calculation_ready:
        gaps.add("TAX_BOUNDARY_UNVERIFIED")
    location_ready = bool(required_assignment is not None and required_assignment.calculation_ready)
    if benchmark_assignment is not None and p_code is None:
        gaps.add("NO_BENCHMARK_PCODE")

    route_details: list[dict[str, Any]] = []
    candidate_route_count = 0
    resolved_route_count = 0
    taxable_route_count = 0
    route_calculations_ready = True
    route_sourcing_ready = True
    filing_ready = True
    exemption_ready = True
    estimated_total = Decimal("0")
    estimated_any = False
    for route_key, rate in sorted(route_rates.items()):
        route = _assess_route(
            demand=demand,
            rate=rate,
            service_category=service_category,
            required_sourcing_role=required_sourcing_role,
            state_code=state_code,
            p_code=p_code,
            member_keys=member_keys,
            crosswalks=crosswalks_by_route.get(route_key, []),
            rules=rules,
            facts_by_key=facts_by_key,
            filing_maps=filing_maps,
            customer_profile=customer_profile,
            exemptions=exemptions,
        )
        route_details.append(route)
        if route["status"] == "not_applicable":
            continue
        candidate_route_count += 1
        resolved_route_count += int(route["resolved"])
        taxable_route_count += int(route["taxability"] == "taxable")
        filing_ready = filing_ready and route["filing_ready"]
        exemption_ready = exemption_ready and route["exemption_ready"]
        route_calculations_ready = route_calculations_ready and route["calculation_ready"]
        route_sourcing_ready = route_sourcing_ready and route["sourcing_ready"]
        gaps.update(route["gap_codes"])
        if route["estimated_tax_amount"] is not None:
            estimated_total += Decimal(route["estimated_tax_amount"])
            estimated_any = True

    if not route_rates:
        gaps.add("NO_BENCHMARK_TAX_ROUTES")
    taxability_ready = bool(route_rates and candidate_route_count == resolved_route_count)
    location_ready = location_ready and route_sourcing_ready
    calculation_ready = bool(
        product_mapping_ready
        and location_ready
        and taxability_ready
        and exemption_ready
        and filing_ready
        and route_calculations_ready
    )
    return {
        "service_category": service_category,
        "required_sourcing_role": required_sourcing_role,
        "product_mapping_ready": product_mapping_ready,
        "location_ready": location_ready,
        "taxability_ready": taxability_ready,
        "exemption_ready": exemption_ready,
        "filing_ready": filing_ready,
        "calculation_ready": calculation_ready,
        "determination_complete": calculation_ready,
        "candidate_route_count": candidate_route_count,
        "resolved_route_count": resolved_route_count,
        "taxable_route_count": taxable_route_count,
        "estimated_public_tax_amount": (
            estimated_total.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
            if estimated_any
            else None
        ),
        "gap_codes": sorted(gaps),
        "route_details": route_details,
    }


def _assess_route(
    *,
    demand: ServiceProductDemand,
    rate: BenchmarkRate,
    service_category: str | None,
    required_sourcing_role: str,
    state_code: str | None,
    p_code: int | None,
    member_keys: set[str],
    crosswalks: list[TaxTypeCrosswalk],
    rules: list[TaxabilityRule],
    facts_by_key: dict[str, TaxFact],
    filing_maps: list[TaxFilingMap],
    customer_profile: CustomerTaxProfile | None,
    exemptions: list[CustomerExemption],
) -> dict[str, Any]:
    gaps: set[str] = set()
    reviewed_crosswalks = [
        item
        for item in crosswalks
        if item.mapping_status in REVIEWED_STATUSES and item.ctd_tax_concept and item.legal_citation
    ]
    reviewed_categories = {
        item.service_category
        for item in reviewed_crosswalks
        if item.service_category and item.service_category != "general"
    }
    if (
        service_category
        and reviewed_categories
        and service_category not in reviewed_categories
        and not any(item.service_category == "general" for item in reviewed_crosswalks)
    ):
        return _route_result(
            rate=rate,
            status="not_applicable",
            resolved=True,
            concept=None,
            taxability="not_applicable",
            filing_ready=True,
            exemption_ready=True,
            calculation_ready=True,
            gap_codes=[],
            reason="reviewed_crosswalk_service_category_mismatch",
        )
    matching_crosswalks = [
        item
        for item in reviewed_crosswalks
        if item.service_category in (None, "general", service_category)
    ]
    concepts = sorted({item.ctd_tax_concept for item in matching_crosswalks})
    if not concepts:
        gaps.add("MISSING_REVIEWED_TAX_CONCEPT_MAP")
        candidate_concepts = sorted(
            {
                item.ctd_tax_concept
                for item in crosswalks
                if item.ctd_tax_concept
                and item.service_category in (None, "general", service_category)
            }
        )
        return _route_result(
            rate=rate,
            status="unresolved",
            resolved=False,
            concept=candidate_concepts[0] if len(candidate_concepts) == 1 else None,
            taxability="unknown",
            filing_ready=False,
            exemption_ready=True,
            calculation_ready=False,
            gap_codes=sorted(gaps),
            reason="no_reviewed_tax_concept_crosswalk",
        )

    concept = concepts[0]
    if len(concepts) > 1:
        gaps.add("AMBIGUOUS_TAX_CONCEPT_MAP")
    rule = _best_rule(
        rules,
        concept=concept,
        tax_level=rate.tax_level,
        service_category=service_category,
        charge_type=demand.charge_type,
        state_code=state_code,
        p_code=p_code,
        member_keys=member_keys,
    )
    if rule is None:
        gaps.add("MISSING_TAXABILITY_DECISION")
        return _route_result(
            rate=rate,
            status="unresolved",
            resolved=False,
            concept=concept,
            taxability="unknown",
            filing_ready=False,
            exemption_ready=True,
            calculation_ready=False,
            gap_codes=sorted(gaps),
            reason="no_reviewed_service_taxability_rule",
        )

    if rule.taxability in {"non_taxable", "not_applicable", "exempt"}:
        return _route_result(
            rate=rate,
            status="resolved",
            resolved=True,
            concept=concept,
            taxability=rule.taxability,
            filing_ready=True,
            exemption_ready=True,
            calculation_ready=True,
            gap_codes=sorted(gaps),
            reason="reviewed_taxability_rule",
            rule=rule,
            estimated_tax_amount="0.000000",
        )
    if rule.taxability != "taxable":
        gaps.add("CONDITIONAL_TAXABILITY_REQUIRES_REVIEW")
        return _route_result(
            rate=rate,
            status="unresolved",
            resolved=False,
            concept=concept,
            taxability=rule.taxability,
            filing_ready=False,
            exemption_ready=True,
            calculation_ready=False,
            gap_codes=sorted(gaps),
            reason="conditional_taxability",
            rule=rule,
        )

    sourcing_ready = rule.sourcing_role == required_sourcing_role
    if not sourcing_ready:
        gaps.add("SOURCING_ROLE_RULE_MISMATCH")

    claimed_exempt = _source_claims_exemption(customer_profile, rate.tax_level)
    exemption = (
        _matching_exemption(
            exemptions,
            tax_level=rate.tax_level,
            state_code=state_code,
            member_keys=member_keys,
            service_category=service_category,
        )
        if claimed_exempt
        else None
    )
    exemption_ready = not claimed_exempt or exemption is not None
    if not exemption_ready:
        gaps.add("EXEMPTION_EVIDENCE_UNVERIFIED")
    if exemption is not None:
        return _route_result(
            rate=rate,
            status="resolved",
            resolved=True,
            concept=concept,
            taxability="customer_exempt",
            filing_ready=True,
            exemption_ready=True,
            calculation_ready=sourcing_ready,
            gap_codes=sorted(gaps),
            reason="verified_customer_exemption",
            rule=rule,
            estimated_tax_amount="0.000000",
        )

    fact = facts_by_key.get(rule.tax_fact_natural_key or "")
    if fact is None:
        gaps.add("MISSING_PUBLIC_FACT_LINK")
    filing_ready = not rule.filing_required or any(
        _filing_map_applies(
            item,
            rate=rate,
            concept=concept,
            state_code=state_code,
            p_code=p_code,
            member_keys=member_keys,
        )
        for item in filing_maps
    )
    if not filing_ready:
        gaps.add("MISSING_FILING_ROUTE")
    estimate, calculation_gap = _estimate_tax(demand, rule, fact)
    if calculation_gap:
        gaps.add(calculation_gap)
    calculation_ready = bool(
        fact is not None
        and estimate is not None
        and exemption_ready
        and filing_ready
        and sourcing_ready
        and not calculation_gap
    )
    return _route_result(
        rate=rate,
        status="resolved",
        resolved=True,
        concept=concept,
        taxability="taxable",
        filing_ready=filing_ready,
        exemption_ready=exemption_ready,
        calculation_ready=calculation_ready,
        gap_codes=sorted(gaps),
        reason="reviewed_taxability_rule",
        rule=rule,
        fact=fact,
        estimated_tax_amount=str(estimate) if estimate is not None else None,
    )


def _route_result(
    *,
    rate: BenchmarkRate,
    status: str,
    resolved: bool,
    concept: str | None,
    taxability: str,
    filing_ready: bool,
    exemption_ready: bool,
    calculation_ready: bool,
    gap_codes: list[str],
    reason: str,
    rule: TaxabilityRule | None = None,
    fact: TaxFact | None = None,
    estimated_tax_amount: str | None = None,
) -> dict[str, Any]:
    return {
        "benchmark_tax_type": rate.tax_type,
        "tax_level": rate.tax_level,
        "benchmark_description": rate.tax_description,
        "ctd_tax_concept": concept,
        "status": status,
        "resolved": resolved,
        "taxability": taxability,
        "reason": reason,
        "taxability_rule": rule.natural_key if rule else None,
        "public_fact": fact.natural_key if fact else None,
        "public_rate": str(fact.rate) if fact and fact.rate is not None else None,
        "filing_ready": filing_ready,
        "exemption_ready": exemption_ready,
        "sourcing_ready": "SOURCING_ROLE_RULE_MISMATCH" not in gap_codes,
        "calculation_ready": calculation_ready,
        "estimated_tax_amount": estimated_tax_amount,
        "legal_citation": rule.legal_citation if rule else None,
        "gap_codes": gap_codes,
    }


def _best_rule(
    rules: list[TaxabilityRule],
    *,
    concept: str,
    tax_level: int,
    service_category: str | None,
    charge_type: str,
    state_code: str | None,
    p_code: int | None,
    member_keys: set[str],
) -> TaxabilityRule | None:
    candidates = [
        item
        for item in rules
        if item.ctd_tax_concept == concept
        and item.tax_level == tax_level
        and item.service_category in ("general", service_category)
        and item.charge_type in (None, "general", charge_type)
        and item.state_code in (None, state_code)
        and item.p_code in (None, p_code)
        and (
            item.jurisdiction_external_key is None or item.jurisdiction_external_key in member_keys
        )
    ]
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda item: (
            item.p_code is not None,
            item.jurisdiction_external_key is not None,
            item.state_code is not None,
            item.service_category != "general",
            item.charge_type not in (None, "general"),
            item.effective_from,
            item.id,
        ),
    )


def _source_claims_exemption(profile: CustomerTaxProfile | None, tax_level: int) -> bool:
    if profile is None:
        return False
    if profile.source_tax_exempt:
        return True
    if tax_level == 0:
        return profile.source_tax_exempt_federal
    if tax_level == 1:
        return profile.source_tax_exempt_state
    return profile.source_tax_exempt_local


def _matching_exemption(
    exemptions: list[CustomerExemption],
    *,
    tax_level: int,
    state_code: str | None,
    member_keys: set[str],
    service_category: str | None,
) -> CustomerExemption | None:
    candidates = [
        item
        for item in exemptions
        if item.tax_level in (None, tax_level)
        and item.state_code in (None, state_code)
        and item.service_category in (None, "general", service_category)
        and (
            item.jurisdiction_external_key is None or item.jurisdiction_external_key in member_keys
        )
    ]
    if not candidates:
        return None
    return max(
        candidates,
        key=lambda item: (
            item.tax_level is not None,
            item.jurisdiction_external_key is not None,
            item.state_code is not None,
            item.service_category not in (None, "general"),
            item.valid_from,
            item.id,
        ),
    )


def _filing_map_applies(
    item: TaxFilingMap,
    *,
    rate: BenchmarkRate,
    concept: str,
    state_code: str | None,
    p_code: int | None,
    member_keys: set[str],
) -> bool:
    return (
        item.benchmark_tax_type in (None, rate.tax_type)
        and item.tax_level == rate.tax_level
        and item.ctd_tax_concept == concept
        and item.state_code in (None, state_code)
        and item.p_code in (None, p_code)
        and (
            item.jurisdiction_external_key is None or item.jurisdiction_external_key in member_keys
        )
    )


def _estimate_tax(
    demand: ServiceProductDemand,
    rule: TaxabilityRule,
    fact: TaxFact | None,
) -> tuple[Decimal | None, str | None]:
    if fact is None:
        return None, None
    if fact.max_base is not None or fact.min_base is not None:
        return None, "CAP_OR_BRACKET_REQUIRES_LINE_LEVEL_CALCULATION"
    taxable_percentage = rule.taxable_percentage or Decimal("1")
    if rule.calculation_method == "percent_of_charge":
        if fact.unit != "percent_of_base" or fact.rate is None:
            return None, "CALCULATION_METHOD_UNSUPPORTED"
        value = Decimal(demand.trailing_billed_amount) * taxable_percentage * Decimal(fact.rate)
        return value.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP), None
    if rule.calculation_method == "flat_per_unit":
        if fact.flat_amount is None:
            return None, "CALCULATION_METHOD_UNSUPPORTED"
        value = Decimal(demand.quantity) * Decimal(fact.flat_amount)
        return value.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP), None
    return None, "CALCULATION_METHOD_UNSUPPORTED"


def _report_row(
    *,
    demand: ServiceProductDemand,
    result: dict[str, Any],
    state_code: str | None,
    p_code: int | None,
    is_new: bool,
    changed: bool,
) -> dict[str, Any]:
    return {
        "source_address_id": demand.source_address_id or "",
        "source_product_id": demand.source_product_id or "",
        "source_tax_group": demand.source_tax_group,
        "service_category": result["service_category"] or "",
        "charge_type": demand.charge_type,
        "state": state_code or "",
        "benchmark_p_code": p_code or "",
        "trailing_billed_amount": str(demand.trailing_billed_amount),
        "new_demand": is_new,
        "assessment_changed": changed,
        "product_mapping_ready": result["product_mapping_ready"],
        "location_ready": result["location_ready"],
        "taxability_ready": result["taxability_ready"],
        "exemption_ready": result["exemption_ready"],
        "filing_ready": result["filing_ready"],
        "calculation_ready": result["calculation_ready"],
        "candidate_routes": result["candidate_route_count"],
        "resolved_routes": result["resolved_route_count"],
        "taxable_routes": result["taxable_route_count"],
        "estimated_public_tax_amount": (
            str(result["estimated_public_tax_amount"])
            if result["estimated_public_tax_amount"] is not None
            else ""
        ),
        "gap_codes": ",".join(result["gap_codes"]),
    }


def write_service_tax_report(
    output_dir: Path,
    *,
    run_id: int,
    counts: dict[str, Any],
    report_rows: list[dict[str, Any]],
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = output_dir / "service-tax-assessment-summary.json"
    gaps_path = output_dir / "service-tax-assessment-gaps.csv"
    summary_path.write_text(
        json.dumps(
            {"run_id": run_id, "generated_at": utcnow().isoformat(), "summary": counts},
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    fieldnames = (
        list(report_rows[0])
        if report_rows
        else [
            "source_address_id",
            "source_tax_group",
            "calculation_ready",
        ]
    )
    with gaps_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(
            sorted(
                (row for row in report_rows if not row["calculation_ready"]),
                key=lambda row: (
                    not row["new_demand"],
                    not row["assessment_changed"],
                    -Decimal(row["trailing_billed_amount"]),
                    row["source_address_id"],
                ),
            )
        )
    return summary_path, gaps_path


def latest_service_tax_data(
    session: Session,
    *,
    state: str | None = None,
    tax_group: str | None = None,
    manual_only: bool = True,
    limit: int = 1000,
) -> dict[str, Any]:
    latest_run = session.scalar(
        select(ServiceTaxAssessment.assessment_run_id)
        .order_by(ServiceTaxAssessment.assessment_run_id.desc())
        .limit(1)
    )
    taxonomy = _taxonomy_summary(session)
    if latest_run is None:
        return {
            "run_id": None,
            "assessment_date": None,
            "summary": _empty_summary(),
            "readiness": [],
            "taxonomy": taxonomy,
            "categories": [],
            "gaps": [],
            "assessments": [],
        }
    all_rows = list(
        session.scalars(
            select(ServiceTaxAssessment)
            .where(ServiceTaxAssessment.assessment_run_id == latest_run)
            .order_by(
                ServiceTaxAssessment.is_new_demand.desc(),
                ServiceTaxAssessment.calculation_ready,
                ServiceTaxAssessment.trailing_billed_amount.desc(),
                ServiceTaxAssessment.source_address_id,
            )
        )
    )
    category_totals: dict[tuple[str, str | None, bool], dict[str, Any]] = {}
    gap_counts: Counter[str] = Counter()
    gap_amounts: defaultdict[str, Decimal] = defaultdict(Decimal)
    for row in all_rows:
        key = (row.source_tax_group, row.service_category, row.product_mapping_ready)
        target = category_totals.setdefault(
            key,
            {
                "source_tax_group": row.source_tax_group,
                "service_category": row.service_category,
                "product_mapping_ready": row.product_mapping_ready,
                "demand_rows": 0,
                "source_addresses": set(),
                "trailing_billed_amount": Decimal("0"),
                "calculation_ready_rows": 0,
            },
        )
        target["demand_rows"] += 1
        if row.source_address_id is not None:
            target["source_addresses"].add(row.source_address_id)
        target["trailing_billed_amount"] += Decimal(row.trailing_billed_amount)
        target["calculation_ready_rows"] += int(row.calculation_ready)
        for code in row.gap_codes or []:
            gap_counts[code] += 1
            gap_amounts[code] += Decimal(row.trailing_billed_amount)
    categories = []
    for target in category_totals.values():
        target["source_addresses"] = len(target["source_addresses"])
        target["trailing_billed_amount"] = str(
            target["trailing_billed_amount"].quantize(Decimal("0.01"))
        )
        categories.append(target)
    categories.sort(
        key=lambda row: (-Decimal(row["trailing_billed_amount"]), row["source_tax_group"])
    )
    filtered = all_rows
    if state:
        filtered = [row for row in filtered if row.state_code == state.upper()]
    if tax_group:
        filtered = [row for row in filtered if row.source_tax_group == tax_group.lower()]
    if manual_only:
        filtered = [row for row in filtered if not row.calculation_ready]

    billed_total = sum((Decimal(row.trailing_billed_amount) for row in all_rows), Decimal())
    ready_total = sum(
        (Decimal(row.trailing_billed_amount) for row in all_rows if row.calculation_ready),
        Decimal(),
    )
    readiness_fields = (
        ("product_mapping_ready", "Product mapping"),
        ("location_ready", "Location / sourcing"),
        ("taxability_ready", "Taxability"),
        ("exemption_ready", "Exemption evidence"),
        ("filing_ready", "Filing route"),
        ("calculation_ready", "Calculation"),
    )
    readiness = [
        {
            "gate": field,
            "name": name,
            "ready_rows": sum(bool(getattr(row, field)) for row in all_rows),
            "total_rows": len(all_rows),
            "ready_billed_amount": str(
                sum(
                    (
                        Decimal(row.trailing_billed_amount)
                        for row in all_rows
                        if getattr(row, field)
                    ),
                    Decimal(),
                ).quantize(Decimal("0.01"))
            ),
        }
        for field, name in readiness_fields
    ]
    return {
        "run_id": latest_run,
        "assessment_date": all_rows[0].assessment_date if all_rows else None,
        "summary": {
            "demand_rows": len(all_rows),
            "source_addresses": len(
                {row.source_address_id for row in all_rows if row.source_address_id is not None}
            ),
            "new_demand_rows": sum(row.is_new_demand for row in all_rows),
            "changed_assessments": sum(row.assessment_changed for row in all_rows),
            "calculation_ready_rows": sum(row.calculation_ready for row in all_rows),
            "manual_rows": sum(not row.calculation_ready for row in all_rows),
            "trailing_billed_amount": str(billed_total.quantize(Decimal("0.01"))),
            "calculation_ready_billed_amount": str(ready_total.quantize(Decimal("0.01"))),
            "calculation_ready_billed_percent": (
                round(100 * float(ready_total / billed_total), 2) if billed_total else None
            ),
        },
        "readiness": readiness,
        "taxonomy": taxonomy,
        "categories": categories,
        "gaps": [
            {
                "code": code,
                "demand_rows": count,
                "trailing_billed_amount": str(gap_amounts[code].quantize(Decimal("0.01"))),
            }
            for code, count in gap_counts.most_common()
        ],
        "assessments": [
            {
                "source_address_id": row.source_address_id,
                "source_product_id": row.source_product_id,
                "source_tax_group": row.source_tax_group,
                "service_category": row.service_category,
                "charge_type": row.charge_type,
                "state": row.state_code,
                "benchmark_p_code": row.benchmark_p_code,
                "trailing_billed_amount": str(row.trailing_billed_amount),
                "new_demand": row.is_new_demand,
                "assessment_changed": row.assessment_changed,
                "product_mapping_ready": row.product_mapping_ready,
                "location_ready": row.location_ready,
                "taxability_ready": row.taxability_ready,
                "exemption_ready": row.exemption_ready,
                "filing_ready": row.filing_ready,
                "calculation_ready": row.calculation_ready,
                "candidate_routes": row.candidate_route_count,
                "resolved_routes": row.resolved_route_count,
                "taxable_routes": row.taxable_route_count,
                "estimated_public_tax_amount": (
                    str(row.estimated_public_tax_amount)
                    if row.estimated_public_tax_amount is not None
                    else None
                ),
                "gap_codes": row.gap_codes or [],
                "routes": row.route_details or [],
            }
            for row in filtered[:limit]
        ],
    }


def _taxonomy_summary(session: Session) -> list[dict[str, Any]]:
    product_counts: Counter[str] = Counter()
    active_product_counts: Counter[str] = Counter()
    for item in session.scalars(select(ProductCatalogItem)):
        product_counts[item.source_tax_group] += 1
        active_product_counts[item.source_tax_group] += int(item.active)
    demand_counts: Counter[str] = Counter()
    demand_amounts: defaultdict[str, Decimal] = defaultdict(Decimal)
    for item in session.scalars(select(ServiceProductDemand)):
        demand_counts[item.source_tax_group] += 1
        demand_amounts[item.source_tax_group] += Decimal(item.trailing_billed_amount)
    mappings = _current_product_mappings(session, date.today())
    groups = sorted(set(product_counts) | set(demand_counts) | set(mappings))
    rows = [
        {
            "source_tax_group": group,
            "service_category": (mappings[group].service_category if group in mappings else None),
            "default_sourcing_role": (
                mappings[group].default_sourcing_role if group in mappings else None
            ),
            "mapping_status": (mappings[group].mapping_status if group in mappings else "missing"),
            "confidence": mappings[group].confidence if group in mappings else "unmapped",
            "catalog_products": product_counts[group],
            "active_catalog_products": active_product_counts[group],
            "demand_rows": demand_counts[group],
            "trailing_billed_amount": str(demand_amounts[group].quantize(Decimal("0.01"))),
            "notes": mappings[group].notes if group in mappings else None,
        }
        for group in groups
    ]
    rows.sort(key=lambda row: (-Decimal(row["trailing_billed_amount"]), row["source_tax_group"]))
    return rows


def _empty_summary() -> dict[str, Any]:
    return {
        "demand_rows": 0,
        "source_addresses": 0,
        "new_demand_rows": 0,
        "changed_assessments": 0,
        "calculation_ready_rows": 0,
        "manual_rows": 0,
        "trailing_billed_amount": "0.00",
        "calculation_ready_billed_amount": "0.00",
        "calculation_ready_billed_percent": None,
    }
