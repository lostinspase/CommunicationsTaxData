# Nexus, Type 1 sales tax, and exemption forms

The `/nexus` dashboard is an informational and operational screen. It does not make an
unreviewed legal conclusion. Each state row keeps four separate questions visible:

1. What does the state's remote-seller threshold say?
2. What revenue did Apeiron bill to service addresses in the state?
3. Does Apeiron have reviewed physical presence, registration, and collection facts?
4. Are product taxability, a Type 1 calculation route, and exemption forms supported?

`ctd seed-nexus` seeds the current 50-state screening matrix and the asserted PA/TX plus
possible CA physical-presence facts supplied for this project. `ctd sync-nexus-exposure`
measures prior- and current-calendar-year invoice revenue by service-address state.
`ctd assess-nexus` writes a daily, append-only outcome and gap list. General sales/use
routes in the shadow determination engine remain blocked until the company determination
is reviewed and collection or registration is active. Telecom-specific provider taxes,
fees, and surcharges are evaluated independently.

## FastSalesTax basic file

The supplied `AS_zip4_basic_07_26.zip` contains 2,629,414 rows, but only five-digit ZIPs.
It reduces to 110,510 distinct state/county/city/sales-rate/use-rate candidates covering
41,319 ZIPs. Repeated rows and split-ZIP candidates are preserved as occurrence counts;
sales and use differ on 320,648 raw rows. This is useful additional combined-rate and
ambiguity evidence, but it cannot replace rooftop assignment because it has no ZIP+4
range, jurisdiction identifiers, component rates, product taxability, or legal citation.

Import it with:

```bash
uv run ctd import-sales-tax-file /path/to/AS_zip4_basic_07_26.zip
```

## Type 1 API

The candidate provider register contains the Certified Service Providers linked from the
Streamlined Sales Tax Governing Board. Selection and credentials are intentionally not
implemented by the seed. A provider adapter must accept CTD's reviewed nexus-state list,
map Apeiron products to provider tax codes, store request/response evidence, health-check
the service, and keep the independent nexus, exemption, and filing gates intact.

## Exemption forms

Authorized downloads are stored outside Git under
`data/exemption_forms/fastsalestax/<retrieval-date>/`. The manifest contains only source
metadata, official links, state inventory results, and filenames; authentication tokens
and credentials are never written. Catalog the directory with:

```bash
uv run ctd catalog-exemption-forms data/exemption_forms/fastsalestax/2026-07-27
```

The July 27, 2026 inventory contains 477 verified PDFs for 45 states plus the District of
Columbia. Alaska, Delaware, Montana, New Hampshire, and Oregon are marked not applicable
for statewide sales tax. FastSalesTax returned no Mississippi forms with a contradictory
no-sales-tax notice, so Mississippi is stored as `source_anomaly` and requires an
authoritative Mississippi Department of Revenue form acquisition rather than being
treated as not applicable.

Forms in this library do not prove a customer exemption. Calculation readiness still
requires a current, verified `ctd_customer_exemption` whose scope matches the customer,
tax, service, jurisdiction, and assessment date.
