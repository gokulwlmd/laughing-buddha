# Additional master product families — 26 October 2026

Owner approved four product families, retaining exact workbook base SKUs and adding the exact base plus `-SUB` for subscriptions. This scope creates master recipes and template drafts only; it does not publish them to FortifyHP or another site or create Sticky products/orders.

| Product family | Source rows (Catalog) | Terms | Exact base SKU pattern |
| --- | --- | --- | --- |
| PT-141 nasal spray 5 mg/mL | 36–39 | 1/3/6/12 months | `PT141-NASAL-5MG-{months}M` |
| NAD+ sublingual tablets 100 mg | 28–31 | 1/3/6/12 months | `NAD-RDT-100MG-{months}M` |
| Sermorelin sublingual tablets 500 mcg | 42–45 | 1/3/6/12 months | `SERM-RDT-500MCG-{months}M` |
| Sertraline 25 mg | 737–739 | 3/6/12 months | `SERT-25MG-90-30-3B`, `SERT-25MG-180-30-6B`, `SERT-25MG-360-30-12B` |

15 source combinations, 30 paired master SKUs, 15 duration options, four separate template drafts, and 30 per-SKU refill policies. Existing therapy treatments are retained while the new forms are appended. Sertraline is organized under Premature Ejaculation. Sermorelin 1 mg remains excluded pending source confirmation. No separate refill SKUs.

## Billing, delivery and care

- Base: full term paid upfront, no renewal. `-SUB`: full term paid upfront, renewal after 30/90/180/360 days.
- One month: one 30-day supply. Three months: one 90-day supply. Six months: two 90-day supplies. Twelve months: four 90-day supplies.
- Six months includes one later $0 delivery; twelve months includes three. Claim windows open 20 days before the current supply ends, subject to remaining entitlement and order state.
- Each approved source row says no refill check-in required. Initial intake remains required; existing per-site verification/review rules remain in effect. Refill orders retain the original SKU.
- Intake bindings use the existing PT-141, NAD+ and Sermorelin templates. Sertraline receives a backend mock intake binding pending the clinical provider's approved questionnaire. This is not a claim of a connected clinical integration.
- Editable draft prices are placeholders, not source retail prices or private costs: PT-141 nasal and Sermorelin sublingual $149/month, NAD+ sublingual $99/month, Sertraline $29/month, multiplied by the term. One-time and subscription prices start equal. Confirm selling prices before site publication.

## Import and recovery

`import_additional_masters.py` defaults to preview and writes one SQLite transaction with a versioned import marker. Existing records cause reconciliation instead of overwrite, except the explicit addition of treatments to the three existing therapies. Existing templates, variants, site assignments, orders, and payment attempts are preserved. Repeat imports validate completeness and retain subsequent price edits. No provider calls are made.

Runtime changes add exact SKU intake bindings and the Sertraline policy editor option. The catalog file contains only approved product metadata; no workbook internal costs, credentials, or patient data are included.

Validation: 40 targeted backend tests passed in both the working checkout and clean Fly release, including paired contracts, preview/template editing, exact SKU names, source delivery rules, intake bindings, atomic rollback, conflict detection, idempotency, edited-price preservation, and no network/provider writes. The changed admin JavaScript passed syntax validation.

## Live result

Installed on the existing Fly app `wlmd-stripe-test-0f89b1bb`, machine `84e117f290dd38`, retaining its persistent database. Image: `registry.fly.io/wlmd-stripe-test-0f89b1bb@sha256:d4fda2053ec3069988a3537930caaeb4f7b35c2289fb6e6d1a23f9bb26045823`. Previous image: `sha256:eecfd35251429645dba5cb135140fd15564e8e13d943a604f95bd9d46487e28c`.

Import created 114 records and appended treatments to three existing therapies. A second invocation was a no-op. Total master records: 281, including the existing unassigned legacy record. All 30 runtime intake bindings resolved successfully. All 15 base SKU spellings, delivery intervals, shipment counts, included-refill counts and check-in flags were independently checked against the original workbook.

The private pre-release database backup remains on `/data/master-additions-20261026-before.sqlite3`; never copy it to GitHub. Comparison after installation confirmed that the only modified existing configuration records were the three intended therapy records, and all existing purchase/checkout records remained identical. Preflight recorded 19 awaiting-card forms and two unresolved authorization attempts; these were preserved without retries or payment operations under the owner's prior deployment authorization.

Public health returned HTTP 200 with payment readiness enabled; unauthenticated admin state returned 401. The served master editor asset matched the release. FortifyHP's public plans API retained its 41 existing plans. These new master drafts have not been published to a client site. No live order or clinical workflow was exercised by this catalog update.

The release was built using Fly's remote builder because local Docker was unavailable. Targeted tests ran against the clean release source; hosted health, assets, runtime bindings and database preservation were then verified. Unrelated AWS/MySQL work in the shared checkout was excluded from this image and commit.
