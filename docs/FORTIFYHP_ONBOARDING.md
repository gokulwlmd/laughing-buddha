# FortifyHP client setup

Updated: 23 October 2026. Status: shared backend and Lovable storefront published.

## Current release handoff

- Shared backend commit `268b30befb6ba04edd8f41374895669456e37a8f`, branch
  `codex/fortifyhp-onboarding`; PR https://github.com/gokulwlmd/laughing-buddha/pull/3.
- Published immutable image:
  `registry.fly.io/wlmd-stripe-test-0f89b1bb@sha256:f39916d414757e5d64980066326bdbb3b972e5e5586998066c9beda3801b2524`.
- User approved the live restart: “Publish now; preserve unfinished attempts.”
  The existing machine and database volume were retained. Sixteen awaiting-card
  attempts, two pending authorizations and one captured record were preserved.
  No payments were retried, charged, canceled or deleted.
- FortifyHP is registered in the shared Sites database, campaign 195 / gateway
  269. Forty products, forty offers, sixteen duration options and four therapy
  checkouts were prepared. All forty authoritative full-term quotes matched.
  Original campaign offers 423 and 481 and all 528 preexisting configuration
  rows were preserved. No patient records were copied or customer orders placed.
- Backend checks: 434 tests passed. Portal browser checks: 19 passed.
  Lovable integration checks before the product-page revision: 23 tests and
  type checks passed.
- Published storefront: https://fortifyhp-care.lovable.app/available-products.
- Patient portal: https://wlmd-stripe-test-0f89b1bb.fly.dev/portal/fortifyhp.
- API base: https://wlmd-stripe-test-0f89b1bb.fly.dev/api/v1/sites/fortifyhp.
- API docs: https://wlmd-stripe-test-0f89b1bb.fly.dev/sites/fortifyhp/docs.
- Public health, catalog (40 plans), portal, portal configuration and OpenAPI
  endpoints returned HTTP 200 after deployment. Warm catalog reads took
  0.60–0.92 seconds; this is not a measurement of payment processing latency.
- On-volume backup: `/data/fortify-before-20261023.sqlite3`; do not export it.
  Setup journal: `/data/fortifyhp-production-catalog-195-v1.json`.
  Shared publication manifest: `/data/site-api-publications.json`.
  Do not repeat catalog creation.
- Intake/doctor service adapters and secure card replacement provider contract
  remain separate pending integrations. A published UI does not establish
  completed clinical review, message delivery or a successful real charge.
- Unrelated untracked `prototypes/` must be preserved.

## Product-page follow-up

The user requested a product catalog linking to the existing product pages,
with plan selection and checkout on those pages. Five medications belong to
four therapies: Semaglutide and Tirzepatide share Weight Loss; Sermorelin,
Metformin and PT-141 are separate therapies. Reuse existing product content
and imagery. Preserve backend pricing and session/payment recovery.

The user explicitly confirmed this work is for the new
`fortifyhp-care.lovable.app` site. Do not modify `fortifyhp.com`, its DNS,
legacy checkout or existing member portal as part of this request.

The product-page implementation is committed in Lovable at
`caad58eae3115c064ce7658aa0314cd034abc4c4`. It lists five product cards with
live full-term upfront prices, reuses existing men/women treatment routes,
and mounts the shared checkout inline after Continue. Formula query values
are matched against available backend medications. `/plan-checkout` remains
supported. Forty focused tests and automated type/build checks passed;
mocked browser checks covered desktop/mobile and pending-payment recovery.

Saved checkouts no longer replace product browsing automatically. Explicit
Resume previous checkout is available independently of the catalog feed;
automatic restoration is limited to Stripe return parameters. Back to plan
choices does not delete the stored session. Existing authoritative session
checks continue to guard pending/uncertain payments.

## Earlier decisions and investigation (historical)

The sections below record the original investigation and planning. Statements
about unpublished/local-only work are historical and superseded by the current
release handoff above.

## Confirmed direction

- Client: FortifyHP.
- Lovable project: `96958a3b-eaee-48b8-a1e7-6d6853a7a467`.
  Editor: <https://lovable.dev/projects/96958a3b-eaee-48b8-a1e7-6d6853a7a467>.
- User selected existing Sticky campaign 195 and requested Stripe Connect v2.
  A fresh read at 15:03:23 UTC / 20:33:23 IST confirmed the user configured
  Fortify Stripe V2 profile 269 for this campaign (see below).
- Use the four existing master therapy categories: Weight Loss (Semaglutide
  and Tirzepatide), Sermorelin, Metformin and PT-141 as the working scope.
- Add an Available products section to existing treatment pages and connect
  the on-page checkout session APIs. Keep processor credentials on the backend.
- Match the existing FortifyHP website styling in the real patient portal,
  retaining order, subscription, intake, refill and account functionality.
- User chose a new portal link on our platform. Create a distinct FortifyHP
  site entry; never reuse another brand's patient URL. A custom portal domain
  is not needed to begin. Existing-customer import scope remains undecided.
- The user explicitly chose **one shared application for all client sites**,
  including a future catalog of 200 sites. Reuse the existing Fly application
  and its backend credentials. Isolate branding, campaign mappings, pricing,
  account ownership, records and API publications by site; do not create a
  separate application or copy credentials for each client. This is an
  architecture decision, not evidence of load-tested capacity for 200 sites.
- Planned portal: `https://wlmd-stripe-test-0f89b1bb.fly.dev/portal/fortifyhp`.
  Planned API base: `https://wlmd-stripe-test-0f89b1bb.fly.dev/api/v1/sites/fortifyhp`.
- The user confirmed that an external system collects and fulfills Sticky
  orders. No additional pharmacy integration is required in this application.
  Intake and messaging adapters remain separate pending integrations; saving
  answers does not establish clinical review or approval.
- The user authorized website prices or editable placeholder prices for setup.
  Prices below are proposed defaults, not verified live selling prices.
- Carry forward separate patient accounts and records per site. Proposed terms
  preserve the agreed full upfront payment, non-renewing one-time choices and
  SUB renewal at 30/90/180/360 days. Six-month delivery terms have two shipments;
  twelve-month terms have four, 90 days apart. Clinical and fulfillment decisions
  are not implied by these billing terms.

## Lovable evidence

Read using the connected account at commit
`172e30434dffb2efb8d5b209e01be13f1b377f4a`. The project metadata name is ObvioRx,
but its source and connector screenshot use FortifyHP branding. The remix is
unpublished. Subsequent implementation added the Available products page,
the four treatment-page integrations and an on-page Stripe Payment Element
flow. The latest integration changes are still being validated; publishing
the website is separate from editing its source.

All four treatment routes already exist for both `/men/products/` and
`/women/products/`: `weight-loss`, `sermorelin`, `metformin`, `pt-141`.
They share `src/components/product/StandardProductPage.tsx`. Its current cart
and pharmacy-price feed are separate from the new site-scoped checkout APIs.
Website product IDs must not be treated as Sticky product IDs without mapping.

The source contains these full-term fallback amounts in USD; men's and women's
versions agree. `useLivePrices` can override them through the existing pharmacy
feed, so these are not a capture of the current rendered live prices.

| Medication | 1 month | 3 months | 6 months | 12 months |
| --- | ---: | ---: | ---: | ---: |
| Semaglutide | 199.00 | 537.30 | 1,014.90 | 1,428.00 |
| Tirzepatide | 299.00 | 807.30 | 1,524.90 | 2,268.00 |
| Sermorelin | 189.00 | 510.30 | 963.90 | 1,814.40 |
| Metformin | 69.00 | 75.00 | 150.00 | 300.00 |
| PT-141 | 199.00 | 537.30 | 1,014.90 | 1,910.40 |

Design source: warm ivory `#F4F1EC`, porcelain `#FBF8F4`, onyx `#141312`,
terracotta `#A2563F` and antique gold `#B08A4E`. Existing typography uses Code
Pro with a restrained italic accent. Reuse the source assets and styles;
retain the portal's readable patient controls rather than copying small
marketing labels into forms.

The source Sign In link points to `https://member.fortifyhp.com/`. The user chose
our new portal link instead. Update the selected Lovable project's Sign In
destination once the FortifyHP entry is published; do not replace the existing
domain's DNS or migrate accounts without a separate migration decision.
The source contact page supplies `support@fortifyhp.com` and existing policy
routes; verify intended use rather than inventing client contact details.

Browser preview redirected to Lovable sign-in. The connector supplied a current
project screenshot and source access, but interactive visual QA is still pending.

## Campaign 195 read-only evidence

- Active campaign name: Fortifyhp; currency USD; country US.
- Initial inspection found profile 151 (NMI), with no Stripe Link route.
  This is superseded by the 23 October 2026 15:03:23 UTC recheck: both primary
  gateway and Stripe Link now map to profile 269, Fortify Stripe V2, provider
  250 (Stripe Connect v2), USD, live publishable-key mode. Capture-on-shipment
  and delayed capture are disabled, matching our immediate-capture integration.
  The gateway mismatch is resolved; this was a read-only configuration check,
  not a successful payment-processing test.
- Shipping profile 2: Free Shipping.
- Reported fulfillment, tax, email and membership provider IDs are all zero.
  The user subsequently confirmed an external system consumes the Sticky orders.
- Offer 423 (Fortifyhp) has 361 product memberships, standard recurring models
  3/4/5/6 at 30/90/180/360 days, no one-time model, and is not prepaid.
- Offer 481 (FortifyHp labs) has 126 product memberships and one-time model 2.
- Inspection of 79 treatment-name candidates found 22 exact master-SKU records
  representing 18 distinct SKUs. This is not an exhaustive audit of all 487
  product memberships. No SUB-suffixed SKUs appeared in those candidates.
- SEMA, TIRZ, METFORM and PT141 have exact 1/3/6/12-month codes. Sermorelin's
  shorter candidates use SERM-30-1B / SERM-30-3B rather than SERM-1M / SERM-3M.
- Duplicate SEMA-1M/6M/12M and TIRZ-1M records have different prices. An exact
  SKU alone is insufficient to identify a payable product/offer/model.
- The inspected exact matches are shippable and non-taxable. Current native
  prepaid checkout deliberately blocks shippable prepaid products pending
  verification of a fulfillment release workflow. The payment-test fixtures
  do not establish production shipping support.
- Initial profile discovery found only profiles belonging to other brands.
  The user subsequently configured the dedicated FortifyHP profile 269. No
  other brand's profile was selected, copied or attached by the assistant.

No campaign settings, products, offers, prices, orders or gateway routes were
modified. No payment authorization or capture was attempted.

## Remaining decisions and implementation

Campaign 195's dedicated Stripe v2 configuration is verified. Await
existing-customer import scope and intake/messaging API readiness. External
fulfillment and the shared-platform portal-link decisions are settled.
Do not request existing account secrets.

1. Prepare an explicit four-therapy product/offer/model mapping and review
   draft prices/terms. Preserve existing campaign catalog and subscriptions.
2. Extend the current payment-test-only API routing and Swagger to a separately
   scoped FortifyHP site. Do not map the new frontend to campaign 422 by default.
3. Wire Available products to backend-owned plan identifiers and prices. Reuse
   the session/configuration/quote/Stripe Payment Element/complete sequence;
   do not create an independent Stripe charge or accept frontend amounts.
4. Publish the real member portal and verified checkout-to-account handoff on
   its approved domain. Decide patient origin handling before embedding it in
   Lovable; the existing portal currently enforces its configured origin.
5. Complete account setup/recovery email, order reconciliation and the actual
   clinical handoff. Secure card replacement still needs a verified provider
   contract. Keep draft messaging and stored intake distinguishable from delivery
   to the medical team until the relevant connection exists.
6. Validate shippable upfront plans, included refill claims and medical release
   behavior before enabling those choices for real patients. No new clinical
   network is a prerequisite; use the team's confirmed Sticky workflow.
7. Review mobile/desktop checkout and portal in the actual Lovable project,
   verify per-site isolation and payment recovery, and prepare the client release.

All saved material here is sanitized configuration and project context. No
patient records, credentials, private checkout URLs, session tokens or gateway
secrets are included.

## Unused infrastructure

An empty app `fortifyhp-0f89b1bb` and encrypted 1 GB volume
`vol_40o36e11n6yookk4` were created before the shared-platform decision was
clarified. It has no machines, copied credentials, orders or patient records.
Automatic approval review rejected credential transfer to that new production
destination and later rejected irreversible app/volume deletion without explicit
approval. The resources are preserved and must not be used for FortifyHP's
deployment. Removing them requires explicit deletion authorization.
