# Two-step checkout and API-driven onboarding

## Checkout

The owner requested two steps: contact/address/discount, then a large payment
form. Products retain independent Sticky orders and charges. Consent remains
unchecked and binds to each exact quoted amount and renewal term. No amount
shown provisionally in Stripe Elements may be sent as a charge amount.

Managed checkout remembers only a nonsecret gateway ID for up to 120 seconds
(256 entries per process). This hint lets fresh campaign and gateway
reads run concurrently. Products are read only after current campaign membership
is confirmed. The current campaign mapping wins;
if its gateway changes, the newly mapped gateway is fetched. No product, price,
routing configuration or quote is served from this hint store. Every total still
calls Sticky's calculator; authorization and capture retain fresh validation.
This reduces serial network waits, not the provider's processing latency.

## Post-checkout contract

API base: `https://wlmd-stripe-test-0f89b1bb.fly.dev`.
All patient paths are scoped to `/api/v1/sites/{site_id}/portal`.

1. For each **captured** checkout, call the existing session `POST /portal`
   with its checkout bearer. This returns a short-lived, site/order-bound
   enrollment URL. Its fragment contains a private invite; never log it or
   place it in analytics, GitHub, or query strings.
2. `GET /portal/onboarding` returns versioned paths, minimum password length,
   the portal URL, and the current intake provider connection status. Frontends
   resolve only expected paths on the configured backend origin.
3. `POST /portal/auth/enroll` takes `{invite_token, password}`. It creates a
   real site-specific account with a scrypt password hash and returns a patient
   bearer session. It never changes an existing account's password. Existing
   members use `POST /portal/auth/login` with `{email, password}`.
4. `POST /portal/auth/claim` with the patient bearer and `{invite_token}` links
   each other purchased item. It requires the receipt invitation and a matching
   authenticated account email, even when Sticky assigned separate customer
   IDs. Successful claim replay is idempotent. Email alone is never proof.
5. `GET /portal/intakes/{order_id}` returns that owned order's saved answers,
   revision, current step and therapy-specific question/section schema.
6. `PATCH /portal/intakes/{order_id}` takes `{revision, answers, current_step}`.
   Save partial answers, serialize writes, retain unsaved input on failure, and
   handle revision conflicts explicitly. Do not put medical answers in browser
   storage or analytics.
7. `POST /portal/intakes/{order_id}/submit` takes `{revision}` after the latest
   save succeeds. Required visible questions are checked server-side. Reload
   after a lost response instead of blindly submitting again.

The backend questionnaire adapter is the existing temporary therapy/SKU adapter.
Submission is durable account storage; it is not clinician delivery, clinical
approval or shipment release. Completion copy says the answers were saved.
The future medical API and password provider belong behind adapters; no provider
credentials or hard-coded questionnaire belong in Lovable.

The FortifyHP storefront origin is enabled for patient bearer APIs. Other sites
may register exact HTTPS `portal_origins` in their site configuration. This is
separate from the public checkout API's wildcard CORS. Patient authorization is
still site-bound; cookies are not shared cross-origin and admin endpoints do not
inherit portal CORS.

Only offline payment/order fixtures may be used for automated full-flow checks.
Live verification uses configuration and quotes, never a charge or an actual
patient's medical intake.

## Backend verification and publication (23 October 2026)

- 450 backend tests passed, including fresh product/campaign validation,
  concurrent configuration reads, exact origin restrictions, real offline
  enrollment and partial intake persistence, and multi-order claims.
- Published image: `registry.fly.io/wlmd-stripe-test-0f89b1bb@sha256:651bfff63172d9632071fbe79ad6a3393cb3506ccf186d9360d777f95cd6708e`.
- Same Fly machine and volume retained; an on-volume database backup was taken
  before restart. No payment was retried, charged, canceled or deleted.
- Health and onboarding contract returned 200; unauthenticated patient access
  returned 401; patient CORS returns only the registered storefront origin.
- Storefront release `5672784f81a20fb423d3f0344e3574a8f7adf5f9` is public.
  150 focused frontend tests and build/type checks passed; mocked desktop/mobile
  journeys covered enrollment, independent intakes, save/resume and submission.
  String template versions are accepted. A small heading offset follow-up
  `0ab915a952aa3f6025a0ee808782546916bd6de7` passed 25 relevant checks and build.
- Public browser QA reached Details → Payment with synthetic contact data,
  a real Stripe Elements panel and an authoritative USD 69 one-time quote.
  The step transition took approximately 0.8 seconds in this observation.
  No consent was accepted, no card was submitted and no order was placed.
- Provider quote timing remains variable: sampled requests took 5.49 and
  10.53 seconds after deployment (baseline 7.59 seconds). Warm session and
  configuration requests took 0.53 and 0.52 seconds. This is not a guarantee
  of end-to-end payment speed. Background preparation and early card mounting
  reduce how much of this wait blocks the customer.
- The medical provider remains unconnected; intake saves are real account
  records, but clinician delivery and approval are not claimed. New postpayment
  account/intake completion was tested offline, not with a real card charge.
