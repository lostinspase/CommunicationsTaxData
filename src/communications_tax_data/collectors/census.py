from __future__ import annotations

import csv
import io
import time
from datetime import date
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from communications_tax_data.collectors.base import (
    CollectionStats,
    finish_run,
    get_or_create_source,
    get_with_retry,
    http_client,
    record_response,
    start_run,
)
from communications_tax_data.constants import STATE_FIPS_TO_ABBR
from communications_tax_data.models import Jurisdiction, PostalAssignment

COUNTY_URL = (
    "https://www2.census.gov/geo/docs/maps-data/data/rel2020/zcta520/"
    "tab20_zcta520_county20_natl.txt"
)
PLACE_URL = (
    "https://www2.census.gov/geo/docs/maps-data/data/rel2020/zcta520/"
    "tab20_zcta520_place20_natl.txt"
)


class CensusRelationshipCollector:
    name = "census-zcta-relationships"

    def collect(self, session: Session) -> CollectionStats:
        run = start_run(session, self.name)
        stats = CollectionStats()
        definitions = [
            ("county", 2, COUNTY_URL, "2020 Census ZCTA-to-county relationship file"),
            ("place", 3, PLACE_URL, "2020 Census ZCTA-to-place relationship file"),
        ]
        with http_client() as client:
            for kind, level, url, title in definitions:
                source, created = get_or_create_source(
                    session,
                    code=f"census-zcta-{kind}-2020",
                    name=title,
                    publisher="U.S. Census Bureau",
                    source_type="geographic_relationship",
                    url=url,
                    tax_level=level,
                    parser=self.name,
                    cadence_days=365,
                    authoritative=False,
                    notes=(
                        "ZCTA is a Census statistical approximation of USPS ZIP Codes. "
                        "It is not rooftop-level tax jurisdiction assignment."
                    ),
                )
                stats.inserted += int(created)
                started = time.monotonic()
                response = get_with_retry(client, url)
                response.raise_for_status()
                record_response(session, source=source, run=run, response=response, started=started)
                parsed = self._load_relationship(session, source, kind, response.content)
                stats.sources += 1
                stats.seen += parsed.seen
                stats.inserted += parsed.inserted
                stats.updated += parsed.updated
                session.flush()
        finish_run(run, stats)
        return stats

    @staticmethod
    def _load_relationship(session, source, kind: str, content: bytes) -> CollectionStats:
        stats = CollectionStats()
        text = content.decode("utf-8-sig")
        reader = csv.DictReader(io.StringIO(text), delimiter="|")
        suffix = "COUNTY_20" if kind == "county" else "PLACE_20"
        geoid_key = f"GEOID_{suffix}"
        name_key = f"NAMELSAD_{suffix}"
        total_key = "AREALAND_ZCTA5_20"
        part_key = "AREALAND_PART"
        valid_from = date(2020, 1, 1)
        existing_jurisdictions = {
            item.external_key: item
            for item in session.scalars(
                select(Jurisdiction).where(Jurisdiction.external_key.like(f"census:{kind}:%"))
            )
        }
        existing_assignments = {
            (item.postal_code, item.jurisdiction_id): item
            for item in session.scalars(
                select(PostalAssignment).where(
                    PostalAssignment.source_id == source.id,
                    PostalAssignment.valid_from == valid_from,
                )
            )
        }
        for row in reader:
            zcta = (row.get("GEOID_ZCTA5_20") or "").strip()
            geoid = (row.get(geoid_key) or "").strip()
            if not zcta or not geoid:
                continue
            stats.seen += 1
            state_fips = geoid[:2]
            state = STATE_FIPS_TO_ABBR.get(state_fips)
            if not state:
                continue
            external_key = f"census:{kind}:{geoid}"
            jurisdiction = existing_jurisdictions.get(external_key)
            if jurisdiction is None:
                name = (row.get(name_key) or geoid).strip()
                jurisdiction = Jurisdiction(
                    external_key=external_key,
                    country_iso="USA",
                    tax_level=2 if kind == "county" else 3,
                    name=name,
                    state_code=state,
                    county_name=name if kind == "county" else None,
                    locality_name=name if kind == "place" else None,
                    fips_code=geoid,
                    parent_external_key=(
                        f"fips:state:{state_fips}"
                        if kind == "county"
                        else f"fips:state:{state_fips}"
                    ),
                    valid_from=valid_from,
                    source_id=source.id,
                    metadata_json={"geography_kind": kind, "statistical": True},
                )
                session.add(jurisdiction)
                session.flush()
                existing_jurisdictions[external_key] = jurisdiction
                stats.inserted += 1
            total_land = Decimal((row.get(total_key) or "0").strip() or "0")
            part_land = Decimal((row.get(part_key) or "0").strip() or "0")
            allocation = part_land / total_land if total_land else None
            assignment = existing_assignments.get((zcta, jurisdiction.id))
            if assignment is None:
                assignment = PostalAssignment(
                    postal_code=zcta,
                    jurisdiction_id=jurisdiction.id,
                    allocation_ratio=allocation,
                    confidence="statistical",
                    assignment_method=f"2020 Census ZCTA-to-{kind} land-area intersection",
                    valid_from=valid_from,
                    source_id=source.id,
                )
                session.add(assignment)
                existing_assignments[(zcta, jurisdiction.id)] = assignment
                stats.inserted += 1
            elif assignment.allocation_ratio != allocation:
                assignment.allocation_ratio = allocation
                stats.updated += 1
        return stats
