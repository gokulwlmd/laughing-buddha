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
