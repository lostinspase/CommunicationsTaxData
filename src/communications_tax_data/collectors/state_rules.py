from __future__ import annotations

import hashlib
import io
import re
import time
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from bs4 import BeautifulSoup
from pypdf import PdfReader
from sqlalchemy import select
from sqlalchemy.orm import Session

from communications_tax_data.collectors.base import (
    CollectionStats,
    finish_run,
    get_or_create_source,
    get_with_retry,
    http_client,
    record_error,
    record_fact_change,
    record_response,
    start_run,
)
from communications_tax_data.models import Jurisdiction, TaxFact
from communications_tax_data.state_authorities import STATE_AUTHORITY_BY_CODE

PA_TELECOM_CODE_URL = (
    "https://www.pacodeandbulletin.gov/secure/pacode/data/061/chapter60/s60.20.html"
)


def _date(value: str) -> date:
    cleaned = value.strip().rstrip("*")
    month, day, year = (int(part) for part in cleaned.split("/"))
    return date(year, month, day)


def _old_values(fact: TaxFact) -> dict[str, Any]:
    return {
        field_name: getattr(fact, field_name)
        for field_name in (
            "rate",
            "flat_amount",
            "unit",
            "max_base",
            "min_base",
            "base_rule",
            "effective_to",
            "legal_citation",
            "source_locator",
            "status",
            "content_sha256",
        )
    }


def _upsert_fact(
    session: Session,
    *,
    run,
    jurisdiction: Jurisdiction,
    source,
    natural_key: str,
    tax_name: str,
    tax_family: str,
    service_category: str,
    effective_from: date,
    effective_to: date | None,
    citation: str,
    locator: str,
    base_rule: str,
    raw_payload: dict[str, Any],
    rate: Decimal | None = None,
    flat_amount: Decimal | None = None,
    unit: str = "percent_of_base",
    status: str = "published",
) -> bool:
    content = (
        f"{natural_key}|{rate}|{flat_amount}|{unit}|{effective_from}|{effective_to}|"
        f"{citation}|{locator}|{base_rule}|{status}"
    ).encode()
    digest = hashlib.sha256(content).hexdigest()
    fact = session.scalar(
        select(TaxFact).where(
            TaxFact.natural_key == natural_key,
            TaxFact.effective_from == effective_from,
        )
    )
    created = fact is None
    old_values = None
    if fact is None:
        fact = TaxFact(
            natural_key=natural_key,
            jurisdiction_id=jurisdiction.id,
            source_id=source.id,
            tax_family=tax_family,
            tax_name=tax_name,
            service_category=service_category,
            rate=rate,
            flat_amount=flat_amount,
            unit=unit,
            effective_from=effective_from,
            effective_to=effective_to,
            legal_citation=citation,
            source_locator=locator,
            content_sha256=digest,
            base_rule=base_rule,
            raw_payload=raw_payload,
            status=status,
        )
        session.add(fact)
    else:
        old_values = _old_values(fact)
        fact.jurisdiction_id = jurisdiction.id
        fact.source_id = source.id
        fact.tax_family = tax_family
        fact.tax_name = tax_name
        fact.service_category = service_category
        fact.rate = rate
        fact.flat_amount = flat_amount
        fact.unit = unit
        fact.effective_to = effective_to
        fact.legal_citation = citation
        fact.source_locator = locator
        fact.content_sha256 = digest
        fact.base_rule = base_rule
        fact.raw_payload = raw_payload
        fact.status = status
    record_fact_change(
        session,
        fact=fact,
        run=run,
        created=created,
        old_values=old_values,
    )
    return created


def _table_rows(soup: BeautifulSoup, table_index: int = 0) -> list[list[str]]:
    tables = soup.find_all("table")
    if len(tables) <= table_index:
        return []
    return [
        [cell.get_text(" ", strip=True) for cell in row.find_all(["th", "td"])]
        for row in tables[table_index].find_all("tr")
    ]


class StateRuleCollector:
    """Normalize only state rules that have source-specific validation."""

    name = "state-rules"

    def collect(self, session: Session) -> CollectionStats:
        # Runtime import avoids a catalog/collector package initialization cycle.
        from communications_tax_data.catalog import STATE_RULE_SOURCES

        run = start_run(session, self.name)
        stats = CollectionStats()
        jurisdictions: dict[str, Jurisdiction] = {}
        with http_client() as client:
            for item in STATE_RULE_SOURCES:
                source, created = get_or_create_source(session, **item)
                stats.inserted += int(created)
                state_code = item["state_code"]
                jurisdiction = jurisdictions.get(state_code)
                if jurisdiction is None:
                    jurisdiction = self._jurisdiction(session, state_code, source.id)
                    jurisdictions[state_code] = jurisdiction
                started = time.monotonic()
                try:
                    response = get_with_retry(client, source.url)
                    response.raise_for_status()
                    record_response(
                        session,
                        source=source,
                        run=run,
                        response=response,
                        started=started,
                    )
                    facts, inserted_facts = self._parse(
                        session,
                        run=run,
                        source=source,
                        jurisdiction=jurisdiction,
                        content=response.content,
                    )
                    stats.sources += 1
                    stats.seen += facts
                    stats.inserted += inserted_facts
                    stats.updated += facts - inserted_facts
                except Exception as exc:
                    record_error(
                        session,
                        source=source,
                        run=run,
                        error=exc,
                        started=started,
                    )
                    stats.sources += 1
                    stats.details.setdefault("errors", []).append(
                        {"source": source.code, "error": str(exc)}
                    )
        finish_run(run, stats, status="partial" if stats.details.get("errors") else "success")
        return stats

    @staticmethod
    def _jurisdiction(session: Session, state_code: str, source_id: int) -> Jurisdiction:
        jurisdiction = session.scalar(
            select(Jurisdiction).where(
                Jurisdiction.external_key == f"state:{state_code}",
                Jurisdiction.valid_from == date(1900, 1, 1),
            )
        )
        if jurisdiction is None:
            jurisdiction = Jurisdiction(
                external_key=f"state:{state_code}",
                country_iso="USA",
                tax_level=1,
                name=STATE_AUTHORITY_BY_CODE[state_code].state_name,
                state_code=state_code,
                valid_from=date(1900, 1, 1),
                source_id=source_id,
                metadata_json={"assignment": "statewide"},
            )
            session.add(jurisdiction)
            session.flush()
        return jurisdiction

    def _parse(
        self,
        session: Session,
        *,
        run,
        source,
        jurisdiction: Jurisdiction,
        content: bytes,
    ) -> tuple[int, int]:
        if source.code == "state-rule-ca-cpuc-surcharge":
            return self._ca_surcharge(session, run, source, jurisdiction, content)
        if source.code == "state-rule-ca-cpuc-user-fee":
            return self._ca_user_fee(session, run, source, jurisdiction, content)
        if source.code == "state-rule-ca-cdtfa-mobile":
            return self._ca_mobile_taxability(
                session, run, source, jurisdiction, content
            )
        if source.code == "state-rule-pa-telecom-grt":
            return self._pa_grt(session, run, source, jurisdiction, content)
        if source.code == "state-rule-pa-sales-use-rate":
            return self._pa_sales_rate(session, run, source, jurisdiction, content)
        if source.code == "state-rule-pa-telecom-taxability":
            return self._pa_telecom_taxability(
                session, run, source, jurisdiction, content
            )
        raise ValueError(f"No state-rule parser for {source.code}")

    def _ca_surcharge(
        self, session, run, source, jurisdiction, content: bytes
    ) -> tuple[int, int]:
        rows = _table_rows(BeautifulSoup(content, "html.parser"))
        parsed: list[tuple[date, Decimal, list[str]]] = []
        for cells in rows:
            if len(cells) < 2 or not re.fullmatch(r"\d{1,2}/\d{1,2}/\d{4}", cells[0]):
                continue
            amount_match = re.fullmatch(r"\$\s*(\d+(?:\.\d+)?)", cells[1])
            if amount_match:
                parsed.append((_date(cells[0]), Decimal(amount_match.group(1)), cells))
        if not parsed:
            raise ValueError("CPUC flat-rate surcharge table format changed")
        parsed.sort(key=lambda row: row[0], reverse=True)
        inserted = 0
        for index, (effective_from, amount, cells) in enumerate(parsed):
            effective_to = (
                parsed[index - 1][0] - timedelta(days=1) if index > 0 else None
            )
            created = _upsert_fact(
                session,
                run=run,
                jurisdiction=jurisdiction,
                source=source,
                natural_key="ca:cpuc:public-purpose-program-flat-surcharge",
                tax_name="California Public Purpose Program surcharge",
                tax_family="connectivity",
                service_category="telephone_access_line",
                flat_amount=amount,
                unit="per_access_line",
                effective_from=effective_from,
                effective_to=effective_to,
                citation="California Public Utilities Code §§ 285 and 285.5; CPUC rate table",
                locator=source.url,
                base_rule=(
                    "Monthly flat surcharge per access line. CPUC states that the "
                    "mechanism applies to wireline, wireless, prepaid, postpaid, and "
                    "interconnected VoIP services, subject to its line-count rules."
                ),
                raw_payload={"published_row": cells},
            )
            inserted += int(created)
        return len(parsed), inserted

    def _ca_user_fee(
        self, session, run, source, jurisdiction, content: bytes
    ) -> tuple[int, int]:
        rows = _table_rows(BeautifulSoup(content, "html.parser"))
        parsed: list[tuple[date, Decimal, list[str]]] = []
        for cells in rows:
            if len(cells) < 2 or not re.fullmatch(
                r"\d{1,2}/\d{1,2}/\d{4}\*?", cells[0]
            ):
                continue
            rate_match = re.fullmatch(r"(\d+(?:\.\d+)?)%", cells[1])
            if rate_match:
                parsed.append(
                    (_date(cells[0]), Decimal(rate_match.group(1)) / 100, cells)
                )
        if not parsed:
            raise ValueError("CPUC user-fee table format changed")
        parsed.sort(key=lambda row: row[0], reverse=True)
        inserted = 0
        for index, (effective_from, rate, cells) in enumerate(parsed):
            effective_to = (
                parsed[index - 1][0] - timedelta(days=1) if index > 0 else None
            )
            created = _upsert_fact(
                session,
                run=run,
                jurisdiction=jurisdiction,
                source=source,
                natural_key="ca:cpuc:telecommunications-user-fee",
                tax_name="California CPUC telecommunications user fee",
                tax_family="regulatory_fee",
                service_category="intrastate_telecommunications_revenue",
                rate=rate,
                unit="percent_of_base",
                effective_from=effective_from,
                effective_to=effective_to,
                citation="California Public Utilities Code §§ 401–443; CPUC user-fee table",
                locator=source.url,
                base_rule=(
                    "Telephone corporation gross intrastate revenue; current CPUC "
                    "guidance applies one user-fee rate to telecommunications services."
                ),
                raw_payload={"published_row": cells},
            )
            inserted += int(created)
        return len(parsed), inserted

    def _ca_mobile_taxability(
        self, session, run, source, jurisdiction, content: bytes
    ) -> tuple[int, int]:
        text = BeautifulSoup(content, "html.parser").get_text(" ", strip=True)
        marker = (
            "Service and/or data plans that do not include mobile phone, tablets "
            "or other wireless devices are not taxable"
        )
        if marker.lower() not in text.lower():
            raise ValueError("CDTFA service-plan taxability statement was not found")
        created = _upsert_fact(
            session,
            run=run,
            jurisdiction=jurisdiction,
            source=source,
            natural_key="ca:cdtfa:standalone-mobile-service-plan",
            tax_name="California sales/use tax treatment — standalone service/data plan",
            tax_family="sales_and_use",
            service_category="mobile_service_and_data_plan_without_device",
            unit="taxability_rule",
            status="not_taxable",
            effective_from=date(2020, 1, 1),
            effective_to=None,
            citation="CDTFA Tax Guide for Mobile Phone Vendors — Industry Topics",
            locator=source.url,
            base_rule=(
                "A service or data plan without a mobile phone, tablet, or other "
                "wireless device is not taxable. Devices and bundled device "
                "transactions have separate tangible-personal-property rules; "
                "prepaid MTS also has 911, 988, and local-charge obligations."
            ),
            raw_payload={"validated_statement": marker},
        )
        return 1, int(created)

    def _pa_grt(
        self, session, run, source, jurisdiction, content: bytes
    ) -> tuple[int, int]:
        text = BeautifulSoup(content, "html.parser").get_text(" ", strip=True)
        match = re.search(
            r"gross receipts tax on telecommunications services is\s+(\d+)\s+mills",
            text,
            re.IGNORECASE,
        )
        if not match:
            raise ValueError("Pennsylvania telecommunications GRT rate was not found")
        mills = Decimal(match.group(1))
        created = _upsert_fact(
            session,
            run=run,
            jurisdiction=jurisdiction,
            source=source,
            natural_key="pa:dor:telecommunications-gross-receipts-tax",
            tax_name="Pennsylvania telecommunications gross receipts tax",
            tax_family="gross_receipts",
            service_category="telecommunications_provider_gross_receipts",
            rate=mills / 1000,
            unit="percent_of_base",
            effective_from=date(2018, 1, 1),
            effective_to=None,
            citation="72 P.S. § 8101(a); Pennsylvania DOR Gross Receipts Tax guidance",
            locator=source.url,
            base_rule=(
                "Provider tax on covered intrastate, interstate, and mobile "
                "telecommunications receipts sourced to Pennsylvania, with statutory "
                "exclusions including Internet access and qualifying resale."
            ),
            raw_payload={"published_rate": f"{mills} mills", "return": "RCT-111"},
        )
        return 1, int(created)

    def _pa_sales_rate(
        self, session, run, source, jurisdiction, content: bytes
    ) -> tuple[int, int]:
        text = BeautifulSoup(content, "html.parser").get_text(" ", strip=True)
        match = re.search(
            r"Pennsylvania sales tax rate is\s+(\d+(?:\.\d+)?)\s+percent",
            text,
            re.IGNORECASE,
        )
        if not match:
            raise ValueError("Pennsylvania sales tax rate was not found")
        rate = Decimal(match.group(1)) / 100
        created = _upsert_fact(
            session,
            run=run,
            jurisdiction=jurisdiction,
            source=source,
            natural_key="pa:dor:state-sales-use-rate",
            tax_name="Pennsylvania state sales and use tax",
            tax_family="sales_and_use",
            service_category="state_taxable_sales_and_services",
            rate=rate,
            unit="percent_of_base",
            effective_from=date(1991, 10, 1),
            effective_to=None,
            citation="72 P.S. § 7202; Pennsylvania DOR Sales, Use and Hotel Occupancy Tax",
            locator=source.url,
            base_rule=(
                "State rate. The separate one-percent Allegheny County and two-percent "
                "Philadelphia additions are local facts and are not included in this "
                "state-level rate."
            ),
            raw_payload={"published_rate": match.group(0)},
        )
        return 1, int(created)

    def _pa_telecom_taxability(
        self, session, run, source, jurisdiction, content: bytes
    ) -> tuple[int, int]:
        reader = PdfReader(io.BytesIO(content))
        text = " ".join(page.extract_text() or "" for page in reader.pages)
        normalized = re.sub(r"\s+", " ", text)
        required = (
            "Enhanced Telecommunications Services",
            "Non-Enhanced Telecommunications Services",
            "Mobile Telecommunications Sourcing Act",
        )
        if not all(value.lower() in normalized.lower() for value in required):
            raise ValueError("Pennsylvania telecommunications bulletin format changed")
        created = _upsert_fact(
            session,
            run=run,
            jurisdiction=jurisdiction,
            source=source,
            natural_key="pa:dor:telecommunications-sales-use-taxability",
            tax_name="Pennsylvania sales/use tax treatment — telecommunications service",
            tax_family="sales_and_use",
            service_category="telecommunications_service",
            rate=Decimal("0.06"),
            unit="percent_of_base",
            effective_from=date(1991, 10, 1),
            effective_to=None,
            citation="61 Pa. Code § 60.20; Sales Tax Bulletin 2005-03",
            locator=PA_TELECOM_CODE_URL,
            base_rule=(
                "International or interstate telecommunications charged to a "
                "Pennsylvania service address and intrastate telecommunications are "
                "taxable. The regulation separately defines enhanced services and "
                "exemptions, including qualifying residential basic local service, "
                "resale, government, and charitable purchases."
            ),
            raw_payload={"validated_sections": list(required)},
        )
        return 1, int(created)
