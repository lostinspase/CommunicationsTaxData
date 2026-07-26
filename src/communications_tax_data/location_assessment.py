from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter, defaultdict
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from communications_tax_data.collectors.base import (
    CollectionStats,
    finish_run,
    start_run,
)
from communications_tax_data.models import (
    AddressAssignment,
    BenchmarkRate,
    Jurisdiction,
    LocationAssessment,
    LocationProfile,
    LocationProfileMember,
    TaxFact,
    TaxFactBenchmarkMap,
    TaxFilingMap,
    TaxTypeCrosswalk,
    utcnow,
)

APPROVED_STATUSES = {"source_verified", "reviewed", "verified", "published"}
LEVEL_NAMES = {
    0: "Federal",
    1: "State",
    2: "County",
    3: "Municipal / special district",
}


def assess_service_locations(
    session: Session,
    *,
    as_of: date | None = None,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    """Create an auditable daily assessment for every current active service address."""
    assessment_date = as_of or date.today()
    run = start_run(session, "daily-location-assessment")
    assignments = list(
        session.scalars(
            select(AddressAssignment)
            .where(AddressAssignment.valid_to.is_(None))
            .order_by(AddressAssignment.source_address_id)
        )
    )
    profile_ids = {
        item.location_profile_id
        for item in assignments
        if item.location_profile_id is not None
    }
    profiles = {
        item.id: item
        for item in session.scalars(
            select(LocationProfile).where(LocationProfile.id.in_(profile_ids))
        )
    }
    members_by_profile: dict[int, dict[int, list[dict[str, Any]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    if profile_ids:
        for profile_id, role, jurisdiction in session.execute(
            select(
                LocationProfileMember.location_profile_id,
                LocationProfileMember.member_role,
                Jurisdiction,
            )
            .join(Jurisdiction, Jurisdiction.id == LocationProfileMember.jurisdiction_id)
            .where(LocationProfileMember.location_profile_id.in_(profile_ids))
        ):
            members_by_profile[profile_id][jurisdiction.tax_level].append(
                {
                    "role": role,
                    "external_key": jurisdiction.external_key,
                    "name": jurisdiction.name,
                }
            )

    rates_by_pcode: dict[int, dict[int, set[int]]] = defaultdict(
        lambda: defaultdict(set)
    )
    federal_tax_types: set[int] = set()
    for rate in session.scalars(
        select(BenchmarkRate).where(
            BenchmarkRate.active.is_(True),
            BenchmarkRate.rate.is_not(None),
            BenchmarkRate.rate != Decimal("0"),
        )
    ):
        rates_by_pcode[rate.p_code][rate.tax_level].add(rate.tax_type)
        if rate.tax_level == 0:
            federal_tax_types.add(rate.tax_type)

    current_fact_keys = set(
        session.scalars(
            select(TaxFact.natural_key).where(
                TaxFact.effective_from <= assessment_date,
                or_(TaxFact.effective_to.is_(None), TaxFact.effective_to >= assessment_date),
                TaxFact.status == "published",
            )
        )
    )
    fact_maps_by_route: dict[tuple[int, int], list[TaxFactBenchmarkMap]] = defaultdict(list)
    for mapping in session.scalars(
        select(TaxFactBenchmarkMap).where(
            TaxFactBenchmarkMap.effective_from <= assessment_date,
            or_(
                TaxFactBenchmarkMap.effective_to.is_(None),
                TaxFactBenchmarkMap.effective_to >= assessment_date,
            ),
            TaxFactBenchmarkMap.mapping_status.in_(APPROVED_STATUSES),
            TaxFactBenchmarkMap.legal_citation.is_not(None),
        )
    ):
        if mapping.public_fact_natural_key not in current_fact_keys:
            continue
        fact_maps_by_route[
            (mapping.benchmark_tax_level, mapping.benchmark_tax_type)
        ].append(mapping)
    cited_crosswalk_routes = {
        (mapping.benchmark_tax_level, mapping.benchmark_tax_type)
        for mapping in session.scalars(select(TaxTypeCrosswalk))
        if mapping.ctd_tax_concept and mapping.legal_citation
    }

    filing_maps_by_level: dict[int, list[TaxFilingMap]] = defaultdict(list)
    recipient_maps_by_level: dict[int, list[TaxFilingMap]] = defaultdict(list)
    for mapping in session.scalars(
        select(TaxFilingMap).where(
            TaxFilingMap.effective_from <= assessment_date,
            or_(
                TaxFilingMap.effective_to.is_(None),
                TaxFilingMap.effective_to >= assessment_date,
            ),
        )
    ):
        if mapping.mapping_status in APPROVED_STATUSES:
            filing_maps_by_level[mapping.tax_level].append(mapping)
        elif mapping.mapping_status == "recipient_verified":
            recipient_maps_by_level[mapping.tax_level].append(mapping)

    previous_by_address: dict[tuple[str, int], LocationAssessment] = {}
    prior_profile_ids: set[int] = set()
    for previous in session.scalars(
        select(LocationAssessment).order_by(
            LocationAssessment.source_system,
            LocationAssessment.source_address_id,
            LocationAssessment.assessment_date.desc(),
            LocationAssessment.id.desc(),
        )
    ):
        previous_by_address.setdefault(
            (previous.source_system, previous.source_address_id), previous
        )
        if previous.location_profile_id is not None:
            prior_profile_ids.add(previous.location_profile_id)

    stats = CollectionStats(seen=len(assignments))
    counts: dict[str, Any] = {
        "assessment_date": str(assessment_date),
        "addresses_assessed": len(assignments),
        "new_addresses": 0,
        "new_jurisdiction_profiles": 0,
        "changed_assessments": 0,
        "profile_changes": 0,
        "complete_assessments": 0,
        "manual_coverage_required": 0,
        "resolver_statuses": {},
        "level_summary": {},
        "gap_codes": {},
    }
    resolver_statuses: Counter[str] = Counter()
    all_gap_codes: Counter[str] = Counter()
    level_summary = {
        level: {
            "level": level,
            "name": LEVEL_NAMES[level],
            "addresses": 0,
            "jurisdiction_resolved": 0,
            "boundary_ready": 0,
            "benchmark_tax_routes": 0,
            "public_rule_routes": 0,
            "filing_routes": 0,
            "manual_required": 0,
            "complete": 0,
        }
        for level in range(4)
    }
    seen_profile_ids = set(prior_profile_ids)
    snapshot_rows: list[LocationAssessment] = []
    report_rows: list[dict[str, Any]] = []

    for assignment in assignments:
        state_code = _resolved_state(
            members_by_profile.get(assignment.location_profile_id or -1, {}),
            assignment.state_code,
        )
        level_details: dict[str, Any] = {}
        manual_gap_levels: list[int] = []
        for level in range(4):
            detail = _assess_level(
                level=level,
                assignment=assignment,
                state_code=state_code,
                members=members_by_profile.get(assignment.location_profile_id or -1, {}).get(
                    level, []
                ),
                benchmark_tax_types=(
                    federal_tax_types
                    if level == 0
                    else rates_by_pcode.get(assignment.benchmark_p_code or -1, {}).get(
                        level, set()
                    )
                ),
                fact_maps_by_route=fact_maps_by_route,
                cited_crosswalk_routes=cited_crosswalk_routes,
                filing_maps=filing_maps_by_level.get(level, []),
                recipient_maps=recipient_maps_by_level.get(level, []),
            )
            level_details[str(level)] = detail
            summary = level_summary[level]
            summary["addresses"] += 1
            summary["jurisdiction_resolved"] += int(detail["jurisdiction_resolved"])
            summary["boundary_ready"] += int(detail["boundary_ready"])
            summary["benchmark_tax_routes"] += detail["benchmark_tax_type_count"]
            summary["public_rule_routes"] += detail["public_rule_covered_count"]
            summary["filing_routes"] += detail["filing_covered_count"]
            summary["manual_required"] += int(detail["manual_required"])
            summary["complete"] += int(detail["status"] == "complete")
            if detail["manual_required"]:
                manual_gap_levels.append(level)
            all_gap_codes.update(detail["gap_codes"])

        digest_payload = {
            "source_address_id": assignment.source_address_id,
            "address_assignment_id": assignment.id,
            "location_profile_id": assignment.location_profile_id,
            "resolver_status": assignment.status,
            "resolver_confidence": assignment.confidence,
            "benchmark_p_code": assignment.benchmark_p_code,
            "level_details": level_details,
        }
        digest = hashlib.sha256(
            json.dumps(digest_payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        address_key = (assignment.source_system, assignment.source_address_id)
        previous = previous_by_address.get(address_key)
        is_new = previous is None
        is_new_profile = bool(
            assignment.location_profile_id is not None
            and assignment.location_profile_id not in seen_profile_ids
        )
        if assignment.location_profile_id is not None:
            seen_profile_ids.add(assignment.location_profile_id)
        profile_changed = bool(
            previous is not None
            and previous.location_profile_id != assignment.location_profile_id
        )
        changed = is_new or previous.assessment_sha256 != digest
        complete = not manual_gap_levels
        gap_count = sum(len(item["gap_codes"]) for item in level_details.values())
        statuses = [level_details[str(level)]["status"] for level in range(4)]
        snapshot = LocationAssessment(
            assessment_run_id=run.id,
            assessment_date=assessment_date,
            source_system=assignment.source_system,
            source_address_id=assignment.source_address_id,
            address_assignment_id=assignment.id,
            location_profile_id=assignment.location_profile_id,
            previous_assessment_id=previous.id if previous else None,
            state_code=state_code,
            postal_code=assignment.postal_code,
            plus_four=assignment.plus_four,
            benchmark_p_code=assignment.benchmark_p_code,
            resolver_status=assignment.status,
            resolver_confidence=assignment.confidence,
            location_calculation_ready=assignment.calculation_ready,
            assessment_complete=complete,
            is_new_address=is_new,
            is_new_profile=is_new_profile,
            profile_changed=profile_changed,
            assessment_changed=changed,
            level_0_status=statuses[0],
            level_1_status=statuses[1],
            level_2_status=statuses[2],
            level_3_status=statuses[3],
            gap_count=gap_count,
            manual_gap_levels=manual_gap_levels,
            level_details=level_details,
            assessment_sha256=digest,
        )
        session.add(snapshot)
        snapshot_rows.append(snapshot)
        resolver_statuses[assignment.status] += 1
        counts["new_addresses"] += int(is_new)
        counts["new_jurisdiction_profiles"] += int(is_new_profile)
        counts["changed_assessments"] += int(changed)
        counts["profile_changes"] += int(profile_changed)
        counts["complete_assessments"] += int(complete)
        counts["manual_coverage_required"] += int(not complete)
        report_rows.append(
            _report_row(
                assignment=assignment,
                profile=profiles.get(assignment.location_profile_id or -1),
                snapshot=snapshot,
            )
        )

    session.flush()
    counts["resolver_statuses"] = dict(sorted(resolver_statuses.items()))
    counts["level_summary"] = {
        str(level): level_summary[level] for level in range(4)
    }
    counts["gap_codes"] = dict(all_gap_codes.most_common())
    stats.inserted = len(snapshot_rows)
    stats.details = counts
    finish_run(run, stats)
    counts["collection_run_id"] = run.id
    if output_dir is not None:
        summary_path, gaps_path = write_location_assessment_report(
            output_dir,
            run_id=run.id,
            counts=counts,
            report_rows=report_rows,
        )
        counts["summary_report"] = str(summary_path)
        counts["gap_report"] = str(gaps_path)
    return counts


def _assess_level(
    *,
    level: int,
    assignment: AddressAssignment,
    state_code: str | None,
    members: list[dict[str, Any]],
    benchmark_tax_types: set[int],
    fact_maps_by_route: dict[tuple[int, int], list[TaxFactBenchmarkMap]],
    cited_crosswalk_routes: set[tuple[int, int]],
    filing_maps: list[TaxFilingMap],
    recipient_maps: list[TaxFilingMap],
) -> dict[str, Any]:
    tax_types = sorted(benchmark_tax_types)
    federal = level == 0
    jurisdiction_resolved = federal or bool(members)
    boundary_ready = federal or (
        assignment.status == "resolved_core" and assignment.calculation_ready
    )
    public_covered = sorted(
        tax_type
        for tax_type in tax_types
        if any(
            _fact_map_applies(mapping, state_code, assignment.benchmark_p_code)
            for mapping in fact_maps_by_route.get((level, tax_type), [])
        )
        or (level, tax_type) in cited_crosswalk_routes
    )
    filing_covered = sorted(
        tax_type
        for tax_type in tax_types
        if any(
            _filing_map_applies(
                mapping,
                tax_type=tax_type,
                state_code=state_code,
                p_code=assignment.benchmark_p_code,
            )
            for mapping in filing_maps
        )
    )
    recipient_only = sorted(
        tax_type
        for tax_type in tax_types
        if tax_type not in filing_covered
        and any(
            _filing_map_applies(
                mapping,
                tax_type=tax_type,
                state_code=state_code,
                p_code=assignment.benchmark_p_code,
            )
            for mapping in recipient_maps
        )
    )
    missing_public = sorted(set(tax_types) - set(public_covered))
    missing_filing = sorted(set(tax_types) - set(filing_covered))
    gaps: list[str] = []
    if not jurisdiction_resolved:
        gaps.append("JURISDICTION_UNRESOLVED")
    if not boundary_ready:
        gaps.append("TAX_BOUNDARY_UNVERIFIED")
    if not federal and assignment.benchmark_p_code is None:
        gaps.append("NO_BENCHMARK_PCODE")
    elif not tax_types:
        gaps.append("NO_REVIEWED_NO_TAX_DETERMINATION")
    if missing_public:
        gaps.append("MISSING_PUBLIC_RULES")
    if missing_filing:
        gaps.append("MISSING_FILING_ROUTES")
    if gaps:
        status = "partial" if jurisdiction_resolved and tax_types else "manual_required"
    else:
        status = "complete"
    return {
        "level": level,
        "name": LEVEL_NAMES[level],
        "status": status,
        "manual_required": bool(gaps),
        "jurisdiction_resolved": jurisdiction_resolved,
        "jurisdictions": (
            [{"role": "federal", "external_key": "federal:usa", "name": "United States"}]
            if federal
            else sorted(members, key=lambda item: (item["role"], item["external_key"]))
        ),
        "boundary_ready": boundary_ready,
        "benchmark_tax_type_count": len(tax_types),
        "benchmark_tax_types": tax_types,
        "public_rule_covered_count": len(public_covered),
        "public_rule_tax_types": public_covered,
        "missing_public_rule_tax_types": missing_public,
        "filing_covered_count": len(filing_covered),
        "filing_tax_types": filing_covered,
        "recipient_only_tax_types": recipient_only,
        "missing_filing_tax_types": missing_filing,
        "gap_codes": gaps,
    }


def _fact_map_applies(
    mapping: TaxFactBenchmarkMap,
    state_code: str | None,
    p_code: int | None,
) -> bool:
    return (
        mapping.state_code in (None, state_code)
        and mapping.p_code in (None, p_code)
    )


def _filing_map_applies(
    mapping: TaxFilingMap,
    *,
    tax_type: int,
    state_code: str | None,
    p_code: int | None,
) -> bool:
    return (
        mapping.benchmark_tax_type in (None, tax_type)
        and mapping.state_code in (None, state_code)
        and mapping.p_code in (None, p_code)
    )


def _resolved_state(
    members_by_level: dict[int, list[dict[str, Any]]], fallback: str | None
) -> str | None:
    for member in members_by_level.get(1, []):
        external_key = member["external_key"]
        if external_key.startswith("state:"):
            return external_key.split(":", 1)[1]
    return fallback


def _report_row(
    *,
    assignment: AddressAssignment,
    profile: LocationProfile | None,
    snapshot: LocationAssessment,
) -> dict[str, Any]:
    row: dict[str, Any] = {
        "assessment_date": str(snapshot.assessment_date),
        "source_address_id": assignment.source_address_id,
        "new_address": snapshot.is_new_address,
        "new_jurisdiction_profile": snapshot.is_new_profile,
        "assessment_changed": snapshot.assessment_changed,
        "profile_changed": snapshot.profile_changed,
        "state": snapshot.state_code or "",
        "postal_code": snapshot.postal_code or "",
        "plus_four": snapshot.plus_four or "",
        "ctd_profile_code": profile.profile_code if profile else "",
        "benchmark_p_code": snapshot.benchmark_p_code or "",
        "resolver_status": snapshot.resolver_status,
        "resolver_confidence": snapshot.resolver_confidence,
        "location_calculation_ready": snapshot.location_calculation_ready,
        "assessment_complete": snapshot.assessment_complete,
        "manual_gap_levels": ",".join(str(value) for value in snapshot.manual_gap_levels or []),
        "gap_count": snapshot.gap_count,
    }
    for level in range(4):
        detail = snapshot.level_details[str(level)]
        row[f"level_{level}_status"] = detail["status"]
        row[f"level_{level}_gaps"] = ",".join(detail["gap_codes"])
        row[f"level_{level}_benchmark_types"] = ",".join(
            str(value) for value in detail["benchmark_tax_types"]
        )
        row[f"level_{level}_missing_public_types"] = ",".join(
            str(value) for value in detail["missing_public_rule_tax_types"]
        )
        row[f"level_{level}_missing_filing_types"] = ",".join(
            str(value) for value in detail["missing_filing_tax_types"]
        )
    return row


def write_location_assessment_report(
    output_dir: Path,
    *,
    run_id: int,
    counts: dict[str, Any],
    report_rows: list[dict[str, Any]],
) -> tuple[Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    summary_path = output_dir / "location-assessment-summary.json"
    gaps_path = output_dir / "location-assessment-gaps.csv"
    summary_path.write_text(
        json.dumps(
            {
                "run_id": run_id,
                "generated_at": utcnow().isoformat(),
                "summary": counts,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )
    fieldnames = list(report_rows[0]) if report_rows else [
        "assessment_date",
        "source_address_id",
        "assessment_complete",
    ]
    with gaps_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(
            sorted(
                (row for row in report_rows if not row["assessment_complete"]),
                key=lambda row: (
                    not row["new_address"],
                    not row["assessment_changed"],
                    row["state"],
                    row["source_address_id"],
                ),
            )
        )
    return summary_path, gaps_path


def latest_location_assessment_data(
    session: Session,
    *,
    state: str | None = None,
    new_only: bool = False,
    manual_only: bool = True,
    limit: int = 1000,
) -> dict[str, Any]:
    latest_run = session.scalar(
        select(LocationAssessment.assessment_run_id)
        .order_by(LocationAssessment.assessment_run_id.desc())
        .limit(1)
    )
    if latest_run is None:
        return {
            "run_id": None,
            "summary": _empty_summary(),
            "levels": [],
            "gap_codes": [],
            "addresses": [],
        }
    all_rows = list(
        session.scalars(
            select(LocationAssessment)
            .where(LocationAssessment.assessment_run_id == latest_run)
            .order_by(
                LocationAssessment.is_new_address.desc(),
                LocationAssessment.assessment_complete,
                LocationAssessment.gap_count.desc(),
                LocationAssessment.state_code,
                LocationAssessment.source_address_id,
            )
        )
    )
    profiles = {
        item.id: item.profile_code
        for item in session.scalars(
            select(LocationProfile).where(
                LocationProfile.id.in_(
                    {
                        row.location_profile_id
                        for row in all_rows
                        if row.location_profile_id is not None
                    }
                )
            )
        )
    }
    level_totals = {
        level: {
            "level": level,
            "name": LEVEL_NAMES[level],
            "addresses": len(all_rows),
            "jurisdiction_resolved": 0,
            "boundary_ready": 0,
            "benchmark_tax_routes": 0,
            "public_rule_routes": 0,
            "filing_routes": 0,
            "manual_required": 0,
            "complete": 0,
        }
        for level in range(4)
    }
    gap_codes: Counter[tuple[int, str]] = Counter()
    for row in all_rows:
        for level in range(4):
            detail = row.level_details[str(level)]
            target = level_totals[level]
            target["jurisdiction_resolved"] += int(detail["jurisdiction_resolved"])
            target["boundary_ready"] += int(detail["boundary_ready"])
            target["benchmark_tax_routes"] += detail["benchmark_tax_type_count"]
            target["public_rule_routes"] += detail["public_rule_covered_count"]
            target["filing_routes"] += detail["filing_covered_count"]
            target["manual_required"] += int(detail["manual_required"])
            target["complete"] += int(detail["status"] == "complete")
            gap_codes.update((level, code) for code in detail["gap_codes"])
    filtered = all_rows
    if state:
        filtered = [row for row in filtered if row.state_code == state.upper()]
    if new_only:
        filtered = [row for row in filtered if row.is_new_address]
    if manual_only:
        filtered = [row for row in filtered if not row.assessment_complete]
    addresses = [
        {
            "source_address_id": row.source_address_id,
            "new_address": row.is_new_address,
            "new_jurisdiction_profile": row.is_new_profile,
            "assessment_changed": row.assessment_changed,
            "profile_changed": row.profile_changed,
            "state": row.state_code,
            "postal_code": row.postal_code,
            "plus_four": row.plus_four,
            "ctd_profile_code": profiles.get(row.location_profile_id),
            "benchmark_p_code": row.benchmark_p_code,
            "resolver_status": row.resolver_status,
            "resolver_confidence": row.resolver_confidence,
            "location_calculation_ready": row.location_calculation_ready,
            "assessment_complete": row.assessment_complete,
            "manual_gap_levels": row.manual_gap_levels,
            "gap_count": row.gap_count,
            "levels": row.level_details,
        }
        for row in filtered[:limit]
    ]
    return {
        "run_id": latest_run,
        "assessment_date": all_rows[0].assessment_date if all_rows else None,
        "summary": {
            "addresses_assessed": len(all_rows),
            "new_addresses": sum(row.is_new_address for row in all_rows),
            "new_jurisdiction_profiles": sum(row.is_new_profile for row in all_rows),
            "changed_assessments": sum(row.assessment_changed for row in all_rows),
            "profile_changes": sum(row.profile_changed for row in all_rows),
            "complete_assessments": sum(row.assessment_complete for row in all_rows),
            "manual_coverage_required": sum(not row.assessment_complete for row in all_rows),
        },
        "levels": [level_totals[level] for level in range(4)],
        "gap_codes": [
            {"level": level, "code": code, "count": count}
            for (level, code), count in sorted(
                gap_codes.items(), key=lambda item: (-item[1], item[0])
            )
        ],
        "addresses": addresses,
    }


def _empty_summary() -> dict[str, int]:
    return {
        "addresses_assessed": 0,
        "new_addresses": 0,
        "new_jurisdiction_profiles": 0,
        "changed_assessments": 0,
        "profile_changes": 0,
        "complete_assessments": 0,
        "manual_coverage_required": 0,
    }
