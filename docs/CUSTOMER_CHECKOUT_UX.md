# Customer checkout redesign

Deployed on 22 October 2026 at the owner's request, using the [VigMD checkout](https://checkout.vigmd.com/wl_checkout/?product=semaglutide) as a visual reference. The implementation uses its clear plan/pricing/form/summary hierarchy without copying medical benefits, included services, savings, cancellation promises, imagery or other claims not configured in this project.

## Customer experience

The parent plan page displays duration cards with each treatment's upfront price. A treatment appears once even when one-time and SUB options have different SKU records. Its payment cards distinguish One-time purchase and Subscription, retaining full upfront pricing, delivery schedules and exact day-based renewal terms. The selected payment's original SKU, option key and purchase-option ID are still used for the server-validated handoff. No additional backend offer becomes available through grouping.

The child checkout has a clear product/plan summary, price, three-step progress, contact and address sections, review and card payment. It hides a redundant payment dropdown when only one choice is available and hides a redundant delivery selector when only one delivery method is configured. Hidden selects retain their original validated request values. Mobile uses a compact summary with an accessible View plan details toggle. Customers see their plan and total before scrolling through the form.

SKU codes, campaign labels, internal offer/model names, Private checkout, Sticky order, shipment orders and synthetic product implementation wording are removed from the customer presentation. Receipts use Order number. The live-charge/no-medication notice remains visible for payment-test checkouts. Recurring/prepaid consent, full upfront prices, exact renewal days, review, Stripe Elements and the payment state machine remain in place. No new medical or discount claims were added. Public/private access rules are unchanged.

The plan subtotal comes from catalog prices; the final total comes from the server quote. The UI never invents a tax/shipping breakdown from the difference between those amounts. Product names/durations use the existing human-readable catalog labels; billing is always based on the returned payment option, not parsed SKU suffixes.

## Files and rollout

The new pages load `web/checkout-v2.js`, `web/checkout-v2.css`, `web/plan-selector-v2.js` and `web/plan-selector-v2.css`. `web/index.html` and `web/plans.html` are their entry points. Legacy app/plans scripts and styles remain intact for pages already loaded in browsers. Future customer changes should use the v2 files; do not assume the old app.js is the active checkout entry point. The QA runner syntax-checks every web JavaScript file, including new versioned assets.

An existing customer payment was awaiting card entry during this work. `scripts/deploy_checkout_assets.py --apply` published new assets before replacing either HTML entry point, so old HTML could continue fetching its original files while new HTML loaded the new version. The live Uvicorn PID/start time stayed identical, and the SQLite owner/reviews/catalog/checkouts/purchase/successor hashes stayed unchanged during application. No payment authorization, capture, cancellation, refund or catalog operation was submitted. Baseline HTML is backed up on the existing Fly volume under `/data/ui-backups/customer-checkout-v2-20261022`.

The current running container image was deliberately not replaced because that would interrupt the in-memory authorization cache. An immutable image containing the same redesigned files was built and pushed for the next safe container deployment: `registry.fly.io/wlmd-stripe-test-0f89b1bb@sha256:d1858245a4a430f15637c63c33c6d9bf3680d05a4c81aaead53a5b9d6da515de`. Use current source or this image for the next authorized deployment; do not redeploy the older image and unintentionally restore the earlier checkout. Normal payment preflight/reconciliation still applies before a process restart.

## Verification

183 backend tests and 74 unique browser scenarios were verified. The full browser run passed 72 scenarios; two assertions still expected earlier copy, and were corrected while preserving all payment and no-duplicate checks. Both passed on rerun, together with the final mobile summary and distinct-SKU handoff scenario. The new customer scenario verifies two treatment cards for four one-time/SUB SKUs, both treatment prices, exact 180-day renewal, correct SUB/non-SUB child selection, no technical identifiers in visible text, hidden redundant controls and no mobile horizontal overflow.

Desktop/mobile screenshots use synthetic QA fixtures. Hosted checks verified all six served assets by SHA-256, healthy service, unchanged private access, and the live four-plan selector with one-time/subscription choices. No card details were entered and the existing customer payment page was left untouched. See [the sanitized deployment record](../tools/stripe-v2-checkout/customer-checkout-ui-deployment.json).


## Medication-first revision (22 October 2026)

The owner requested a faster, clearer flow: **Medication → plan length and upfront price → one-time or subscription**. The selector now shows medication cards first, filters duration prices to that medication, and resets dependent choices when medication changes. Plan/payment clicks render locally without catalog requests or arbitrary selection defaults. Duration cards use a compact two-column layout. Continue immediately shows a loading state and prevents duplicate navigation; back navigation restores the current page state.

The card library is deferred until review/payment rather than blocking the contact page. An unresolved attempt is recognized directly from the initial status response, without first waiting for the full remote catalog or loading the card library. The old generic error is replaced by a payment-status panel with a read-only Check payment status action and configured support contact. It never clears the attempt, creates a successor, authorizes or captures another payment. A new payment is not a recovery mechanism for an uncertain result.

Read-only live diagnosis found one authorization_pending attempt with no stored intent/order. Its result could not be established from the application's persisted record or available sanitized application logs. It remains held; absence of an intent/order in the app is not proof of no processor authorization. Resolving that attempt requires an authoritative Sticky/provider lookup of the original request. No retry, reset, order creation, cancellation or charge was submitted. This remains an outstanding operational issue, separate from the deployed UI improvements.

Active assets are now **checkout-v3.* and plan-selector-v3.***. The v2 assets remain intact for open pages. The static rollout again preserved the running payment worker and every database fingerprint. Build and deploy current source for the next safe container replacement; the earlier v2-only image would restore the preceding layout. Remote campaign/catalog verification remains on the first plan load and selected checkout handoff; this revision does not claim those upstream calls are instantaneous. No cross-request price cache or payment validation bypass was introduced.

Validation for the medication-first revision: six targeted flow/status cases passed, and all eight payment regressions were verified. The uncertain-capture test initially expected the removed generic error; its assertion now targets the new panel and repeats a status check while retaining the one-order/no-repeat checks, and passed on rerun. Served asset hashes and live medication/price/payment selection were verified. The next-safe image is `registry.fly.io/wlmd-stripe-test-0f89b1bb@sha256:63375b369b4896b1a663bb4c6077de759404e074063a9fbde27941c49b4337a4`. See [the sanitized release record](../tools/stripe-v2-checkout/medication-first-ui-deployment.json).
