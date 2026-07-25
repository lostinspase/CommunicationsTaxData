from __future__ import annotations

import hashlib
import io
import re
import time
from datetime import date
from decimal import Decimal

from bs4 import BeautifulSoup
from pypdf import PdfReader
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
from communications_tax_data.models import Jurisdiction, TaxFact

USAC_URL = "https://www.usac.org/service-providers/making-payments/contribution-factors/"
IRS_URL = "https://www.irs.gov/instructions/i720"
TRS_URL = "https://docs.fcc.gov/public/attachments/DA-26-646A1.pdf"
US_CODE_URL = (
    "https://uscode.house.gov/view.xhtml?edition=prelim&f=treesort&jumpTo=true&num=0&"
    "req=%28title%3A26+section%3A4251+edition%3Aprelim%29"
)

MONTHS = {
    "january": 1,
    "april": 4,
    "july": 7,
    "october": 10,
}


def _upsert_fact(
    session: Session,
    *,
    jurisdiction: Jurisdiction,
    source,
    natural_key: str,
    tax_name: str,
    tax_family: str,
    service_category: str,
    rate: Decimal,
    effective_from: date,
    effective_to: date | None,
    citation: str,
    locator: str,
    base_rule: str,
    raw_payload: dict,
) -> bool:
    content = (
        f"{natural_key}|{rate}|{effective_from}|{effective_to}|{citation}|{base_rule}"
    ).encode()
    digest = hashlib.sha256(content).hexdigest()
    fact = session.scalar(
        select(TaxFact).where(
            TaxFact.natural_key == natural_key,
            TaxFact.effective_from == effective_from,
        )
    )
    created = fact is None
    if fact is None:
        fact = TaxFact(
            natural_key=natural_key,
            jurisdiction_id=jurisdiction.id,
            source_id=source.id,
            tax_family=tax_family,
            tax_name=tax_name,
            service_category=service_category,
            rate=rate,
            unit="percent_of_base",
            effective_from=effective_from,
            effective_to=effective_to,
            legal_citation=citation,
            source_locator=locator,
            content_sha256=digest,
            base_rule=base_rule,
            raw_payload=raw_payload,
        )
        session.add(fact)
    else:
        fact.rate = rate
        fact.effective_to = effective_to
        fact.legal_citation = citation
        fact.source_locator = locator
        fact.content_sha256 = digest
        fact.base_rule = base_rule
        fact.raw_payload = raw_payload
    return created


class FederalCollector:
    name = "federal"

    def collect(self, session: Session) -> CollectionStats:
        run = start_run(session, self.name)
        stats = CollectionStats()
        jurisdiction = session.scalar(
            select(Jurisdiction).where(Jurisdiction.external_key == "usa:federal")
        )
        if jurisdiction is None:
            jurisdiction = Jurisdiction(
                external_key="usa:federal",
                country_iso="USA",
                tax_level=0,
                name="United States",
                valid_from=date(1900, 1, 1),
            )
            session.add(jurisdiction)
            session.flush()
            stats.inserted += 1
        with http_client() as client:
            self._collect_fusf(session, client, run, stats, jurisdiction)
            self._collect_excise(session, client, run, stats, jurisdiction)
            self._collect_trs(session, client, run, stats, jurisdiction)
        finish_run(run, stats)
        return stats

    def _collect_fusf(self, session, client, run, stats, jurisdiction) -> None:
        source, created = get_or_create_source(
            session,
            code="usac-contribution-factors",
            name="Universal Service Fund contribution factors",
            publisher="Universal Service Administrative Company / FCC",
            source_type="federal_rate",
            url=USAC_URL,
            tax_level=0,
            parser=self.name,
            cadence_days=14,
            notes="USAC table links each quarterly factor to its FCC Public Notice.",
        )
        stats.inserted += int(created)
        started = time.monotonic()
        response = client.get(USAC_URL)
        response.raise_for_status()
        record_response(session, source=source, run=run, response=response, started=started)
        stats.sources += 1
        soup = BeautifulSoup(response.text, "html.parser")
        seen_quarters = 0
        for row in soup.select("tr"):
            cells = row.find_all(["td", "th"])
            if len(cells) < 3:
                continue
            period = cells[0].get_text(" ", strip=True)
            rate_text = cells[1].get_text(" ", strip=True)
            match_period = re.search(
                r"(January|April|July|October)\s*[–-]\s*(?:March|June|September|December)\s+(\d{4})",
                period,
                re.IGNORECASE,
            )
            match_rate = re.search(r"(\d+(?:\.\d+)?)%", rate_text)
            if not match_period or not match_rate:
                continue
            month = MONTHS[match_period.group(1).lower()]
            year = int(match_period.group(2))
            begin = date(year, month, 1)
            end_month = month + 2
            next_month = date(year + (end_month == 12), (end_month % 12) + 1, 1)
            end = date.fromordinal(next_month.toordinal() - 1)
            rate = Decimal(match_rate.group(1)) / 100
            notice_cell = cells[-1]
            anchor = notice_cell.find("a", href=True)
            locator = anchor["href"] if anchor else USAC_URL
            if locator.startswith("/"):
                locator = "https://www.usac.org" + locator
            citation = notice_cell.get_text(" ", strip=True) or "47 CFR § 54.709"
            created_fact = _upsert_fact(
                session,
                jurisdiction=jurisdiction,
                source=source,
                natural_key=f"fcc:fusf:{year}:q{((month - 1) // 3) + 1}",
                tax_name="Federal Universal Service Fund contribution factor",
                tax_family="connectivity",
                service_category="interstate_and_international_telecommunications_revenue",
                rate=rate,
                effective_from=begin,
                effective_to=end,
                citation=f"{citation}; 47 CFR § 54.709",
                locator=locator,
                base_rule="Projected collected interstate and international end-user revenue.",
                raw_payload={"period": period, "published_rate": rate_text},
            )
            stats.inserted += int(created_fact)
            stats.updated += int(not created_fact)
            stats.seen += 1
            seen_quarters += 1
        if not seen_quarters:
            raise ValueError("USAC contribution-factor table format changed")

    def _collect_excise(self, session, client, run, stats, jurisdiction) -> None:
        source, created = get_or_create_source(
            session,
            code="irs-form-720-communications-tax",
            name="IRS Form 720 instructions — communications tax",
            publisher="Internal Revenue Service",
            source_type="federal_rate",
            url=IRS_URL,
            tax_level=0,
            parser=self.name,
            cadence_days=30,
            notes="Operational IRS guidance cross-cited to 26 USC 4251.",
        )
        stats.inserted += int(created)
        started = time.monotonic()
        response = client.get(IRS_URL)
        response.raise_for_status()
        record_response(session, source=source, run=run, response=response, started=started)
        stats.sources += 1
        text = BeautifulSoup(response.text, "html.parser").get_text(" ", strip=True)
        match = re.search(
            r"tax is\s+(\d+(?:\.\d+)?)%\s+of amounts paid for local telephone service",
            text,
            re.IGNORECASE,
        )
        if not match:
            raise ValueError("IRS communications-tax rate text was not found")
        rate = Decimal(match.group(1)) / 100
        created_fact = _upsert_fact(
            session,
            jurisdiction=jurisdiction,
            source=source,
            natural_key="irs:communications-excise:local-service",
            tax_name="Federal communications excise tax",
            tax_family="excise",
            service_category="local_telephone_and_teletypewriter_exchange_service",
            rate=rate,
            effective_from=date(2006, 8, 1),
            effective_to=None,
            citation="26 USC § 4251; IRS Form 720, IRS No. 22",
            locator=US_CODE_URL,
            base_rule=(
                "Amounts paid for local telephone and teletypewriter exchange service. "
                "Bundled service and long-distance service require separate treatment."
            ),
            raw_payload={"matched_text": match.group(0)},
        )
        stats.inserted += int(created_fact)
        stats.updated += int(not created_fact)
        stats.seen += 1

    def _collect_trs(self, session, client, run, stats, jurisdiction) -> None:
        source, created = get_or_create_source(
            session,
            code="fcc-trs-2026-27",
            name="FCC TRS Fund contribution factors, fund year 2026-27",
            publisher="Federal Communications Commission",
            source_type="federal_rate",
            url=TRS_URL,
            tax_level=0,
            parser=self.name,
            cadence_days=30,
            notes="Annual FCC order; collector validates and extracts both approved factors.",
        )
        stats.inserted += int(created)
        started = time.monotonic()
        response = client.get(TRS_URL)
        response.raise_for_status()
        record_response(session, source=source, run=run, response=response, started=started)
        stats.sources += 1
        reader = PdfReader(io.BytesIO(response.content))
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
        normalized = re.sub(r"\s+", " ", text)
        match = re.search(
            r"contribution factors shall be\s+(0\.\d+)\s+for non-\s*Internet-based TRS "
            r"and\s+(0\.\d+)\s+for Internet-based TRS",
            normalized,
            re.IGNORECASE,
        )
        if not match:
            raise ValueError("FCC TRS contribution factors were not found in the order")
        facts = [
            ("non-internet", Decimal(match.group(1)), "interstate_and_international_revenue"),
            ("internet", Decimal(match.group(2)), "all_end_user_revenue"),
        ]
        for kind, rate, category in facts:
            created_fact = _upsert_fact(
                session,
                jurisdiction=jurisdiction,
                source=source,
                natural_key=f"fcc:trs:2026-27:{kind}",
                tax_name=(
                    "Federal TRS contribution factor"
                    if kind == "non-internet"
                    else "Federal Internet-based TRS contribution factor"
                ),
                tax_family="connectivity",
                service_category=category,
                rate=rate,
                effective_from=date(2026, 7, 1),
                effective_to=date(2027, 6, 30),
                citation="FCC DA 26-646; 47 CFR § 64.604(c)(5)(iii)",
                locator=TRS_URL,
                base_rule=(
                    "Non-Internet TRS applies to interstate/international end-user revenue; "
                    "Internet TRS applies to intrastate, interstate, and international revenue."
                ),
                raw_payload={"fund_year": "2026-27", "kind": kind},
            )
            stats.inserted += int(created_fact)
            stats.updated += int(not created_fact)
            stats.seen += 1
