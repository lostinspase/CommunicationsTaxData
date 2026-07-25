# Source coverage and acquisition roadmap

## Implemented machine-readable sources

| Layer | Source | Refresh | Normalized output |
|---|---|---:|---|
| Federal | USAC factor table with FCC notice links | 14 days | Quarterly FUSF factors |
| Federal | IRS Form 720 instructions / 26 USC 4251 | 30 days | Communications excise rate and base note |
| Federal | FCC DA 26-646 | 30 days | 2026–27 TRS factors and distinct revenue bases |
| State/local sales | SST rate directory | Quarterly, checked weekly | Four rate variants and effective periods |
| Geography | 2020 Census ZCTA relationship files | Annual | County/place overlaps and allocation ratios |

## Monitored discovery sources

- FCC annual 911 fee report directory.
- FCC USF quarterly filing directory.
- SST taxability matrices.
- Census TIGER/Line release directory.
- Fifty official state DOR sales/use tax landing pages.

Monitoring proves a source was checked and changed; it does not claim normalization.

## Priority acquisition sequence

1. Import the benchmark and rank active gaps by Apeiron transaction/state footprint.
2. Implement state communications sources for those states: PUC assessments, USF, TRS,
   911/988, gross receipts, and communications-specific sales tax.
3. Add non-SST sales/use feeds for footprint states.
4. Normalize product/service taxability, exemptions, caps, bases, and tax-on-tax rules.
5. License or procure ZIP+4/address boundary data and add 911/rate-center overlays.
6. Expand local ordinance collectors in order of billed revenue and benchmark gap count.

## Geographic warning

ZIP Codes are USPS delivery constructs. ZCTAs are Census statistical areas. Municipal,
county, special district, 911, and rate-center boundaries can split a ZIP or fail to align
with one another. The current Census collector is useful for discovering candidate
jurisdictions and quantifying gaps; it is not sufficient for an invoice tax engine.
