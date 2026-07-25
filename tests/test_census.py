from communications_tax_data.collectors.census import CensusRelationshipCollector
from communications_tax_data.models import Source


def test_census_allocation_is_idempotent_at_database_precision(session):
    source = Source(
        code="test-census",
        name="Test Census",
        publisher="Census",
        source_type="geographic_relationship",
        url="https://example.test/census.txt",
    )
    session.add(source)
    session.commit()
    content = (
        b"GEOID_ZCTA5_20|GEOID_COUNTY_20|NAMELSAD_COUNTY_20|"
        b"AREALAND_ZCTA5_20|AREALAND_PART\n"
        b"12345|01001|Autauga County|3|1\n"
    )

    first = CensusRelationshipCollector._load_relationship(session, source, "county", content)
    session.commit()
    session.expire_all()
    second = CensusRelationshipCollector._load_relationship(session, source, "county", content)

    assert first.inserted == 2
    assert second.inserted == 0
    assert second.updated == 0
