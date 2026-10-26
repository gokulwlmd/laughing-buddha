# Site-scoped API publication

## Shared application runtime

FortifyHP and later clients use the existing shared checkout application at
`https://wlmd-stripe-test-0f89b1bb.fly.dev`. Each client has its own approved
publication, Sticky campaign and patient portal; no separate Fly app or copied
database is needed. The existing root, checkout, owner and patient routes retain
their behavior. Continue running one payment worker with its existing encrypted
volume, disabled access logging and no proxy-header trust.

Set `SITE_API_MANIFEST=/data/site-api-publications.json` to enable the optional
`demo.runtime.install_site_api` integration. A missing file starts with no
published site APIs while health and existing routes remain available. After
approved bootstrap, `python -m fortifyhp_publish_api` verifies all forty client
plans, publishes their public copies and atomically appends FortifyHP to the
manifest. Other sites are preserved. The runtime reloads valid changes without
restarting the payment worker. Invalid replacements fail API requests closed
without replacing the last validated in-memory configuration or affecting the
existing checkout routes. The original separate payment-test API app is unchanged.

Catalog reads call the engine's admin service directly. Payment API requests
use a bounded loopback-only connection to the same process on port 8080, with
the configured external application Origin/Host and the existing per-attempt CSRF and
cookies. This avoids an external Fly round trip while retaining every payment
engine check. Excess session requests wait asynchronously so internal engine
calls retain worker capacity. No processor credentials are returned to Lovable.
Set `SITE_API_ALLOWED_ORIGINS` to the approved Lovable browser origins or the
owner-authorized `*` bearer-only policy; portal cookie authentication remains
same-origin and is not exposed through that CORS policy.

This supports adding many configured sites to one application. It is not a
certification of simultaneous traffic for 200 sites; capacity and production
concurrency require a separate measured test with the payment worker constraints.

## Existing separate API service compatibility

The existing `payment-test` API remains available with its original sixteen
choices and durable sessions. Additional sites are opt-in through a deployment
manifest. No request may submit campaign, gateway, Sticky product/offer/model,
price or arbitrary checkout URL.

Set `SITE_API_MANIFEST` to an absolute JSON path readable by service UID 10001.
Store it on the API service's existing `/data` volume, outside source credentials.
It contains configuration IDs only; no tokens, account secrets or patient data.
The standalone API service validates this file at startup and refuses invalid
or duplicate mappings. Its original no-manifest behavior serves `payment-test`;
the shared application's optional installer starts with no extra API site.

Schema (illustrative IDs below must be replaced with reviewed records):

```json
{
  "version": 1,
  "sites": [{
    "site_id": "fortifyhp",
    "site_name": "FortifyHP",
    "brand_id": "REVIEWED_BRAND_ID",
    "campaign_id": 195,
    "portal_site_id": "fortifyhp",
    "color": "#A2563F",
    "therapies": [{
      "therapy_id": "weight-loss",
      "name": "Weight Loss",
      "source_plan_id": "REVIEWED_SOURCE_PLAN_ID",
      "published_plan_id": "site-api-fortifyhp-weight-loss",
      "plans": [{
        "sku": "SEMA-1M",
        "selection": "1:2:3",
        "purchase_option_id": "REVIEWED_PURCHASE_OPTION_ID"
      }]
    }]
  }]
}
```

FortifyHP's four therapy IDs are `weight-loss`, `sermorelin`, `metformin` and
`pt-141`. Weight Loss includes both Semaglutide and Tirzepatide. Each SKU has
exactly one approved offer/product/model selection. Include only choices that
are available and verified for the client's real fulfillment configuration;
unsupported choices are not replaced with payment-test products. Do not commit
the illustrative mapping above as the actual deployment manifest.

After the source site has been prepared through the owner-approved workflow,
`demo.publish.publish_site(admin, site_configuration)` validates source and child
brand/campaign membership, exact selections, non-test status and current payable
terms, then creates separate public parent/child records in one transaction.
It performs no Sticky writes. It preserves source links and existing attempts,
refuses partial publications or changed records, and is idempotent for an
unchanged publication. Public/API publication is distinct from clinical launch
approval and does not establish fulfillment or medical integrations.

## Lovable contract

Use the existing API origin plus `/api/v1/sites/fortifyhp`:

- `GET /therapies` returns this site's available therapy IDs and names.
- `GET /plans?therapy_id=weight-loss` returns backend-owned prices, terms and
  plan IDs for that treatment page. Omit the filter for all approved plans.
- `POST /sessions` with `{ "plan_id": "sema-1m" }` returns a fresh checkout ID
  and a token scoped to that checkout and site.
- Follow the existing configuration → quote → payment → Stripe.js confirmation
  → complete sequence from `docs/SITE_PAYMENT_API.md`. Send the session token as
  Bearer authorization. Never send card details to this API.
- `POST /sessions/{session_id}/portal` is available only after confirmed capture
  and a working checkout-engine enrollment endpoint. The portal site and origin
  are verified before returning a link. Absence of that integration must remain
  an error, never a simulated enrollment or completed order.

Swagger: `/sites/fortifyhp/docs`; OpenAPI: `/sites/fortifyhp/openapi.json`.
These documents contain only FortifyHP paths. Client catalog responses use
`demo: false` and `payment_test_only: false`; each plan has `therapy_id` and
`therapy_name`. Catalog prices are display data: the quote and checkout engine
revalidate exact amounts, routing and current terms before payment.

The independent public catalogs refresh concurrently, remain fresh for 60
seconds and expire after at most 120 seconds. Failed or changed selections fail
closed. No payment authorization, capture, customer contact or Stripe client
secret is cached in these catalog reads.
