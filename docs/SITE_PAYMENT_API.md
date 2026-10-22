# Checkout APIs for your own frontend

Swagger: <https://wlmd-site-api-demo-0f89b1bb.fly.dev/sites/payment-test/docs>

OpenAPI JSON: <https://wlmd-site-api-demo-0f89b1bb.fly.dev/sites/payment-test/openapi.json>

Base URL: `https://wlmd-site-api-demo-0f89b1bb.fly.dev/api/v1/sites/payment-test`

These APIs let your frontend own plan selection, customer details, Stripe's
secure payment fields and the order confirmation. The new `/sessions` flow
returns a checkout session, **not a checkout URL**. No frontend was added or
changed for this API release. The old `/checkout` redirect endpoint remains
available for the older demo and is marked deprecated in Swagger.

The current site contains sixteen approved campaign-422 payment-test plans.
Its gateway is live: customers who finish payment make real payments. No
medication is shipped by these test plans. Account credentials remain on the
payment server. Only a session-scoped bearer token, the Stripe publishable key
and that customer's PaymentIntent client secret are returned to the customer.

## Endpoint sequence

| Request | Body | Result |
| --- | --- | --- |
| `GET /plans` | None | Medications, durations, prices and terms |
| `POST /sessions` | `{ "plan_id": "sema-1m" }` | `session_id`, `session_token`, `expires_at` |
| `GET /sessions/{id}/configuration` | None | Public Stripe configuration, allowed countries/shipping and plan terms |
| `POST /sessions/{id}/quote` | Contact/address and optional `shipping_id` | Exact `quote_id`, `amount`, `currency`, terms and required consent |
| `POST /sessions/{id}/payment` | `quote_id`, `accept_terms` | Stripe `publishable_key`, `client_secret`, intent ID and verified amount |
| Your browser confirms with Stripe.js | Secure Payment Element | An authorized PaymentIntent, normally `requires_capture` |
| `POST /sessions/{id}/complete` | `{ "payment_intent_id": "pi_..." }` | Verified order receipt with `status: "captured"` |

All session-specific requests require:

```http
Authorization: Bearer SESSION_TOKEN_FROM_CREATE
Content-Type: application/json
```

No account API key is required for this public payment-test site's session
creation. The token authorizes exactly one checkout. A different checkout's
token is rejected. Save the session ID/token in that customer's browser/server
session before requesting payment preparation. Access expires after 24 hours;
expiry does not cancel, reset or retry a payment. Never log, share or put the
session token or PaymentIntent client secret into URLs.

The APIs accept no client prices, campaigns, gateways, alternative destinations
or raw card details. Pricing and permitted payment choices come from approved
site mappings and the payment engine. Plan display prices are major-unit
strings (`"249.00"`); quote/payment `amount` values are integer minor units
(`24900` means USD 249.00).

## Example quote

```json
{
  "contact": {
    "name": "API Integration Test",
    "email": "customer@example.invalid",
    "phone": "+12025550100",
    "address": "1 Test Way",
    "city": "San Francisco",
    "region": "CA",
    "postal_code": "94105",
    "country": "US"
  },
  "shipping_id": null
}
```

Use two-letter US state/territory codes, not full names. Configuration lists
the campaign's allowed countries/shipping choices. `shipping_id: null` is valid
for these non-shippable test plans; use the configured shipping ID when required.
The API does not accept card numbers, expiry dates or CVV.

Example response:

```json
{
  "quote_id": "SERVER_GENERATED_QUOTE_ID",
  "amount": 24900,
  "currency": "usd",
  "payment_terms": "Pay 249.00 USD today. One-time payment. No automatic renewal.",
  "terms_consent_required": false
}
```

Display the actual returned amount and terms. If `terms_consent_required` is
true, collect the customer's explicit agreement and send `accept_terms: true`
when preparing payment. Native prepaid schedules require acceptance of their
payment terms even when they have no automatic renewal. Do not infer renewal
from that consent flag; read the displayed terms and plan's `renewal` value.
Quotes expire after ten minutes. A changed price or route requires a fresh
quote and customer review.

## Render payment in your frontend

Use the **returned payment response's** `publishable_key` and `client_secret`
to initialize Stripe.js and mount its Payment Element in your own page. This is
the existing Sticky-created Stripe v2 intent; do not create an independent
Stripe charge or send card data to this API.

Confirm that intent using Stripe.js `confirmPayment` with `redirect: 'if_required'`
and your frontend's HTTPS `return_url`. Normal card checkout can stay on your
page. Bank authentication or redirect-based payment methods can still require
a redirect, as documented by [Stripe](https://docs.stripe.com/js/payment_intents/confirm_payment?type=paymentElement).
Keep the session ID/token through the bank-return flow, remove Stripe's return
query parameters from the address bar, and retrieve the same intent's result.

Only call `/complete` after Stripe reports the matching intent with status
`requires_capture`. This tells the API to finish the existing Sticky order and
verify its read-back. The browser's success message alone is not an order
receipt. Only API `status: "captured"` and its `order_id` mean this application
has verified completion. The API does not independently retrieve intents with a
Stripe secret key; it retains the existing Sticky capture/read-back contract.

## Refresh, decline and uncertain results

| Request/state | Action |
| --- | --- |
| `GET /sessions/{id}` | Read durable payment status and the recorded receipt |
| `POST /sessions/{id}/resume` with `{}` | Retrieve the same prepared intent after refresh/decline; creates no new intent |
| `new` | No prepared intent yet; may already have a reviewed quote |
| `awaiting_card` | Resume the same intent; do not create another session to retry it |
| `authorization_pending`, `capture_pending`, `needs_review` | Check status and preserve this checkout; do not blindly repeat a payment |
| `captured` | Show its recorded order receipt; repeating completion returns the same receipt |
| HTTP 409 | Inspect status/error; a changed price needs review, and an uncertain payment stays held |
| HTTP 410 | Session access expired; contact the store about unfinished payments |

If an authorization reply is lost, resume can recover the exact existing
intent when the payment engine has it. An uncertain capture is never retried
blindly; a later confirmed receipt can resolve it. A payment-service restart
that loses an unfinished intent's in-memory client secret remains a held case.
These APIs add no refund, cancellation, subscription-management or webhook
reconciliation feature.

## Calling from another frontend

Server-to-server requests work now with the session token. Return the payment
setup JSON to that customer's browser so it can use Stripe's secure fields.
The unchanged payment engine currently sees this API service's network IP,
including for browser-originated API calls. No arbitrary client-IP override is
accepted. Preserving end-customer IP in Sticky requires a trusted native bridge
in the payment engine; that worker update is deferred to preserve open forms.
Stripe's browser confirmation still runs in the customer's browser.

The owner authorized any frontend origin. `SITE_API_ALLOWED_ORIGINS="*"`
enables direct browser GET/POST calls with Authorization/Content-Type from any
origin. Each session still requires its own bearer token; cross-origin cookie
credentials are disabled. No domain registration or new processor credentials
are needed. Keep session tokens private to the customer using that session.

## Operation and verification

The API service stores only its own session bindings and upstream checkout
cookies on its separate Fly volume. Tokens are hashed; contact details and
Stripe client secrets are not persisted in this API database. Payment state,
customer details and receipts remain in the existing durable payment engine.
Verified HTTPS carries the session-scoped requests to the existing checkout service.
It cannot select an arbitrary upstream host/path or forward owner credentials.
The live payment worker, original volume and old attempts were not restarted or
replaced. No Sticky/Stripe account credentials were copied into the API app.

Offline tests cover the existing engine with fake Sticky responses, including
server pricing, consent, isolated sessions, stale quotes/routes, lost replies,
resumption, idempotent completion and crash recovery. Live verification calls
only session creation, configuration, status and one synthetic draft quote. It
never invokes payment preparation, Stripe confirmation, capture or order
creation. Existing upstream latency remains; this release does not claim a
completed live charge or faster end-to-end processing.

Run the non-payment hosted smoke check from the repository root:

```sh
.venv/bin/python scripts/check_site_payment_api.py --quote
```

## Response speed

The API keeps the plan display catalog warm in the background. Public display
configuration is shared for at most 60 seconds by link and plan; each caller
still passes a fresh session/link access check. Concurrent readers share one
configuration load. An expired cache is never used to hide an upstream error.
Quote, authorization, resume and capture continue using fresh authoritative
checks. Use the publishable key returned by `/payment` when initializing Stripe.

HTTPS connections are reused without sharing cookies. Connection failures never
trigger automatic retries. Payment preparation fetches configuration and status
concurrently, then waits for both before preparing or resuming the intent.
`Server-Timing` reports application time without exposing payment details.

Run `scripts/benchmark_site_payment_api.py` with the project virtualenv to measure
plans, session creation, configuration and a synthetic draft quote. It makes no
payment calls. See [measured speed evidence](SITE_API_SPEED.md) for current
results and limits. No frontend integration changes are required.
