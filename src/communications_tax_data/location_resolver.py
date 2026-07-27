from __future__ import annotations

import hashlib
import json
import re
import time
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from communications_tax_data.collectors.base import (
    CollectionStats,
    finish_run,
    get_or_create_source,
    get_with_retry,
    http_client,
    start_run,
)
from communications_tax_data.config import get_settings
from communications_tax_data.models import (
    AddressAssignment,
    BenchmarkJurisdiction,
    Jurisdiction,
    LocationProfile,
    LocationProfileMember,
    SourceCheck,
    utcnow,
)

CENSUS_GEOCODER_URL = "https://geocoding.geo.census.gov/geocoder/"
CENSUS_BENCHMARK = "Public_AR_Current"
CENSUS_VINTAGE = "Current_Current"
SOURCE_SYSTEM = "apeiron_service_address"
SOURCING_ROLE = "service_address"


@dataclass(frozen=True)
class ResolverAddress:
    source_address_id: int
    street: str | None
    city: str | None
    state_code: str | None
    postal_code: str | None
    plus_four: str | None = None
    suite: str | None = None
    country_iso: str = "USA"
    latitude: Decimal | None = None
    longitude: Decimal | None = None
    benchmark_p_code: int | None = None

    @classmethod
    def from_mapping(cls, row: dict[str, Any]) -> ResolverAddress:
        street = _clean(row.get("street1")) or " ".join(
            value
            for value in (
                _clean(row.get("housenumber")),
                _clean(row.get("predirectional")),
                _clean(row.get("streetname")),
            )
            if value
        )
        country = (_clean(row.get("country")) or "USA").upper()
        if country == "US":
            country = "USA"
        return cls(
            source_address_id=int(row["source_address_id"]),
            street=street or None,
            city=_clean(row.get("city")) or _clean(row.get("muni")),
            state_code=(_clean(row.get("state_code")) or "").upper() or None,
            postal_code=_postal5(row.get("postal_code")),
            plus_four=_plus4(row.get("plus_four")),
            suite=_clean(row.get("suite")) or _clean(row.get("street2")),
            country_iso=country,
            latitude=_decimal(row.get("latitude")),
            longitude=_decimal(row.get("longitude")),
            benchmark_p_code=_integer(row.get("benchmark_p_code")),
        )

    def fingerprint(self) -> str:
        payload = {
            "street": _normalize_address_part(self.street),
            "suite": _normalize_address_part(self.suite),
            "city": _normalize_address_part(self.city),
            "state": (self.state_code or "").upper(),
            "postal_code": self.postal_code or "",
            "plus_four": self.plus_four or "",
            "country": self.country_iso,
            "latitude": str(self.latitude) if self.latitude is not None else "",
            "longitude": str(self.longitude) if self.longitude is not None else "",
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()

    def one_line(self) -> str | None:
        if not self.street or not self.city or not self.state_code or not self.postal_code:
            return None
        postal = self.postal_code
        if self.plus_four:
            postal = f"{postal}-{self.plus_four}"
        return f"{self.street}, {self.city}, {self.state_code} {postal}"


@dataclass(frozen=True)
class GeographyMember:
    role: str
    external_key: str
    name: str
    tax_level: int
    state_code: str
    fips_code: str
    parent_external_key: str | None
    geography_kind: str


@dataclass(frozen=True)
class Resolution:
    status: str
    method: str
    confidence: str
    members: tuple[GeographyMember, ...] = ()
    latitude: Decimal | None = None
    longitude: Decimal | None = None
    evidence: dict[str, Any] | None = None


class CensusGeocoder:
    """Resolve core Census geographies without treating them as tax authority data."""

    def __init__(self, client: httpx.Client | None = None) -> None:
        self.client = client or http_client()
        self._owns_client = client is None
        self.requests = 0

    def close(self) -> None:
        if self._owns_client:
            self.client.close()

    def __call__(self, address: ResolverAddress) -> Resolution:
        if _valid_coordinates(address.latitude, address.longitude):
            coordinate_result = self._coordinates(address)
            resolved_state = next(
                (
                    member.state_code
                    for member in coordinate_result.members
                    if member.role == "state"
                ),
                None,
            )
            coordinate_agrees = not address.state_code or resolved_state == address.state_code
            if coordinate_result.status == "resolved_core" and coordinate_agrees:
                return coordinate_result
            one_line = address.one_line()
            if one_line:
                fallback = self._address_range(one_line)
                evidence = dict(fallback.evidence or {})
                evidence["coordinate_fallback"] = (
                    "state_mismatch" if not coordinate_agrees else "geography_unmatched"
                )
                return Resolution(
                    status=fallback.status,
                    method=fallback.method,
                    confidence=fallback.confidence,
                    members=fallback.members,
                    latitude=fallback.latitude,
                    longitude=fallback.longitude,
                    evidence=evidence,
                )
            return coordinate_result
        one_line = address.one_line()
        if not one_line:
            return Resolution(
                status="insufficient_input",
                method="census_geocoder_not_called",
                confidence="none",
                evidence={"has_street": bool(address.street), "has_coordinates": False},
            )
        return self._address_range(one_line)

    def _coordinates(self, address: ResolverAddress) -> Resolution:
        params = {
            "x": str(address.longitude),
            "y": str(address.latitude),
            "benchmark": CENSUS_BENCHMARK,
            "vintage": CENSUS_VINTAGE,
            "format": "json",
        }
        payload = self._get("geographies/coordinates", params)
        geographies = payload.get("result", {}).get("geographies", {})
        return _resolution_from_geographies(
            geographies,
            method="census_coordinate_geographies",
            confidence="coordinate",
            latitude=address.latitude,
            longitude=address.longitude,
            evidence={"match_count": 1, "input_mode": "coordinates"},
        )

    def _address_range(self, one_line: str) -> Resolution:
        params = {
            "address": one_line,
            "benchmark": CENSUS_BENCHMARK,
            "vintage": CENSUS_VINTAGE,
            "format": "json",
        }
        payload = self._get("geographies/onelineaddress", params)
        matches = payload.get("result", {}).get("addressMatches", [])
        if not matches:
            return Resolution(
                status="unmatched",
                method="census_address_range",
                confidence="none",
                evidence={"match_count": 0, "input_mode": "street_address"},
            )
        candidates = [
            _resolution_from_geographies(
                match.get("geographies", {}),
                method="census_address_range",
                confidence="address_range",
                latitude=_decimal(match.get("coordinates", {}).get("y")),
                longitude=_decimal(match.get("coordinates", {}).get("x")),
                evidence={
                    "match_count": len(matches),
                    "input_mode": "street_address",
                    "tiger_line_id": match.get("tigerLine", {}).get("tigerLineId"),
                },
            )
            for match in matches
        ]
        signatures = {
            tuple(sorted(member.external_key for member in candidate.members))
            for candidate in candidates
        }
        if len(signatures) > 1:
            return Resolution(
                status="ambiguous",
                method="census_address_range",
                confidence="none",
                evidence={"match_count": len(matches), "input_mode": "street_address"},
            )
        return candidates[0]

    def _get(self, path: str, params: dict[str, str]) -> dict[str, Any]:
        request = self.client.build_request("GET", f"{CENSUS_GEOCODER_URL}{path}", params=params)
        self.requests += 1
        response = get_with_retry(self.client, str(request.url))
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("Census Geocoder returned a non-object response")
        return payload


def load_active_service_addresses(*, limit: int | None = None) -> list[ResolverAddress]:
    """Load distinct active service addresses without copying customer identities."""
    engine = create_engine(get_settings().benchmark_url(), pool_pre_ping=True, future=True)
    sql = text(
        """
        SELECT DISTINCT
               a.id AS source_address_id,
               a.housenumber,
               a.predirectional,
               a.streetname,
               a.street1,
               a.street2,
               a.suite,
               a.city,
               a.muni,
               LEFT(TRIM(a.state), 8) AS state_code,
               LEFT(TRIM(a.postal_code), 10) AS postal_code,
               LEFT(TRIM(a.plus_four), 4) AS plus_four,
               a.country,
               a.lat AS latitude,
               a.lon AS longitude,
               a.p_code AS benchmark_p_code
        FROM apeiron_apeironaddress a
        INNER JOIN apeiron_apeironcustomer c ON c.service_address_id = a.id
        WHERE c.closed = 0
          AND c.test_account = 0
          AND c.generate_invoices = 1
          AND UPPER(COALESCE(NULLIF(TRIM(a.country), ''), 'USA')) IN ('US', 'USA')
        ORDER BY a.id
        """
    )
    try:
        with engine.connect() as connection:
            rows = connection.execute(sql).mappings()
            addresses = [ResolverAddress.from_mapping(dict(row)) for row in rows]
    finally:
        engine.dispose()
    return addresses[:limit] if limit is not None else addresses


def resolve_priority_locations(
    session: Session,
    *,
    force: bool = False,
    limit: int | None = None,
    addresses: Iterable[ResolverAddress | dict[str, Any]] | None = None,
    geocoder: Callable[[ResolverAddress], Resolution] | None = None,
    retire_missing: bool | None = None,
) -> dict[str, Any]:
    """Resolve active service addresses to deterministic CTD jurisdiction profiles."""
    externally_supplied_addresses = addresses is not None
    if addresses is None:
        address_rows = load_active_service_addresses(limit=limit)
    else:
        address_rows = [
            item if isinstance(item, ResolverAddress) else ResolverAddress.from_mapping(item)
            for item in addresses
        ]
        if limit is not None:
            address_rows = address_rows[:limit]
    if retire_missing is None:
        retire_missing = not externally_supplied_addresses and limit is None
    source, source_created = get_or_create_source(
        session,
        code="census-geocoder-current",
        name="Census Geocoder Current Geographies",
        publisher="U.S. Census Bureau",
        source_type="address_geocoder",
        url=CENSUS_GEOCODER_URL,
        parser="location-resolver-census-v1",
        cadence_days=30,
        authoritative=False,
        notes=(
            "Official Census address-range and coordinate geography lookup. It identifies "
            "core Census geography but is not a rooftop tax-jurisdiction or tax-authority source."
        ),
    )
    run = start_run(session, "location-resolver-v1")
    stats = CollectionStats(sources=1, seen=len(address_rows))
    counts: dict[str, Any] = {
        "addresses_seen": len(address_rows),
        "addresses_skipped_unchanged": 0,
        "geocoder_requests": 0,
        "resolved_core": 0,
        "unmatched": 0,
        "ambiguous": 0,
        "insufficient_input": 0,
        "errors": 0,
        "profiles_inserted": 0,
        "profiles_reused": 0,
        "assignments_inserted": 0,
        "assignments_refreshed": 0,
        "assignments_superseded": 0,
        "assignments_retired": 0,
        "assignments_preserved_on_error": 0,
        "benchmark_state_match": 0,
        "benchmark_state_mismatch": 0,
        "benchmark_county_match": 0,
        "benchmark_county_mismatch": 0,
        "benchmark_locality_match": 0,
        "benchmark_locality_mismatch": 0,
        "calculation_ready": 0,
    }
    if source_created:
        stats.inserted += 1

    owned_geocoder = geocoder is None
    census_geocoder = CensusGeocoder() if owned_geocoder else None
    resolver = census_geocoder if census_geocoder is not None else geocoder
    assert resolver is not None
    started = time.monotonic()
    run_cache: dict[str, Resolution] = {}
    current_rows = {
        (row.source_address_id, row.sourcing_role): row
        for row in session.scalars(
            select(AddressAssignment).where(
                AddressAssignment.source_system == SOURCE_SYSTEM,
                AddressAssignment.valid_to.is_(None),
            )
        )
    }
    seen_assignment_keys: set[tuple[int, str]] = set()
    try:
        for address in address_rows:
            assignment_key = (address.source_address_id, SOURCING_ROLE)
            seen_assignment_keys.add(assignment_key)
            fingerprint = address.fingerprint()
            current = current_rows.get(assignment_key)
            if (
                current is not None
                and current.address_fingerprint == fingerprint
                and current.benchmark_p_code == address.benchmark_p_code
                and current.status != "error"
                and not force
            ):
                counts["addresses_skipped_unchanged"] += 1
                continue

            try:
                resolution = run_cache.get(fingerprint)
                if resolution is None:
                    resolution = resolver(address)
                    run_cache[fingerprint] = resolution
            except (httpx.HTTPError, ValueError, KeyError, TypeError) as error:
                resolution = Resolution(
                    status="error",
                    method="census_geocoder_error",
                    confidence="none",
                    evidence={"error_type": type(error).__name__},
                )

            if resolution.status == "error" and current is not None:
                counts["errors"] += 1
                counts["assignments_preserved_on_error"] += 1
                continue

            profile = None
            profile_created = False
            if resolution.status == "resolved_core":
                jurisdictions = [
                    _get_or_create_jurisdiction(session, source.id, member)
                    for member in resolution.members
                ]
                profile, profile_created = _get_or_create_profile(
                    session, jurisdictions, resolution.members
                )
                counts["profiles_inserted" if profile_created else "profiles_reused"] += 1

            benchmark = _benchmark_comparison(
                session,
                address.benchmark_p_code,
                resolution.members,
            )
            for field in ("state", "county", "locality"):
                value = benchmark.get(f"{field}_match")
                if value is not None:
                    counts[f"benchmark_{field}_{'match' if value else 'mismatch'}"] += 1

            evidence = dict(resolution.evidence or {})
            evidence.update(
                {
                    "resolver_version": 1,
                    "collection_run_id": run.id,
                    "census_benchmark": CENSUS_BENCHMARK,
                    "census_vintage": CENSUS_VINTAGE,
                    "jurisdiction_external_keys": [
                        member.external_key for member in resolution.members
                    ],
                    "benchmark_comparison": benchmark,
                }
            )
            assignment, action = _upsert_assignment(
                session,
                current=current,
                address=address,
                fingerprint=fingerprint,
                resolution=resolution,
                profile=profile,
                source_id=source.id,
                evidence=evidence,
            )
            current_rows[assignment_key] = assignment
            counts[f"assignments_{action}"] += 1
            counts[resolution.status if resolution.status in counts else "errors"] += 1
            stats.inserted += int(action in {"inserted", "superseded"}) + int(profile_created)
            stats.updated += int(action in {"refreshed", "superseded"})
        if retire_missing:
            retired_at = utcnow()
            for assignment_key, current in current_rows.items():
                if assignment_key not in seen_assignment_keys and current.valid_to is None:
                    current.valid_to = retired_at
                    counts["assignments_retired"] += 1
                    stats.updated += 1
    finally:
        if census_geocoder is not None:
            counts["geocoder_requests"] = census_geocoder.requests
            census_geocoder.close()

    now = utcnow()
    source.last_checked_at = now
    assignments_changed = bool(
        counts["assignments_inserted"]
        or counts["assignments_superseded"]
        or counts["assignments_retired"]
    )
    if assignments_changed:
        source.last_changed_at = now
    session.add(
        SourceCheck(
            source_id=source.id,
            run_id=run.id,
            checked_at=now,
            status_code=200 if counts["errors"] == 0 else None,
            changed=assignments_changed,
            elapsed_ms=round((time.monotonic() - started) * 1000),
            error=(f"{counts['errors']} address lookup errors" if counts["errors"] else None),
        )
    )
    stats.details = counts
    finish_run(run, stats, status="partial" if counts["errors"] else "success")
    counts["collection_run_id"] = run.id
    return counts


def _resolution_from_geographies(
    geographies: dict[str, Any],
    *,
    method: str,
    confidence: str,
    latitude: Decimal | None,
    longitude: Decimal | None,
    evidence: dict[str, Any],
) -> Resolution:
    state = _first(geographies, "States")
    county = _first(geographies, "Counties")
    place = _first(geographies, "Incorporated Places")
    subdivision = _first(geographies, "County Subdivisions")
    cdp = _first(geographies, "Census Designated Places")
    members: list[GeographyMember] = []
    state_code = (_clean(state.get("STUSAB")) if state else None) or ""
    state_geoid = (_clean(state.get("GEOID")) if state else None) or ""
    if state and state_code and state_geoid:
        members.append(
            GeographyMember(
                role="state",
                external_key=f"state:{state_code}",
                name=_geography_name(state),
                tax_level=1,
                state_code=state_code,
                fips_code=state_geoid,
                parent_external_key=None,
                geography_kind="state",
            )
        )
    county_key = None
    if county and state_code and county.get("GEOID"):
        county_geoid = str(county["GEOID"])
        county_key = f"census:county:{county_geoid}"
        members.append(
            GeographyMember(
                role="county",
                external_key=county_key,
                name=_geography_name(county),
                tax_level=2,
                state_code=state_code,
                fips_code=county_geoid,
                parent_external_key=f"state:{state_code}",
                geography_kind="county",
            )
        )
    if place and state_code and place.get("GEOID"):
        geoid = str(place["GEOID"])
        members.append(
            GeographyMember(
                role="incorporated_place",
                external_key=f"census:place:{geoid}",
                name=_geography_name(place),
                tax_level=3,
                state_code=state_code,
                fips_code=geoid,
                parent_external_key=f"state:{state_code}",
                geography_kind="incorporated_place",
            )
        )
    if subdivision and state_code and subdivision.get("GEOID"):
        geoid = str(subdivision["GEOID"])
        members.append(
            GeographyMember(
                role="county_subdivision",
                external_key=f"census:county-subdivision:{geoid}",
                name=_geography_name(subdivision),
                tax_level=3,
                state_code=state_code,
                fips_code=geoid,
                parent_external_key=county_key,
                geography_kind="county_subdivision",
            )
        )
    evidence = dict(evidence)
    if cdp:
        evidence["census_designated_place"] = {
            "geoid": cdp.get("GEOID"),
            "name": _geography_name(cdp),
            "excluded_from_taxing_membership": True,
        }
    status = "resolved_core" if state and county else "unmatched"
    return Resolution(
        status=status,
        method=method,
        confidence=confidence if status == "resolved_core" else "none",
        members=tuple(members) if status == "resolved_core" else (),
        latitude=latitude,
        longitude=longitude,
        evidence=evidence,
    )


def _get_or_create_jurisdiction(
    session: Session, source_id: int, member: GeographyMember
) -> Jurisdiction:
    jurisdiction = session.scalar(
        select(Jurisdiction)
        .where(
            Jurisdiction.external_key == member.external_key,
            Jurisdiction.valid_to.is_(None),
        )
        .order_by(Jurisdiction.valid_from.desc())
    )
    if jurisdiction is None:
        jurisdiction = Jurisdiction(
            external_key=member.external_key,
            valid_from=date(1900, 1, 1) if member.role == "state" else date(2020, 1, 1),
            source_id=source_id,
        )
        session.add(jurisdiction)
    jurisdiction.country_iso = "USA"
    jurisdiction.tax_level = member.tax_level
    jurisdiction.name = member.name
    jurisdiction.state_code = member.state_code
    jurisdiction.fips_code = member.fips_code
    jurisdiction.parent_external_key = member.parent_external_key
    if member.role == "county":
        jurisdiction.county_name = member.name
    elif member.tax_level == 3:
        jurisdiction.locality_name = member.name
    metadata = dict(jurisdiction.metadata_json or {})
    metadata.update(
        {
            "geography_kind": member.geography_kind,
            "observed_by": "census_geocoder_current",
            "tax_authority_status": "not_determined",
        }
    )
    jurisdiction.metadata_json = metadata
    session.flush()
    return jurisdiction


def _get_or_create_profile(
    session: Session,
    jurisdictions: list[Jurisdiction],
    members: tuple[GeographyMember, ...],
) -> tuple[LocationProfile, bool]:
    member_pairs = sorted((member.role, member.external_key) for member in members)
    payload = {"schema": "ctd-jurisdiction-set-v1", "members": member_pairs}
    composition = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    profile_code = f"CTD-JUR-{composition[:20].upper()}"
    profile = session.scalar(
        select(LocationProfile).where(LocationProfile.profile_code == profile_code)
    )
    created = profile is None
    if profile is None:
        state_codes = {member.state_code for member in members if member.state_code}
        profile = LocationProfile(
            profile_code=profile_code,
            composition_sha256=composition,
            country_iso="USA",
            state_code=next(iter(state_codes)) if len(state_codes) == 1 else None,
            assignment_method="deterministic Census core jurisdiction set v1",
            confidence="address_range",
            calculation_ready=False,
            status="resolved_core",
            valid_from=date.today(),
        )
        session.add(profile)
        session.flush()
        by_key = {jurisdiction.external_key: jurisdiction for jurisdiction in jurisdictions}
        for member in members:
            session.add(
                LocationProfileMember(
                    location_profile_id=profile.id,
                    jurisdiction_id=by_key[member.external_key].id,
                    member_role=member.role,
                    evidence={
                        "source": "census_geocoder_current",
                        "geography_kind": member.geography_kind,
                    },
                )
            )
    return profile, created


def _upsert_assignment(
    session: Session,
    *,
    current: AddressAssignment | None,
    address: ResolverAddress,
    fingerprint: str,
    resolution: Resolution,
    profile: LocationProfile | None,
    source_id: int,
    evidence: dict[str, Any],
) -> tuple[AddressAssignment, str]:
    now = utcnow()
    profile_id = profile.id if profile else None
    result_changed = current is not None and (
        current.address_fingerprint != fingerprint
        or current.location_profile_id != profile_id
        or current.status != resolution.status
        or current.assignment_method != resolution.method
        or current.confidence != resolution.confidence
    )
    if current is not None and not result_changed:
        current.resolved_at = now
        current.source_id = source_id
        current.evidence = evidence
        current.benchmark_p_code = address.benchmark_p_code
        current.latitude = resolution.latitude
        current.longitude = resolution.longitude
        return current, "refreshed"
    if current is not None:
        current.valid_to = now
        action = "superseded"
        evidence = dict(evidence)
        evidence["previous_assignment_id"] = current.id
    else:
        action = "inserted"
    assignment = AddressAssignment(
        source_system=SOURCE_SYSTEM,
        source_address_id=address.source_address_id,
        sourcing_role=SOURCING_ROLE,
        address_fingerprint=fingerprint,
        country_iso=address.country_iso,
        state_code=address.state_code,
        postal_code=address.postal_code,
        plus_four=address.plus_four,
        latitude=resolution.latitude,
        longitude=resolution.longitude,
        location_profile_id=profile_id,
        benchmark_p_code=address.benchmark_p_code,
        source_id=source_id,
        assignment_method=resolution.method,
        confidence=resolution.confidence,
        calculation_ready=False,
        status=resolution.status,
        evidence=evidence,
        valid_from=now,
        resolved_at=now,
    )
    session.add(assignment)
    session.flush()
    return assignment, action


def _benchmark_comparison(
    session: Session,
    p_code: int | None,
    members: tuple[GeographyMember, ...],
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "p_code_present": p_code is not None,
        "state_match": None,
        "county_match": None,
        "locality_match": None,
    }
    if p_code is None:
        return result
    benchmark = session.scalar(
        select(BenchmarkJurisdiction)
        .where(BenchmarkJurisdiction.p_code == p_code)
        .order_by(BenchmarkJurisdiction.alternate.asc(), BenchmarkJurisdiction.benchmark_id)
    )
    if benchmark is None:
        result["benchmark_row_present"] = False
        return result
    result["benchmark_row_present"] = True
    state = next((member for member in members if member.role == "state"), None)
    county = next((member for member in members if member.role == "county"), None)
    localities = [
        member for member in members if member.role in {"incorporated_place", "county_subdivision"}
    ]
    if state:
        result["state_match"] = (
            state.state_code.casefold() == (benchmark.state_code or "").casefold()
        )
    if county:
        result["county_match"] = _county_names_match(county.name, benchmark.county_name)
    if benchmark.locality_name and localities:
        result["locality_match"] = any(
            _normalize_jurisdiction_name(member.name)
            == _normalize_jurisdiction_name(benchmark.locality_name)
            for member in localities
        )
    return result


def _first(geographies: dict[str, Any], key: str) -> dict[str, Any] | None:
    rows = geographies.get(key) or []
    return rows[0] if rows and isinstance(rows[0], dict) else None


def _geography_name(row: dict[str, Any]) -> str:
    return _clean(row.get("NAME")) or _clean(row.get("BASENAME")) or "Unknown"


def _normalize_jurisdiction_name(value: Any) -> str:
    text_value = str(value or "").casefold().replace("’", "'").replace("'", "")
    text_value = re.sub(r"[^a-z0-9 ]", " ", text_value)
    words = [
        "st" if word == "saint" else word
        for word in text_value.split()
        if word
        not in {
            "county",
            "parish",
            "borough",
            "city",
            "town",
            "village",
            "township",
            "cdp",
            "planning",
            "region",
        }
    ]
    return "".join(words)


def _county_names_match(left: Any, right: Any) -> bool:
    left_name = _normalize_jurisdiction_name(left)
    right_name = _normalize_jurisdiction_name(right)
    if left_name == right_name:
        return True
    # Dade County formally became Miami-Dade County; Avalara still uses both labels.
    return {left_name, right_name} == {"dade", "miamidade"}


def _normalize_address_part(value: Any) -> str:
    return " ".join(str(value or "").strip().casefold().split())


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    cleaned = " ".join(str(value).strip().split())
    return cleaned or None


def _postal5(value: Any) -> str | None:
    match = re.search(r"\d{5}", str(value or ""))
    return match.group(0) if match else None


def _plus4(value: Any) -> str | None:
    digits = re.sub(r"\D", "", str(value or ""))
    return digits[:4] if len(digits) >= 4 else None


def _decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _integer(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _valid_coordinates(latitude: Decimal | None, longitude: Decimal | None) -> bool:
    return bool(
        latitude is not None
        and longitude is not None
        and Decimal("-90") <= latitude <= Decimal("90")
        and Decimal("-180") <= longitude <= Decimal("180")
        and not (latitude == 0 and longitude == 0)
    )
