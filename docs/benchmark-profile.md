# Initial Avalara benchmark profile

Profiled from the two supplied read-only replica tables on 2026-07-24. No licensed
row-level data is committed to this repository.

## Rate table

- 169,703 effective-dated rows
- 39,337 active rows
- 557 distinct active `p_code` values
- Effective dates range from 1900-01-01 through 2026-07-01

| Avalara level | Active rows | Distinct `p_code` | Tax types |
|---:|---:|---:|---:|
| 0 | 21,723 | 557 | 39 |
| 1 | 13,350 | 556 | 272 |
| 2 | 2,421 | 505 | 108 |
| 3 | 1,483 | 344 | 125 |
| 4 | 360 | 154 | 44 |

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

## First strict comparison

After the initial public seed:

- 45,508 public facts were current as of 2026-07-24.
- 5,557 of 39,337 active benchmark rate rows had an exact supported federal
  identity/rate match (14.127%).
- 65,736 of 75,766 benchmark U.S. postal rows had at least a Census ZCTA candidate
  (86.762% statistical coverage).
- 43,863 open exceptions were generated: 23,184 missing public rates, 10,596 rate
  mismatches, 10,030 postal gaps, and 53 unimplemented monitored parsers.

Federal rate rows repeat across `p_code`, so the rate-match percentage is a row coverage
measure, not a count of distinct laws. Non-federal SST rows are not credited merely because
a state and rate exist; communications taxability and jurisdiction identity must first be
normalized.
