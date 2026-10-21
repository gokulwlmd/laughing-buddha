# Therapy purchase options and checkouts

The owner-defined hierarchy is **Therapy → Purchase option → Assigned SKUs → Branded checkout**.

A purchase option represents a product duration, such as a **3-month plan**, and contains treatment alternatives such as TIRZ-3M and SEMA-3M. The customer chooses **one SKU**, then one of its configured payment choices: one-time, subscription or supported prepaid. SKU duration must match the purchase option exactly. Product duration remains independent of billing frequency and clinical/refill rules.

## Owner workflow

1. Create a therapy in **Therapies**. The Weight Loss starter fills a reviewable draft with Tirzepatide and Semaglutide.
2. Open **Purchase options**, choose the therapy and duration, name the plan, and select its allowed payment types. You can save it before assigning SKUs.
3. Assign matching-duration SKUs in the purchase-option editor. If a SKU is missing, use the Master SKUs shortcut to add it with its therapy, treatment, duration and billing configuration, then return to assign it.
4. Apply the master SKUs to the brand campaign in **Campaigns**. Each SKU retains its own rules, and each brand retains its configured prices.
5. Open **Checkout links → brand → New plan checkout**. Select the campaign and therapy, then load purchase options. Choose one option for a dedicated checkout, or several for comparison. Their assigned SKUs and supported payment choices are included automatically. Review and approve publication.
6. Copy the public or private link. Duration cards show **each treatment's price and payment terms before selection**. The customer selects a duration option, one treatment/SKU, and a payment choice. A checkout containing one duration option preselects that duration.

“Purchase option” means the duration-level catalog record. Master-SKU one-time, subscription and prepaid configurations are labelled **payment choices** to distinguish them.

No example products, durations or prices are automatically added to production. Only configured master assignments for the selected brand/campaign supply checkout prices; unrelated Sticky offers with the same SKU are excluded. Trial and complex billing flows retain their existing capability restrictions. Listed prices are product prices; Sticky calculates final totals, shipping, taxes and billing adjustments at checkout.

## Changes and publication

Purchase options are reusable presets. Published checkouts retain the approved snapshot of assigned SKUs, payment types, name and duration. Editing a preset marks affected checkouts **Purchase option updates available**. Edit and publish the checkout again to adopt the new version. Managed brand price replacement continues updating existing child mappings through the established reviewed pricing workflow.

Disabling a purchase option immediately makes its published choices unavailable. Disabling a therapy or parent checkout also blocks its children. All affected open payment attempts block these edits. Changing a master SKU's therapy or duration is rejected while it is assigned to an incompatible purchase option; remove the assignment first. Published choices also recheck current master duration at access time.

## Implementation

- `plans.py` stores `therapy`, `purchase_option` and `plan_checkout` records in the existing SQLite configuration table. This release does not migrate or rewrite saved configuration.
- New checkout proposals provide purchase-option IDs. The server derives membership and exact offer/product/model keys from each approved master assignment and current managed offerings for the selected brand/campaign.
- Every purchase-option/SKU combination has its own private child checkout. Different options sharing a SKU cannot grant access to each other's payment choices. The choose endpoint validates the complete option/SKU/payment combination before handoff.
- Public/private `/plans/{id}` URLs reuse existing invitation, revision and payment safeguards. Browsing or selecting a plan never authorizes or captures payment.
- Configuration fingerprints include purchase options. Stale owner previews require a fresh review. Published membership changes disable removed children and rotate parent/child invitations.
- Existing standalone links and earlier manually configured multi-SKU links remain supported. Earlier multi-SKU customer pages are grouped by their explicit master duration; editing them retains their established SKU/payment selection workflow. There is no automatic conversion to new purchase-option records.
- Customer preferences do not establish clinical eligibility, prescribing, dosage, medication benefits or refill approval.

## Verification

`test_purchase_options.py` covers matching duration, incompatible later master edits, empty draft options, server-derived prices and choices, injected membership rejection, isolated access when two options share a SKU, publication snapshots, disabling, open-payment guards, excluding unrelated same-SKU offers, brand-price replacement, missing assignments and stale previews.

`qa/therapy.spec.cjs` uses the actual admin UI to create therapy and master records, assign SKUs to duration options, provision a fixture campaign, publish one or multiple purchase options, compare per-treatment prices, edit and republish, and exercise private access, mobile layout and payment handoff. A synthetic one-time order is captured once; the recurring choice reaches checkout with the correct model. All payment tests use fake Sticky and Stripe services.

Latest verification: 144 backend tests passed; all 62 browser scenarios are verified across the full run and a targeted rerun after correcting a sign-in readiness wait in the test helper. See [the QA receipt](PURCHASE_OPTIONS_QA_RESULTS.json). The container startup/persistence checks and read-only hosted desktop/mobile sign-in checks passed. Served assets match the tested image. Owner, configuration, reviews, checkout attempts and purchase-successor records have identical before/after hashes; no live Sticky or payment writes were made.
