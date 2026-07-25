# CommunicationsTaxData

An auditable collection agent and coverage dashboard for U.S. communications and
sales/use tax data. It stores public facts with source URLs, legal citations, retrieval
history, and effective dates, then compares them with Apeiron's licensed Avalara data
without treating the commercial data as an upstream source.

This is an evidence and gap-management system, not yet a drop-in tax calculation engine.
The first release intentionally reports what public data cannot reproduce.

## First-release coverage

| Data set | Scope | Collector | Important limitation |
|---|---|---|---|
| FCC/USAC USF | Federal quarterly factors | `federal` | Contribution factor is not, by itself, a customer taxability rule |
| FCC TRS | Federal 2026–27 Internet and non-Internet factors | `federal` | Different revenue bases are stored separately |
| IRS communications excise | Federal 3% current operational rule | `federal` | Bundled/long-distance treatment requires the recorded base rule |
| SST rate files | 24 member states; state/county/city/special district sales/use components | `sst` | Does not establish whether a communications product is taxable |
| Census ZCTA relationships | Nationwide ZCTA-to-county and ZCTA-to-place intersections | `census` | Statistical geography, not USPS ZIP+4 or rooftop assignment |
| State DOR catalog | 50 official state landing pages | `monitor` | Non-SST state parsers remain explicit exceptions |
| Avalara benchmark | Supplied address/rate tables from read-only replica | `benchmark-sync` | Used only for completeness comparisons |

All facts use half-open business semantics represented as inclusive `effective_from` and
`effective_to` dates. Source checks preserve hashes, ETags, last-modified headers, status,
timing, and whether content changed.

## Quick start

Python 3.11+ and `uv` are recommended.

```bash
uv sync --extra dev
uv run ctd init
uv run ctd seed-catalog
uv run ctd collect --collector federal
uv run ctd collect --collector sst
uv run ctd collect --collector census
uv run ctd serve
```

Open <http://127.0.0.1:8080>. JSON endpoints are available at:

- `/api/health`
- `/api/coverage`
- `/api/source-health?failed_only=true`
- `/api/rates?state=WA&tax_family=sales_and_use`
- `/api/exceptions?state=CA&exception_type=MISSING_PUBLIC_RATE`

## Database configuration

Copy `.env.example` to `.env`. Do not commit `.env`.

For local development, the default is SQLite. For MariaDB:

```dotenv
CTD_DATABASE_URL=
CTD_DB_HOST=database-host
CTD_DB_PORT=3306
CTD_DB_NAME=apeirondb
CTD_DB_USER=service-account
CTD_DB_PASSWORD=secret
```

The benchmark connection is deliberately separate and should remain read-only:

```dotenv
CTD_AVALARA_HOST=replica-host
CTD_AVALARA_PORT=3306
CTD_AVALARA_NAME=apeiron
CTD_AVALARA_USER=read-only-account
CTD_AVALARA_PASSWORD=secret
```

Passwords are assembled with SQLAlchemy's structured URL API, so special characters do
not need to be hand-escaped.

## Complete collection and comparison run

```bash
uv run ctd init
uv run ctd seed-catalog
uv run ctd collect --collector all
uv run ctd benchmark-sync
uv run ctd compare
uv run ctd report
```

`ctd report` writes:

- `reports/coverage-summary.json` — counts by type, severity, and state
- `reports/coverage-exceptions.csv` — actionable row-level gaps

Generated reports are ignored by Git because they can describe licensed benchmark data.

For a first production deployment, a previously verified local seed can be copied in
bounded batches and one atomic transaction:

```bash
uv run ctd bootstrap --source communications_tax_data.sqlite3 --replace
```

`--replace` deletes and reloads only the nine `ctd_*` tables. It never touches existing
Apeiron application tables.

## Data model

- `ctd_source` and `ctd_source_check`: source ownership, cadence, parser, retrieval
  evidence, and change detection.
- `ctd_collection_run`: collector audit log and record counts.
- `ctd_jurisdiction`: effective-dated federal/state/county/municipal/special entities.
- `ctd_postal_assignment`: ZIP/ZCTA/ZIP+4-to-jurisdiction evidence with confidence and
  assignment method.
- `ctd_tax_fact`: normalized rate/fee, unit, base rule, service category, citation, and
  effective dates.
- `ctd_benchmark_jurisdiction` and `ctd_benchmark_rate`: replaceable snapshots of the two
  supplied commercial tables.
- `ctd_coverage_exception`: versioned, row-level missing-rate, rate-mismatch, geographic,
  and parser gaps.

The project uses a `ctd_` prefix so initialization is isolated from existing Apeiron
tables. `ctd init` is idempotent and does not alter non-CTD tables.

## Comparison policy

The comparison is conservative:

1. A source being monitored does not count as rate coverage.
2. A state sales/use rate does not count as communications taxability coverage.
3. A ZCTA-to-place overlap does not count as rooftop or ZIP+4 coverage.
4. A benchmark fact is credited only when tax identity, rate, jurisdiction, and effective
   period can be normalized.
5. Previous open exceptions are retained as `superseded`; history is not destroyed.

This prevents a high-looking completion percentage built from unlike records.

## Scheduled operation

`.github/workflows/collect.yml` runs collection and comparison daily when its environment
secrets are configured. The runner must have network access to the MariaDB target and
benchmark replica. For private IPs, use a self-hosted runner on the Apeiron network.

Required GitHub environment secrets:

- `CTD_DB_HOST`, `CTD_DB_NAME`, `CTD_DB_USER`, `CTD_DB_PASSWORD`
- `CTD_AVALARA_HOST`, `CTD_AVALARA_NAME`, `CTD_AVALARA_USER`,
  `CTD_AVALARA_PASSWORD`

## What remains before calculation-engine parity

The exception report is the work queue. The largest substantive workstreams are:

- state communications taxability matrices, exemptions, bases, and tax-on-tax ordering;
- state USF, TRS, PUC, 911/988, regulatory, and gross-receipts collectors;
- non-SST state/local sales and use rate parsers;
- local UUT, franchise, license, and communications-tax ordinances;
- current USPS ZIP+4 or licensed address GIS plus 911/rate-center boundaries;
- service/product taxonomy mapping to Apeiron's engine;
- legal review and approval workflow for interpretive rules.

See [docs/architecture.md](docs/architecture.md) and
[docs/source-coverage.md](docs/source-coverage.md). Production installation and
operations are documented in
[docs/production-deployment.md](docs/production-deployment.md).

## Development

```bash
uv run ruff check .
uv run pytest
```

No source HTML/PDF, credentials, or licensed benchmark rows are committed.
