# Next master families and NAD+ umbrella — 26 October 2026

The owner approved the six groups proposed from the workbook and explicitly requested all NAD+ injection variants under the existing NAD+ therapy. Scope: master configuration and reusable template drafts, not publication to client sites or new Sticky payment objects.

## Added products

| Template | Exact base SKUs | Terms | Source rows |
| --- | --- | --- | --- |
| Propranolol 20 mg | `PROP-20MG-3B` | 3 months | 733 |
| Ramelteon 8 mg | `RAM-8MG-3M` | 3 months | 763 |
| HydraBoost Gel | `HYDRABOOST-GEL-1M`, `HYDRABOOST-GEL-3M` | 1/3 months | 746–747 |
| Copper Peptide Cream | `C-DERM-CREAM2-1M` | 1 month | 743 |
| Women's arousal gels | `ALPRO-VAG-0.1%-{term}M`, `OGEL-VAG-{term}M`, `OGEL-PEPP-VAG-{term}M`, `VIXEN-VAG-{term}M` | 1/3/6/12 months | 292–307 |
| NAD+ all formats | New `NAD-INJ-200MG-10ML-{term}M`, alongside existing injection, nasal and sublingual SKUs | 1/3/6/12 months | New rows 24–27 |

Source: WLMD Offering Catalog Master Oct 23, Catalog sheet. No internal costs or patient data are included. Every exact base SKU receives its exact `-SUB` counterpart: 25 new product/duration combinations, 50 masters, 50 refill policies, 13 duration options and six template drafts. Skin products share the Skin Care therapy; all four women's gel variants share Women's Sexual Health.

The new NAD+ injection's source identity is **200 mg/mL**. Its SKU contains `200MG-10ML`; do not interpret that substring as 200 mg total per 10 mL. Original package text is preserved. The original generic injection SKU is not renamed or silently substituted. All NAD records use `therapy_id=nad-plus`; the combined draft presents the original injection, explicit 200 mg/mL injection, nasal spray and sublingual tablets together. Each duration resolves to eight exact SKUs, four forms/variants with both purchase types. Existing templates and published sites remain intact.

## Source-specific delivery and refill rules

- All base SKUs charge the full term once; `-SUB` charges the full term and renews after 30/90/180/360 days as applicable.
- Women's gels ship every 30 days: 3/6/12-month plans contain 3/6/12 deliveries and 2/5/11 included $0 refills. They must not inherit the quarterly shipment schedule.
- The added NAD+ injection ships a 30-day supply for one month, otherwise 90-day supplies: 6/12 months include one/three later $0 deliveries.
- Propranolol and Ramelteon each have one 90-day shipment; HydraBoost has one 30- or 90-day shipment; Copper Peptide has one 30-day shipment. No included refill follows these single shipments.
- Claim windows open 20 days before each supply ends, subject to remaining entitlement and verified order state. All selected rows say no refill check-in. Initial intake and existing review/identity rules remain required. Refills retain their original SKU.
- New therapy intake bindings use the backend mock question provider pending approved external clinical questionnaires. This change does not connect or certify clinical services.

Draft prices are editable placeholders: Propranolol $29/month, Ramelteon $49/month, HydraBoost and Copper Peptide $59/month, women's gels $99/month, explicit NAD+ injection $199/month, multiplied by the term. Existing NAD prices are preserved. Confirm selling prices and provider mappings before publishing to a site.

## Validation and import

`import_next_masters.py` uses the existing atomic importer with its own catalog and run ID. The shared importer now supports multiple variants per duration and a combined therapy draft. Earlier import markers and source hashes are unchanged. Repeat imports retain price edits; collisions or a failed write roll back the entire batch.

46 focused backend tests passed against the clean Fly release. They cover the prior batches, all 50 new SKU pairs, NAD umbrella selection, monthly/quarterly schedules, admin draft validation, intake bindings, no network writes, transaction rollback, and preservation of earlier prices/templates. An offline provider test exercised all eleven $0 monthly refill claims, opening at days 10/40/.../310, duplicate protection, no extra check-in and same-SKU child orders. This is offline verification, not a live Sticky billing test. Admin JavaScript syntax validation passed.

The source-only Fly release excludes unrelated AWS/MySQL changes in the shared checkout. The remote builder is used because local Docker is unavailable. No live order, card authorization, charge or fulfillment operation is part of this task.

## Live result

Installed on the existing Fly app `wlmd-stripe-test-0f89b1bb`, machine `84e117f290dd38`, with its original persistent database. Runtime image: `registry.fly.io/wlmd-stripe-test-0f89b1bb@sha256:3a9883fe264207e77e9c8966f79193784ff3e0095cf506f56d3a4d152ed32dca`. Previous image: `sha256:d4fda2053ec3069988a3537930caaeb4f7b35c2289fb6e6d1a23f9bb26045823`.

The importer created 179 records and updated only the existing NAD+ therapy to append the new injection variant. A repeat import was a no-op. Total master records: 331 including the unassigned legacy record. All 50 runtime intake bindings resolved, and the combined NAD+ draft contains eight SKU choices per duration. Independent workbook comparison confirmed all 25 source SKU spellings, package descriptions, shipment intervals/counts, refill entitlements and check-in flags.

The private backup `/data/next-master-families-20261026-before.sqlite3` remains on the volume and must not enter GitHub. After installation, all existing configuration records matched it except the intended NAD+ treatment addition. Existing purchase and checkout records remained identical. Preflight held two unresolved authorization attempts and 19 awaiting-card forms under the owner's prior preserve-and-deploy authorization; no payment was retried.

Public health returned 200 with payment readiness enabled; unauthenticated admin state returned 401. The deployed editor asset matched source. FortifyHP retained its 41 published API plans. These six new drafts are visible in the shared admin but are not yet published to client sites. Publishing monthly prepaid gels still requires site-specific provider mapping and billing verification; offline tests do not certify a live payment gateway.
