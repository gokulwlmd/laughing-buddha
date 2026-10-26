# FortifyHP finalized storefront catalog

## Scope and decisions

The owner approved publishing finalized master products to the existing FortifyHP Lovable site's Available Products pages. Use the shared Fly application, FortifyHP site, Sticky campaign 195 and its existing Stripe v2 profile 269. Existing customers, orders, subscriptions and prices are preserved. This is not an AWS deployment.

The rollout covers the 30 product families with matching existing informational pages. The original five families retain their 40 choices. Another 271 exact base variants have one-time and terminal `-SUB` counterparts: 542 choices, including the previously published NAD annual subscription. Published total: 582 choices, 291 of each purchase type. Unresolved formulations and products without an exact existing page remain outside this publication.

The SKU names are copied exactly from the approved master catalog. Do not normalize punctuation or replace aliases with invented spellings. New optional API fields `sku`, `family_id`, `treatment_id` and `format` disambiguate strengths, quantities and formulations. Medication labels distinguish variants. Lovable's price-free identity registry must agree with those fields and the duration. The API remains authoritative for prices and availability.

Delivery schedules come from each SKU's approved contract. Monthly deliveries must remain monthly, while quarterly products retain 90-day deliveries. The full term is paid upfront; a subscription renews after the full term, not at every included delivery. Portal refill policies retain each SKU's check-in requirement and the existing 20-day claim window. No separate refill SKUs are introduced.

New independent catalog products use the existing site's physical, non-taxable, free-shipping configuration and exact approved SKUs. The owner's external fulfillment system consumes Sticky orders. Product publication does not represent a prescription, clinical approval or medication shipment. Existing provider product IDs and order mappings are not overwritten.

## Implementation and recovery

`tools/stripe-v2-checkout/fortifyhp_rollout.py` is restricted to the existing shared app and campaign. Its stages are `prepare`, `provision`, `verify_quotes`, and `publish`. Private journal and pre-change database backup are stored on `/data`; they must not be committed. Every external write is journaled before submission. A pending or ambiguous result requires read-only reconciliation, never a blind retry. Completed steps are resumed by verified object ID.

Products are grouped into offers with identical billing configuration. All approved choices must pass read-only full-upfront quotes before publication. After publication, run `ops/fortifyhp_site_sources.py` with the app directory on `PYTHONPATH` to add canonical site/template source copies and update the manifest source references. This separate operator script was applied to the live database without another runtime release. It preserves all previous source/public URLs and rejects conflicting canonical records. The local publication records are committed together, then the site manifest is atomically replaced. Existing public URLs and unfinished attempts remain saved.

Verified display catalogs avoid fetching hundreds of provider products when someone opens Available Products. Local edits to the catalog invalidate the saved display snapshot. Checkout still resolves and quotes the selected provider product before payment; this snapshot does not authorize a charge.

The shared admin supports up to 256 SKUs in a purchase option and 1,000 alternatives in a checkout, so the expanded ED and HRT groups remain editable. Larger sets and duplicate selections remain rejected.

## Verification and deployment

- Deployed and verified on the shared Fly app: `registry.fly.io/wlmd-stripe-test-0f89b1bb@sha256:6a3edbbdd489dd17e5810ba1e469ba63b6a33297acc1c12e0bdb1cefeb7d4179`. Runtime source hashes match the isolated release files. Unrelated working-tree AWS/MySQL changes were excluded.
- Sticky: 541 new products, 13 new offers, 542 successful read-only upfront quotes including the retained NAD subscription. No provider orders created.
- Live API: 582 choices, 291 exact once/SUB pairs. All 41 previous prices, durations, renewal intervals and shipment schedules match their pre-change values. Existing required nullable API fields are preserved; optional identity fields are omitted when unavailable.
- Existing admin records are unchanged except for added display identity on the retained NAD campaign master. All ten new template groups have matching canonical admin checkouts with current template snapshots (none missing or stale). Patients and captured/unfinished payment states are preserved. Browsing product pages can create ordinary fresh checkout sessions; those are not paid orders.
- Lovable publication `745b5656-e88e-4e9e-9966-09046fdab8c3` is live at https://fortifyhp-care.lovable.app. Its 271 base identities match backend metadata exactly. The storefront's 148 focused/regression checks and offline desktop/mobile checks passed. Live browser verification confirmed NAD injection/nasal cards with prices, annual NAD once/SUB selections and four deliveries 90 days apart, plus ED strength/quantity choices and annual Divigel with 12 deliveries 30 days apart.
- A final public catalog request returned all 582 choices in 1.77 seconds from the operator's location. This is a single warm measurement, not a latency guarantee.
- Targeted backend verification: 97 tests plus two canonical-source tests passed, covering full provisioning/resume, both purchase types, monthly/quarterly schedules, API compatibility, prior site publications, intake/refill bindings and catalog invalidation.

No live test orders, card authorizations, patient identity submissions, clinical submissions or password changes are part of this rollout.

## Remaining work

The queued portal subscription/card-management review follows this catalog publication. Saved-card upsells remain disabled until their provider path is verified. Products without exact matching informational pages require a separate storefront change rather than substitution with a similar formulation.
