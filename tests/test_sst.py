from __future__ import annotations

import hashlib

from communications_tax_data.collectors.base import get_or_create_source
from communications_tax_data.collectors.sst import SstRateCollector
from communications_tax_data.models import Jurisdiction, TaxFact


def test_discovers_current_rate_files():
    html = """
    <a href="ARR2026Q3JUN02.csv">AR</a>
    <a href="KSR2026Q3MAY20.zip">KS</a>
    <a href="../">parent</a>
    """
    assert SstRateCollector._discover(html) == {
        "AR": ("https://www.streamlinedsalestax.org/ratesandboundry/Rates/ARR2026Q3JUN02.csv"),
        "KS": ("https://www.streamlinedsalestax.org/ratesandboundry/Rates/KSR2026Q3MAY20.zip"),
    }


def test_loads_effective_dated_rate_variants(session):
    source, _ = get_or_create_source(
        session,
        code="sst-rate-ar",
        name="AR",
        publisher="SST",
        source_type="machine_readable_rate",
        url="https://example.test/ARR.csv",
        state_code="AR",
    )
    content = (
        b"05,45,05,0.065,0.065,0.065,0.065,20260101,29991231\n"
        b"05,00,001,0.0125,0.0125,0.0100,0.0100,20260701,20260930\n"
    )
    stats = SstRateCollector()._load_file(
        session,
        source=source,
        filename="ARR.csv",
        content=content,
        digest=hashlib.sha256(content).hexdigest(),
    )
    session.flush()
    assert stats.seen == 2
    assert session.query(Jurisdiction).count() == 2
    assert session.query(TaxFact).count() == 8
    state_fact = (
        session.query(TaxFact)
        .filter(TaxFact.natural_key == "sst:AR:45:05:general_intrastate")
        .one()
    )
    assert str(state_fact.rate) == "0.065000000"
    assert state_fact.effective_to is None
