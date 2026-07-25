from datetime import timedelta

from communications_tax_data.collectors.monitor import SourceMonitor
from communications_tax_data.models import Source, SourceCheck, utcnow


def _source(code: str, last_checked_at, cadence_days: int = 30) -> Source:
    return Source(
        code=code,
        name=code,
        publisher="Test",
        source_type="test",
        url=f"https://example.test/{code}",
        last_checked_at=last_checked_at,
        cadence_days=cadence_days,
    )


def test_failed_sources_retry_daily_while_healthy_sources_keep_cadence(session):
    now = utcnow()
    failed = _source("failed", now - timedelta(days=2))
    healthy = _source("healthy", now - timedelta(days=2))
    normally_due = _source("normally-due", now - timedelta(days=31))
    never_checked = _source("new", None)
    session.add_all([failed, healthy, normally_due, never_checked])
    session.flush()
    session.add_all(
        [
            SourceCheck(
                source_id=failed.id,
                checked_at=failed.last_checked_at,
                error="HTTPStatusError: transient failure",
            ),
            SourceCheck(
                source_id=healthy.id,
                checked_at=healthy.last_checked_at,
                status_code=200,
            ),
        ]
    )
    session.commit()

    due = SourceMonitor._due_sources(session, now=now, force=False)

    assert [source.code for source in due] == ["failed", "normally-due", "new"]
    assert len(SourceMonitor._due_sources(session, now=now, force=True)) == 4
