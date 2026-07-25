# Initial Avalara benchmark profile

Profiled from the two supplied read-only replica tables on 2026-07-24. No licensed
row-level data is committed to this repository.

## Rate table

- 169,703 effective-dated rows
- 39,337 active rows before zero-rate filtering
- 26,335 active rows with a nonzero rate
- 299 distinct active, nonzero numeric `tax_type` values nationwide
- 557 distinct active `p_code` values
- Effective dates range from 1900-01-01 through 2026-07-01

| Avalara level | Active nonzero rows | Distinct `p_code` | Distinct tax types |
|---:|---:|---:|---:|
| 0 | 15,039 | 557 | 27 |
| 1 | 8,235 | 556 | 197 |
| 2 | 1,683 | 436 | 88 |
| 3 | 1,124 | 319 | 106 |
| 4 | 254 | 134 | 36 |

Tax coverage now uses distinct numeric `tax_type` only. Zero-rate placeholders are
excluded, and repetition across `p_code`, level, category, or description does not
increase the tax-type denominator. Tax level remains routing and filing metadata.

The source contains a level 4 even though the requested public acquisition model names
levels 0–3. The app preserves and reports level 4 as `Other`; it does not silently fold it
into municipal data.

Largest active categories are connectivity (18,718), regulatory (4,495), E-911 (4,395),
sales/use (3,449), cable regulatory (1,267), excise (786), gross receipts (726), utility
users (433), communications services (410), business (383), and right-of-way (168).
`RESERVED` and null categories also exist and require taxonomy review.

## Address table

The entire commercial table contains 123,719 rows across several countries. The U.S. and
included U.S. territory slice copied into local benchmark tables contains 76,261 rows:

| Country code | Rows | Distinct `p_code` |
|---|---:|---:|
| USA | 75,835 | 56,075 |
| PRI | 321 | 78 |
| GUM | 64 | 19 |
| ASM | 17 | 14 |
| VIR | 17 | 16 |
| MNP | 7 | 7 |

The table includes sentinel jurisdiction rows whose ZIP values begin with `000`. Exception
generation excludes `00000` and `00001` from postal-coverage percentages.

## Superseded row-based comparison

After the initial public seed:

- 45,508 public facts were current as of 2026-07-24.
- 5,557 of 39,337 active benchmark rate rows had an exact supported federal
  identity/rate match (14.127%).
- 65,736 of 75,766 benchmark U.S. postal rows had at least a Census ZCTA candidate
  (86.762% statistical coverage).
- 43,863 open exceptions were generated: 23,184 missing public rates, 10,596 rate
  mismatches, 10,030 postal gaps, and 53 unimplemented monitored parsers.

These figures are retained as the initial deployment record only. The production
comparison no longer uses rate rows as the tax denominator.

## Customer-priority profile

The invoice-tax path is:

`apeiron_apeirontaxchargessummary.avalara_id` → benchmark rate,
`customer_id` → customer, and customer `service_address_id` → ZIP/ZIP+4/p_code.

There are 840 customers with at least one nonzero invoice-tax row. Of those, 565 are
currently open, non-test, invoice-generating customers. A second freshness view contains
426 active customers whose most recent nonzero tax invoice is within the trailing 12
months.

| Scope | Customers | p_codes | Customer ZIP recognized | Distinct nonzero tax types |
|---|---:|---:|---:|---:|
| Ever taxed | 840 | 317 | 785 / 840 (93.452%) | 267 |
| Active and ever taxed | 565 | 210 | 543 / 565 (96.106%) | 259 |
| Active and taxed in trailing 12 months | 426 | 132 | 420 / 426 (98.592%) | 212 |

ZIP recognition remains a separate statistical dimension. Tax-type, public-law,
filing-entity, and location-assignment coverage are not blended.

## Tax types and change history

- Active nonzero rates contain 299 distinct numeric tax types. The former counts of 406
  types, 588 type/level pairs, and 591 signatures included zero-rate placeholders and
  non-identity dimensions; they are no longer coverage denominators.
- CTD's existing public `tax_type_code` values are SST jurisdiction component codes, not
  Avalara tax-type IDs. No direct numeric equivalence should be inferred.
- The app reports one record per numeric tax type. It preserves levels, categories,
  descriptions, and rates as attributes and requires explicit review before a proposed
  numeric crosswalk counts as reviewed.
- Invoice tax summaries label charge mechanics as `percentage` or `perLine`; those values
  are units, not the Avalara tax identity. The `avalara_id` join supplies identity when
  present.

The supplied Avalara changelog contains 114,384 rows through 2026-07-01, covering 15,037
p_code/type/level rules, 439 p_codes, and 201 tax types. CTD incrementally mirrors it in
`ctd_benchmark_rate_change`. Public-source hashes and normalized fact-field changes are
kept separately, so licensed benchmark changes are never treated as upstream authority.
