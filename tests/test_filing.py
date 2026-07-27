from sqlalchemy import select

from communications_tax_data.catalog import NY_LOCAL_UTILITY_RULES, seed_catalog
from communications_tax_data.collectors.base import start_run
from communications_tax_data.collectors.state_rules import StateRuleCollector
from communications_tax_data.filing import (
    seed_federal_filing_map,
    seed_state_filing_and_benchmark_maps,
)
from communications_tax_data.models import (
    FilingDocument,
    FilingEntity,
    Source,
    TaxFact,
    TaxFactBenchmarkMap,
    TaxFilingMap,
)
from communications_tax_data.web import filing_map


def test_federal_filing_seed_is_idempotent(session):
    first = seed_federal_filing_map(session)
    session.flush()

    assert first == {
        "entities_inserted": 4,
        "documents_inserted": 5,
        "maps_inserted": 36,
        "federal_usf_crosswalks_enriched": 0,
    }
    assert session.query(FilingEntity).count() == 4
    assert session.query(FilingDocument).count() == 5
    assert session.query(TaxFilingMap).count() == 36

    excise = filing_map(tax_type=6, state=None, limit=100, session=session)
    assert excise[0]["return"]["form"] == "720"
    assert excise[0]["exemption"]["form"] == "Publication 510"
    assert excise[0]["payment_entity"] == "Internal Revenue Service — Excise Tax"

    second = seed_federal_filing_map(session)
    session.flush()

    assert second == {
        "entities_inserted": 0,
        "documents_inserted": 0,
        "maps_inserted": 0,
        "federal_usf_crosswalks_enriched": 0,
    }
    assert session.query(TaxFilingMap).count() == 36


def test_local_ny_utility_rule_maps_rate_and_recipient_without_claiming_form(session):
    seed_catalog(session)
    config = next(item for item in NY_LOCAL_UTILITY_RULES if item["locality"] == "Johnstown")
    source = session.scalar(select(Source).where(Source.code == config["source"]["code"]))
    run = start_run(session, "state-rules")
    content = """
        <html><body>
        City of Johnstown. A tax equal to 1% of gross income is imposed on every
        utility within the territorial limits of the city. Gross operating income
        definitions have the meanings in Subdivision 2 of § 186-a of the Tax Law.
        </body></html>
    """.encode()

    seen, inserted = StateRuleCollector()._parse(
        session,
        run=run,
        source=source,
        jurisdiction=None,
        content=content,
        local_config=config,
    )
    session.flush()

    assert (seen, inserted) == (1, 1)
    fact = session.scalar(
        select(TaxFact).where(TaxFact.natural_key == "ny:local:johnstown:utility-gross-receipts")
    )
    assert str(fact.rate) == "0.010000000"
    assert "modern VoIP" in fact.base_rule
    assert "incorporated by reference" in fact.base_rule

    first = seed_state_filing_and_benchmark_maps(session)
    session.flush()

    assert first["fact_maps_inserted"] == 1
    fact_map = session.scalar(
        select(TaxFactBenchmarkMap).where(
            TaxFactBenchmarkMap.benchmark_tax_type == 14,
            TaxFactBenchmarkMap.benchmark_tax_level == 3,
            TaxFactBenchmarkMap.p_code == 2560500,
        )
    )
    assert fact_map.mapping_status == "source_verified"
    recipient_map = session.scalar(
        select(TaxFilingMap).where(
            TaxFilingMap.benchmark_tax_type == 14,
            TaxFilingMap.tax_level == 3,
            TaxFilingMap.p_code == 2560500,
        )
    )
    assert recipient_map.mapping_status == "recipient_verified"
    assert recipient_map.return_document_id is None
    assert "No public downloadable return was found" in recipient_map.reporting_basis
    entity = session.get(FilingEntity, recipient_map.filing_entity_id)
    assert entity.name == "City of Johnstown — City Treasurer"

    second = seed_state_filing_and_benchmark_maps(session)
    session.flush()

    assert second == {
        "entities_inserted": 0,
        "documents_inserted": 0,
        "filing_maps_inserted": 0,
        "fact_maps_inserted": 0,
        "fact_maps_removed": 0,
    }
