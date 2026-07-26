# Architecture and operating controls

## Pipeline

1. **Discover** current authoritative source artifacts.
2. **Retrieve** with an identified user agent and store check metadata and SHA-256.
3. **Parse** into source-specific records; fail visibly if the published format changes.
4. **Normalize** jurisdiction, tax family, service category, unit, base, citations, and
   effective period.
5. **Compare** against the commercial benchmark using strict matching.
6. **Report** missing facts, mismatches, geographic gaps, stale sources, and parser gaps.
7. **Review** interpretive changes before a calculation engine consumes them.

The acquisition loop is demand-driven: `benchmark-sync` joins invoice tax charges to the
exact licensed rate row that produced them, stores trailing-365-day demand by
type/level/p_code, and exposes an aggregate-only work queue. No customer identifiers are
returned by that queue.

Collectors are idempotent by natural key plus effective date. They do not overwrite a
historical period with a new current value.

## Change ledgers

Change detection has three distinct layers:

- `ctd_source_check` records every retrieval, response/hash, and whether the source
  artifact changed.
- `ctd_tax_fact_change` records inserted or changed normalized fields and ties the event
  to the collection run. Effective-dated facts remain the calculation history.
- `ctd_benchmark_rate_change` incrementally mirrors the licensed comparison changelog.
  It is benchmark evidence only and is never treated as a public upstream source.

## Coverage denominators

`ctd_coverage_metric` keeps the numerator and denominator for each run. Full-universe
coverage and customer-priority coverage are not interchangeable. The primary operational
scope is active, non-test, invoice-generating customers that have had nonzero invoice
tax. Historical and trailing-12-month scopes remain alongside it.

Tax coverage uses distinct active Avalara `tax_type` values with a nonzero rate. Zero-rate
placeholders and repeated p_code/rate rows are excluded. Tax levels, jurisdictions,
categories, descriptions, and service variants remain attributes and routing rules, not
additional tax identities. ZIP recognition, reviewed taxonomy mapping, public-law
support, filing-entity mapping, and calculation-ready location profiles are separate
dimensions. The dashboard does not collapse them into one blended percentage.

## Filing and payment map

`ctd_tax_filing_map` links an effective-dated CTD concept and optional benchmark
tax-type/location key to the report recipient, payment recipient, return or portal,
exemption document, cadence, due rule, reporting basis, and legal citation. Federal seed
records are public-source verified. A local `recipient_verified` record means an adopted
ordinance names the recipient and due rule, but a public return/portal has not been
found; it remains a filing exception. State/local mappings otherwise remain exceptions
until their exact tax-type and jurisdiction association is reviewed.

`ctd_tax_fact_benchmark_map` is the state-aware legal bridge between a public fact and a
commercial type/level route. It includes optional p_code scope so a New York citation
cannot cover the same numeric type in another state. A source-verified bridge may support
comparison and work-queue coverage; interpretive product/base decisions still require
review before calculation use.

## Location identifiers

Avalara p_codes are stored in the benchmark namespace. CTD's canonical identifier is a
deterministic `CTD-JUR-…` profile code based only on the sorted effective jurisdiction
composition—not on a street address, ZIP, or Avalara p_code. Therefore addresses with
the same state/county/incorporated-place/county-subdivision set reuse one CTD profile.

Location Resolver v1 reads only the service-address rows required by active, non-test,
invoice-generating customers, including new addresses with no invoice-tax history. It prefers an existing
valid coordinate and otherwise calls the official Census current address-range
geocoder. It creates an effective-dated `ctd_address_assignment`, retaining the source
address row ID and a one-way address fingerprint instead of copying the street address.
The dashboard and resolver API return aggregates only.
On an unrestricted full-footprint run, a current assignment whose source address is no
longer in the priority population is closed with `valid_to`; limited and fixture runs do
not retire unseen rows.

## Daily address assessment gate

After each daily benchmark refresh, location resolution, and filing-map seed, CTD writes
one `ctd_location_assessment` snapshot for every current active service address. The
snapshot detects a new address, a newly observed jurisdiction-set profile, a profile
change, or a change in available tax content. Each of levels 0–3 records:

- resolved public jurisdiction members and tax-boundary readiness;
- distinct active nonzero benchmark tax-type routes;
- routes backed by a current published public fact and approved legal mapping;
- routes with an approved filing/payment map; and
- explicit manual gap codes and missing benchmark tax-type IDs.

An address is complete only when every level is complete. A Census match is useful
location evidence but keeps levels 1–3 in `TAX_BOUNDARY_UNVERIFIED` until an authoritative
tax boundary or reviewed statutory safe harbor is present. When a benchmark level has
no nonzero type, CTD emits `NO_REVIEWED_NO_TAX_DETERMINATION` instead of assuming the
absence of tax. The dashboard/API and generated CSV identify the source address row,
state, ZIP, CTD profile, and p_code comparison reference without copying street or
customer data.

Census state, county, incorporated-place, and county-subdivision identities become core
profile members. A Census designated place is diagnostic evidence only because it is a
statistical geography rather than an incorporated taxing municipality. Avalara
state/county/locality names are compared after resolution as a benchmark diagnostic;
they do not control profile assignment. All v1 assignments remain
`calculation_ready=false` pending authoritative communications-tax, sales-tax, 911, and
special-district boundary evidence or an applicable statutory ZIP safe harbor.

## Trust levels

- `authoritative=true`: agency, legislature, regulator, or its designated administrator.
- `authoritative=false`: statistical or directory source useful for discovery/assignment,
  but not sufficient legal authority for tax calculation.
- `confidence=statistical`: Census ZCTA relationships.
- `confidence=coordinate` or `address_range`: Census Resolver v1 core-geography
  evidence, still non-calculation-ready.
- Future address assignments must use explicit values such as `zip4`, `parcel`, `rooftop`,
  or `manual_legal_review`; they must not silently upgrade Census evidence.

## Failure behavior

- A collector parser mismatch fails the collection run and leaves prior facts intact.
- A transient resolver error leaves the last current address assignment intact, marks
  the run partial, and retries that address on the next daily run.
- The monitor records one source failure without stopping checks of other sources.
- Source hashes show content changes even when a parser yields the same normalized fact.
- Exceptions are superseded, not deleted, on the next comparison.

## Production controls still required

- Least-privilege database users: DDL only for deployment, DML for the agent, read-only
  for the dashboard, and read-only for the Avalara replica.
- TLS verification and private-network routing for MariaDB.
- GitHub environment protection or a secrets manager.
- Human approval states (`proposed`, `reviewed`, `published`) for interpretive taxability
  and base rules.
- Alerts for failed/stale sources and material rate changes.
- Backups and point-in-time recovery for the CTD schema.
