# ED combination master templates — 2026-10-26

Owner approved adding three ED combination groups with every source duration and paired one-time/subscription SKUs. This change adds reusable master drafts in the shared Fly admin; it does not assign products to client sites or create Sticky products, offers, campaigns, or orders.

## Source and selection

Source: `WLMD_Offering_Catalog_Master_Oct 23_INTERNAL ONLY.xlsx`, Catalog sheet. No internal costs or patient records are included here.

| Group | Exact base SKU prefix | Source rows | Tablets per 30 days |
|---|---|---|---|
| Sildenafil 100 mg / Oxytocin 100 IU | `SILD-OXYT-RDT-100MG-100IU` | 133–136 | 10 |
| Tadalafil 5 mg / Oxytocin 50 IU (daily) | `TADA-OXYT-RDT-5MG-50IU` | 214–217 | 30 |
| Tadalafil 20 mg / Oxytocin 100 IU | `TADA-OXYT-RDT-20MG-100IU` | 218–221 | 10 |

Each prefix has `-1M`, `-3M`, `-6M`, and `-12M`, plus the corresponding `-SUB` SKU: 24 master SKUs total. All are sublingual rapid-dissolve tablets. One new ED combination template presents medication/strength, duration, then purchase type. Existing ED treatments and templates remain intact.

## Billing and care

| Term | Supply per delivery | Deliveries per term | Included refills | Subscription renewal |
|---|---|---|---|---|
| 1 month | 30 days | 1 | 0 | 30 days |
| 3 months | 90 days | 1 | 0 | 90 days |
| 6 months | 90 days | 2 | 1 | 180 days |
| 12 months | 90 days | 4 | 3 | 360 days |

Both purchase types charge the entire term upfront. Base SKUs do not renew; `-SUB` SKUs renew for the full term. Quarterly deliveries contain three times the monthly tablet quantity. Included refill claims open 20 days before the current supply ends. Initial intake is required; the sheet marks refill check-in as No for all these rows. Existing identity and review gates remain in force. Refill orders retain the same SKU.

Prices are editable draft placeholders of $99 per month of supply ($99/$297/$594/$1,188), not source retail prices. Confirm client selling prices and provider mappings before publishing client checkouts.

## Implementation and verification

- Catalog: `tools/stripe-v2-checkout/ed_combination_catalog.json`.
- Importer: `import_ed_combinations.py`; preview by default, atomic application with `--apply`, idempotent run marker `owner-approved-ed-oxytocin-combinations-20261026-v1`.
- 78 new configuration records: 24 masters, 24 SKU records, 24 refill policies, four purchase options, one template draft, and one source/variant record. The existing ED therapy gains three treatments.
- 23 targeted tests passed across ED combinations, additional masters, next masters, and ASTV refill restrictions. Coverage includes paired SKUs, exact quantities, billing cycles, rollback, idempotency, preservation, and an offline 12-month portal journey with three $0 included claims and duplicate protection.
- Runtime image: `registry.fly.io/wlmd-stripe-test-0f89b1bb@sha256:e645b2a13b4b39a24c9cf10fdca96c742935f6ad916977859c1b5baa2804029a`.
- Deploy target: existing shared app `wlmd-stripe-test-0f89b1bb`, preserving its machine and persistent database.
- No Sticky or real payment tests are part of this import. ASTV's unconfirmed longer durations remain disabled.
- Live readback confirmed all 24 masters, four plans, 24 refill policies, runtime intake bindings, and 363 total master records. Re-running the import made no changes. All previous payment rows and configuration records were preserved, apart from the approved additive ED treatment list update.
