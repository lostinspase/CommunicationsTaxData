from __future__ import annotations

import hashlib
import json
import re
from datetime import date

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from communications_tax_data.models import (
    CustomerTaxNeed,
    Jurisdiction,
    LocationProfile,
    LocationProfileMember,
    PostalAssignment,
)


def build_customer_location_profiles(
    session: Session, *, as_of: date | None = None
) -> dict[str, int]:
    """Build clearly labeled statistical CTD codes for priority customer locations."""
    effective_date = as_of or date.today()
    customers = list(session.scalars(select(CustomerTaxNeed)))
    assignments: dict[str, list[tuple[PostalAssignment, Jurisdiction]]] = {}
    rows = session.execute(
        select(PostalAssignment, Jurisdiction)
        .join(Jurisdiction, Jurisdiction.id == PostalAssignment.jurisdiction_id)
        .where(
            PostalAssignment.valid_from <= effective_date,
            (PostalAssignment.valid_to.is_(None) | (PostalAssignment.valid_to >= effective_date)),
        )
    )
    for assignment, jurisdiction in rows:
        assignments.setdefault(assignment.postal_code, []).append((assignment, jurisdiction))

    grouped: dict[tuple[str, str | None], list[CustomerTaxNeed]] = {}
    for customer in customers:
        if (
            customer.postal_code
            and re.fullmatch(r"\d{5}", customer.postal_code)
            and (customer.country_code or "").upper() in {"US", "USA"}
        ):
            grouped.setdefault((customer.postal_code, customer.plus_four or None), []).append(
                customer
            )

    counts = {
        "priority_location_keys": len(grouped),
        "profiles_inserted": 0,
        "profiles_refreshed": 0,
        "profiles_without_public_geography": 0,
        "ambiguous_profiles": 0,
        "calculation_ready_profiles": 0,
    }
    ordered_groups = sorted(grouped.items(), key=lambda item: (item[0][0], item[0][1] or ""))
    for (postal_code, plus_four), group in ordered_groups:
        candidates = assignments.get(postal_code, [])
        member_payload = sorted(
            {
                (
                    jurisdiction.external_key,
                    str(assignment.allocation_ratio)
                    if assignment.allocation_ratio is not None
                    else "",
                )
                for assignment, jurisdiction in candidates
            }
        )
        payload = {
            "country": "USA",
            "postal_code": postal_code,
            "plus_four": plus_four,
            "members": member_payload,
            "method": "2020 Census ZCTA candidate relationships",
        }
        composition = hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        profile_code = f"CTD-{composition[:20].upper()}"
        profile = session.scalar(
            select(LocationProfile).where(LocationProfile.profile_code == profile_code)
        )
        created = profile is None
        pcodes = {item.p_code for item in group if item.p_code is not None}
        states = {item.state_code for item in group if item.state_code}
        if profile is None:
            profile = LocationProfile(
                profile_code=profile_code,
                composition_sha256=composition,
                valid_from=date(2020, 1, 1),
                assignment_method="2020 Census ZCTA candidate relationships",
                confidence="statistical",
                calculation_ready=False,
                status="candidate",
            )
            session.add(profile)
            session.flush()
        profile.country_iso = "USA"
        profile.state_code = next(iter(states)) if len(states) == 1 else None
        profile.postal_code = postal_code
        profile.plus_four = plus_four
        profile.benchmark_p_code = next(iter(pcodes)) if len(pcodes) == 1 else None
        profile.valid_to = None
        profile.assignment_method = (
            "2020 Census ZCTA-to-county/place candidate set; not rooftop sourcing"
        )
        profile.confidence = "statistical"
        profile.calculation_ready = False
        profile.status = "candidate"
        counts["profiles_inserted" if created else "profiles_refreshed"] += 1
        if not candidates:
            counts["profiles_without_public_geography"] += 1
        levels = {}
        for _, jurisdiction in candidates:
            levels.setdefault(jurisdiction.tax_level, set()).add(jurisdiction.id)
        if any(len(values) > 1 for values in levels.values()):
            counts["ambiguous_profiles"] += 1

        session.execute(
            delete(LocationProfileMember).where(
                LocationProfileMember.location_profile_id == profile.id
            )
        )
        seen_jurisdictions: set[int] = set()
        for assignment, jurisdiction in candidates:
            if jurisdiction.id in seen_jurisdictions:
                continue
            seen_jurisdictions.add(jurisdiction.id)
            session.add(
                LocationProfileMember(
                    location_profile_id=profile.id,
                    jurisdiction_id=jurisdiction.id,
                    member_role="candidate",
                    allocation_ratio=assignment.allocation_ratio,
                    evidence={
                        "assignment_id": assignment.id,
                        "confidence": assignment.confidence,
                        "method": assignment.assignment_method,
                    },
                )
            )
    return counts
