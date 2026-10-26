# ED PT-141 and Vardenafil master blends — 2026-10-26

The owner approved three additional ED sublingual variants with all four source durations and both purchase types. Scope: reusable master drafts in the shared Fly admin. Client publication and Sticky product/campaign provisioning are separate steps.

## Approved source

`WLMD_Offering_Catalog_Master_Oct 23_INTERNAL ONLY.xlsx`, Catalog rows 222–233. Only product metadata is retained; no private costs or patient information.

| Variant | Exact base SKU prefix | Rows | Tablets per 30 days |
|---|---|---|---|
| Tadalafil 10 mg / Oxytocin 100 IU / PT-141 1 mg | `TADA-OXYT-PT141-RDT-10MG-100IU-1MG` | 222–225 | 8 |
| Tadalafil 20 mg / Oxytocin 100 IU / PT-141 2 mg | `TADA-OXYT-PT141-RDT-20MG-100IU-2MG` | 226–229 | 8 |
| Tadalafil 5 mg / Vardenafil 5 mg | `TADA-VARD-RDT-5MG-5MG` | 230–233 | 10 |

Every prefix has `-1M`, `-3M`, `-6M`, `-12M` and each exact base plus `-SUB`: 24 master SKUs. Template `master-therapy-ed-pt141-vardenafil-combinations` groups the three variants under Erectile Dysfunction. Each duration contains six SKU choices. Selection is blend, duration, then purchase type. Existing ED templates and treatments are retained.

## Billing and refill rules

- Full-term upfront payment for both purchase types. Base is one-time; `-SUB` renews after 30/90/180/360 days.
- One month: one 30-day shipment. Three months: one 90-day shipment. Six months: two 90-day shipments. Twelve months: four 90-day shipments.
- Quarterly quantities are 24 tablets for the PT-141 blends and 30 for Tadalafil/Vardenafil.
- Included later $0 deliveries: zero for 1/3 months, one for 6 months, three for 12 months. Claims open 20 days before supply ends. Refill orders retain the purchased SKU.
- Initial intake is required. Each selected source row says no refill check-in; existing identity, ownership, and clinical review gates remain.
- Draft prices use the preceding batch's editable $99/month placeholder: $99/$297/$594/$1,188, equal for both purchase types. These are not source retail prices; confirm brand prices before publication.

## Import and verification

`import_ed_advanced.py` validates exact SKUs and quantity/delivery contracts, previews by default, and applies atomically with a dedicated run marker. It adds 78 configuration records and appends three treatments to the existing ED therapy. Repeat imports preserve price edits and do not duplicate records.

27 targeted tests passed: new variants, previous ED combinations, earlier master batches, and ASTV exclusions. Coverage includes paired contracts, intake bindings, quantities, claim windows, rollback, idempotency, preservation, and an offline 12-month subscription journey with three duplicate-protected $0 claims. No provider or real payment calls were made by the tests/import.

Runtime image: `registry.fly.io/wlmd-stripe-test-0f89b1bb@sha256:ba4028b6ebde2874d129f160f9ae4ab3cacb32bd87021ed4c25255634ef525e1`.

Deployment reuses the existing shared Fly app, machine and database. The source release excludes unrelated AWS/MySQL work. The private pre-change database backup remains on the persistent volume. Existing unfinished payment records are preserved under the owner's prior deployment authorization.

Live readback verified 24 new masters, four purchase options and 24 refill policies, with 387 total master records. Repeat import was a no-op. Existing configuration records matched the backup except the approved additive ED treatment update; all previous purchase/checkout rows were preserved. The deployed intake bindings resolved and public health returned HTTP 200. These remain master drafts, not published client checkouts.
