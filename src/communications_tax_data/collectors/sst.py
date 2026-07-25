from __future__ import annotations

import csv
import hashlib
import io
import re
import time
import zipfile
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import PurePosixPath

from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.orm import Session

from communications_tax_data.collectors.base import (
    CollectionStats,
    finish_run,
    get_or_create_source,
    http_client,
    record_response,
    start_run,
)
from communications_tax_data.constants import STATE_FIPS_TO_ABBR, sst_level, sst_type_name
from communications_tax_data.models import Jurisdiction, TaxFact

RATE_DIRECTORY = "https://www.streamlinedsalestax.org/ratesandboundry/Rates/"
RATE_FILE_RE = re.compile(r"^(?P<state>[A-Z]{2})R[^/]*\.(?:csv|zip)$", re.IGNORECASE)


def _date(value: str):
    parsed = datetime.strptime(value.strip(), "%Y%m%d").date()
    return None if parsed.year >= 2999 else parsed


def _csv_bytes(content: bytes, filename: str) -> bytes:
    if filename.lower().endswith(".zip"):
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            members = [name for name in archive.namelist() if name.lower().endswith(".csv")]
            if len(members) != 1:
                raise ValueError(f"Expected one CSV in {filename}; found {len(members)}")
            return archive.read(members[0])
    return content


class SstRateCollector:
    name = "sst-rates"

    def collect(self, session: Session) -> CollectionStats:
        run = start_run(session, self.name)
        stats = CollectionStats()
        directory, _ = get_or_create_source(
            session,
            code="sst-rate-directory",
            name="Streamlined Sales Tax rate files",
            publisher="Streamlined Sales Tax Governing Board",
            source_type="rate_directory",
            url=RATE_DIRECTORY,
            tax_level=1,
            parser=self.name,
            cadence_days=7,
            notes="Quarterly member-state sales/use rate files in SST Technology Guide format.",
        )
        with http_client() as client:
            started = time.monotonic()
            response = client.get(RATE_DIRECTORY)
            response.raise_for_status()
            record_response(session, source=directory, run=run, response=response, started=started)
            files = self._discover(response.text)
            stats.sources += 1
            stats.details["states_discovered"] = sorted(files)
            for state, url in sorted(files.items()):
                source, created = get_or_create_source(
                    session,
                    code=f"sst-rate-{state.lower()}",
                    name=f"{state} SST sales/use rate file",
                    publisher=f"{state} tax authority via SSTGB",
                    source_type="machine_readable_rate",
                    url=url,
                    tax_level=1,
                    state_code=state,
                    parser=self.name,
                    cadence_days=30,
                    notes=(
                        "Contains state, county, municipal, and special-district components; "
                        "not a communications-tax taxability determination."
                    ),
                )
                stats.inserted += int(created)
                started = time.monotonic()
                file_response = client.get(url)
                file_response.raise_for_status()
                digest = record_response(
                    session, source=source, run=run, response=file_response, started=started
                )
                stats.sources += 1
                parsed = self._load_file(
                    session,
                    source=source,
                    filename=PurePosixPath(url).name,
                    content=file_response.content,
                    digest=digest,
                )
                stats.seen += parsed.seen
                stats.inserted += parsed.inserted
                stats.updated += parsed.updated
                session.flush()
        finish_run(run, stats)
        return stats

    @staticmethod
    def _discover(html: str) -> dict[str, str]:
        soup = BeautifulSoup(html, "html.parser")
        files: dict[str, str] = {}
        for anchor in soup.find_all("a", href=True):
            filename = PurePosixPath(anchor["href"]).name
            match = RATE_FILE_RE.match(filename)
            if match:
                state = match.group("state").upper()
                files[state] = RATE_DIRECTORY + filename
        if not files:
            raise ValueError("No SST rate files discovered; directory format may have changed")
        return files

    def _load_file(
        self,
        session: Session,
        *,
        source,
        filename: str,
        content: bytes,
        digest: str,
    ) -> CollectionStats:
        stats = CollectionStats()
        csv_content = _csv_bytes(content, filename).decode("utf-8-sig", errors="replace")
        jurisdictions = {
            item.external_key: item
            for item in session.scalars(
                select(Jurisdiction).where(Jurisdiction.external_key.like("sst:%"))
            )
        }
        facts = {
            (item.natural_key, item.effective_from): item
            for item in session.scalars(
                select(TaxFact).where(TaxFact.source_id == source.id)
            )
        }
        reader = csv.reader(io.StringIO(csv_content))
        for line_number, row in enumerate(reader, start=1):
            if not row or all(not cell.strip() for cell in row):
                continue
            stats.seen += 1
            if len(row) != 9:
                raise ValueError(f"{filename}:{line_number}: expected 9 fields, got {len(row)}")
            state_fips, type_code, jurisdiction_code = (cell.strip() for cell in row[:3])
            state = STATE_FIPS_TO_ABBR.get(state_fips)
            if not state:
                raise ValueError(f"{filename}:{line_number}: unknown state FIPS {state_fips}")
            external_key = f"sst:{state}:{type_code}:{jurisdiction_code}"
            level = sst_level(type_code)
            jurisdiction = jurisdictions.get(external_key)
            if jurisdiction is None:
                jurisdiction = Jurisdiction(
                    external_key=external_key,
                    country_iso="USA",
                    tax_level=level,
                    name=f"{state} {sst_type_name(type_code)} {jurisdiction_code}",
                    state_code=state,
                    fips_code=(
                        f"{state_fips}{jurisdiction_code}"
                        if type_code in {"00", "01"} and jurisdiction_code.isdigit()
                        else None
                    ),
                    parent_external_key=f"fips:state:{state_fips}" if level > 1 else "usa:federal",
                    source_id=source.id,
                    metadata_json={
                        "sst_jurisdiction_type": type_code,
                        "sst_jurisdiction_code": jurisdiction_code,
                    },
                )
                session.add(jurisdiction)
                session.flush()
                jurisdictions[external_key] = jurisdiction
                stats.inserted += 1
            begin = _date(row[7])
            end = _date(row[8])
            assert begin is not None
            variants = [
                ("general_intrastate", row[3]),
                ("general_interstate", row[4]),
                ("food_drug_intrastate", row[5]),
                ("food_drug_interstate", row[6]),
            ]
            for category, raw_rate in variants:
                if not raw_rate.strip():
                    # Some historical state files leave non-applicable food/drug fields blank.
                    continue
                try:
                    rate = Decimal(raw_rate.strip())
                except InvalidOperation as exc:
                    raise ValueError(
                        f"{filename}:{line_number}: invalid rate {raw_rate!r}"
                    ) from exc
                natural_key = f"sst:{state}:{type_code}:{jurisdiction_code}:{category}"
                fact = facts.get((natural_key, begin))
                payload = {
                    "state_fips": state_fips,
                    "jurisdiction_type": type_code,
                    "jurisdiction_code": jurisdiction_code,
                    "source_file": filename,
                    "line": line_number,
                }
                content_hash = hashlib.sha256(
                    f"{natural_key}|{rate}|{begin}|{end}|{digest}".encode()
                ).hexdigest()
                if fact is None:
                    fact = TaxFact(
                        natural_key=natural_key,
                        jurisdiction_id=jurisdiction.id,
                        source_id=source.id,
                        tax_family="sales_and_use",
                        tax_name="Sales and use tax",
                        service_category=category,
                        tax_type_code=f"sst-{type_code}",
                        rate=rate,
                        unit="percent_of_base",
                        effective_from=begin,
                        effective_to=end,
                        legal_citation="SST Technology Guide, chapter 5",
                        source_locator=f"{source.url}#line={line_number}",
                        content_sha256=content_hash,
                        raw_payload=payload,
                    )
                    session.add(fact)
                    facts[(natural_key, begin)] = fact
                    stats.inserted += 1
                else:
                    changed = (
                        fact.rate != rate
                        or fact.effective_to != end
                        or fact.content_sha256 != content_hash
                    )
                    fact.rate = rate
                    fact.effective_to = end
                    fact.content_sha256 = content_hash
                    fact.source_locator = f"{source.url}#line={line_number}"
                    fact.raw_payload = payload
                    stats.updated += int(changed)
        return stats
