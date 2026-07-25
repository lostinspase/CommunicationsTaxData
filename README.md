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
- `/api/coverage-metrics?scope=customer_active`
- `/api/priority-locations?active_only=true&recent_days=365`
- `/api/tax-types?mapping_status=proposed`
- `/api/filing-map?tax_type=6`
- `/api/changes?change_source=benchmark`
- `/api/location-profiles?calculation_ready=false`

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
uv run ctd seed-filing-map
uv run ctd build-location-profiles
uv run ctd compare
uv run ctd report
```

`ctd report` writes:

- `reports/coverage-summary.json` — counts by type, severity, and state
- `reports/coverage-exceptions.csv` — actionable row-level gaps

Generated reports are ignored by Git because they can describe licensed benchmark data.

Tax-type APIs and coverage metrics use one record per distinct active Avalara `tax_type`
with a nonzero rate. Repeated p_code/rate rows and zero-rate placeholders are excluded.
FUSF service and billing variants are normalized under one legal FUSF concept; see
[`docs/federal-fusf-taxonomy.md`](docs/federal-fusf-taxonomy.md).

For a first production deployment, a previously verified local seed can be copied in
bounded batches and one atomic transaction:

```bash
uv run ctd bootstrap --source communications_tax_data.sqlite3 --replace
```

`--replace` deletes and reloads only tables owned by the CTD model (`ctd_*`). It never touches existing
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
- `ctd_benchmark_rate_change`: append-only mirror of the supplied Avalara changelog.
- `ctd_customer_tax_need`: customer-number/location priority set derived from actual
  nonzero invoice-tax history.
- `ctd_coverage_metric`: versioned numerator, denominator, percentage, methodology, and
  scope for total and customer-weighted comparisons.
- `ctd_tax_type_crosswalk`: proposed and reviewed mappings from Avalara
  type/level/description signatures to CTD concepts.
- `ctd_tax_fact_change`: field-level history for changes to normalized public facts.
- `ctd_filing_entity`, `ctd_filing_document`, and `ctd_tax_filing_map`: reporting entity,
  payment recipient, return/portal, exemption document, cadence, due rule, and citation.
- `ctd_location_profile` and `ctd_location_profile_member`: CTD-owned, effective-dated
  jurisdiction-set identifiers. Current Census-derived profiles are explicitly
  `calculation_ready=false`.
- `ctd_coverage_exception`: versioned, row-level missing-rate, rate-mismatch, geographic,
  parser, and filing-map gaps.

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

Coverage is reported independently for the full benchmark universe; every customer that
has ever had nonzero invoice tax; active/non-test/invoice-generating customers with tax
history; and trailing-12-month customers with and without the active filter. Each scope
separates ZIP recognition, p_code availability, exact rate rows, candidate/reviewed tax
types, full p_code coverage, and filing-entity coverage.

## p_code policy

Avalara `p_code` remains an opaque benchmark/external identifier. CTD stores it for
comparison and continuity with existing invoices, but does not invent values in
Avalara's namespace. CTD generates deterministic `CTD-…` location-profile codes from an
effective-dated jurisdiction composition. A calculation engine may use a profile only
when `calculation_ready=true`; Census ZIP/ZCTA candidates remain false until an
authoritative ZIP+4, rooftop, parcel, or reviewed legal assignment supports them.

## Scheduled operation

The production schedule is installed on `cdrcost3` by `deploy/install-cron.sh`; see
[docs/production-deployment.md](docs/production-deployment.md). The
`.github/workflows/collect.yml` workflow is retained as a manual recovery/validation
option. Its runner must have network access to the MariaDB target and benchmark replica.

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
