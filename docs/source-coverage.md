# Source coverage and acquisition roadmap

## Implemented machine-readable sources

| Layer | Source | Refresh | Normalized output |
|---|---|---:|---|
| Federal | USAC factor table with FCC notice links | 14 days | Quarterly FUSF factors |
| Federal | IRS Form 720 instructions / 26 USC 4251 | 30 days | Communications excise rate and base note |
| Federal | FCC DA 26-646 | 30 days | 2026–27 TRS factors and distinct revenue bases |
| State/local sales | SST rate directory | Quarterly, checked weekly | Four rate variants and effective periods |
| Geography | 2020 Census ZCTA relationship files | Annual | County/place overlaps and allocation ratios |
| Geography | Census current coordinate and address-range geocoder | Daily for new/changed active service addresses; forced monthly | Effective-dated core state/county/place/subdivision assignment to deterministic CTD profiles |
| Assessment | Resolver + benchmark + approved public-rule/filing maps | Daily | New-address and changed-profile report with manual gaps at levels 0–3 |
| Federal filing | IRS Form 720/Publication 510, USAC Forms 499, FCC CORES | 14–30 days | Filing entity, payment recipient, return/portal, exemption guidance |
| California PUC | CPUC surcharge and user-fee tables | Daily; source cadence 7 days | Flat per-line surcharge and gross-intrastate-revenue user-fee histories |
| California revenue | CDTFA mobile-phone industry guidance | Daily; source cadence 14 days | Standalone service/data-plan taxability rule and device/prepaid distinction |
| Pennsylvania revenue | DOR gross-receipts, sales/use, and telecom bulletin | Daily; source cadence 14–30 days | 50-mill GRT, 6% state rate, and telecom taxability/base rule |
| New York sales/use | DTF Publication 718 and telecommunications quick reference | Daily; source cadence 7–14 days | State rate, 76 reporting-jurisdiction local components/codes, and intrastate telecom taxability |
| New York wireless | DTF Publications 451 and 452 | Daily; source cadence 7 days | Effective-dated state and county/NYC postpaid and prepaid surcharge components |
| New York provider tax | DTF Tax Expenditure Report and current CT-186-E materials | Daily; source cadence 30 days | § 186-e nonmobile/mobile rates, bases, recipient, and return |
| New York municipal utility tax | Eight current city/village code articles | Daily; source cadence 14 days | One-percent local utility GRT, telecom base boundary, local recipient, and due rule |
| Invoice demand | Apeiron invoice tax linked to benchmark rate IDs | Daily | Trailing-365-day and lifetime dollars/rows by customer, p_code, type, and level |
| Product demand | Apeiron catalog plus recurring, nonrecurring, data, message, and usage charge summaries | Daily | Tax attributes and trailing-365-day billed demand by address/product/charge type |
| Service tax assessment | Product demand + reviewed CTD rules, location, exemptions, and filing maps | Daily | Six-gate shadow readiness, exposure-weighted gaps, and supported public-tax estimates |

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
- New York Publication 718 explicitly says reporting codes, rather than ZIP codes,
  should identify customer location. CTD therefore stores its state/local component and
  reporting-code evidence separately from any commercial p_code. Publications 451/452
  likewise separate the state amount from county/New York City wireless surcharges.
  Local municipal telecommunications gross-receipts taxes are not inferred from the
  state § 186-e provider tax or a statewide enabling law. The first demand-ranked
  tranche validates adopted one-percent ordinances for Johnstown, Amsterdam, Fort
  Plain, Saratoga Springs, Albany, Lake George, Scotia, and Clayton. City ordinances
  generally state the traditional telephony/telephone utility base directly;
  Johnstown instead incorporates Tax Law § 186-a definitions by reference.
  Village Law § 5-530 and the village ordinances limit telephony receipts to local
  exchange service wholly consummated within the village. Neither formulation is
  treated as automatic authority for every VoIP, wireless, or bundle variant.
- The other 47 states are cataloged and monitored but remain `not_pulled` until a
  state-specific parser validates rates, bases, effective dates, taxability, sourcing,
  exemptions, and filing routes. A generic sales-tax rate or healthy homepage is not
  credited as communications-tax rule coverage.

## Priority acquisition sequence

1. Rank gaps from `ctd_customer_tax_need_detail` by active customer p_code,
   trailing-365-day invoice-tax use, and tax dollars.
2. Implement state communications and filing sources for those states: PUC assessments, USF, TRS,
   911/988, gross receipts, and communications-specific sales tax.
3. Add the return, payment portal/payee, exemption forms, and due rule for every reviewed
   tax-type/jurisdiction mapping.
4. Add non-SST sales/use feeds for footprint states.
5. Review the seeded product taxonomy and add effective-dated service taxability,
   exemption, cap, base, and tax-on-tax rules in billed-dollar order.
6. License or procure ZIP+4/address boundary data and add 911/rate-center overlays.
7. Expand local ordinance collectors in order of billed revenue and benchmark gap count.

## New York local filing status

The eight adopted ordinances identify the City Treasurer, Village Treasurer,
Clerk-Treasurer, Commissioner of Finance, or City Comptroller as the recipient and state
the applicable cadence and due date. They also direct the recipient to furnish or
prescribe the return. CTD records those routes as `recipient_verified`, with no return
document ID, because no public downloadable local return or filing portal was found.
This closes the legal-rate gap without closing the filing-form exception.

## Geographic warning

ZIP Codes are USPS delivery constructs. ZCTAs are Census statistical areas. Municipal,
county, special district, 911, and rate-center boundaries can split a ZIP or fail to align
with one another. The current Census collector is useful for discovering candidate
jurisdictions and quantifying gaps; it is not sufficient for an invoice tax engine.

Location Resolver v1 materially improves address-to-core-geography assignment over
ZIP-centroid or ZCTA matching, but it does not change that calculation rule. Census
geocoding uses address ranges and Census legal/statistical geographies, not tax authority
boundaries. ZIP+4 is retained as input and completeness evidence, not treated as a
national p_code replacement. State-authorized boundary databases and communications,
911, and special-district overlays are the calculation-ready gate.
