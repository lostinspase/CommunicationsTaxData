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
NY_FRACTIONS = {
    "¼": Decimal("0.25"),
    "½": Decimal("0.5"),
    "¾": Decimal("0.75"),
    "⅛": Decimal("0.125"),
    "⅜": Decimal("0.375"),
    "⅝": Decimal("0.625"),
    "⅞": Decimal("0.875"),
}


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


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", value.casefold()).strip("-")


def _ny_percent(value: str) -> Decimal:
    whole = Decimal(value[0])
    fraction = NY_FRACTIONS.get(value[1:], Decimal())
    return (whole + fraction) / 100


class StateRuleCollector:
    """Normalize only state rules that have source-specific validation."""

    name = "state-rules"

    def collect(self, session: Session) -> CollectionStats:
        # Runtime import avoids a catalog/collector package initialization cycle.
        from communications_tax_data.catalog import (
            NY_LOCAL_UTILITY_RULES,
            STATE_RULE_SOURCES,
        )

        run = start_run(session, self.name)
        stats = CollectionStats()
        jurisdictions: dict[str, Jurisdiction] = {}
        local_configs = {
            item["source"]["code"]: item for item in NY_LOCAL_UTILITY_RULES
        }
        sources = STATE_RULE_SOURCES + [
            item["source"] for item in NY_LOCAL_UTILITY_RULES
        ]
        with http_client() as client:
            for item in sources:
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
                        local_config=local_configs.get(source.code),
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
        local_config: dict[str, Any] | None = None,
    ) -> tuple[int, int]:
        if local_config is not None:
            return self._ny_local_utility_grt(
                session,
                run,
                source,
                content,
                config=local_config,
            )
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
        if source.code == "state-rule-ny-sales-rates":
            return self._ny_sales_rates(session, run, source, jurisdiction, content)
        if source.code == "state-rule-ny-telecom-taxability":
            return self._ny_telecom_taxability(
                session, run, source, jurisdiction, content
            )
        if source.code == "state-rule-ny-wireless-postpaid":
            return self._ny_wireless_surcharge(
                session,
                run,
                source,
                jurisdiction,
                content,
                prepaid=False,
            )
        if source.code == "state-rule-ny-wireless-prepaid":
            return self._ny_wireless_surcharge(
                session,
                run,
                source,
                jurisdiction,
                content,
                prepaid=True,
            )
        if source.code == "state-rule-ny-telecom-excise":
            return self._ny_telecom_excise(
                session, run, source, jurisdiction, content
            )
        raise ValueError(f"No state-rule parser for {source.code}")

    def _ny_local_utility_grt(
        self,
        session: Session,
        run,
        source,
        content: bytes,
        *,
        config: dict[str, Any],
    ) -> tuple[int, int]:
        text = re.sub(
            r"\s+",
            " ",
            BeautifulSoup(content, "html.parser").get_text(" ", strip=True),
        )
        rate_match = re.search(
            r"\btax\s+equal\s+to\s+(\d+(?:\.\d+)?)\s*%",
            text,
            re.IGNORECASE,
        )
        required = (
            config["locality"].casefold() in text.casefold(),
            "gross income" in text.casefold(),
            bool(
                re.search(
                    r"\btelephon(?:e|y|ic|ical)\b",
                    text,
                    re.IGNORECASE,
                )
            ),
            "territorial limits" in text.casefold()
            or "wholly consummated within" in text.casefold(),
        )
        if rate_match is None or not all(required):
            raise ValueError(
                f"{config['locality']} utility-tax ordinance validation changed"
            )
        rate = Decimal(rate_match.group(1)) / 100
        if rate != Decimal("0.01"):
            raise ValueError(
                f"{config['locality']} utility-tax rate is no longer one percent"
            )

        is_village = config["municipality_type"] == "village"
        jurisdiction = self._ny_local_jurisdiction(
            session,
            source=source,
            name=config["locality"],
            tax_level=3,
            namespace="utility-gross-receipts",
            metadata={
                "assignment": "adopted_municipal_ordinance",
                "municipality_type": config["municipality_type"],
                "benchmark_p_code": config["p_code"],
                "customer_bill_treatment": config["customer_bill_treatment"],
            },
        )
        enabling_citation = (
            "New York Village Law § 5-530"
            if is_village
            else "New York General City Law § 20-b"
        )
        base_rule = (
            "One-percent tax on qualifying utility gross income or gross operating "
            f"income within {config['locality']}. "
        )
        if is_village:
            base_rule += (
                "For telephony or telephone service, gross income includes only "
                "receipts from local exchange service wholly consummated within "
                "the village. "
            )
        else:
            base_rule += (
                "The codified utility definition includes telephony or telephone "
                "service, and excludes transactions originating or consummated "
                "outside the city. "
            )
        base_rule += (
            "The ordinance text does not by itself establish treatment for every "
            "modern VoIP, wireless, or bundled-service variant."
        )
        created = _upsert_fact(
            session,
            run=run,
            jurisdiction=jurisdiction,
            source=source,
            natural_key=(
                f"ny:local:{_slug(config['locality'])}:utility-gross-receipts"
            ),
            tax_name=f"{config['locality']} utility gross receipts tax",
            tax_family="gross_receipts",
            service_category="local_telecommunications_utility_gross_receipts",
            rate=rate,
            unit="percent_of_base",
            effective_from=date.fromisoformat(config["effective_from"]),
            effective_to=None,
            citation=f"{config['local_citation']}; {enabling_citation}",
            locator=source.url,
            base_rule=base_rule,
            raw_payload={
                "validated_rate": f"{rate * 100}%",
                "locality": config["locality"],
                "municipality_type": config["municipality_type"],
                "benchmark_p_code": config["p_code"],
                "filing_entity_name": config["filing_entity_name"],
                "filing_frequency": config["filing_frequency"],
                "due_rule": config["due_rule"],
                "customer_bill_treatment": config["customer_bill_treatment"],
            },
        )
        return 1, int(created)

    @staticmethod
    def _ny_local_jurisdiction(
        session: Session,
        *,
        source,
        name: str,
        tax_level: int,
        namespace: str,
        metadata: dict[str, Any],
    ) -> Jurisdiction:
        external_key = f"ny:{namespace}:{tax_level}:{_slug(name)}"
        jurisdiction = session.scalar(
            select(Jurisdiction).where(
                Jurisdiction.external_key == external_key,
                Jurisdiction.valid_from == date(1900, 1, 1),
            )
        )
        if jurisdiction is None:
            jurisdiction = Jurisdiction(
                external_key=external_key,
                country_iso="USA",
                tax_level=tax_level,
                name=name,
                state_code="NY",
                county_name=name if tax_level == 2 else None,
                locality_name=name if tax_level == 3 else None,
                parent_external_key="state:NY",
                valid_from=date(1900, 1, 1),
                source_id=source.id,
                metadata_json=metadata,
            )
            session.add(jurisdiction)
            session.flush()
        else:
            jurisdiction.source_id = source.id
            jurisdiction.metadata_json = metadata
        return jurisdiction

    def _ny_sales_rates(
        self, session, run, source, jurisdiction, content: bytes
    ) -> tuple[int, int]:
        text = " ".join(
            page.extract_text() or "" for page in PdfReader(io.BytesIO(content)).pages
        )
        normalized = re.sub(r"\s+", " ", text)
        effective_match = re.search(
            r"Effective\s+([A-Za-z]+)\s+(\d{1,2}),\s+(\d{4})",
            normalized,
        )
        if not effective_match:
            raise ValueError("New York Publication 718 effective date was not found")
        effective_from = date(
            int(effective_match.group(3)),
            {
                "January": 1,
                "February": 2,
                "March": 3,
                "April": 4,
                "May": 5,
                "June": 6,
                "July": 7,
                "August": 8,
                "September": 9,
                "October": 10,
                "November": 11,
                "December": 12,
            }[effective_match.group(1)],
            int(effective_match.group(2)),
        )
        matches = list(
            re.finditer(
                r"([*A-Za-z][*A-Za-z .’()–-]{1,80}?)\s+"
                r"(\d(?:[¼½¾⅛⅜⅝⅞])?)\s+(\d{4})",
                normalized,
            )
        )
        if len(matches) < 70:
            raise ValueError("New York Publication 718 rate table format changed")

        state_rate = Decimal("0.04")
        inserted = int(
            _upsert_fact(
                session,
                run=run,
                jurisdiction=jurisdiction,
                source=source,
                natural_key="ny:dor:state-sales-use-rate",
                tax_name="New York State sales and use tax",
                tax_family="sales_and_use",
                service_category="state_taxable_sales_and_services",
                rate=state_rate,
                effective_from=date(1971, 6, 1),
                effective_to=None,
                citation="New York Tax Law § 1105; Publication 718",
                locator=source.url,
                base_rule=(
                    "State rate only. Publication 718 publishes combined state/local "
                    "rates and reporting codes; local components are normalized "
                    "separately."
                ),
                raw_payload={
                    "published_rate": "4%",
                    "publication_effective_from": effective_from.isoformat(),
                    "reporting_code": "0021",
                },
            )
        )
        facts = 1
        for match in matches[1:]:
            raw_name, raw_rate, reporting_code = match.groups()
            if "see New York City " in raw_name:
                raw_name = raw_name.rsplit("see New York City ", 1)[-1]
            name = (
                raw_name.replace("*", "")
                .replace(" – except", "")
                .replace(" (city)", "")
                .strip()
            )
            if not name or "New York State only" in name:
                continue
            is_city = "(city)" in raw_name or name == "New York City"
            tax_level = 3 if is_city else 2
            local = self._ny_local_jurisdiction(
                session,
                source=source,
                name=name,
                tax_level=tax_level,
                namespace="sales",
                metadata={
                    "assignment": "official_reporting_jurisdiction",
                    "reporting_code": reporting_code,
                    "published_combined_rate": raw_rate,
                },
            )
            combined_rate = _ny_percent(raw_rate)
            local_rate = combined_rate - state_rate
            created = _upsert_fact(
                session,
                run=run,
                jurisdiction=local,
                source=source,
                natural_key=(
                    f"ny:dor:sales-use-local:{tax_level}:{_slug(name)}"
                ),
                tax_name=f"{name} local sales and use tax",
                tax_family="sales_and_use",
                service_category="locally_taxable_sales_and_services",
                rate=local_rate,
                effective_from=effective_from,
                effective_to=None,
                citation="New York Tax Law Article 29; Publication 718",
                locator=source.url,
                base_rule=(
                    "Local component derived from the official combined rate less "
                    "the four-percent New York State rate. Apply only after the "
                    "service is classified as taxable and the reporting jurisdiction "
                    "is assigned; ZIP codes are not reporting jurisdictions."
                ),
                raw_payload={
                    "published_name": raw_name,
                    "published_combined_rate": raw_rate,
                    "state_rate": "4%",
                    "reporting_code": reporting_code,
                },
            )
            inserted += int(created)
            facts += 1
        return facts, inserted

    def _ny_telecom_taxability(
        self, session, run, source, jurisdiction, content: bytes
    ) -> tuple[int, int]:
        text = re.sub(
            r"\s+",
            " ",
            BeautifulSoup(content, "html.parser").get_text(" ", strip=True),
        )
        marker = "utility and (intrastate) telecommunication services"
        if marker.casefold() not in text.casefold():
            raise ValueError("New York telecommunications taxability statement changed")
        created = _upsert_fact(
            session,
            run=run,
            jurisdiction=jurisdiction,
            source=source,
            natural_key="ny:dor:intrastate-telecommunications-sales-taxability",
            tax_name="New York sales-tax treatment — intrastate telecommunications",
            tax_family="sales_and_use",
            service_category="intrastate_telecommunications_service",
            unit="taxability_rule",
            status="taxable",
            effective_from=date(1965, 8, 1),
            effective_to=None,
            citation="New York Tax Law § 1105(b); NYS DTF Quick Reference Guide",
            locator=source.url,
            base_rule=(
                "Intrastate telecommunications services are included in the "
                "Department's list of taxable services. Product classification, "
                "sourcing, exclusions, and exemptions require their own rules."
            ),
            raw_payload={"validated_statement": marker},
        )
        return 1, int(created)

    def _ny_wireless_surcharge(
        self,
        session,
        run,
        source,
        jurisdiction,
        content: bytes,
        *,
        prepaid: bool,
    ) -> tuple[int, int]:
        soup = BeautifulSoup(content, "html.parser")
        text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
        date_match = re.search(
            r"Effective\s+([A-Za-z]+)\s+(\d{1,2}),\s+(\d{4})",
            text,
        )
        state_match = re.search(
            r"is\s+\$(\d+(?:\.\d+)?)"
            + (
                r"\s+\(\d+\s+cents\)\s+on each retail sale"
                if prepaid
                else r"\s+per month for each device"
            ),
            text,
            re.IGNORECASE,
        )
        if not date_match or not state_match:
            raise ValueError("New York wireless surcharge header format changed")
        month = {
            name: index
            for index, name in enumerate(
                (
                    "",
                    "January",
                    "February",
                    "March",
                    "April",
                    "May",
                    "June",
                    "July",
                    "August",
                    "September",
                    "October",
                    "November",
                    "December",
                )
            )
        }[date_match.group(1)]
        effective_from = date(
            int(date_match.group(3)), month, int(date_match.group(2))
        )
        state_amount = Decimal(state_match.group(1))
        flavor = "prepaid" if prepaid else "postpaid"
        unit = "per_retail_sale" if prepaid else "per_device_month"
        inserted = int(
            _upsert_fact(
                session,
                run=run,
                jurisdiction=jurisdiction,
                source=source,
                natural_key=f"ny:dor:wireless-surcharge:{flavor}:state",
                tax_name=f"New York State {flavor} wireless communications surcharge",
                tax_family="public_safety",
                service_category=f"{flavor}_wireless_communications_service",
                flat_amount=state_amount,
                unit=unit,
                effective_from=effective_from,
                effective_to=None,
                citation=f"New York Tax Law § 186-f; Publication {'452' if prepaid else '451'}",
                locator=source.url,
                base_rule=(
                    "State surcharge on each retail sale occurring in New York."
                    if prepaid
                    else (
                        "State monthly surcharge for each device in service during "
                        "any part of a month when the customer's place of primary "
                        "use is in New York."
                    )
                ),
                raw_payload={"published_state_amount": str(state_amount)},
            )
        )
        facts = 1
        tables = soup.find_all("table")
        if not tables:
            raise ValueError("New York wireless surcharge locality table was not found")
        expiration_notes: dict[str, date] = {}
        if len(tables) > 1:
            for cells in _table_rows(soup, 1):
                if len(cells) < 2 or not cells[0].isdigit():
                    continue
                expiration = re.search(
                    r"expires\s+([A-Za-z]+)\s+(\d{1,2}),\s+(\d{4})",
                    cells[1],
                    re.IGNORECASE,
                )
                if expiration:
                    expiration_notes[cells[0]] = date(
                        int(expiration.group(3)),
                        {
                            name: index
                            for index, name in enumerate(
                                (
                                    "",
                                    "January",
                                    "February",
                                    "March",
                                    "April",
                                    "May",
                                    "June",
                                    "July",
                                    "August",
                                    "September",
                                    "October",
                                    "November",
                                    "December",
                                )
                            )
                        }[expiration.group(1)],
                        int(expiration.group(2)),
                    )
        for cells in _table_rows(soup, 0)[1:]:
            if len(cells) < 2 or not cells[1].startswith("$"):
                continue
            raw_name = cells[0]
            note_match = re.search(r"\s+([1-9])$", raw_name)
            note = note_match.group(1) if note_match else None
            name = re.sub(r"\s+[1-9]$", "", raw_name).strip()
            is_city = name == "New York City"
            if name.endswith(" County"):
                name = name[: -len(" County")]
            tax_level = 3 if is_city else 2
            combined_amount = Decimal(cells[1].lstrip("$").replace(",", ""))
            local_amount = combined_amount - state_amount
            local = self._ny_local_jurisdiction(
                session,
                source=source,
                name=name,
                tax_level=tax_level,
                namespace=f"wireless-{flavor}",
                metadata={
                    "assignment": (
                        "place_of_primary_use" if not prepaid else "retail_sale_location"
                    ),
                    "published_combined_amount": str(combined_amount),
                },
            )
            created = _upsert_fact(
                session,
                run=run,
                jurisdiction=local,
                source=source,
                natural_key=(
                    f"ny:dor:wireless-surcharge:{flavor}:local:"
                    f"{tax_level}:{_slug(name)}"
                ),
                tax_name=f"{name} local {flavor} wireless communications surcharge",
                tax_family="public_safety",
                service_category=f"{flavor}_wireless_communications_service",
                flat_amount=local_amount,
                unit=unit,
                effective_from=effective_from,
                effective_to=expiration_notes.get(note),
                citation=f"New York Tax Law § 186-f; Publication {'452' if prepaid else '451'}",
                locator=source.url,
                base_rule=(
                    "Local component derived from the published combined surcharge "
                    "less the New York State surcharge."
                ),
                raw_payload={
                    "published_name": raw_name,
                    "published_combined_amount": str(combined_amount),
                    "state_amount": str(state_amount),
                    "expiration_note": note,
                },
            )
            inserted += int(created)
            facts += 1
        return facts, inserted

    def _ny_telecom_excise(
        self, session, run, source, jurisdiction, content: bytes
    ) -> tuple[int, int]:
        text = re.sub(
            r"\s+",
            " ",
            BeautifulSoup(content, "html.parser").get_text(" ", strip=True),
        )
        nonmobile = re.search(
            r"§\s*186-e provides for an excise tax on telecommunications "
            r"services at rate of\s+(\d+(?:\.\d+)?)\s+percent",
            text,
            re.IGNORECASE,
        )
        mobile = re.search(
            r"sale of mobile telecommunication services.*?rate of\s+"
            r"(\d+(?:\.\d+)?)\s+percent",
            text,
            re.IGNORECASE,
        )
        if not nonmobile or not mobile:
            raise ValueError("New York telecommunications excise rates were not found")
        inputs = (
            (
                "nonmobile",
                Decimal(nonmobile.group(1)) / 100,
                "nonmobile_telecommunications_provider_gross_receipts",
                (
                    "Gross receipts from intrastate services and interstate or "
                    "international services that originate or terminate in New York "
                    "and are billed to a New York service address."
                ),
            ),
            (
                "mobile",
                Decimal(mobile.group(1)) / 100,
                "mobile_telecommunications_provider_gross_receipts",
                (
                    "Gross receipts from mobile telecommunications provided by a "
                    "home service provider when the customer's place of primary use "
                    "is within New York."
                ),
            ),
        )
        inserted = 0
        for flavor, rate, category, base_rule in inputs:
            created = _upsert_fact(
                session,
                run=run,
                jurisdiction=jurisdiction,
                source=source,
                natural_key=f"ny:dor:telecommunications-excise:{flavor}",
                tax_name=f"New York {flavor} telecommunications excise tax",
                tax_family="gross_receipts",
                service_category=category,
                rate=rate,
                effective_from=date(2015, 5, 1) if flavor == "mobile" else date(2000, 1, 1),
                effective_to=None,
                citation="New York Tax Law § 186-e",
                locator=source.url,
                base_rule=base_rule,
                raw_payload={"published_rate": f"{rate * 100}%"},
            )
            inserted += int(created)
        return 2, inserted

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
