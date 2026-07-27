from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from communications_tax_data.collectors.base import (
    CollectionStats,
    finish_run,
    get_with_retry,
    http_client,
    record_error,
    record_response,
    start_run,
)
from communications_tax_data.models import Source, SourceCheck, utcnow


class SourceMonitor:
    name = "source-monitor"

    @staticmethod
    def _raise_for_soft_error(response) -> None:
        path = response.url.path.lower()
        markers = ("/404error", "/404-error", "/page-not-found", "/not-found")
        if any(marker in path for marker in markers):
            raise ValueError(f"Source redirected to an error page: {response.url}")

    @staticmethod
    def _due_sources(session: Session, *, now, force: bool) -> list[Source]:
        sources = list(
            session.scalars(select(Source).where(Source.active.is_(True)).order_by(Source.id))
        )
        if force:
            return sources
        latest_check_ids = select(func.max(SourceCheck.id)).group_by(SourceCheck.source_id)
        failed_source_ids = set(
            session.scalars(
                select(SourceCheck.source_id).where(
                    SourceCheck.id.in_(latest_check_ids),
                    SourceCheck.error.is_not(None),
                )
            )
        )
        return [
            source
            for source in sources
            if source.last_checked_at is None
            or (source.id in failed_source_ids and source.last_checked_at < now - timedelta(days=1))
            or source.last_checked_at < now - timedelta(days=source.cadence_days)
        ]

    def collect(self, session: Session, *, force: bool = False) -> CollectionStats:
        run = start_run(session, self.name)
        stats = CollectionStats()
        now = utcnow()
        sources = self._due_sources(session, now=now, force=force)

        def fetch(client, source):
            started = time.monotonic()
            try:
                response = get_with_retry(client, source.url)
                response.raise_for_status()
                self._raise_for_soft_error(response)
                return source, started, response, None
            except Exception as exc:
                return source, started, None, exc

        with http_client() as client, ThreadPoolExecutor(max_workers=8) as executor:
            futures = [executor.submit(fetch, client, source) for source in sources]
            for future in as_completed(futures):
                source, started, response, error = future.result()
                stats.sources += 1
                if error is None:
                    assert response is not None
                    record_response(
                        session, source=source, run=run, response=response, started=started
                    )
                    stats.seen += 1
                else:  # one source must not stop the monitor
                    record_error(session, source=source, run=run, error=error, started=started)
                    stats.details.setdefault("errors", []).append(
                        {"source": source.code, "error": str(error)}
                    )
        finish_run(run, stats, status="partial" if stats.details.get("errors") else "success")
        return stats
