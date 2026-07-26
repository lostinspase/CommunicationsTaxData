from __future__ import annotations

import hashlib
from collections.abc import Iterable
from datetime import date, timedelta
from typing import Any

from sqlalchemy import Engine, create_engine, delete, select, text
from sqlalchemy.orm import Session

from communications_tax_data.collectors.base import CollectionStats, finish_run, start_run
from communications_tax_data.config import get_settings
from communications_tax_data.models import (
    CustomerTaxProfile,
    ProductCatalogItem,
    ProductTaxonomyMap,
    ServiceProductDemand,
    utcnow,
)

UNMAPPED_TAX_GROUP = "__unmapped__"
SOURCE_SYSTEM = "apeiron_product"

# These are operational candidates, not legal conclusions. A reviewer must publish a
# mapping before it can satisfy the product-classification readiness gate.
TAX_GROUP_CANDIDATES: dict[str, tuple[str, str, str]] = {
    "account_nocomm": (
        "non_communications_account_charge",
        "service_address",
        "Account charge with no communications classification in its internal name.",
    ),
    "cellular": (
        "cellular",
        "primary_place_of_use",
        "Wireless service; primary-place-of-use sourcing must be established separately.",
    ),
    "cellualr": (
        "cellular",
        "primary_place_of_use",
        "Apparent legacy misspelling of the cellular tax group; review before publishing.",
    ),
    "cellular-data-usage": (
        "wireless_data",
        "primary_place_of_use",
        "Wireless data usage; bundled and device treatment require separate rules.",
    ),
    "cellular-surcharge": (
        "cellular",
        "primary_place_of_use",
        "Customer charge associated with cellular service, not itself a government tax.",
    ),
    "equipment-included": (
        "bundled_equipment",
        "service_address",
        "Included equipment requires bundle allocation and title-transfer review.",
    ),
    "equipment-lease": (
        "equipment_lease",
        "service_address",
        "Leased tangible equipment candidate.",
    ),
    "equipment-sale": (
        "equipment_sale",
        "ship_to",
        "Tangible equipment sale candidate; ship-to sourcing may differ from service address.",
    ),
    "infosvc-dip": (
        "information_service",
        "service_address",
        "Directory/information-service candidate; communications treatment is state-specific.",
    ),
    "internet_access": (
        "internet_access",
        "service_address",
        "Internet access candidate; do not infer state taxability from the label alone.",
    ),
    "internet_broadband_wireless": (
        "internet_access",
        "service_address",
        "Fixed-wireless broadband candidate.",
    ),
    "mpls-internet": (
        "internet_access",
        "service_address",
        "MPLS internet component candidate; transport and internet may need allocation.",
    ),
    "mpls-network": (
        "private_network_transport",
        "service_address",
        "Private network transport candidate.",
    ),
    "mpls-voice": (
        "private_line_voice_transport",
        "service_address",
        "MPLS voice component candidate.",
    ),
    "network_ip": (
        "private_network_transport",
        "service_address",
        "IP network transport candidate.",
    ),
    "network_lte": (
        "wireless_data",
        "primary_place_of_use",
        "LTE network service candidate.",
    ),
    "paas": (
        "platform_service",
        "service_address",
        "Platform service candidate; bundled communications components need allocation.",
    ),
    "platform_pots": (
        "fixed_local_telephone",
        "service_address",
        "POTS platform component candidate.",
    ),
    "sms": (
        "messaging_service",
        "primary_place_of_use",
        "Messaging service candidate.",
    ),
    "sms-did": (
        "messaging_service",
        "primary_place_of_use",
        "Messaging-enabled number candidate.",
    ),
    "software-license": (
        "software_license",
        "service_address",
        "Software license candidate.",
    ),
    "voice-did": (
        "telephone_number_service",
        "service_address",
        "Telephone-number/DID service candidate.",
    ),
    "voice-feature": (
        "ancillary_telecommunications_service",
        "service_address",
        "Ancillary voice feature candidate.",
    ),
    "voice-platform": (
        "interconnected_voip",
        "primary_place_of_use",
        "Voice platform candidate; confirm whether it includes interconnected VoIP.",
    ),
    "voice-pots": (
        "fixed_local_telephone",
        "service_address",
        "Traditional fixed local exchange candidate.",
    ),
    "voice-tfn": (
        "toll_free_telephone_service",
        "service_address",
        "Toll-free number/service candidate.",
    ),
    "voice-trunk": (
        "interconnected_voip",
        "primary_place_of_use",
        "Voice trunk candidate; product configuration must confirm interconnected VoIP.",
    ),
    "voice-usage": (
        "telecommunications_usage",
        "call_jurisdiction",
        "Usage requires origination/termination and interstate/intrastate classification.",
    ),
    "vpaas": (
        "platform_service",
        "service_address",
        "Video/platform-as-a-service candidate.",
    ),
    "webrtc": (
        "interconnected_voip",
        "primary_place_of_use",
        "WebRTC candidate; PSTN interconnection and service configuration require review.",
    ),
}


def _chunks(rows: Iterable[dict[str, Any]], size: int = 2000):
    batch: list[dict[str, Any]] = []
    for row in rows:
        batch.append(dict(row))
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch


def normalize_tax_group(value: str | None) -> str:
    normalized = (value or "").strip().lower()
    if normalized in {"", "null", "none"}:
        return UNMAPPED_TAX_GROUP
    return normalized[:100]


def seed_product_taxonomy(
    session: Session,
    tax_groups: Iterable[str],
    *,
    effective_from: date = date(1900, 1, 1),
) -> dict[str, int]:
    """Seed missing candidate mappings without overwriting human review."""
    existing = {
        (row.source_system, row.source_tax_group, row.effective_from): row
        for row in session.scalars(select(ProductTaxonomyMap))
    }
    inserted = 0
    known_candidates = 0
    unmapped_candidates = 0
    for raw_group in sorted(set(tax_groups)):
        group = normalize_tax_group(raw_group)
        key = (SOURCE_SYSTEM, group, effective_from)
        if key in existing:
            continue
        candidate = TAX_GROUP_CANDIDATES.get(group)
        category, sourcing_role, notes = candidate or (
            None,
            None,
            "Observed internal tax group has no normalized CTD service-category candidate.",
        )
        session.add(
            ProductTaxonomyMap(
                source_system=SOURCE_SYSTEM,
                source_tax_group=group,
                service_category=category,
                default_sourcing_role=sourcing_role,
                mapping_status="proposed",
                mapping_method="internal_tax_group_candidate",
                confidence="candidate" if candidate else "unmapped",
                source_reference="apeiron.apeiron_apeironproduct.tax_group",
                notes=notes,
                effective_from=effective_from,
            )
        )
        inserted += 1
        known_candidates += int(candidate is not None)
        unmapped_candidates += int(candidate is None)
    return {
        "taxonomy_inserted": inserted,
        "known_candidates_inserted": known_candidates,
        "unmapped_candidates_inserted": unmapped_candidates,
    }


def sync_product_demand(
    session: Session,
    *,
    as_of: date | None = None,
    benchmark_engine: Engine | None = None,
) -> dict[str, Any]:
    """Refresh product, exemption-flag, and trailing billed-demand snapshots."""
    assessment_date = as_of or date.today()
    trailing_start = assessment_date - timedelta(days=365)
    owns_engine = benchmark_engine is None
    engine = benchmark_engine or create_engine(
        get_settings().benchmark_url(), pool_pre_ping=True, future=True
    )
    run = start_run(session, "apeiron-product-demand-sync")
    counts: dict[str, Any] = {
        "as_of": str(assessment_date),
        "trailing_window_start": str(trailing_start),
        "products": 0,
        "customer_profiles": 0,
        "service_product_demands": 0,
        "source_tax_groups": 0,
    }
    observed_groups: set[str] = {"voice-usage", "sms"}
    try:
        session.execute(delete(ServiceProductDemand))
        session.execute(delete(CustomerTaxProfile))
        session.execute(delete(ProductCatalogItem))
        session.flush()
        with engine.connect().execution_options(stream_results=True) as connection:
            product_sql = text(
                """
                SELECT id AS source_product_id, sku, title, active, product_type,
                       tax_type AS source_tax_type, tax_group AS source_tax_group,
                       billing_type, charge_frequency, report_category, product_platform,
                       interstate AS interstate_percent,
                       intrastate AS intrastate_percent,
                       voice_percent, sms_percent, wireless_data_percent, transport_percent
                FROM apeiron_apeironproduct
                ORDER BY id
                """
            )
            for batch in _chunks(connection.execute(product_sql).mappings()):
                now = utcnow()
                for row in batch:
                    row["source_tax_group"] = normalize_tax_group(row["source_tax_group"])
                    row["synced_at"] = now
                    observed_groups.add(row["source_tax_group"])
                session.execute(ProductCatalogItem.__table__.insert(), batch)
                counts["products"] += len(batch)
                session.flush()

            customer_sql = text(
                """
                SELECT c.user_id AS customer_id, c.customer_number,
                       c.service_address_id AS source_address_id,
                       (c.closed = 0 AND c.test_account = 0
                         AND c.generate_invoices = 1) AS active_customer,
                       COALESCE(c.tax_exempt, 0) AS source_tax_exempt,
                       COALESCE(c.tax_exempt_federal, 0) AS source_tax_exempt_federal,
                       COALESCE(c.tax_exempt_state, 0) AS source_tax_exempt_state,
                       COALESCE(c.tax_exempt_local, 0) AS source_tax_exempt_local
                FROM apeiron_apeironcustomer c
                WHERE c.closed = 0
                  AND c.test_account = 0
                  AND c.generate_invoices = 1
                ORDER BY c.user_id
                """
            )
            for batch in _chunks(connection.execute(customer_sql).mappings()):
                now = utcnow()
                for row in batch:
                    row["evidence_status"] = (
                        "source_flag_only"
                        if any(
                            row[field]
                            for field in (
                                "source_tax_exempt",
                                "source_tax_exempt_federal",
                                "source_tax_exempt_state",
                                "source_tax_exempt_local",
                            )
                        )
                        else "not_claimed"
                    )
                    row["synced_at"] = now
                session.execute(CustomerTaxProfile.__table__.insert(), batch)
                counts["customer_profiles"] += len(batch)
                session.flush()

            demand_sql = text(
                """
                SELECT c.user_id AS customer_id, c.customer_number,
                       c.service_address_id AS source_address_id,
                       lines.source_product_id,
                       lines.source_tax_group,
                       lines.charge_type,
                       1 AS active_customer,
                       MIN(lines.invoice_at) AS first_invoice_at,
                       MAX(lines.invoice_at) AS last_invoice_at,
                       COUNT(DISTINCT lines.invoice_id) AS invoice_count,
                       COUNT(*) AS charge_rows,
                       SUM(lines.quantity) AS quantity,
                       SUM(ABS(lines.amount)) AS trailing_billed_amount
                FROM (
                    SELECT s.customer_id, s.invoice_id, i.stop AS invoice_at,
                           oi.product_id AS source_product_id,
                           COALESCE(NULLIF(LOWER(TRIM(p.tax_group)), ''),
                                    '__unmapped__') AS source_tax_group,
                           'recurring' AS charge_type,
                           s.total AS amount, s.quantity AS quantity
                    FROM apeiron_apeironrecurringchargessummary s
                    INNER JOIN apeiron_apeironinvoice i ON i.id = s.invoice_id
                    LEFT JOIN apeiron_apeironorderitem oi ON oi.id = s.order_item_id
                    LEFT JOIN apeiron_apeironproduct p ON p.id = oi.product_id
                    WHERE i.stop >= :trailing_start
                    UNION ALL
                    SELECT s.customer_id, s.invoice_id, i.stop,
                           oi.product_id,
                           COALESCE(NULLIF(LOWER(TRIM(p.tax_group)), ''),
                                    '__unmapped__'),
                           'nonrecurring', s.total, s.qty
                    FROM apeiron_apeironnonrecurringchargessummary s
                    INNER JOIN apeiron_apeironinvoice i ON i.id = s.invoice_id
                    LEFT JOIN apeiron_apeironorderitem oi ON oi.id = s.order_item_id
                    LEFT JOIN apeiron_apeironproduct p ON p.id = oi.product_id
                    WHERE i.stop >= :trailing_start
                    UNION ALL
                    SELECT s.customer_id, s.invoice_id, i.stop,
                           s.product_id,
                           COALESCE(NULLIF(LOWER(TRIM(p.tax_group)), ''),
                                    'cellular-data-usage'),
                           'data_usage', s.total, s.volume
                    FROM apeiron_apeirondatachargessummary s
                    INNER JOIN apeiron_apeironinvoice i ON i.id = s.invoice_id
                    LEFT JOIN apeiron_apeironproduct p ON p.id = s.product_id
                    WHERE i.stop >= :trailing_start
                    UNION ALL
                    SELECT s.customer_id, s.invoice_id, i.stop,
                           NULL, 'voice-usage', 'voice_usage',
                           s.total, s.quantity
                    FROM apeiron_apeironusagechargessummary s
                    INNER JOIN apeiron_apeironinvoice i ON i.id = s.invoice_id
                    WHERE i.stop >= :trailing_start
                    UNION ALL
                    SELECT s.customer_id, s.invoice_id, i.stop,
                           NULL, 'sms', 'message_usage',
                           s.total, s.quantity
                    FROM apeiron_apeironmsgchargessummary s
                    INNER JOIN apeiron_apeironinvoice i ON i.id = s.invoice_id
                    WHERE i.stop >= :trailing_start
                ) lines
                INNER JOIN apeiron_apeironcustomer c ON c.user_id = lines.customer_id
                WHERE c.closed = 0
                  AND c.test_account = 0
                  AND c.generate_invoices = 1
                GROUP BY c.user_id, c.customer_number, c.service_address_id,
                         lines.source_product_id, lines.source_tax_group, lines.charge_type
                ORDER BY c.user_id, lines.source_tax_group, lines.charge_type,
                         lines.source_product_id
                """
            )
            rows = connection.execute(demand_sql, {"trailing_start": trailing_start}).mappings()
            for batch in _chunks(rows):
                now = utcnow()
                for row in batch:
                    row["source_tax_group"] = normalize_tax_group(row["source_tax_group"])
                    observed_groups.add(row["source_tax_group"])
                    row["demand_key"] = hashlib.sha256(
                        "|".join(
                            (
                                str(row["customer_id"]),
                                str(row["source_address_id"] or ""),
                                str(row["source_product_id"] or ""),
                                row["source_tax_group"],
                                row["charge_type"],
                            )
                        ).encode()
                    ).hexdigest()
                    row["trailing_window_start"] = trailing_start
                    row["synced_at"] = now
                session.execute(ServiceProductDemand.__table__.insert(), batch)
                counts["service_product_demands"] += len(batch)
                session.flush()

        counts.update(seed_product_taxonomy(session, observed_groups))
        counts["source_tax_groups"] = len(observed_groups)
        stats = CollectionStats(
            sources=1,
            seen=counts["products"] + counts["service_product_demands"],
            inserted=(
                counts["products"]
                + counts["customer_profiles"]
                + counts["service_product_demands"]
                + counts["taxonomy_inserted"]
            ),
            details=counts,
        )
        finish_run(run, stats)
        counts["collection_run_id"] = run.id
        return counts
    except Exception as exc:
        finish_run(
            run,
            CollectionStats(details=counts),
            status="failed",
            error=f"{type(exc).__name__}: {exc}",
        )
        raise
    finally:
        if owns_engine:
            engine.dispose()
