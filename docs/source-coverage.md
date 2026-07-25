# Source coverage and acquisition roadmap

## Implemented machine-readable sources

| Layer | Source | Refresh | Normalized output |
|---|---|---:|---|
| Federal | USAC factor table with FCC notice links | 14 days | Quarterly FUSF factors |
| Federal | IRS Form 720 instructions / 26 USC 4251 | 30 days | Communications excise rate and base note |
| Federal | FCC DA 26-646 | 30 days | 2026–27 TRS factors and distinct revenue bases |
| State/local sales | SST rate directory | Quarterly, checked weekly | Four rate variants and effective periods |
| Geography | 2020 Census ZCTA relationship files | Annual | County/place overlaps and allocation ratios |
| Federal filing | IRS Form 720/Publication 510, USAC Forms 499, FCC CORES | 14–30 days | Filing entity, payment recipient, return/portal, exemption guidance |
| California PUC | CPUC surcharge and user-fee tables | Daily; source cadence 7 days | Flat per-line surcharge and gross-intrastate-revenue user-fee histories |
| California revenue | CDTFA mobile-phone industry guidance | Daily; source cadence 14 days | Standalone service/data-plan taxability rule and device/prepaid distinction |
| Pennsylvania revenue | DOR gross-receipts, sales/use, and telecom bulletin | Daily; source cadence 14–30 days | 50-mill GRT, 6% state rate, and telecom taxability/base rule |

## Monitored discovery sources

- FCC annual 911 fee report directory.
- FCC USF quarterly filing directory.
- SST taxability matrices.
- Census TIGER/Line release directory.
- Fifty official PUC/PSC/commission sites.
- Fifty official state revenue/tax authority sites.
- SST member-state status and taxability matrix directory.

Monitoring proves a source was checked and changed; it does not claim normalization.

The dashboard’s `/states` register reports the two state tracks independently. “Partial”
means at least one effective-dated rule concept has been normalized; it never means a
state is calculation-ready. The agent monitors each authority landing page for
availability/content change and gives parsed rule sources a shorter cadence.

## State interpretation notes

- California sales/use tax is now administered by CDTFA, not the former State Board of
  Equalization. Current CDTFA mobile guidance distinguishes taxable devices from
  standalone service/data plans and separately identifies prepaid 911, 988, and local
  charge obligations. CPUC telecommunications surcharges and user fees are a separate
  regulatory track.
- Pennsylvania sales/use tax and telecommunications gross-receipts tax are separate
  regimes. The former applies the state sales/use rate to covered telecommunications
  under 61 Pa. Code § 60.20, with listed sourcing and exemptions. The latter is a
  provider gross-receipts tax reported on RCT-111 under 72 P.S. § 8101.
- The other 48 states are cataloged and monitored but remain `not_pulled` until a
  state-specific parser validates rates, bases, effective dates, taxability, sourcing,
  exemptions, and filing routes. A generic sales-tax rate or healthy homepage is not
  credited as communications-tax rule coverage.

## Priority acquisition sequence

1. Rank gaps by active customer p_code, recent invoice-tax use, and tax dollars.
2. Implement state communications and filing sources for those states: PUC assessments, USF, TRS,
   911/988, gross receipts, and communications-specific sales tax.
3. Add the return, payment portal/payee, exemption forms, and due rule for every reviewed
   tax-type/jurisdiction mapping.
4. Add non-SST sales/use feeds for footprint states.
5. Normalize product/service taxability, exemptions, caps, bases, and tax-on-tax rules.
6. License or procure ZIP+4/address boundary data and add 911/rate-center overlays.
7. Expand local ordinance collectors in order of billed revenue and benchmark gap count.

## Geographic warning

ZIP Codes are USPS delivery constructs. ZCTAs are Census statistical areas. Municipal,
county, special district, 911, and rate-center boundaries can split a ZIP or fail to align
with one another. The current Census collector is useful for discovering candidate
jurisdictions and quantifying gaps; it is not sufficient for an invoice tax engine.
