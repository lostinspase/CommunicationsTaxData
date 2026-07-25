from communications_tax_data.filing import seed_federal_filing_map
from communications_tax_data.models import FilingDocument, FilingEntity, TaxFilingMap
from communications_tax_data.web import filing_map


def test_federal_filing_seed_is_idempotent(session):
    first = seed_federal_filing_map(session)
    session.flush()

    assert first == {
        "entities_inserted": 4,
        "documents_inserted": 5,
        "maps_inserted": 36,
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
    }
    assert session.query(TaxFilingMap).count() == 36
