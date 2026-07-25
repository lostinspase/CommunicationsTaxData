from pathlib import Path

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session

from communications_tax_data.bootstrap import bootstrap_from_sqlite
from communications_tax_data.models import Base, Source


def _source(code: str) -> Source:
    return Source(
        code=code,
        name=code,
        publisher="Test",
        source_type="test",
        url=f"https://example.test/{code}",
    )


def test_bootstrap_requires_replace_for_populated_target(tmp_path: Path):
    source_path = tmp_path / "seed.sqlite3"
    source_engine = create_engine(f"sqlite:///{source_path}")
    target_engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(source_engine)
    Base.metadata.create_all(target_engine)
    with Session(source_engine) as session:
        session.add(_source("seed"))
        session.commit()
    with Session(target_engine) as session:
        session.add(_source("existing"))
        session.commit()

    with pytest.raises(ValueError, match="not empty"):
        bootstrap_from_sqlite(target_engine, source_path)

    counts = bootstrap_from_sqlite(target_engine, source_path, replace=True, batch_size=1)

    assert counts["ctd_source"] == 1
    with Session(target_engine) as session:
        assert session.scalar(select(func.count()).select_from(Source)) == 1
        assert session.scalar(select(Source.code)) == "seed"
