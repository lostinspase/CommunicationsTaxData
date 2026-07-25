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

ZIP recognition, p_code completeness, tax-rule matching, reviewed taxonomy mapping,
filing-entity mapping, and calculation-ready location profiles are separate dimensions.
The dashboard does not collapse them into one blended percentage.

## Filing and payment map

`ctd_tax_filing_map` links an effective-dated CTD concept and optional benchmark
tax-type/location key to the report recipient, payment recipient, return or portal,
exemption document, cadence, due rule, reporting basis, and legal citation. Federal seed
records are public-source verified. State/local mappings remain exceptions until their
exact tax-type and jurisdiction association is reviewed.

## Location identifiers

Avalara p_codes are stored in the benchmark namespace. CTD's canonical identifier is a
deterministic `CTD-…` profile code based on the effective jurisdiction composition.
Current ZCTA relationships generate only statistical candidate profiles. They retain
the benchmark p_code as a cross-reference when unambiguous, but remain
`calculation_ready=false`.

## Trust levels

- `authoritative=true`: agency, legislature, regulator, or its designated administrator.
- `authoritative=false`: statistical or directory source useful for discovery/assignment,
  but not sufficient legal authority for tax calculation.
- `confidence=statistical`: Census ZCTA relationships.
- Future address assignments must use explicit values such as `zip4`, `parcel`, `rooftop`,
  or `manual_legal_review`; they must not silently upgrade Census evidence.

## Failure behavior

- A collector parser mismatch fails the collection run and leaves prior facts intact.
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
