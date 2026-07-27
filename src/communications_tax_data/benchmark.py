from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from datetime import date, timedelta

from sqlalchemy import Engine, create_engine, delete, func, select, text
from sqlalchemy.orm import Session

from communications_tax_data.config import get_settings
from communications_tax_data.models import (
    BenchmarkJurisdiction,
    BenchmarkRate,
    BenchmarkRateChange,
    CollectionRun,
    CustomerTaxNeed,
    CustomerTaxNeedDetail,
    TaxTypeCrosswalk,
    utcnow,
)
from communications_tax_data.taxonomy import enrich_federal_usf_crosswalk

US_COUNTRIES = ("USA", "PRI", "GUM", "VIR", "ASM", "MNP")


def _chunks(rows: Iterable[dict], size: int = 2000):
    batch = []
    for row in rows:
        batch.append(dict(row))
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


def _tax_concept(category: str | None, description: str | None) -> str | None:
    """Generate a conservative concept candidate; this is not legal approval."""
    value = f"{category or ''} {description or ''}".lower()
    if "universal service" in value or re.search(r"\b(?:f|s)?usf\b", value):
        return "universal_service_fund"
    if "relay" in value or re.search(r"\btrs\b", value):
        return "telecommunications_relay_service"
    if "911" in value:
        return "emergency_911"
    if "988" in value:
        return "emergency_988"
    if "sales tax" in value:
        return "sales_tax"
    if "use tax" in value:
        return "use_tax"
    if "excise" in value:
        return "excise_tax"
    if "gross receipt" in value:
        return "gross_receipts_tax"
    if "utility user" in value:
        return "utility_users_tax"
    if "franchise" in value:
        return "franchise_fee"
    if "p.u.c" in value or "public utility commission" in value:
        return "public_utility_assessment"
    if "regulatory fee" in value:
        return "regulatory_fee"
    return None


def _signature(row: dict) -> str:
    payload = "|".join(
        [
            str(row["tax_type"]),
            str(row["tax_level"]),
            (row.get("tax_category") or "").strip().casefold(),
            (row.get("tax_description") or "").strip().casefold(),
        ]
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def sync_benchmark(session: Session) -> dict[str, int]:
    """Refresh local benchmark tables from the read-only Apeiron replica."""
    benchmark_engine: Engine = create_engine(
        get_settings().benchmark_url(),
        pool_pre_ping=True,
        future=True,
    )
    run = CollectionRun(collector="avalara-benchmark-sync", status="running")
    session.add(run)
    session.flush()
    counts = {
        "jurisdictions": 0,
        "rates": 0,
        "rate_changes_inserted": 0,
        "customer_needs": 0,
        "customer_need_details": 0,
        "tax_type_candidates_inserted": 0,
    }
    try:
        session.execute(delete(CustomerTaxNeedDetail))
        session.execute(delete(BenchmarkRate))
        session.execute(delete(BenchmarkJurisdiction))
        session.execute(delete(CustomerTaxNeed))
        session.flush()
        with benchmark_engine.connect().execution_options(stream_results=True) as connection:
            address_sql = text(
                """
                SELECT id AS benchmark_id, p_code, alternate, country_iso,
                       state AS state_code, county AS county_name,
                       city_locality AS locality_name, zip_begin, zip_end,
                       `timestamp` AS source_timestamp
                FROM apeiron_avalara_alladr
                WHERE country_iso IN ('USA','PRI','GUM','VIR','ASM','MNP')
                ORDER BY id
                """
            )
            for batch in _chunks(connection.execute(address_sql).mappings()):
                now = utcnow()
                for row in batch:
                    row["synced_at"] = now
                session.execute(BenchmarkJurisdiction.__table__.insert(), batch)
                counts["jurisdictions"] += len(batch)
                session.flush()
            rate_sql = text(
                """
                SELECT id AS benchmark_id, p_code, tax_type, tax_level, effective_date,
                       active, tax_category, tax_description, level_exemptible, rate,
                       max_base, county_override_tax, state_override_tax,
                       state_override_on, county_override_on,
                       `timestamp` AS source_timestamp
                FROM apeiron_avalarataxrate
                ORDER BY id
                """
            )
            for batch in _chunks(connection.execute(rate_sql).mappings()):
                now = utcnow()
                for row in batch:
                    row["synced_at"] = now
                session.execute(BenchmarkRate.__table__.insert(), batch)
                counts["rates"] += len(batch)
                session.flush()
            last_change_id = (
                session.scalar(select(func.max(BenchmarkRateChange.benchmark_change_id))) or 0
            )
            change_sql = text(
                """
                SELECT id AS benchmark_change_id, `timestamp` AS source_timestamp,
                       run_timestamp, p_code, tax_category, tax_description,
                       old_effective_date, new_effective_date, old_rate, new_rate,
                       tax_type, tax_level
                FROM apeiron_avalarataxratechangelog
                WHERE id > :last_change_id
                ORDER BY id
                """
            )
            for batch in _chunks(
                connection.execute(change_sql, {"last_change_id": last_change_id}).mappings()
            ):
                now = utcnow()
                for row in batch:
                    row["synced_at"] = now
                session.execute(BenchmarkRateChange.__table__.insert(), batch)
                counts["rate_changes_inserted"] += len(batch)
                session.flush()
            customer_sql = text(
                """
                SELECT c.user_id AS customer_id, c.customer_number,
                       a.p_code, LEFT(TRIM(a.postal_code), 5) AS postal_code,
                       a.plus_four, LEFT(a.state, 8) AS state_code,
                       a.country AS country_code,
                       (c.closed = 0 AND c.test_account = 0
                         AND c.generate_invoices = 1) AS active_customer,
                       MIN(i.stop) AS first_tax_invoice,
                       MAX(i.stop) AS last_tax_invoice,
                       COUNT(*) AS tax_charge_rows,
                       SUM(ABS(t.total)) AS absolute_tax_amount
                FROM apeiron_apeirontaxchargessummary t
                INNER JOIN apeiron_apeironinvoice i ON i.id = t.invoice_id
                INNER JOIN apeiron_apeironcustomer c ON c.user_id = t.customer_id
                LEFT JOIN apeiron_apeironaddress a ON a.id = c.service_address_id
                GROUP BY c.user_id, c.customer_number, a.p_code,
                         LEFT(TRIM(a.postal_code), 5), a.plus_four,
                         LEFT(a.state, 8), a.country,
                         c.closed, c.test_account, c.generate_invoices
                HAVING SUM(t.total <> 0) > 0
                ORDER BY c.user_id
                """
            )
            for batch in _chunks(connection.execute(customer_sql).mappings()):
                now = utcnow()
                for row in batch:
                    row["synced_at"] = now
                session.execute(CustomerTaxNeed.__table__.insert(), batch)
                counts["customer_needs"] += len(batch)
                session.flush()
            trailing_start = date.today() - timedelta(days=365)
            customer_detail_sql = text(
                """
                SELECT c.user_id AS customer_id, c.customer_number,
                       r.p_code, LEFT(TRIM(addr.postal_code), 5) AS postal_code,
                       addr.plus_four, LEFT(addr.state, 8) AS state_code,
                       addr.country AS country_code,
                       r.tax_type, r.tax_level, r.tax_category, r.tax_description,
                       (c.closed = 0 AND c.test_account = 0
                         AND c.generate_invoices = 1) AS active_customer,
                       MIN(i.stop) AS first_tax_invoice,
                       MAX(i.stop) AS last_tax_invoice,
                       COUNT(*) AS tax_charge_rows,
                       SUM(ABS(t.total)) AS lifetime_tax_amount,
                       SUM(CASE WHEN i.stop >= :trailing_start THEN 1 ELSE 0 END)
                         AS trailing_12m_charge_rows,
                       SUM(CASE WHEN i.stop >= :trailing_start
                                THEN ABS(t.total) ELSE 0 END)
                         AS trailing_12m_tax_amount
                FROM apeiron_apeirontaxchargessummary t
                INNER JOIN apeiron_apeironinvoice i ON i.id = t.invoice_id
                INNER JOIN apeiron_apeironcustomer c ON c.user_id = t.customer_id
                INNER JOIN apeiron_avalarataxrate r ON r.id = t.avalara_id
                LEFT JOIN apeiron_apeironaddress addr
                  ON addr.id = c.service_address_id
                WHERE t.total <> 0
                GROUP BY c.user_id, c.customer_number, r.p_code,
                         LEFT(TRIM(addr.postal_code), 5), addr.plus_four,
                         LEFT(addr.state, 8), addr.country,
                         r.tax_type, r.tax_level, r.tax_category,
                         r.tax_description, c.closed, c.test_account,
                         c.generate_invoices
                ORDER BY c.user_id, r.p_code, r.tax_level, r.tax_type
                """
            )
            for batch in _chunks(
                connection.execute(
                    customer_detail_sql,
                    {"trailing_start": trailing_start},
                ).mappings()
            ):
                now = utcnow()
                for row in batch:
                    row["detail_key"] = hashlib.sha256(
                        "|".join(
                            [
                                str(row["customer_id"]),
                                str(row["p_code"]),
                                str(row["tax_type"]),
                                str(row["tax_level"]),
                                (row["tax_category"] or "").strip().casefold(),
                                (row["tax_description"] or "").strip().casefold(),
                            ]
                        ).encode()
                    ).hexdigest()
                    row["trailing_window_start"] = trailing_start
                    row["synced_at"] = now
                session.execute(CustomerTaxNeedDetail.__table__.insert(), batch)
                counts["customer_need_details"] += len(batch)
                session.flush()
            type_sql = text(
                """
                SELECT DISTINCT tax_type, tax_level, tax_category, tax_description
                FROM apeiron_avalarataxrate
                WHERE active = 1
                  AND COALESCE(rate, 0) <> 0
                ORDER BY tax_type, tax_level, tax_category, tax_description
                """
            )
            crosswalk_rows = list(session.scalars(select(TaxTypeCrosswalk)))
            for item in crosswalk_rows:
                item.benchmark_signature = _signature(
                    {
                        "tax_type": item.benchmark_tax_type,
                        "tax_level": item.benchmark_tax_level,
                        "tax_category": item.benchmark_tax_category,
                        "tax_description": item.benchmark_tax_description,
                    }
                )
            session.flush()
            existing = {item.benchmark_signature for item in crosswalk_rows}
            for raw in connection.execute(type_sql).mappings():
                row = dict(raw)
                signature = _signature(row)
                if signature in existing:
                    continue
                session.add(
                    TaxTypeCrosswalk(
                        benchmark_signature=signature,
                        benchmark_tax_type=row["tax_type"],
                        benchmark_tax_level=row["tax_level"],
                        benchmark_tax_category=row["tax_category"],
                        benchmark_tax_description=row["tax_description"],
                        ctd_tax_concept=_tax_concept(row["tax_category"], row["tax_description"]),
                        mapping_status="proposed",
                        mapping_method="normalized_description",
                        confidence="candidate",
                        notes=(
                            "Machine-proposed semantic family only. Taxability, service "
                            "variant, filing entity, and legal review remain required."
                        ),
                    )
                )
                existing.add(signature)
                counts["tax_type_candidates_inserted"] += 1
            counts["federal_usf_crosswalks_enriched"] = enrich_federal_usf_crosswalk(session)
        run.status = "success"
        run.source_count = 5
        run.records_seen = (
            counts["jurisdictions"]
            + counts["rates"]
            + counts["rate_changes_inserted"]
            + counts["customer_needs"]
            + counts["customer_need_details"]
        )
        run.records_inserted = (
            counts["jurisdictions"]
            + counts["rates"]
            + counts["rate_changes_inserted"]
            + counts["customer_needs"]
            + counts["customer_need_details"]
            + counts["tax_type_candidates_inserted"]
        )
        run.details = counts
        run.finished_at = utcnow()
        return counts
    except Exception as exc:
        run.status = "failed"
        run.error = f"{type(exc).__name__}: {exc}"
        run.finished_at = utcnow()
        raise
    finally:
        benchmark_engine.dispose()
