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
