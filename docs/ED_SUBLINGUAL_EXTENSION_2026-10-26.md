# Sublingual variants in the original ED setup — 2026-10-26

The owner requested adding these variants to the initial ED setup, not a separate therapy or template. The existing `master-therapy-ed` draft is extended from 12 to 16 plan groups. Its original 176 SKU choices remain, with 32 additional sublingual choices: 208 total. The original variant catalog grows from 88 to 104 product combinations.

## Approved source and products

Source: WLMD Offering Catalog Master Oct 23, Catalog rows 137–140, 206–213 and 255–258. Product metadata only; no costs, credentials or patient information.

| Variant | Exact base prefix | Monthly quantity |
|---|---|---|
| Sildenafil 100 mg, sublingual | `SILD-RDT-100MG` | 10 tablets |
| Tadalafil 5 mg daily, sublingual | `TADA-RDT-5MG` | 30 tablets |
| Tadalafil 20 mg, sublingual | `TADA-RDT-20MG` | 10 tablets |
| Vardenafil 25 mg, sublingual | `VARD-RDT-25MG` | 10 tablets |

Each prefix has `-1M`, `-3M`, `-6M`, `-12M`, and the corresponding exact base plus `-SUB`. Labels explicitly identify the sublingual formulation. Existing oral variants, user-edited prices, plans and variant metadata remain unchanged. Previous ED blend templates remain intact.

Both purchase types charge the full term upfront. Base SKUs do not renew; subscriptions renew after 30/90/180/360 days. One month ships once with 30 days of supply. Longer plans ship 90 days at a time: 3 months has one shipment, 6 months has two, 12 months has four. Six/twelve months include one/three later $0 deliveries. Claims open 20 days before current supply ends; refill orders retain the purchased SKU. Initial intake is required; these source rows require no refill check-in. Existing identity/review gates still apply.

New prices are editable $99/month placeholders ($99/$297/$594/$1,188), equal across purchase types. They are not source retail prices. Confirm selling prices and provider mappings before site publication.

## Implementation and verification

- `import_ed_sublingual.py` requires the original ED draft and variant metadata. It refuses missing/conflicting records, previews by default and applies one transaction.
- Adds 100 records: 32 masters, 32 SKU records, 32 refill policies and four purchase options. Updates only the ED therapy, original template draft and original variant catalog.
- No second ED template or new therapy is created. Published site checkout snapshots are not edited.
- Repeat imports preserve owner edits and verify the new choices remain attached to the original template.
- 34 targeted tests passed, covering original ED, new sublingual variants, earlier ED blends and ASTV exclusions. Includes rollback, edited-price preservation, no-network imports and an offline annual refill journey with three duplicate-protected $0 claims.
- Runtime image: `registry.fly.io/wlmd-stripe-test-0f89b1bb@sha256:f17be0e846cf7c8dbbc878c4f10094fb4029cd438f9c9aed9054b39a8a6adf55`.
- Uses the existing shared Fly app/machine/volume. The source release excludes unrelated AWS/MySQL work. A private pre-change database backup is retained on the volume.

This is master setup, not client publication or Sticky billing acceptance. No provider products, real orders, payment retries or charges are created by this change.

Live verification confirmed 32 new masters and refill policies, 16 plans / 208 unique SKU choices in the original ED draft, and 419 masters platform-wide. Template count did not increase. Previous ED plans, variants and all existing master prices were preserved, as were all prior purchase/checkout records. Repeat import was a no-op, runtime intake bindings resolved, and public health returned HTTP 200.
