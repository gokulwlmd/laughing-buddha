# ED master therapy

Owner-approved setup added to the existing Fly admin on 25 October 2026 and
corrected the same day to use base / `-SUB` purchase pairs.
This is master configuration, not an activated site checkout. AWS and Lovable
were not changed. No Sticky products, offers, orders or payments were created.

## Catalog and selection

Therapy ID: `erectile-dysfunction`.

| Treatment | Strengths (mg) | Tablets per month | Terms (months) | Product combinations |
| --- | --- | --- | --- | --- |
| Sildenafil | 50, 100 | 6, 8, 10, 12, 14 | 1, 3, 6, 12 | 40 |
| Tadalafil Daily | 2.5, 5 | 30 | 1, 3, 6, 12 | 8 |
| Tadalafil as needed | 10, 20 | 6, 8, 10, 12, 14 | 1, 3, 6, 12 | 40 |

These 88 product combinations have **176 master SKUs**: each exact base SKU is
one-time upfront with no renewal; its `-SUB` counterpart is recurring upfront.
Both retain the same approved delivery schedule. Reference prices initially
match across the pair; no subscription discount is assumed.

Intended customer selection: medication, strength, monthly quantity, duration,
then **One-time / Subscription**.
Daily tadalafil has a fixed quantity of 30. Strength selection is a preference,
not clinical approval. The conditional customer selector is not deployed by
this catalog-only import; implement it when publishing ED to a site.

All 88 exact base SKU codes and shipment counts were matched against the owner's
WLMD Offering Catalog, Oct 23, Catalog sheet. Only non-patient product metadata
is stored in `tools/stripe-v2-checkout/ed_master_catalog.json`; internal costs,
credentials and provider product IDs are excluded. Structured variant metadata
is retained as `therapy_variant_catalog/erectile-dysfunction` for later API and
selector work. This record is not itself a public API endpoint.

Editable starter prices come from Anuwell's ED source configuration at commit
`5e49a9532316abddb26e979c98242c29dc390665`. They are reference prices, not current
brand quotes. Existing brand pricing is untouched.

## Billing and fulfillment

Both purchase types charge the full term upfront. The base SKU has no renewal;
only `-SUB` uses the platform's approved day-based renewal intervals below.
Anuwell's recurring-only reference did not override this platform convention.

| Term | `-SUB` renewal | Shipments | Days from cycle start | Included later deliveries |
| --- | --- | --- | --- | --- |
| 1 month | 30 days | 1 | 0 | 0 |
| 3 months | 90 days | 1 | 0 | 0 |
| 6 months | 180 days | 2 | 0, 90 | 1 |
| 12 months | 360 days | 4 | 0, 90, 180, 270 | 3 |

Intermediate included deliveries are $0. The workbook lists no required
check-in for these rows; intake/clinical review must still be configured when
activating a site. Do not copy weight-loss check-in requirements into ED.

## Admin records and operational boundary

- Therapy: Erectile Dysfunction (ED), with the three treatments above.
- Master SKUs: 176 editable entries, 88 one-time and 88 subscription, with
  descriptive strength/quantity/purchase-type names.
- Plans: 12, grouped by medication and term, respecting the current 20-SKU
  purchase-option limit (20 SKUs for as-needed products, 4 for daily).
- Template draft: `master-therapy-ed`, named
  **Master Therapy · Erectile Dysfunction (ED)**.
- Current import marker: `owner-approved-ed-master-purchase-pairs-v2`.
- Historical marker `owner-approved-ed-master-v1` is retained for audit only.

The draft is deliberately not in `checkout_template`, so adding a site does
not accidentally activate unverified ED offers or block existing site setup.
Before selling ED, verify the selected site's provider mappings, price,
fulfillment and recurring/prepaid billing, then publish explicitly. No Anuwell
pharmacy IDs or another site's campaign IDs were reused. The draft master
schema's legacy fulfillment-source default is not an approved ED mapping.

## Repeatable import and verification

From `tools/stripe-v2-checkout`, preview against an existing SQLite database:

```sh
python import_ed_master.py --database /path/to/checkout.sqlite3
```

Add `--apply` only for the intended target. The importer uses the target
release's catalog validators and `catalog_contracts.validate_purchase_pairs`,
makes one transaction, rejects conflicting records, and preserves owner edits
on repeat runs. The v1 correction verifies its historical record set, refuses
any external assignment/publication reference, and preserves edited master
prices and shipment settings. It does not start the app,
read application secrets, call providers, or create a missing database.

The original v1 import added 191 configuration records but incorrectly treated
the base codes as recurring. The authorized correction adds 176 records for
88 `-SUB` master/SKU pairs and updates the original draft's purchase contracts,
plans and metadata. It does not change other therapies, sites or payments.
Live correction read-back verified 88 one-time and 88 subscription masters,
with the worker unchanged and all unrelated configuration preserved.
Thirteen tests cover both purchase types, the variant/delivery matrix, admin
API visibility/editing, migration refusal for assigned products, rollback,
preservation of edited prices/schedules, and absence of network calls. These
are catalog tests, not payment acceptance.

The project catalog skill records the purchase-pair convention and points to
the executable validator. New recipes must fail validation for missing `-SUB`
counterparts, recurring base SKUs, nonrecurring `-SUB` SKUs, or mismatched
product identity and delivery rules. Existing legacy subscriptions are outside
this new-recipe rule and must not be rewritten automatically.
