# Two-call Site API demo

This is a running, isolated demonstration of the proposed integration, not the
production Site API. It does not import the live app, read its database or
credentials, contact Sticky/Stripe, collect card details, create orders, or
take payments. The existing Fly app is unchanged. The demo directory is excluded
from the live image by its existing Docker allowlist.

From the repository root:

```sh
.venv/bin/python tools/stripe-v2-checkout/demo/run.py
```

- Frontend: <http://127.0.0.1:8872>
- Willow Swagger: <http://127.0.0.1:8871/sites/willow-health/docs>
- Harbor Swagger: <http://127.0.0.1:8871/sites/harbor-wellness/docs>
- OpenAPI: <http://127.0.0.1:8871/sites/willow-health/openapi.json>

The frontend and API run on different ports, exercising actual cross-origin
requests. Select a sample site to compare independent branding/prices. Select a
medication, duration and purchase type, then Continue to checkout. A separate
branded demo checkout opens; Finish demo returns to the sample frontend without
creating an order or payment. No card fields or fake payment widget are used.

The 16 sample plans per site derive from the repository's weight-loss skeleton.
Willow uses its illustrative starter prices; Harbor uses a clearly independent
10% sample markup. These are not prices fetched from the live sites. One-time
plans charge upfront without renewal; subscriptions renew after 30/90/180/360
days. Six/twelve-month samples show two/four shipments, 90 days apart.

## The developer integration

```javascript
const base = 'http://127.0.0.1:8871/api/v1/sites/willow-health';
const {plans} = await fetch(base + '/plans').then(r => r.json());

// Render the plans, then send the customer's selected plan_id.
const result = await fetch(base + '/checkout', {
  method: 'POST',
  headers: {'Content-Type': 'application/json'},
  body: JSON.stringify({
    plan_id: 'sema-6m-sub',
    return_url: 'http://127.0.0.1:8872/complete'
  })
}).then(r => r.json());

window.location.assign(result.checkout_url);
```

No amount, campaign, gateway, processor key or admin credentials are accepted.
Return URLs must match the demo's registered frontend origin and `/complete`
path. Each generated link is independent and expires after 15 minutes. Sessions
are memory-only and disappear if this local demo is restarted. Only registered
frontend origins receive CORS permission. Swagger is site-specific and exposes
exactly the two public calls; use its example body to try them.

Swagger uses FastAPI's standard Swagger UI renderer and its default CDN assets:
[official configuration documentation](https://fastapi.tiangolo.com/how-to/configure-swagger-ui/).
The API, frontend and checkout need no external service; the Swagger UI assets
need internet access.

## Verification

```sh
cd tools/stripe-v2-checkout
../../.venv/bin/python -m unittest -q test_site_api_demo
QA_PYTHON=../../.venv/bin/python qa/node_modules/.bin/playwright test site-api-demo.spec.cjs
```

Seven backend cases verify catalog terms/site prices, rejected price overrides,
return URL/origin restrictions, independent expiring sessions, scoped Swagger,
absence of payment/admin routes, and no upstream network access. Three browser
cases verify the two real API calls, checkout/return navigation, a second site,
selection accuracy and mobile layout. The full backend discovery run passed 207
tests. CI now discovers all `test_*.py` modules rather than an incomplete fixed
list. Browser tests launch their own disposable demo servers.

Production work remains separate: map the two endpoints to approved published
site catalogs and the existing hosted checkout, provide the chosen site access
policy, integrate authoritative payment-return status, and review release to
Fly. The demo's Finish action must never be interpreted as a paid receipt.

## Public demo with the existing real checkout

Public frontend: <https://wlmd-site-api-demo-0f89b1bb.fly.dev/>

Swagger: <https://wlmd-site-api-demo-0f89b1bb.fly.dev/sites/payment-test/docs>

The owner explicitly chose the real Stripe v2 checkout for the public demo.
`demo.public` is a separate Fly service with **no processor credentials**. It
reads only the newly published campaign-422 weight-loss payment-test catalog.
Its two endpoints are:

```text
GET  /api/v1/sites/payment-test/plans
POST /api/v1/sites/payment-test/checkout
     {"plan_id":"sema-1m"}
     -> {"checkout_url":"https://…/go/…"}
```

Opening the returned link hands the selected SKU and approved payment choice
to the existing hosted checkout. The browser enters details and pays using the
existing Stripe Payment Element/Express Checkout flow. These are **real charges
if the customer chooses to pay**, with no medication fulfillment. Neither API
call authorizes or captures a payment. The demo receipt stays on the existing
checkout; automatic return URLs, signed payment status/webhooks, arbitrary
frontend origins, additional sites and developer access management are future
production API work. The earlier local demo retains its simulated completion
and return flow; that does not describe this public mode.

The catalog is read through the existing public plan API, cached for 15 seconds,
and fails closed if billing mappings cannot be verified. Pricing, contact
validation, quotes and payments remain authoritative on the existing checkout.
API callers cannot send amounts, campaigns, gateways, arbitrary destinations or
return URLs. Handoff links are independent, bounded to 1,000 concurrent links,
expire after 15 minutes, and disappear if the demo service restarts. Browser
payment isolation and durable attempt protection remain with the live app.

`demo.publish` creates a separate public parent and sixteen new private child
links from the already approved payment-test checkout. Original private links
and all existing records are retained. It makes no Sticky writes, creates no
owner/session/review approval, validates upstream availability, refuses changed
or partial existing publications, and records the publication. The operator
saved an on-volume backup before applying the owner's explicit public-demo
request. This utility must not publish unrelated private catalogs by default.

Redeploy only the separate demo service from `tools/stripe-v2-checkout`:

```sh
flyctl deploy --config fly-demo.toml --remote-only --ha=false --strategy immediate --yes
```

The Dockerfile-specific allowlist includes only demo runtime files, skeleton and
pinned dependencies. The live app's Docker allowlist still excludes this demo.
No volume or secrets are configured for the demo service. One worker/machine
and disabled automatic stopping keep its short-lived handoff links available.
Do not deploy `fly.toml` as part of updating this demo.

`test_site_api_public` verifies real handoff mapping, one-time prepaid versus
renewing prepaid, server-controlled prices/routes, expiry, scoped Swagger,
fail-closed upstream handling and atomic/idempotent publication. The explicit
`qa/site-api-public-smoke.cjs` checks the hosted frontend and fresh contact form
without entering contact/card details or invoking authorize/capture/resume.
