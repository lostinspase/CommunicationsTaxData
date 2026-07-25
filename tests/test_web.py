from communications_tax_data.models import Source, SourceCheck
from communications_tax_data.web import dashboard_data, source_health


def test_dashboard_data_handles_empty_database(session):
    data = dashboard_data(session)

    assert data["metrics"]["sources"] == 0
    assert data["metrics"]["source_failures"] == 0
    assert data["metrics"]["current_facts"] == 0
    assert data["coverage"] == [
        {"level": 0, "name": "Federal", "public": 0, "benchmark": 0},
        {"level": 1, "name": "State", "public": 0, "benchmark": 0},
        {"level": 2, "name": "County", "public": 0, "benchmark": 0},
        {"level": 3, "name": "Municipal/special", "public": 0, "benchmark": 0},
    ]


def test_source_health_reports_latest_failure(session):
    source = Source(
        code="failed-source",
        name="Failed source",
        publisher="Test",
        source_type="test",
        url="https://example.test/source",
    )
    session.add(source)
    session.flush()
    session.add(SourceCheck(source_id=source.id, error="HTTP 403"))
    session.commit()

    data = dashboard_data(session)
    rows = source_health(failed_only=True, limit=100, session=session)

    assert data["metrics"]["source_failures"] == 1
    assert rows[0]["source"] == "failed-source"
    assert rows[0]["error"] == "HTTP 403"
