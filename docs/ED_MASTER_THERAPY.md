# ED master therapy

Owner-approved setup added to the existing Fly admin on 25 October 2026.
This is master configuration, not an activated site checkout. AWS and Lovable
were not changed. No Sticky products, offers, orders or payments were created.

## Catalog and selection

Therapy ID: `erectile-dysfunction`.

| Treatment | Strengths (mg) | Tablets per month | Terms (months) | SKUs |
| --- | --- | --- | --- | --- |
| Sildenafil | 50, 100 | 6, 8, 10, 12, 14 | 1, 3, 6, 12 | 40 |
| Tadalafil Daily | 2.5, 5 | 30 | 1, 3, 6, 12 | 8 |
| Tadalafil as needed | 10, 20 | 6, 8, 10, 12, 14 | 1, 3, 6, 12 | 40 |

Intended customer selection: medication, strength, monthly quantity, duration.
Daily tadalafil has a fixed quantity of 30. Strength selection is a preference,
not clinical approval. The conditional customer selector is not deployed by
this catalog-only import; implement it when publishing ED to a site.

All 88 exact SKU codes and shipment counts were matched against the owner's
WLMD Offering Catalog, Oct 23, Catalog sheet. Only non-patient product metadata
is stored in `tools/stripe-v2-checkout/ed_master_catalog.json`; internal costs,
credentials and provider product IDs are excluded. Structured variant metadata
is retained as `therapy_variant_catalog/erectile-dysfunction` for later API and
selector work. This record is not itself a public API endpoint.

Editable starter prices come from Anuwell's ED source configuration at commit
`5e49a9532316abddb26e979c98242c29dc390665`. They are reference prices, not current
brand quotes. Existing brand pricing is untouched.

## Billing and fulfillment

The approved Anuwell ED configuration is recurring, with full-term upfront
payment. Follow the platform's previously approved day-based renewal intervals.

| Term | Renewal | Shipments | Days from cycle start | Included later deliveries |
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
- Master SKUs: 88 editable entries with descriptive strength/quantity names.
- Plans: 12, grouped by medication and term, respecting the current 20-SKU
  purchase-option limit (10 alternatives for as-needed products, 2 for daily).
- Template draft: `master-therapy-ed`, named
  **Master Therapy · Erectile Dysfunction (ED)**.
- Import marker: `owner-approved-ed-master-v1`.

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
release's catalog validators, makes one transaction, rejects conflicting
records, and preserves owner edits on repeat runs. It does not start the app,
read application secrets, call providers, or create a missing database.

Live import read-back verified 88 master SKUs, 12 plans and the template draft;
191 admin configuration records were added. All pre-existing configuration
remained byte-for-byte unchanged, and the payment worker was not restarted.
Nine tests passed, covering the variant/delivery matrix, admin API visibility
and editing, atomic failure, conflict detection, repeat preservation, and
absence of network calls. These are catalog tests, not payment acceptance.
