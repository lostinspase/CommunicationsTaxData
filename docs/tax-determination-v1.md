# Tax Determination v1

Tax Determination v1 turns the address-level coverage inventory into a product-aware,
exposure-weighted shadow assessment. It does not post taxes, alter invoices, or treat
Avalara as a source of law.

## Daily flow

1. `ctd sync-products` reads the replica and refreshes:
   - tax-relevant attributes from `apeiron_apeironproduct`;
   - recurring, nonrecurring, data, message, and voice-usage charges from the trailing
     365 days;
   - the active customer's service-address key and federal/state/local exemption flags.
2. Missing internal tax groups receive a candidate `ctd_product_taxonomy_map` row.
   Candidate rows are always `proposed`; a sync never overwrites a human-reviewed row.
3. `ctd assess-services` joins actual billed demand to the required sourcing assignment,
   benchmark tax-type routes, reviewed tax-type crosswalk, reviewed taxability rule,
   current public fact, structured exemption evidence, and filing route.
4. CTD stores one immutable `ctd_service_tax_assessment` snapshot per demand row/run and
   writes aggregate JSON plus a manual-gap CSV.

The dashboard is `/tax-determination`; JSON is available at
`/api/tax-determination`, `/api/product-taxonomy`, and `/api/taxability-rules`.
The determination API omits the large per-route audit evidence by default. Request it
for a bounded result set with `include_routes=true`; summary, gate, and gap fields are
available without loading route evidence.

## Readiness gates

Each billed product/address/charge-type row carries six independent gates:

| Gate | Required evidence |
|---|---|
| Product mapping | Effective mapping to a CTD service category with status `reviewed` or `published` |
| Location / sourcing | A calculation-ready assignment for the mapping's legal sourcing role |
| Taxability | Reviewed tax concept crosswalk and reviewed taxable/non-taxable/exempt decision |
| Exemption | No exemption claimed, or a current verified exemption matching the tax/service/geographic scope |
| Filing | An approved filing map for every applicable taxable route that requires reporting |
| Calculation | Supported rate/unit/base semantics and all preceding gates |

`calculation_ready=true` only when every gate passes. A reviewed taxability decision can
therefore remain visible while a boundary, filing form, or exemption certificate is
still missing.

## Product mapping policy

Apeiron's `tax_group` is useful operational evidence, but its label is not a legal
taxability conclusion. CTD seeds candidates for known groups such as `voice-trunk`,
`voice-did`, `voice-pots`, `voice-tfn`, `cellular`, `sms`, `internet_access`,
`internet_broadband_wireless`, `mpls-voice`, `equipment-sale`, and usage groups.

The candidate also identifies the expected sourcing role. Examples include
`service_address`, `primary_place_of_use`, `ship_to`, and `call_jurisdiction`. Location
Resolver v1 currently creates service-address assignments only, so wireless, VoIP,
equipment-shipment, or call-jurisdiction rows remain explicit sourcing gaps until the
appropriate evidence is added.

Product percentage fields—voice, SMS, wireless data, transport, interstate, and
intrastate—are retained in the catalog snapshot for future reviewed bundle/allocation
rules. V1 does not automatically convert them into a taxable percentage.

## Taxability rules

`ctd_taxability_rule` is the interpretive layer. A reviewed rule states:

- CTD tax concept and optional exact public-fact natural key;
- tax level and optional state, jurisdiction, or benchmark-comparison p_code scope;
- service category and optional charge type;
- taxable, non-taxable, exempt, or conditional treatment;
- required sourcing role;
- calculation method and taxable percentage;
- filing requirement, legal citation, effective period, reviewer, and review status.

The benchmark tax type reaches this rule only through a reviewed, cited
`ctd_tax_type_crosswalk`. A commercial numeric type is never embedded as the public-law
identity.

For a taxable decision, V1 estimates public tax only for:

- `percent_of_charge` with a public `percent_of_base` rate; or
- `flat_per_unit` with a public flat amount and source quantity.

Caps, brackets, minimum bases, tax-on-tax, invoice rounding, bundle allocation, and
other line-sensitive logic emit an explicit calculation gap. Aggregate trailing-period
estimates are prioritization evidence, not invoice reproductions.

## Exemption policy

Source fields `tax_exempt`, `tax_exempt_federal`, `tax_exempt_state`, and
`tax_exempt_local` are imported as warnings only. They do not prove legal eligibility.
When a flag would suppress an otherwise taxable route, CTD requires a current
`ctd_customer_exemption` record scoped by level, state/jurisdiction, service category,
and effective date. CTD stores only document/certificate references, not document
contents.

## Main gap codes

- `PRODUCT_TAX_GROUP_UNMAPPED`
- `PRODUCT_MAPPING_UNREVIEWED`
- `LOCATION_ASSIGNMENT_MISSING`
- `MISSING_REQUIRED_SOURCING_ASSIGNMENT`
- `SOURCING_ROLE_RULE_MISMATCH`
- `TAX_BOUNDARY_UNVERIFIED`
- `MISSING_REVIEWED_TAX_CONCEPT_MAP`
- `AMBIGUOUS_TAX_CONCEPT_MAP`
- `MISSING_TAXABILITY_DECISION`
- `EXEMPTION_EVIDENCE_UNVERIFIED`
- `MISSING_PUBLIC_FACT_LINK`
- `MISSING_FILING_ROUTE`
- `CALCULATION_METHOD_UNSUPPORTED`
- `CAP_OR_BRACKET_REQUIRES_LINE_LEVEL_CALCULATION`

## Privacy and operational output

The detailed API and CSV expose internal address/product IDs, tax group, service
category, state, p_code comparison reference, billed amount, readiness gates, and gaps.
They do not expose customer identity or copy street addresses. The CTD tables retain
customer IDs internally only to join the customer's exemption evidence and to maintain
stable demand snapshots.

Generated files are:

- `reports/service-tax-assessment-summary.json`
- `reports/service-tax-assessment-gaps.csv`
