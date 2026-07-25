from __future__ import annotations

from sqlalchemy import func, select

from communications_tax_data.catalog import seed_catalog
from communications_tax_data.models import Source
from communications_tax_data.state_authorities import STATE_AUTHORITIES
from communications_tax_data.web import state_authority_data


def test_state_register_is_exactly_50_states():
    codes = [profile.state_code for profile in STATE_AUTHORITIES]

    assert len(codes) == 50
    assert len(set(codes)) == 50
    assert "DC" not in codes
    assert sum(profile.sst_membership == "full" for profile in STATE_AUTHORITIES) == 23
    assert sum(profile.sst_membership == "associate" for profile in STATE_AUTHORITIES) == 1
    assert all(profile.commission_url.startswith("https://") for profile in STATE_AUTHORITIES)
    assert all(profile.revenue_url.startswith("https://") for profile in STATE_AUTHORITIES)


def test_catalog_seeds_both_authority_tracks(session):
    seed_catalog(session)

    assert session.scalar(
        select(func.count())
        .select_from(Source)
        .where(Source.source_type == "state_communications_regulator")
    ) == 50
    assert session.scalar(
        select(func.count())
        .select_from(Source)
        .where(Source.source_type == "state_tax_landing")
    ) == 50
    assert session.scalar(
        select(func.count())
        .select_from(Source)
        .where(Source.parser == "state-rules")
    ) == 11


def test_state_page_does_not_count_catalog_as_rule_coverage(session):
    seed_catalog(session)

    data = state_authority_data(session)

    assert data["summary"] == {
        "states": 50,
        "commission_sites_cataloged": 50,
        "revenue_sites_cataloged": 50,
        "puc_rules_started": 0,
        "revenue_rules_started": 0,
        "sst_participants": 24,
    }
    california = next(
        item for item in data["states"] if item["state_code"] == "CA"
    )
    assert california["commission"]["health"]["status"] == "not_checked"
    assert california["commission"]["status"] == "not_pulled"
    assert california["revenue"]["status"] == "not_pulled"
