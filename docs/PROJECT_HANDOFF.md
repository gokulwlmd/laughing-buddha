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

## Latest: faster entry, remaining upstream payment latency

checkout-v9.js reveals editable contact inputs after a fresh attempt is checked,
while validated configuration loads. Submission/country/state remain gated;
held/resume/receipt/bank-return behavior and Stripe Payment Element are retained.
The static release preserved the worker and database. The separate demo now
uses single-flight background catalog refresh (60 seconds fresh, 120 seconds
maximum display age); financial quote/auth/capture checks are unchanged.

One hosted comparison measured Continue-to-typing at 6.878 seconds on v8 versus
2.517 seconds on v9. Configuration validation remained variable and reached
17.919 seconds in the new run. Overall card-entry/payment latency is NOT solved.
Sticky campaign retrieval is the dominant measured wait. See CHECKOUT_SPEED.md
and checkout-loading-deployment.json. Seven customer browser checks, eight
payment regressions and fifteen targeted demo backend cases passed without
submitting any real financial request. No new credential or account setup is
required. The existing permanent site-setup backend fix is still undeployed.

## Public API invitation gate correction

The earlier API used a public parent whose child checkouts required invitation
cookies. Following the handoff in one browser worked, but resolving it on a
frontend server and then opening its final URL in another browser returned 401
and the invitation gate. That screen belongs to this checkout service.

A separate publication, site-api-public-weight-loss, now has sixteen PUBLIC
child checkout copies. The API maps approved plans directly to these public
children. It retains the short-lived opaque handoff URL, with no invitation
secret in the response or destination. The existing private original and older
demo children, their revisions and all old payment attempts remain unchanged.
New public copies still enforce their parent membership, enabled state,
published payment choices, browser-owned attempt, CSRF and live payment checks.
No processor credentials or configuration were changed, and the live worker was
not restarted. A private on-volume backup and publication audit were saved.

Frontend integration: the server POSTs plan_id and returns checkout_url to its
browser. Navigate the browser to that URL. Do not embed/proxy the payment HTML
in another origin; it needs its own browser state and Stripe security policy.
Reuse the API to create a new handoff instead of storing its expiring URL.

## On-page checkout APIs (no frontend implementation)

The owner clarified that they need APIs for their own frontends, not another
frontend implementation. New site-scoped session APIs are implemented on the
API service: create session, public configuration, exact quote, prepare Stripe
Payment Element, resume, read status and complete the Sticky order. The old
redirect endpoint remains for compatibility and is deprecated in Swagger. No
frontend source files were changed for this release.

Read SITE_PAYMENT_API.md for the integration and response contract. Session
creation returns session_id/session_token, not a checkout URL. All further
requests require that checkout's bearer token. Amount, campaign, gateway,
selection and intent ownership remain server-controlled. Account credentials
stay on the original payment engine; only the customer's own Stripe setup is
returned. Tokens are hashed and no customer contact or Stripe client secret is
persisted in the API database. New APIs use the existing engine's authoritative
quotes, Sticky-created Stripe v2 intents, capture and order read-back.

The API app has a separate private 1 GB volume, site_api_sessions in iad, with
0600 session storage. Its machine changed to 8d96521b7d9768 to attach that new
volume. The live payment app/machine/volume and open forms were not restarted
or replaced. Inflight financial operations become held on an API restart, and
there are no blind payment retries. A lost authorization reply can resume only
the same existing intent; uncertain captures require confirmed status/read-back.

The attempted direct private route could not connect because the existing live
worker listens on IPv4; no live listener, HTTPS setting or network address was
changed. The API uses verified HTTPS to the existing checkout. Consequently
Sticky sees the API service's IP; trusted end-customer IP forwarding needs a
later native payment-engine change. This limitation is documented, not silently
worked around. The owner explicitly authorized any frontend origin: the API
uses SITE_API_ALLOWED_ORIGINS="*", requires each session bearer token and
disables cross-origin cookie credentials. No domain registration or new account
credentials are required. Payment latency remains unresolved.

Validation: the full backend suite passed 233 cases, and the final 32 focused
session/demo cases passed. Live verification is restricted to session creation,
configuration, status and a synthetic read-only quote; no authorization, card
confirmation, capture or order creation is part of that smoke check. See
scripts/check_site_payment_api.py and site-payment-api-deployment.json for the
final hosted evidence and image. The earlier permanent site-setup backend fix
remains undeployed on the payment worker.

## Site API performance update (23 October 2026)

The separate API app now warms its plan catalog, shares sanitized display
configuration for 60 seconds with fresh per-session access checks, reuses
cookie-free HTTPS connections and overlaps independent payment-preparation
reads. Financial validation and no-retry behavior remain unchanged. No frontend
integration change is needed; all 255 backend tests passed. Hosted plan loading
measured 0.312–0.335 s versus 6.843 s before; cached configuration measured
0.312–0.321 s versus 3.851 s. Fresh quotes still varied from 3.205 to 7.643 s;
end-to-end live payment improvement is not established. See SITE_API_SPEED.md
and tools/stripe-v2-checkout/site-api-speed-deployment.json. The API volume and
existing sessions survived; the original payment worker was not restarted.

## Hosted checkout reference redesign (23 October 2026)

The owner requested the VigMD checkout's visual layout for the hosted customer
checkout. The plan picker and details page now share a white canvas, compact
Red Hat Display type, clear choices and a pale order summary. Plan selection
starts with the requested/first available medication, lists durations longest
first and requires explicit duration/payment choices. Site accent colors,
upfront prices, shipment schedules, renewal terms and the existing Stripe v2
checkout-v9.js behavior are retained. Font assets and OFL are self-hosted.

Read CHECKOUT_REFERENCE_DESIGN.md before editing these pages. The versioned
static overlay is designed to preserve the running payment worker and database.
Use tools/stripe-v2-checkout/checkout-reference-deployment.json for actual live
publication and final test evidence. Hosted visual checks must not submit a
payment; local financial regression tests use the fake backend. No customer
screenshots or private checkout URLs are committed.

## Patient portal direction and isolated demo

The owner confirmed separate patient portals/records per site. The medical team
will fetch information from Sticky; intake and doctor-messaging APIs will be
provided later. Use backend-served therapy-specific sample questions and mock
messaging in the meantime. Do not introduce medical-network integration as a
prerequisite or infer clinical approval from payment/submission.

Read PATIENT_PORTAL_PLAN.md and tools/stripe-v2-checkout/patient_demo/README.md.
The new loopback demo has its own synthetic database, site/role-scoped demo
tokens, sample orders, saved intake drafts, immutable submissions, messages,
admin progress views and site Swagger. Its persona switch is not real patient
authentication. Partial leads are display fixtures. No production order import,
Sticky intake handoff, clinical decision, refill, store or funnel builder is
connected yet. Existing live checkout and API deployments remain unchanged.


## Latest: real Sticky member portal (23 October 2026)

The owner rejected synthetic portal orders. The implementation now lives in
`tools/stripe-v2-checkout/member_portal`, integrated into the real checkout app.
See its README for accounts, exact APIs, order import/renewal lineage, address
updates, subscription holds, per-SKU refill/early-request policies and the $1
checkout toggle. The old `patient_demo` module is an offline fixture only, apart
from its reusable mock questionnaire functions. Never serve it as real orders.

Existing Fly/Sticky authentication was verified without requesting credentials.
Read-only inspection found both the campaign 422 test site and markrx campaign
423. Historical captured receipts need current Sticky status reconciliation;
do not display every locally captured row as currently paid. No customer or
credential data belongs in this handoff.

Eight new actual Sticky Dry Run orders verified $1 full-term renewals and $0
included cycles. Their sanitized evidence is documented in the member README.
The gateway, catalog prices and existing live order records were preserved.
Medical-provider APIs and the tokenized saved-card replacement contract remain
external dependencies. Code readiness is not a claim of production deployment;
check the release record and process version before directing members to it.

Private real-data preview is running at `http://127.0.0.1:8873` through a Fly
proxy to an additional process on port 8081. Owner entry is
`/portal-admin/master-therapy-test-422`; member entry is
`/portal/master-therapy-test-422`. Use the existing owner login. The preview
reuses the existing server-side Sticky credentials and database in place; no
credentials or customer data were copied locally. No orders were fabricated.
The original checkout worker and all existing payment rows were unchanged.
The old synthetic localhost listener was stopped. See
`tools/stripe-v2-checkout/member-portal-preview.json` for verification.

This private process/tunnel is a development preview, not a durable public
deployment. The public checkout's new $1 toggle, receipt enrollment and the
external session API enrollment endpoint still need their normal releases.
At preflight, the existing worker had 15 awaiting-card and 2 authorization-
pending attempts; preserve them and honor the owner's prior request to leave
open payments untouched before restarting. The portal does not auto-import
account-wide orders: sync site-bound receipts or explicitly import exact
matching order IDs, then issue a member invitation.

Customer experience: send patients to `/portal/{site_id}`. The separate
`/portal-admin/{site_id}` area is labeled **Administration · staff only** and
contains order import and checkout testing. It is not the patient experience.
An existing owner cookie never signs someone into a patient account or grants
patient order access. Admin has an explicit link to open the customer portal.

## Latest: SKU intakes and quarterly care journey (23 October 2026)

Forty existing master SKUs now have explicit product intake assignments across
Semaglutide, Tirzepatide, Sermorelin, Metformin and PT-141. The master editor's
member-portal settings expose intake selection, purchase-intake requirement and
check-in day offsets. These settings do not change Sticky prices or billing.
Twelve-month terms use days 0/90/180/270; six-month terms use 0/90; one- and
three-month terms use the purchase intake. See DECISIONS.md and the member README.

Each verified paid term keeps its own questions and care schedule. Every step
has a separate autosaved draft and immutable submission. The matching current
check-in and earlier required steps must be completed before a refill review
request. Site, patient, task and term boundaries are enforced. Staff summaries
include the individual checkpoint labels. Medical provider APIs remain mocked.

The owner's existing markrx Sticky Dry Run order completed the full requested
test: four mock intakes and three simulated refill requests awaiting review.
Partial drafts resumed, submissions remained immutable, and retries did not
duplicate requests. Original Sticky order, subscription dates and billing state
were verified unchanged. No additional order, real charge or shipment occurred.
The care-only test clock is restricted to a verified non-shippable Dry Run order,
expires after 24 hours, and retains simulation provenance. It does not advance
Sticky. Never use simulated answers to qualify a live medication request.

Private preview updated; the original public checkout worker was preserved.
Verification: 352 backend tests, followed by all 17 final care/security cases;
8 portal browser scenarios, 23 provider cases, 6 master-policy cases, 2 template
cases and the repaired master-editor browser regression passed. Check
member-portal-preview.json for the exact running source bundle. Customer data,
test answers, passwords and private account links are excluded from this handoff.


## Verified private preview: native included claims (23 October 2026)

The latest request supersedes the earlier review-only refill interaction. The
customer sequence is now purchase → initial intake if missing → claim the next
included shipment → fresh check-in for the resulting native Sticky child order.
A 360-day / 12-month four-shipment term opens included claims at days 80/170/260;
a 180-day / six-month term opens one at day 80. These are ten-day windows before
the original 90-day shipment anchors. One- and three-month purchases have only
the initial shipment. The portal store links to the site's existing paid checkout
choices for new purchases, independently of whether an included claim is open.

Implementation lives in `member_portal/claims.py`, the provider adapter, and the
care/member API modules. `member_refill_claims` journals one native claim per paid
term/cycle; retries reconcile uncertain outcomes through reads. Claims verify
original paid terms, exact native cycle and ownership, zero additional
order/shipping/tax amounts, current configuration and scheduler conflicts. The following native
cycle remains anchored to the original paid term. The final paid renewal is not
an included claim and must never be forced by this endpoint.

Initial forms remain in `member_care_intakes`. New post-claim forms live in the
separate `member_claim_intakes` table, scoped to a claim and verified child order.
Existing review-only requests and old submissions are preserved and exposed as
history; they cannot silently satisfy the fresh post-claim form. Staff progress
summaries include checkpoint and claim/order references. Patient views use one
care journey per paid term while retaining the actual child orders in history.
The care clock now follows `term_order_id`, so native children share the parent's
simulated day and a later paid renewal remains separate.

The current native-order path is restricted to verified non-shippable,
non-taxable configurations without external fulfillment integrations and with
zero recurring shipping. Actual $0 Dry Run orders can exercise the order flow.
Physical medication release still needs a clinical/fulfillment hold contract;
medical intake and messaging APIs and secure saved-card replacement also remain
external work. The original public checkout worker and existing payment attempts
must stay untouched unless a separately authorized release changes that status.

The private Fly portal preview now runs this claim-first implementation. On the
existing authorized Markrx Dry Run term, all three actual included native Sticky
orders were created and read back at $0, using simulated claim days 80/170/260.
Each claim received its own submitted mock check-in; the original initial intake
and earlier review-only history were preserved. Duplicate claims returned the
same order. Following cycle anchors remained 180/270/360 days from purchase, and
the paid renewal boundary was rejected without a charge. No medication shipped.
The public checkout worker and every existing checkout row remained unchanged.

Real Sticky responses omit shipping IDs on some native children and include all
descendants in ancestor child lists. The provider verifies the original free
shipping profile and exact descendant lineage; unrelated references, changed
profiles, fees and ambiguous writes remain blocked.

Validation includes the full backend suite, targeted provider/claim regressions,
and nine browser scenarios, including a full three-claim journey and delayed
page loading. Exact counts and bundle identity are in `member-portal-preview.json`.
Markrx's four existing checkout plans remain private, so they are excluded from
the paid portal store. Publishing those plans or adding a scoped patient checkout
handoff is still needed for Markrx repurchases. Card replacement, clinical APIs,
and physical fulfillment hold/release remain the provider dependencies above.
No customer details, passwords, private invitation links, tokens or questionnaire
answers are recorded here.

## Patient portal design pass (23 October 2026)

Patient screens now use a calmer card layout, readable 17–18px text, larger
controls, stronger contrast and responsive order timelines. Technical provider
and testing notices remain in staff controls rather than patient intake, order
or care screens. Submission confirms that answers are saved; it does not claim
that a clinician has received or approved them.

The timeline shows order received, health intake (or the exact refill check-in),
medical review, prescription and shipping from recorded evidence. Unknown or
blocked states stay pending or need attention. Monthly plans do not promise
included prepaid shipments. Patient plan labels avoid raw SKU identifiers.
Address dialogs now contain keyboard focus and restore the opening control.
Light brand colors receive an accessible foreground/button variant without
changing saved branding.

All 12 member browser scenarios passed across the full and affected follow-up
runs. Desktop, tablet and mobile screenshots were reviewed; the release record
identifies the private preview bundle. This design pass changes no provider,
billing, clinical, fulfillment or authentication contract. The dependencies
recorded above still apply.

## Delivery updates, refills hub and doctor-chat drafts (23 October 2026)

The patient portal now has a dedicated refill view, notification inbox with an
unread indicator, shipment details, and a doctor-chat composer. The refill view
groups by original paid term so separate treatment purchases remain independent
and native child orders do not inflate remaining entitlements. Existing claim
confirmation, per-order check-ins and provider protections remain in place.

Authorized order responses now include normalized Sticky tracking numbers and
shipping dates. The UI displays shipment details only for recorded shipped or
delivered orders; it invents no carrier, arrival estimate or tracking URL.
`member_portal/notifications.py` derives patient updates from authorized local
snapshots without extra Sticky reads. Read receipts are durable and scoped to
site and patient. Alerts open the relevant order, form or treatment card; they
never place orders by themselves.

The doctor-chat box supports private server-backed message drafts with revision
checks. Drafts are explicitly saved, can be reopened, and remain drafts until a
real messaging adapter is connected. No clinician reply or delivery is faked.
The new `member_message_drafts` and `member_notification_reads` tables are
additive migrations. Medical providers, notification delivery by email/SMS and
scheduled order reconciliation remain separate integrations. Source and API
contracts are documented in the member portal README; preview identity and
verification counts are in `member-portal-preview.json`.


## Latest: action-first refresh of the existing member portal (23 October 2026)

The standalone option-1 prototype was rejected as too limited. The real member
frontend now uses its neutral action-first style while retaining all six nav
sections and existing handlers/APIs. Home shows the next care action, verified
plan facts, distinct purchased treatment terms, latest order progress and
shortcuts. Full order history, subscription/address actions, intake/check-ins,
refills, notifications, drafts and paid choices remain in their existing views.

All 17 browser scenarios passed across the main and focused final runs, including
new same-medication purchase grouping and retained-filter coverage. The private
preview received only verified JS/CSS replacements with backups; both worker
processes stayed running and healthy. Public checkout/database untouched.
No real provider transaction was performed for this design change. User chose
automated checks rather than signing into the real-data portal for inspection.
Read PORTAL_DESIGN_REFRESH.md and member-portal-preview.json for exact scope.


## Sticky-owned member passwords (24 October 2026)

The owner selected Sticky as the sole live membership/password provider, with
password setup immediately after a verified purchase and no membership email
request. See [the contract, migration and boundaries](STICKY_MEMBER_PASSWORDS.md).
The shared post-checkout component carries the form across sites. Existing
Sticky passwords are never overwritten by a new receipt. Site-scoped patient
records, order grants and clinical drafts stay in this application.


## 24 October 2026 — intake reuse and earlier included refills

The owner approved reusing stable answers and verified identity facts, with
explicit confirmation for changing health information. The included-refill
window opens 20 days before supply ends (70/160/250 for 90-day supplies in a
12-month plan); no additional free cycles are created. Unavailable refills must
stay visible, grayed out with dates and full instructions. Every order now
links to its refill options; paid plan choices remain separate checkout actions.

See [the implementation and provider contract](INTAKE_REUSE_AND_REFILL_WINDOWS.md).
Existing site/patient/order grants protect answer reuse. Submitted snapshots
remain immutable and guest receipts do not expose other-order health history.
The real ID/SSN verification APIs are still needed; only the trusted backend
adapter hook is implemented. No clinical review or identity verification is
fabricated.

This release is live on the shared Fly app. Hosted code hashes and policy
migration were verified; 473 backend tests and 10 targeted browser scenarios
passed. Existing orders, patients, app, machine and volume were preserved.


### Refill screen clarity — 24 October 2026

The owner approved separating monthly paid renewals from prepaid included
refills. Single-shipment plans now state that included refills are not part of
the plan, without a misleading free-claim button. Prepaid plans retain visible,
disabled claims, opening dates and instructions. Nonrenewing prepaid cycles do
not imply a future paid renewal. Medication titles remove redundant duration
and subscription suffixes.

Manage subscription goes directly to existing controls. Get next supply early
uses explicitly one-time, same-site/product plans, explains the unchanged
subscription schedule and sends the patient to checkout to review and pay.
It does not force-bill, reschedule a renewal, cancel, or create an extra recurring
subscription. The store API now includes SKU and explicit recurring metadata;
subscription responses include billing interval and prepaid renewal metadata.
Renewal dates come from Sticky. Renewal amount is unavailable in the current
adapter, and the UI says so rather than guessing from discounted initial totals.

Validation: 67 affected backend tests; 25 unique portal browser scenarios
passed across the full run and targeted reruns. The full run had 23 passes and
one outdated monthly fixture failure, corrected and rerun successfully; the
final four-case check covers monthly, paused, six-month nonrenewing prepaid,
and twelve-month upcoming refills. Mobile and desktop screenshots inspected.
No live payment, refill, subscription or identity writes were performed.

Live release verified: health 200, unauthenticated portal 401, hosted JavaScript,
CSS and backend hashes match. Existing checkout and patient counts are unchanged.
Immutable image and validation details are in `tools/stripe-v2-checkout/deployment.json`.


### Native early renewal supersedes the separate-purchase shortcut

24 October 2026: the owner asked to implement the intended subscription behavior.
For active standard monthly/90-day subscriptions, Request refill sooner now
quotes Sticky's recurring total and explicitly confirms the charge plus next
payment date, then advances that same subscription with a native child order.
The previous one-time-purchase shortcut is removed from subscription cards.
The old statement that the recurring price is unavailable is superseded by the
verified recurring_total/calculate integration. Included prepaid cycles remain
on their own $0-claim path. See [Native early renewals](NATIVE_EARLY_RENEWALS.md)
for API contracts, policy rollout, durable uncertainty handling and limitations.
No live payment or renewal was performed during development.

Release verified 24 October 2026 on the existing shared Fly app: image
`sha256:c2711bff95fa3ebbe7462ae72f4dadcfd27f9a1c1c1feba835ca5f4e4978bbd9`.
118 member backend tests, 48 targeted tests (overlapping renewal coverage), and
26 portal browser scenarios passed. Hosted source hashes match; health returned
200 and unauthenticated member data returned 401. Saved checkout/patient counts
were unchanged. Ten existing FortifyHP 1/3-month SKU policies were enabled.
Read-only live recurring pricing included the continuing discount; no live
charge, subscription advance or included-refill claim was submitted as QA.

## WLMD identity/intake integration — contract pending

The owner selected WLMD for identity checks, intake, order stages and later
clinical services. Site setup now accepts a separate `wlmd_site_id`; mapping
preservation and accidental reassignment protection are implemented locally.
See [WLMD integration](WLMD_INTEGRATION.md) for the provided endpoint and exact
missing contract details. No WLMD credentials were configured in the live app.
FortifyHP's WLMD ID, base URL/authentication, sanitized result examples, `user`
semantics and check/image flow remain requested. Identity gating is not activated
and no live identity request or patient-data transfer was performed. Do not
confuse this foundation with the deployed native-refill release above.

WLMD configuration update, 24 October 2026: owner confirmed live origin
`https://api.whitelabelmd.com` (do not use stage-api) and FortifyHP WLMD ID `288`.
The existing FortifyHP site record now contains that mapping. The complete
`authtoken` header value is stored as encrypted Fly secret `WLMD_AUTHTOKEN`,
with origin in `WLMD_API_URL`; no credential is stored in this repository.
Site setup UI/model deployed in image
`sha256:d0c61ff881e0faf50c3219ca411f953dc571ef7d71a3abcc70f1720dddc77175`.
31 site/Fortify backend tests and one site browser scenario passed; deployed
source hashes match and saved checkout/patient counts are unchanged.
No identity request or patient-data transfer was performed. The Postman route
`/v1/site/{site}/order/{order}/identity_ssncheck` differs from the supplied PHP
route `/v1/site/{site}/identity-check/{order}`. Current route/body and response
semantics still require confirmation. Credentials are configured, not yet
authenticated against the identity endpoint. Shared intake remains unchanged.

WLMD authorized test update: the supplied identity routes did not produce a
verification result on the configured live origin. One returned non-JSON; the
PHP-shaped route returned an error 404 from RoutingMiddleware.php. No patient
was marked verified. Await the full resolved Postman api_url/base path before
another identity request. See WLMD_INTEGRATION.md; test personal data is omitted.

WLMD correction: live hostname is confirmed. The Postman-shaped POST SSN
route returns a PHP TypeError (HTTP 200, not JSON), rather than a verification
result. OPTIONS independently raises a routing error and is not evidence that
the POST route is missing. Resolve the handler/body contract (`ssn` versus
`last4`/`user`) with the WLMD developer; do not keep asking for the hostname.
No verified fact was saved. Sanitized evidence is in WLMD_INTEGRATION.md.

WLMD blocker resolved for SSN: owner clarified `last4` (not `ssn`) and that
`user` identifies our system. Authorized live POST to the Postman-shaped
identity_ssncheck route with system identifier `laughing-buddha` returned JSON
`status: "success"` in about 6 seconds. Credential authentication and this SSN
contract are now verified. Use the explicit JSON success string, never HTTP 200
alone. No local verified fact was created by the standalone test. Next work is
the shared server adapter, site/patient status persistence and intake gate/UI;
crosscheck/ID-image and failure/expiry semantics remain separate unconfirmed
contracts. Do not repeat the earlier malformed requests. Sanitized details are
in WLMD_INTEGRATION.md; no request personal data or raw message was retained.
