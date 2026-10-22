# Laughing Buddha project handoff

Laughing Buddha contains WLMD Core, a FastAPI and SQLite checkout administration application in `tools/stripe-v2-checkout`. Resume here and in [the decision record](DECISIONS.md). This handoff carries the product decisions from the earlier “Set up laughing-buddha” conversation, retrieved on 22 October 2026, without copying credentials, private invitations, payment receipts or customer records.

## Repository and protected live service

Repository: `gokulwlmd/laughing-buddha`. The starting checkout was clean at `f109e5151b840687d9a0731d8611acf73048b979`. The Sites and Checkout Templates implementation was still unimplemented in that starting commit.

The existing Fly application is `wlmd-stripe-test-0f89b1bb`, with one worker on machine `84e117f290dd38` and volume `vol_40o3gdk37mo7zy24` mounted at `/data` in `iad`. Treat it as live: it contains owner configuration and payment records, and its Sticky routing can use a live processor. Preserve the app, volume, SQLite database, owner, reviews, links and historical attempts. Never copy this database into development or staging. Production deployment remains a separate operation governed by [FLY.md](../tools/stripe-v2-checkout/FLY.md), including inspection and reconciliation of current pending payments before any restart.

The previous cloud workspace failed to start. That failure did not replace the repository or Fly storage. This continuation uses a writable local checkout; it does not depend on recovering the old cloud machine.

## Product decisions

The everyday admin has two primary screens: **Sites** and **Checkout Templates**. Catalog, therapies, plans, campaign management, prices, billing, existing checkout links and history remain available in **Advanced settings**, including their established hash routes.

The template editor now combines therapy selection or creation, editable duration plans, matching catalog products, payment choices and a customer selection preview. It displays product names and default catalog prices. Incomplete templates can be saved and resumed as drafts; drafts are excluded from new sites and never replace an existing published template. A new therapy saved with a draft becomes available for catalog assignment. The editor owns copies of its plans, so it does not rewrite shared legacy plans.

A Checkout Template is a complete therapy checkout. It contains duration **Plans**, which are the existing `purchase_option` records. A plan contains alternative master SKUs representing treatments. The customer selects **one SKU**, then one of its enabled **Payment choices**. A checkout may display one plan or several. SKU product duration must match the plan exactly. Each duration card shows every treatment's configured price before treatment selection.

Adding a site is a two-step flow: branding, then included checkouts. New branding is the default; reusing an existing brand is optional. A reviewed payment setup can be remembered for future sites, each with independent campaign pricing. The first site requires choosing that payment setup (synthetic staging supplies its demo source). Adding a site includes all enabled templates automatically. The owner selects an existing brand or supplies a new brand design, then selects an accessible Sticky campaign or creates one from reviewed payment and shipping settings. One consolidated preview lists the brand, templates, required SKUs, prices, intervals and exact catalog operations. Only an explicit owner approval applies those operations. Read-back validates configuration before plan links become ready. A missing gateway, inaccessible campaign or unsupported choice must remain incomplete.

Site checkouts inherit brand logo, colors and support details. They initially use hosted URLs and private previews. The site dashboard separates Ready to preview, Published, Paused and Needs attention, with Preview, Copy private preview, Edit checkout and explicit Publish actions. Copy public link appears only after publication. Synthetic public checkouts remain labelled test mode with payments blocked. An owner can explicitly make a checkout public. A custom domain is only pending configuration until DNS and HTTPS have actually been verified.

Later template, plan or master changes show **Update available**. Applying them requires a new review. Preserve customized titles, enabled plans, payment choices, campaign prices, published URL paths, existing subscriptions and legacy brand assignments. Saving a master or template is not permission to modify a campaign automatically.

Do not invent missing treatment SKUs, prices or clinical rules. Billing intervals never establish medication supply, dose, clinical eligibility or refill approval. Existing trial, physical prepaid, shipping/tax, advanced-schedule and processor-verification restrictions still apply.

## Implementation map

| Area | Responsibility |
| --- | --- |
| `admin.py` | Owner authentication, CSRF, configuration, guarded review/apply and reconciliation |
| `sites.py` | Checkout templates, site setup, snapshots, customizations and current readiness |
| `master.py` | Master SKU catalog, independent campaign offers, provisioning and read-back |
| `plans.py` | Therapies, duration plans, parent checkouts and isolated private child links |
| `catalog.py` | Authoritative campaign/SKU, gateway, pricing and payment-choice resolution |
| `app.py` | Quotes and durable payment state machine; staging payment gate |
| `synthetic.py` | Persistent offline demo catalog with payment writes rejected |
| `web/sites-admin.js` | Primary Sites and Checkout Templates screens |

Published plan checkouts retain reviewed snapshots. A private child link is unique to each checkout, plan and SKU, preserving payment-choice access boundaries. Open payments block affected configuration edits. Pending or uncertain writes remain held for reconciliation and must not be automatically resubmitted.

## Resume and collaborate

Read the repository checkout and catalog skills under `.agents/skills`, then [local development](LOCAL_DEVELOPMENT.md), [collaboration and staging](COLLABORATION.md), [the therapy plan architecture](THERAPY_PLAN_CHECKOUTS.md), and the application README, ADMIN and FLY guides. Inspect the actual branch and working tree before changing code.

Check existing Fly authentication, GitHub connector permissions and local Git authentication before requesting credentials. Hosted Sticky secrets already exist on the live app; leave them there. Secrets, setup links, invitation URLs, real contact information and gateway profiles must not enter commits, reports or chat handoffs.

Run backend tests and browser scenarios with disposable state and fake services. Passing offline tests does not verify live processor payments or future rebills. No real charge, owner impersonation, clinical action or live catalog setup is part of routine QA.

## Latest: Master Therapy 1 skeleton

Weight Loss is now a built-in versioned skeleton in Checkout Templates, linked from Therapies. It includes the 16 exact SEMA/TIRZ SKUs and upfront/renewal/fulfillment rules in [MASTER_THERAPY_1.md](MASTER_THERAPY_1.md). The four-plan draft is saved only through the normal owner review flow; deployment itself does not modify stored owner/catalog/review/checkout records. No prices are invented. Activation remains blocked pending prices, exact schedules and verified renewing prepaid support. Existing site creation uses only completed published templates.

## Latest: three therapies and 32 priced master SKUs

The user authorized actual master database records with editable starter prices, adding Sermorelin and Metformin to Weight Loss. See [MASTER_THERAPY_CATALOG.md](MASTER_THERAPY_CATALOG.md) for all 32 SKU codes, price assumptions, term/renewal rules, missing delivery details and the atomic idempotent synthetic-only import. These priced master drafts use `planning_contract`; processor mappings remain empty and activation blocked pending verification. Default prices can be edited through the normal owner-reviewed master form. Existing brand prices, therapy records and saved drafts must not be overwritten.

## Latest: editable upfront shipments and PT-141

Master SKUs now expose Edit upfront plan: full-term price, shipment count, interval in days and timeline. Saving rebuilds `product_setup` from the contract; templates read current SKU settings. Six-month default: 2 shipments at days 0/90. Twelve-month default: 4 at days 0/90/180/270. SUB renewal is day-based: 30/90/180/360 days for 1/3/6/12-month plans. PT-141 adds eight exact PT141 SKUs as Master Therapy 4, bringing the catalog to 40 SKUs and sixteen plans. See [MASTER_THERAPY_CATALOG.md](MASTER_THERAPY_CATALOG.md). Use the explicit synthetic-only import with `--all`; its separate migration markers preserve existing prices and later schedule edits.


## Current direction: work on the existing live app

On 22 October 2026 the owner explicitly requested moving the tested implementation to the existing live Fly application and continuing there. This supersedes staging as the required shared product workspace. Stop separate Stripe dashboard exploration and do not make new staging authentication or processor setup a prerequisite for admin/catalog development. Keep local automated tests and GitHub pull requests; the synthetic staging workflow remains optional.

Live admin: https://wlmd-stripe-test-0f89b1bb.fly.dev/admin. The tested Sites, Checkout Templates and master plan editor have been deployed to the existing machine/volume. The original database was backed up on that volume and every existing table fingerprint matched immediately after deployment. No processor settings, charges or historical attempts were changed.

The explicit `promote_live(application)` catalog operation in `import_master_therapies.py` adds missing master drafts, plans and template drafts to this exact app only. It preserves every existing SKU and owner-created draft and makes no Sticky requests. Existing TIRZ-1M retains its older approved billing setup and is excluded from newly generated duration plans until its requested new terms receive a separate review. Do not describe draft masters as campaign-provisioned or payable. Existing links and campaign offers retain their configuration.

The latest renewal decision is **30/90/180/360 days** for 1/3/6/12-month SUB plans, full-term payment upfront. Earlier references to calendar-month renewal are superseded. Non-SUB charges once. Six/twelve-month prepaid shipment timelines remain days 0/90 and 0/90/180/270. Processor activation of these catalog drafts remains separate from saving and editing them.

Live promotion completed: 101 additive configuration rows, including 39 master drafts, 16 plans and 4 checkout-template drafts. All 40 requested SKU codes are present including the preserved earlier TIRZ-1M. Every pre-existing row matched the on-volume backup; repeat promotion made no changes. Validation: 176 backend tests and 24 affected browser scenarios. See `tools/stripe-v2-checkout/live-sites-deployment.json` for the immutable image and non-secret verification. New master activation remains pending; these are catalog drafts, not 40 newly payable campaign offers.


## Current: four therapy checkouts ready for owner live payment tests

The owner explicitly authorized campaign-422 setup and a separate eight-order Dry Run verification. Forty new products (55866–55905) and offers (715–754) are now attached to the existing connected campaign **422**, preserving original offers and gateway 254. All forty upfront quotes passed. Four private checkouts are available under **Sites → Master Therapy Payment Test → Preview** on the live app. Weight Loss has sixteen SKU entries; Sermorelin, Metformin and PT-141 eight each. The new offers are non-shippable payment-test records and display real-charge/no-medication notices. The owner submits any real payment; no live payment was submitted by the agent.

Native two/four-cycle prepaid renewals passed eight isolated Dry Run orders on campaign 428. API access to that new campaign was initially denied, then the owner enabled it. Owner/session/review/payment/receipt/successor rows and existing remote products/offers/routing remained unchanged. Only TIRZ-1M therapy/treatment/duration metadata and membership in the existing one-month plan were added; its legacy offers stay intact. See [the complete setup and limits](MASTER_THERAPY_LIVE_TESTS.md) and `master-therapy-payment-deployment.json`. Earlier notes that campaign setup/activation was pending are historical and superseded for these payment-test checkouts.

The deployed source passed 183 backend tests and 34 affected browser scenarios. No external setup is currently blocked for the owner to test these links. Actual live processing, future elapsed rebills and clinical fulfillment are not certified by the Dry Run results. Do not repeat proof orders or create a new gateway by default. Preserve the durable provisioning journal and the master-fingerprint-bound `test_catalog_activation` records during future work.


## Current: customer-friendly checkout design

The live customer plan selector and card checkout now use a cleaner branded form and order-summary layout inspired by the owner's reference. Internal SKU/offer/model/campaign labels are hidden, duplicate treatment entries are combined into one treatment with distinct payment choices, and exact upfront/renewal terms remain visible. The original four payment-test checkouts and all campaign/price data are unchanged. Read [the UI implementation and rollout](CUSTOMER_CHECKOUT_UX.md).

Active customer assets are `checkout-v2.*` and `plan-selector-v2.*`, loaded by `index.html`/`plans.html`; legacy app/plans assets are retained for already-open pages. Static files were published without restarting the live payment worker. An immutable image with the same UI is built for the next safe container deployment; its digest and the exact active asset hashes are in `customer-checkout-ui-deployment.json`. Do not blindly redeploy the preceding container image and restore the old UI. Before any process restart, perform the existing payment-state preflight. Verification: 183 backend tests and 74 unique browser scenarios, plus live asset/health/privacy checks. No payment or catalog mutation was made by this design release.


## Current: medication-first checkout and unresolved attempt diagnosis

The owner requested medication first, then its duration prices, then one-time/subscription. This is deployed as checkout-v3.* / plan-selector-v3.*; older assets remain for open pages. Selection clicks are local, the card library loads at review/payment, and unresolved attempts display status/support actions immediately without waiting for the remote catalog. Six targeted browser cases and eight payment regression cases passed against fake services. Live asset hashes and health were verified without restarting the worker or changing database rows.

One real SEMA-1M-SUB attempt is authorization_pending with no stored intent/order. Do not reset or retry it. The available app record/logs do not establish the original Sticky authorization result; an authoritative upstream lookup is still needed. Read docs/CUSTOMER_CHECKOUT_UX.md for diagnosis and release limits. Initial remote catalog loads and handoff validation still have network latency. The UX fix does not establish settlement, cancel an authorization or unblock the held attempt.


## Current: checkout performance work and payment-widget correction

Active customer assets are checkout-v7.js, checkout-v3.css and plan-selector-v3.*. The original Stripe Payment Element and Express Checkout interface is restored; confirmation uses Stripe confirmPayment on the intent created by Sticky authorize_payment, followed by Sticky capture/read-back. The classic Card Element experiment is superseded. It was deployed briefly as v5, not merely tested in isolation; v6 was built but never deployed. Retain earlier deployed scripts for already-open pages. The deferred-gateway capability remains in the backend for compatibility, but v7 does not use it; future Fly config disables it.

Browser-owned per-tab visits fix fresh shared URLs reusing a held test. Fresh navigation starts a new attempt; reload and bank return resume that tab's attempt. No prior attempt is reset. The checkout_visitors table stores a cookie hash. Scoped catalog resolution reduces unrelated reads, product/gateway reads run concurrently, plan pricing is prefetched within one request, and handoff avoids a duplicate lookup. No cross-request price cache is used. Quote/authorization/capture retain authoritative checks and legacy quote fingerprints.

Performance is NOT resolved or certified. An earlier catalog sample improved 5.883 to 2.435 seconds, but the latest live sample was 8.380 seconds for catalog and 6.304 seconds for a fresh review quote. Neither sample measures full card entry or completed payment. Do not present the earlier speed-release claim as completion. No new credentials or external account setup is known to be needed for this remaining work.

The owner approved prior backend restarts while preserving old unfinished tests. Those rows and the original receipt remain intact; old process-local secrets were lost across approved restarts. The SEMA-1M-SUB authorization_pending attempt remains unresolved and must not be reset/retried. The v7 correction publishes static files without restarting the worker or changing database records. Validation and limits are in CHECKOUT_SPEED.md and checkout-speed-deployment.json. No real payment was submitted by the agent.

## Current: US state dropdown

The owner requested all states in a dropdown and only state codes sent to Sticky. checkout-v8.js adds all 50 US states, DC, territories and military codes; labels are full names and values are two-letter codes. Other campaign countries retain a region text input. Existing pending rows remain held; fresh visits use the updated form. A targeted fake-service browser check verifies the selected California/New York codes in quotes and both Sticky billingState/shippingState fields. Three targeted cases passed including recurring consent and prepaid. This fixes a documented input mismatch observed in failed attempts, but does not prove that it was their only failure cause or reconcile them. No live authorization/capture was submitted.

## Site setup: harmless Sticky defaults and recovered approved setup

A held site setup on campaign 423 had created product 55906, then stopped before creating its offer. Its exact read-back mismatch was a non-shippable product's absent weight/unit becoming Sticky defaults 0/unit 1. SKU, category, price, tax, shipping and restrictions matched. The old checker deterministically failed at that first read-back, so no following write had run. The approved plan was recovered using that same product; all 40 products and 40 offers are now recorded, the existing campaign's offers were extended as approved, and all four therapy checkouts are ready/private. No payment was submitted. The recovery is logged in admin_recoveries, with a private on-volume backup; no owner account/session was fabricated.

The permanent fix introduces product_contract_matches without changing stored contracts/fingerprints. Only absent weights on non-shippable products can match the observed zero/default-unit response; explicit weights, real shipping, tax, SKU, category and restrictions remain strict. Admin plan execution is shared with the narrow operator recovery utility and journals the operation index/stage before each write. Uncertain operations remain held without retries. Finalization reuses fresh reads within the operation, after all remote writes finish.

Validation: 200 backend tests passed, including no-duplicate recovery and price/open-payment guards. Five affected browser cases passed; two site navigation assertions were updated for the already-established medication-first selector. Immutable image db82a299df069a23b2317cdb08a01ff1781ddfb4585d281d5915f7271cf7bf87 is built. Deployment is waiting for the owner's response about a newly opened $249 Semaglutide card form; do not restart and discard its in-memory client secret without reconciling it or obtaining that explicit approval. Current live worker remains on the prior image with v8 static assets. See SITE_SETUP_RECOVERY.md and site-setup-deployment.json.

## Two-call API demo (local only)

The owner requested a minimal developer integration with no Sticky or Stripe credentials. An isolated working demo is in tools/stripe-v2-checkout/demo: GET site plans, POST selected plan_id/registered return_url, then open the returned branded checkout_url. Two sample sites have independent branding/prices and separate Swagger/OpenAPI documents. The frontend/API use separate loopback ports 8872/8871. No live app imports, state, credentials, gateway requests, card input or real orders are involved. Finish demo returns to the sample frontend and never represents payment success.

Seven new backend tests and three browser scenarios passed; full backend discovery passed 207 tests. QA now discovers all test modules. Run instructions, scope, API sample and production gaps are in demo/README.md. The live Fly worker remains untouched under the owner's instruction to leave their open payment test alone. The earlier permanent site-default fix is still built but undeployed; this new demo does not change that deployment state.

## Public Site API demo connected to real checkout

The owner requested a public working URL and explicitly selected the existing
real Stripe v2 checkout. The separate demo is live at
https://wlmd-site-api-demo-0f89b1bb.fly.dev/ with site-specific Swagger at
https://wlmd-site-api-demo-0f89b1bb.fly.dev/sites/payment-test/docs.
It serves actual campaign-422 weight-loss plan prices and returns an opaque
handoff URL for a selected plan. The browser then uses the existing Stripe v2
checkout. Real charges occur only if the user completes payment; no medication
is shipped. No processor credentials were copied into the demo service or given
to frontend developers.

A separate public payment-test parent and sixteen new private child links were
published from existing approved choices. Every pre-existing configuration row
was verified unchanged, and an on-volume backup was saved. No Sticky objects,
routing, prices, owner sessions or historical payments were changed. The live
worker was not restarted; the previously pending permanent site setup image is
still undeployed. Public access applies only to this new demo publication.

The demo supports GET plans and POST plan_id to obtain checkout_url. Its receipt
stays on the existing hosted checkout; return URLs, authoritative server payment
status/webhooks and production developer/site access management are not built.
The API's short-lived handoff links are memory-only. See demo/README.md,
fly-demo.toml and site-api-demo-deployment.json. Existing local sample mode is
still available separately and remains non-payment.
