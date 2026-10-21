# Sticky Stripe Connect v2 campaign/SKU checkout

A private integration harness deployed at `https://wlmd-stripe-test-0f89b1bb.fly.dev`. It resolves any campaign/SKU accessible to the Sticky API and accepts card details only through Stripe Elements. This is separate from the planned production application.

## Links and configuration

Use `/checkout/{campaign_id}/{url_encoded_sku}`. The original example is:

`https://wlmd-stripe-test-0f89b1bb.fly.dev/checkout/422/WLMD-CORE-2USD-0f89b1bb`

The existing private invitation signs the owner into the host; links require that access cookie. To sign in directly on another campaign/SKU page, append `?access=INVITATION` using the existing private token, without saving it in source or documentation. The app exchanges it for an HttpOnly Secure cookie and removes it from the URL. Do not log query strings or share invitation tokens publicly. `/` redirects to the original example. Campaign/SKU links stay reusable: a new visitor gets a fresh checkout; a returning browser sees its current attempt or receipt. A completed receipt has a **Start another purchase** button, which creates a separate attempt with a new intent when the customer proceeds to payment. The original receipt stays stored.

The server reads the campaign's offers, fetches only their candidate products, matches the exact SKU, and presents configured offer/product/billing-model choices. Duplicate SKU records remain distinct choices. It reads the campaign's Stripe Link gateway mapping and verifies provider 250; it never changes campaign settings or substitutes gateway 254 for unrelated campaigns. Countries, shipping, gateway currency and positive order totals come from Sticky.

Supported payments are standard one-time and day-based recurring offers, quantity one, with one address used for billing and shipping. Recurring billing needs explicit consent. Other accessible offers remain visible but payment is blocked if they require unsupported trial, prepaid, series, seasonal, bundle, variant or custom-schedule selections. Delayed capture and capture-on-shipment profiles are blocked. Supported two-decimal currencies: USD, EUR, GBP, CAD, AUD, NZD, CHF. A valid campaign/SKU alone does not establish payment eligibility.

## Pricing and payment boundary

`/api/quote` calls Sticky `POST /api/v2/order_total/calculate` with the configured offer, model, quantity, shipping selection, billing location and `use_tax_provider: 1`. No price override is supplied. Ten-minute quotes and configuration fingerprints are stored server-side and revalidated before authorization and capture. The browser cannot submit an amount, gateway, arbitrary product or PaymentIntent.

Authorization uses explicit billing/shipping fields, `forceGatewayId` and **`auth_amount`** in currency units. Sticky returns the client secret and matching `transactionID`/`transId`. Stripe.js confirms this intent, including its frontend challenge, with the campaign/SKU page as the HTTPS return URL. Capture uses Sticky `new_order`, `creditCardType: stripe_link`, `tranType: Capture`, and that server-stored `transactionId`. No independent Stripe charge or custom line-price override is created. Read-back must confirm the expected approved order and amount before completion is recorded.

No Stripe private key is needed for this flow. The gateway's publishable key is public; gateway OAuth/access/refresh tokens remain in Sticky. The harness does not independently retrieve PaymentIntents server-side. Additional Sticky response 101 completion, webhooks, refunds, subscription management, and clinical/refill orchestration are not implemented. Such results are held for reconciliation rather than reported as paid.

## Install and validate

From this directory:

```sh
python3 -m venv /workspace/.venvs/stripe-v2-checkout
/workspace/.venvs/stripe-v2-checkout/bin/python -m pip install -r requirements-dev.txt
/workspace/.venvs/stripe-v2-checkout/bin/python -m unittest -v test_checkout test_admin test_qa test_master test_brands
node --check web/app.js
node --check web/admin.js
node --check web/brand-design.js
npm --cache /workspace/.cache/npm --prefix qa ci --ignore-scripts
/workspace/.venvs/stripe-v2-checkout/bin/python qa/run.py
```

All 133 backend tests and 61 Chromium browser scenarios pass without real payment or Sticky configuration writes. Browser cases use a fake Sticky service and Stripe.js contract stub; see [the QA report](../../docs/QA_REPORT.md). The backend tests make no external requests. They include buying twice through the same link with distinct intents/orders, preserving the first receipt, repeat-click idempotency, persistence, independent first visits, and rejecting stale tabs or replacement of an unresolved attempt. They cover campaign access, exact and duplicate SKU resolution, configured selections, authoritative prices/taxes, changed configuration, recurring consent, secret/card-data boundaries, session isolation, legacy receipt migration, repeated capture and uncertain/3DS holds.

## Start and persist

Reuse `STICKY_API_USERNAME` and `STICKY_API_PASSWORD` secure bindings scoped to `whitelabelmd.sticky.io`.

```sh
CHECKOUT_AUTHORIZATION_VERIFIED=1 /workspace/.venvs/stripe-v2-checkout/bin/python -m uvicorn app:app --host 127.0.0.1 --port 8000 --workers 1 --no-access-log --no-proxy-headers
```

`CHECKOUT_PUBLIC_URL` must be a working HTTPS origin before card entry. `/health` checks startup. Do not send cloud loopback links to the owner. See [FLY.md](FLY.md) for hosting updates and existing deployed secrets/resources.

SQLite `checkouts` and the invitation live in `CHECKOUT_STATE_DIR` (`/data` on Fly). The original singleton `purchase` table is preserved and migrated into the legacy checkout. All campaign/SKU attempts use browser-specific cookies and durable rows. `POST /api/new-purchase` requires private access, CSRF/origin validation and a completed previous attempt. Its durable `purchase_successors` mapping makes double clicks and response retries return one successor. Pending or uncertain attempts cannot be replaced. Requests carry `X-Checkout-Attempt`; stale tabs are rejected before they can act on a different purchase. Never delete/reset an attempt after an uncertain response. Atomic state transitions prevent automatic repeat authorizations/captures. Use one machine and worker because client secrets exist only in process memory. A browser refresh calls POST /api/resume to restore the same cached authorization, contact and selection after checking the configuration fingerprint; it cannot create a replacement intent. Reconcile any open authorization before restarting; a restart loses its in-memory secret and leaves the attempt held for reconciliation.

Hosted verification of the reusable link passed: the prior receipt stayed intact, a fresh attempt quoted USD 2.00, repeated start requests reused that attempt, and stale-tab requests returned 409. No additional live authorization or capture was submitted. See `deployment.json` for the image and validation metadata.

## Original payment evidence

The owner reported the $2 checkout working; its durable state recorded captured order **505015**. Read-back on 2026-10-21 confirmed USD 2.00, campaign 422, product 54537, offer 706, billing model 2, gateway 254 and non-recurring quantity one. Sticky then returned status **6** with blank transaction/auth IDs. That later status has not been mapped authoritatively; current processor settlement is not independently verified. The existing receipt remains preserved, and no follow-up charge or refund has been submitted.

Read the reusable [checkout skill](../../.agents/skills/stickyio-stripe-checkout/SKILL.md) for the exact API and deployment workflow.

## Owner admin

The owner admin is served at `/admin`. See [ADMIN.md](ADMIN.md) for first-owner setup, email/password sign-in, brand/SKU/offer/link controls, explicit change approval, tests and current limits. Customer checkout access never grants admin access.

The admin includes versioned **Master SKUs** at `/admin#master` for assigning preset SKU/offer/billing configurations to campaigns. See [the master SKU guide](../../docs/master-sku-setup.md) for the first TIRZ-1M preset and test-campaign rollout workflow.

Fixed-term prepaid test plans are supported: [setup, verified orders and limits](../../docs/research/sticky-prepaid-quarterly-shipments.md). The native four-order test sequence is separate from the offline suite; no real processor payment was submitted.

## Therapy plan selection

Use Therapies to group master SKUs by treatment, then create a combined checkout inside a brand’s Checkout links workspace. Customers can compare treatments and durations and select an enabled purchase option. See [the owner workflow](../../docs/THERAPY_PLAN_CHECKOUTS.md). Configuration still requires owner preview and approval; no example SKU prices are automatically created.
