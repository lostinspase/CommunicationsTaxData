# Production deployment

## Host layout

The initial production installation uses the existing `cdrcost3` operating pattern:
user-owned application files, an isolated Python runtime, cron scheduling, file locks,
and append-only operational logs.

- Application: `/home/apeironsys/communications-tax-data`
- Python environment: `/home/apeironsys/communications-tax-data/.venv`
- Secret configuration: `/home/apeironsys/communications-tax-data/.env` (`0600`)
- Reports: `/home/apeironsys/communications-tax-data/reports`
- Logs: `/home/apeironsys/communications-tax-data/logs`
- Runtime locks: `/home/apeironsys/communications-tax-data/runtime`
- Dashboard: `127.0.0.1:8091`

The dashboard binds to loopback only. Reach it from a workstation with:

```bash
ssh -L 8091:127.0.0.1:8091 cdrcost3.apeiron.io
```

Then open <http://127.0.0.1:8091>.

## Schedule

The server clock is UTC:

- Daily 06:17: source catalog, federal facts, due-source monitoring, benchmark refresh,
  comparison, and exception report.
- Sunday 07:37: SST state/local sales and use files, comparison, and report.
- First day of each month 08:57: Census relationships, comparison, and report.
- Every five minutes and at reboot: ensure the loopback dashboard is running.

Every data job uses the same non-blocking `flock`, so collections cannot overlap. A
skipped run is recorded in `logs/refresh.log` and the next scheduled run retries it.

## Operations

```bash
cd /home/apeironsys/communications-tax-data

# Manual daily refresh
deploy/run-refresh.sh daily

# Check dashboard
curl -fsS http://127.0.0.1:8091/api/health

# Inspect recent activity
tail -100 logs/refresh.log
tail -100 logs/dashboard.log

# Review schedule
crontab -l
```

The `.env` file and generated row-level reports are not committed to Git.

## Initial deployment record

Production was initialized on 2026-07-25:

- Host alias: `cdrcost3.apeiron.io`
- Database: `apeirondb` on MariaDB 10.6
- Application commit installed: `1a22da3c6aacbad7bdad19831566539545e98d8e`
- Initial atomic bootstrap: 569,736 rows across nine `ctd_*` tables
- Dashboard/API health: passing on `127.0.0.1:8091`
- Cron daemon and installed application schedule: active
- Manual daily workflow: completed successfully in approximately 82 seconds
- Production comparison: 39,337 active benchmark rates, 45,508 current public facts,
  and 43,863 open exceptions

Comparison runs preserve prior exceptions as `superseded`, so total exception-table rows
grow over time while the dashboard reports only the current open set.
