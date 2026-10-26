# FortifyHP finalized storefront catalog

## Scope and decisions

The owner approved publishing finalized master products to the existing FortifyHP Lovable site's Available Products pages. Use the shared Fly application, FortifyHP site, Sticky campaign 195 and its existing Stripe v2 profile 269. Existing customers, orders, subscriptions and prices are preserved. This is not an AWS deployment.

The rollout covers the 30 product families with matching existing informational pages. The original five families retain their 40 choices. Another 271 exact base variants have one-time and terminal `-SUB` counterparts: 542 choices, including the previously published NAD annual subscription. Published total: 582 choices, 291 of each purchase type. Unresolved formulations and products without an exact existing page remain outside this publication.

The SKU names are copied exactly from the approved master catalog. Do not normalize punctuation or replace aliases with invented spellings. New optional API fields `sku`, `family_id`, `treatment_id` and `format` disambiguate strengths, quantities and formulations. Medication labels distinguish variants. Lovable's price-free identity registry must agree with those fields and the duration. The API remains authoritative for prices and availability.

### Storefront grouping correction

The owner clarified that Available Products should present one card per master therapy, rather than one card per internal medication family. Erectile Dysfunction (ED), for example, contains Sildenafil, Tadalafil, Tadalafil Daily and the approved Amplify blend. The exact family identities remain necessary for matching approved plans; they are not separate top-level therapy cards.

Filter eligible families by audience before grouping. Inside a therapy, let the customer choose the medication/formulation, then its approved strength or pack size, duration and purchase type. Keep existing formulation-specific information and deep links accessible. Search for a medication should find its parent therapy. Group starting prices must use only that audience's eligible plans and retain the actual full upfront term. Do not broaden SKU eligibility, change billing/refill contracts or introduce unresolved variants to implement presentation grouping.

The owner's subsequent review clarified that the medicine selector must be part of the purchase panel, labeled "Choose your medication", rather than a detached full-width filter/navigation strip. Show the selected medicine explicitly, number the visible plan decisions sequentially, preserve focus while switching dedicated product routes, and suppress redundant legacy links to medicines already offered in that selector. Keep product media top-aligned so the configuration column does not create a blank image area.

This correction is published in deployment `033242be-af63-457e-a3d7-a4c5994d79de`, source commit `510a5cbe9fecffe97bb744871105c1fcde105434`. Lovable reported 236/236 tests passing across 24 files and a successful build. Desktop and 390px mobile fixture checks covered all four ED choices, selected text/checkmark, same-route and cross-route focus, sequential steps and no horizontal overflow; non-read requests were blocked. Live operator verification confirmed removal of the top band, the inline chooser and the Amplify-to-Tadalafil Daily route switch. Existing product eligibility and payment settings are unchanged.

Published in Lovable deployment `f0d84484-334b-4d5f-a4ab-04ef577915c2`, source commit `86c59379acb5aae4948a3c154e8aa8ebbea615f7`. The storefront now displays 13 men's cards and 11 women's cards. Women's sole Amplify option retains its appropriate label and page. All 30 exact families and 582 plans remain reachable. The Lovable build/typecheck and 147 focused/regression tests passed, with desktop/mobile fixture checks. Operator live verification confirmed 13 men's cards, one ED search result for Sildenafil, four persistent ED medicine links, Tadalafil Daily dose/term selections and Amplify's approved one-month five-pack with both purchase types. No cart submission or payment was made. This change requires no Fly/backend restart.

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
