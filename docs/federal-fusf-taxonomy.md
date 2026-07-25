# Federal USF tax-type normalization

## One mechanism, multiple application rules

The federal Universal Service Fund is one contribution mechanism. CTD therefore stores
one canonical concept, `federal_universal_service_fund`, and treats service, revenue-base,
safe-harbor, and customer-billing differences as application rules beneath that concept.

The public hierarchy is:

1. 47 USC § 254(d) establishes the contribution obligation.
2. 47 CFR § 54.706 identifies contributors and covered interstate services, expressly
   including cellular, paging, and interconnected VoIP.
3. 47 CFR § 54.709 applies one quarterly contribution factor to the assessable interstate
   and international end-user revenue base.
4. FCC Form 499-A instructions classify revenue and publish optional interstate-revenue
   safe harbors: 37.1% for cellular/broadband PCS, 12.0% for paging, and 64.9% for
   interconnected VoIP.
5. 47 CFR § 54.712 governs optional recovery from customers. A contributor may choose
   whether to state a customer line item, subject to the rule's cap.

The safe-harbor percentage is not a second tax rate. It determines the interstate share of
revenue to which the single quarterly contribution factor applies.

## Avalara's twelve nonzero federal-USF types

| Avalara type | Label | CTD treatment | Public basis |
|---:|---|---|---|
| 18 | Fed Universal Service Fund | General FUSF rule | 47 CFR §§ 54.706(b), 54.709 |
| 55 | Fed USF Cellular | Cellular applicability | § 54.706(a)(1); Form 499-A wireless rules |
| 56 | Fed USF Paging | Paging applicability | § 54.706(a)(1); Form 499-A wireless rules |
| 162 | FUSF (VoIP) | Interconnected-VoIP applicability | § 54.706(a)(18); Form 499-A VoIP rules |
| 277 | Federal USF (Non-Billable) | General rule plus vendor billing treatment | § 54.712(a) |
| 311 | FUSF (Multi-line) | Fixed-local product subtype | Form 499-A Lines 303/404 |
| 444 | Federal USF (Centrex) | Fixed-local product subtype | Form 499-A Lines 303/404 |
| 625 | FUSF Cellular (Non-Billable) | Cellular plus vendor billing treatment | Wireless rules; § 54.712(a) |
| 626 | FUSF Paging (Non-Billable) | Paging plus vendor billing treatment | Wireless rules; § 54.712(a) |
| 627 | FUSF Centrex (Non-Billable) | Fixed-local subtype plus vendor billing treatment | Fixed-local rules; § 54.712(a) |
| 628 | FUSF Multi-Line (Non-Billable) | Fixed-local subtype plus vendor billing treatment | Fixed-local rules; § 54.712(a) |
| 629 | FUSF VoIP (Non-Billable) | VoIP plus vendor billing treatment | VoIP rules; § 54.712(a) |

Cellular, paging, and interconnected VoIP are expressly supported public categories.
Centrex, multi-line, and “non-billable” are not separately named federal FUSF mechanisms
in the controlling authorities. CTD records them as Avalara product or billing variants,
not as additional taxes. Their exact numeric-ID semantics remain vendor-derived until an
Avalara data dictionary is reviewed.

## Monitored public sources

- [47 CFR § 54.706](https://www.ecfr.gov/current/title-47/chapter-I/subchapter-B/part-54/subpart-H/section-54.706)
- [47 CFR § 54.709](https://www.ecfr.gov/current/title-47/chapter-I/subchapter-B/part-54/subpart-H/section-54.709)
- [47 CFR § 54.712](https://www.ecfr.gov/current/title-47/chapter-I/subchapter-B/part-54/subpart-H/section-54.712)
- [2026 FCC Form 499-A instructions](https://docs.fcc.gov/public/attachments/DA-25-308A3.pdf)
- [FCC 06-94 contribution methodology order](https://docs.fcc.gov/public/attachments/FCC-06-94A1.pdf)

CTD monitors all five sources and exposes them with each FUSF record returned by
`/api/tax-types`.
