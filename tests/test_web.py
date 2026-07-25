from communications_tax_data.web import dashboard_data


def test_dashboard_data_handles_empty_database(session):
    data = dashboard_data(session)

    assert data["metrics"]["sources"] == 0
    assert data["metrics"]["current_facts"] == 0
    assert data["coverage"] == [
        {"level": 0, "name": "Federal", "public": 0, "benchmark": 0},
        {"level": 1, "name": "State", "public": 0, "benchmark": 0},
        {"level": 2, "name": "County", "public": 0, "benchmark": 0},
        {"level": 3, "name": "Municipal/special", "public": 0, "benchmark": 0},
    ]
