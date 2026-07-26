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

- Daily 06:17: source catalog, federal and validated state facts, due-source monitoring,
  benchmark refresh, product-demand sync, new/changed active-address resolution, daily
  level-by-level address assessment, service-aware shadow determination, comparison, and
  exception reports.
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
curl -fsS http://127.0.0.1:8091/api/location-resolver
curl -fsS http://127.0.0.1:8091/api/location-assessments?new_only=true
curl -fsS http://127.0.0.1:8091/api/tax-determination?manual_only=true
curl -fsS http://127.0.0.1:8091/api/product-taxonomy

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

## Customer-priority and filing-map extension

Production was upgraded on 2026-07-25 to commit
`a7b6dbbfa3ffc9a6d1e3ff5ba57b16c758b8bd7f`:

- 114,384 benchmark changelog rows were imported append-only.
- 840 customer tax-need records were derived from nonzero invoice tax; 565 are active.
- 591 benchmark tax signatures were staged, with 419 semantic concept candidates and
  zero mappings counted as reviewed.
- 36 source-verified federal tax-type filing maps link four entities and five filing or
  exemption documents.
- 403 CTD location profiles were generated for priority ZIP/ZIP+4 keys; all remain
  statistical and `calculation_ready=false`.
- The active-customer comparison reports 543/565 statistical ZIP recognition,
  1,986/15,187 strict rate-row matches, and 0/210 fully covered p_codes.
- Dashboard and JSON endpoints were verified on `127.0.0.1:8091`; 15 automated tests and
  lint pass in the release workspace.

## Distinct nonzero tax-type correction

Production was upgraded on 2026-07-25 to commit
`36b7a8ad0d0a63ce2d8f1814a61917c5ae40929b`:

- The tax denominator is now 299 distinct active, nonzero Avalara `tax_type` values,
  rather than 39,337 repeated active rate rows.
- The federal slice is 27 distinct nonzero types. Current strict public-rate support
  reaches 21 of 27 federal types; the total/customer-active metrics are 21/299 and
  21/259 respectively.
- The twelve nonzero Avalara FUSF types are normalized to one CTD FUSF concept with
  cited service, revenue-allocation, and customer-billing rules.
- Five FCC/eCFR FUSF authorities were added to monitored sources.
- One rate exception is now emitted per distinct nonzero tax type. The comparison
  superseded 34,219 obsolete row-based exceptions and left 11,140 current open
  exceptions, including postal, filing-route, and parser gaps.
- The dashboard and `/api/tax-types` were restarted and verified on
  `127.0.0.1:8091`. Seventeen automated tests and lint pass in the release workspace.

## 50-state authority register

Production was upgraded on 2026-07-25 to commit
`971bbdc111036dd333a029931f82f45fe1eda3f4`:

- All 50 official PUC/PSC/commission sites and all 50 state revenue/tax authority
  sites are cataloged independently.
- `/states` and `/api/state-authorities` report source health separately from
  normalized-rule coverage.
- California has two normalized CPUC concepts across sixteen effective versions and
  one CDTFA communications sales/use taxability concept.
- Pennsylvania has three normalized revenue concepts: the 50-mill telecommunications
  gross-receipts tax, the 6% state sales/use rate, and telecommunications taxability
  under 61 Pa. Code § 60.20.
- The first production state run checked six parsed sources and inserted twenty fact
  versions with twenty append-only change records.
- A forced monitor checked 152 sources. Forty PUC/PSC sites and forty-three revenue
  sites were reachable; the remaining sites reported explicit 403, TLS, connection
  reset, or server-specific 404 failures for follow-up.
- The 50-state HTML register, JSON summary, production comparison, 20 automated tests,
  and lint all passed.

## Location Resolver v1

Production was upgraded on 2026-07-26 through commit
`21b9fb6b79a54f1ed0ff8e73140bf35cf0cace73`:

- 542 distinct current service addresses are in the active-customer, nonzero-invoice-tax
  priority footprint; no customer identities or copied street addresses are exposed by
  the resolver dashboard/API.
- 465 addresses resolve to core Census state/county geography (85.79%): 93 from existing
  coordinates and 372 from Census address-range matches. The footprint reuses 217
  deterministic `CTD-JUR-*` jurisdiction-set profiles.
- 69 addresses are unmatched, seven lack sufficient address/coordinate input, and one
  is ambiguous. All are retained as explicit current assignment statuses.
- 119 priority address rows have ZIP+4 input. ZIP+4 is recorded as evidence, not treated
  as a nationwide tax-boundary or p_code equivalent.
- Among comparable Avalara rows, state agreement is 462/462, county agreement is
  435/462, and legal-place/county-subdivision agreement with the Avalara locality label
  is 290/459. Differences remain diagnostic and do not control CTD assignment.
- All 542 assignments remain `calculation_ready=false`; communications-tax, 911, sales-tax,
  and special-district boundary evidence is still required.
- Assignment versions carry collection-run evidence and supersede rather than overwrite
  a changed address/profile result. HTTP client request URLs are suppressed from INFO
  logs because resolver query strings can carry address or coordinate inputs.
- `/locations`, `/api/location-resolver`, daily new/changed resolution, monthly forced
  revalidation, 27 automated tests, lint, and dashboard restart/health checks passed.

## Daily active-address assessment

Production was extended on 2026-07-26 through commit
`7b81776ab92975d9bc64326d5daecd78c50d01b9` to cover every active, non-test,
invoice-generating service address, including
addresses that have not yet appeared on a taxed invoice:

- The active universe is 704 distinct service addresses. The first expanded run added
  162 addresses and 65 previously unseen CTD jurisdiction-set profiles.
- Resolver coverage is 566/704 core geography results (80.40%), with 75 unmatched,
  62 insufficient-input, and one ambiguous result. The active footprint uses 282 CTD
  profiles; 213 source rows have ZIP+4 input.
- Daily assessment run 64 correctly reports the 162-address new cohort. All 704 addresses
  currently require some manual coverage and none is calculation-ready.
- Address-route coverage is reported independently by level: federal public rules
  8,448/19,008 and filing 19,008/19,008; state public rules 1,529/8,934 and filing
  1,161/8,934; county 679/2,646 for both; municipal/special public rules 515/2,154 and
  filing 366/2,154. These are summed distinct nonzero tax-type routes per address, not
  unique tax-type counts.
- `reports/location-assessment-summary.json` and the 704-row
  `reports/location-assessment-gaps.csv` were generated. The gap CSV includes internal
  source address ID, ZIP, CTD profile, benchmark p_code reference, resolver status, and
  per-level missing type IDs; it excludes street and customer data.
- `/location-assessments` and `/api/location-assessments` passed live checks. The daily
  refresh now resolves addresses and writes this assessment after filing-map refresh;
  28 automated tests and lint pass.

## Service-aware tax determination v1

Production was upgraded on 2026-07-26 through commit
`6afba56c6bd93537e3fd2d618131f3dc4bcc0a86`:

- The product-demand sync loaded 929 Apeiron products, 10,661 active customer tax
  profiles, and 5,571 distinct trailing-year billed product/address/charge-type demands
  across 601 service addresses and $8,143,741.79 of billed charges.
- Thirty-one source tax groups are in the review queue. Thirty received known candidate
  classifications and one remained unmapped. All candidates remain deliberately
  `proposed`; collection never self-approves a legal product classification.
- Assessment run 70 stored 5,571 immutable shadow snapshots. All are new on the first
  run and all remain manual: product, location/sourcing, taxability, filing, and final
  calculation are zero-ready until their legal evidence is reviewed. Exemption evidence
  passes 5,571/5,571 because no applicable source exemption claim currently requires a
  missing verified certificate in this demand set.
- The largest exposure gaps are missing reviewed tax-concept maps (5,571 rows,
  $8,143,741.79), unreviewed product mappings (4,368 rows, $8,021,311.72), missing
  required-role sourcing assignments (2,932 rows, $6,855,124.66), and unverified tax
  boundaries (2,639 rows, $1,288,617.13). One unmapped product group affects 1,203 rows
  and $122,430.07.
- MariaDB production compatibility fixes bound assessment insert batches and normalize
  report sorting for unresolved address IDs. API summaries defer large route-evidence
  JSON; detailed evidence is opt-in with `include_routes=true`.
- Live checks returned the product taxonomy in 0.48 seconds, a one-row determination
  summary in 0.91 seconds, opt-in route evidence in 1.10 seconds, and the HTML dashboard
  in 1.12 seconds. Customer identities and street addresses are absent from these
  outputs. Thirty-two automated tests and lint pass.
