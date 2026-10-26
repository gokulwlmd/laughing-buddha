# Payment confirmation timing — 26 October 2026

The owner reported slow Pay-to-confirmation on FortifyHP. A read-only probe
from the live Fly machine resolved one existing captured Fortify plan without
submitting an authorization, order, card or customer information.

Observed configuration resolution: 12,107 ms total. The campaign GET alone
was 11,214 ms; the concurrently started gateway GET was 426 ms, then the offer
GET took 587 ms and product GET 300 ms. This is one sample, not an SLA or a
measurement of Stripe authorization or Sticky new_order latency.

The financial engine performs a fresh campaign/price validation before
Sticky authorization and again before capture. The cart processes individual
orders sequentially. These waits therefore accumulate. There is also a global
engine mutation lock; its actual contribution on the user's order was not
measured and it remains in place to preserve admin/payment coordination.

## Published change

The site session API previously fetched /api/config immediately before
/api/authorize or /api/resume, duplicating remote catalog work. It now gets the
publishable key from the engine's exact validated authorization/resume response.
The initial configuration prerequisite remains. The engine still verifies fresh
campaign, gateway, product, offer, total, coupon, consent and order readback.
No price caching, write retries, concurrency of financial writes, response-time
padding or premature success was added. Public API response shape is unchanged.

Sanitized logs now record operation duration for provider campaign, offer,
product, gateway, calculation, authorization, new-order and order-view calls.
Engine mutation logs separately record lock wait and execution duration. Logs
contain fixed operation labels and timings only: no identifiers, customer data,
request/response bodies, card data or credentials. They will allow the next
customer-driven attempt to be measured without repeating a real payment for QA.

## Validation

206 targeted offline tests passed across checkout, site session API, catalog,
quotes, coupons, prepaid, test billing, external fulfillment, visits, entry,
transport/runtime, public access, receipt intake, upgrades and admin behavior.
After adding lock timing, 32 affected checkout/preparation tests passed again.
The new cases verify one fresh validation instead of duplicate config reads,
both resume paths retaining the intent, gateway drift blocking authorization,
failed status stopping before authorization, missing verified keys remaining
held, and timing logs excluding sensitive payloads/errors.

Fly image:
`registry.fly.io/wlmd-stripe-test-0f89b1bb@sha256:6f1131dc5d8a2d5a0f51505ccaca30a1767020cce52ad36f9ae8128d3312f2ee`

Prior image:
`registry.fly.io/wlmd-stripe-test-0f89b1bb@sha256:c24ead25fdfdc04140c53fac614faa8bf77395367cc769cb34b101ed053fe658`

Pre-release private backup: `/data/backups/intake-steps-1793032790` (39 SQLite
databases and two encryption keys). Existing unfinished attempts remain saved.
The live /health endpoint returned HTTP 200 with payments configured. Both changed
runtime files matched the tested source hashes, and all 22 previously unfinished
checkout records matched the backup byte-for-byte.

The largest observed dependency delay remains the fresh Sticky campaign GET.
This release removes a duplicate lookup; it does not establish that total
Pay-to-confirmation latency is solved. No real payment was submitted or retried.
