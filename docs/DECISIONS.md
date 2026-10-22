# Checkout administration decisions

These decisions define the authorized Sites and Checkout Templates implementation as of 22 October 2026. Preserve their behavior when extending the application.

## Reuse the existing payment and catalog architecture

Keep FastAPI, SQLite, master SKU provisioning, campaign-scoped catalog resolution and the owner review/apply flow. Templates and sites are additional `admin_config` record kinds, so the migration does not rewrite existing records. No existing brand, link or payment is automatically converted or reassigned.

## Use one set of customer terms

**Therapy → Checkout Template → Plans → one treatment SKU → Payment choice.** The existing `purchase_option` schema remains the duration-plan representation. A plan's SKU duration must match exactly. One-time, subscription and supported prepaid terms belong to the SKU's payment choices; they are not duration plans or bundles. Preserve per-treatment price visibility before selection.

## Provision only the template catalog

Site setup gathers the union of explicitly assigned master SKUs from all enabled templates. Reuse the master provisioner with that selected set, including its source, currency, shipping/tax, billing and reconciliation guards. Do not bulk-provision unrelated or excluded test SKUs. The owner sees the complete proposed catalog and plan configuration before applying.

New campaigns copy payment, country and shipping selections only; other integrations need explicit setup. Campaign access and Stripe Link routing must pass read-back. An unverified campaign remains incomplete. No retry follows an uncertain catalog write, even through a newly named site or the Advanced campaign tools.

## Keep site pricing scopes independent

A site keeps its brand and campaign once published. A brand may own multiple site campaigns. The same brand/campaign pair cannot be assigned to two site records, because the existing offer and price keys are scoped to that pair. Use a separate campaign for independent site prices. Existing legacy links in that campaign retain their mappings and are listed in affected-link reviews where applicable.

Site price edits use the existing Advanced replacement-offer workflow: original subscription products/offers remain unchanged. New site setup and template updates preserve existing campaign prices rather than resetting them to master defaults.

## Snapshot defaults and apply updates explicitly

Each site checkout records its template, plans and master metadata snapshot. Template source changes only mark an update; they do not republish. Site setup is the reviewed update action and retains saved overrides for title, plans, payment choices, visibility and enabled state. A customization uses the published snapshot until an update is reviewed. Removing a customized plan from a template requires resolving that customization explicitly.

Published `/plans/{id}` paths derive deterministically from the site and template. Repeating unchanged setup preserves private invitations as well as paths. Intentional checkout changes still rotate invitations under the existing revision policy. Brand design inheritance remains shared and explicitly reviewed.

## Publish after read-back and preserve incomplete work

After approved catalog writes, validate assignments, resolve the reviewed plans through managed offerings, and atomically publish each complete parent/child checkout. Save the site and recorded campaign even when a checkout is incomplete, so the next reviewed setup reuses existing objects. Partial or uncertain writes retain their object IDs in the review journal. Catalog read failures display incomplete state without removing the admin workspace.

Ready means current configuration is available on a private hosted link. Live means the owner made that checkout public and the application payment gate is enabled; neither label proves a successful processor payment. Synthetic staging always blocks payments. Custom domains remain pending until separately verified.

## Isolate development and staging

Production continues using its existing app and database. Development and staging use `SyntheticSticky`, which has no network client, persists only demo catalog state, and rejects authorization and order creation. The staging environment forcibly disables payment processing even if an authorization flag or real credentials are accidentally supplied. No owner account, session or approval is seeded.

GitHub runs tests on pull requests and relevant pushes. Fly staging deployment is manual, reruns tests, uses a staging-only config and app-scoped deploy token, and verifies the hosted synthetic/payment-block health flags. There is no automated production deploy.

## Guided admin setup (22 October 2026)

Use Checkout Template for a complete therapy experience, Plan for duration choices, and Payment choice for billing. The primary template editor combines plans, catalog product assignment and preview. Save drafts separately from the published template; publishing commits new therapy/owned plans/template in one SQLite transaction. Template-owned plan identifiers remain stable when plans are reordered. Shared legacy plans and existing published site snapshots remain intact.

Site setup defaults to new branding and a separate campaign created from an explicitly selected or previously reviewed payment source. Remember the source only when its review is approved. The initial source must be chosen by the owner; synthetic staging may select its known demo campaign. Keep the campaign mapping immutable on existing sites. Ready preview, public publication, paused and incomplete are distinct states. Never label a synthetic checkout as accepting live payments.

Catalog products and their billing rules remain managed under Advanced. The template editor selects existing matching products and displays their catalog prices; it does not invent medication SKUs or alter shared prices. Missing products are reported at the affected plan, with draft saving available.

## Master Therapy 1 skeleton (22 October 2026)

The Weight Loss skeleton defines separate SEMA/TIRZ SKUs for 1/3/6/12-month terms, with and without `-SUB`. All terms are paid in full upfront; `-SUB` renews the full payment after the same calendar-month duration. Six-month terms contain two shipments, twelve-month terms four. Further shipments within the term have no extra charge. Prices, exact shipment timing and short-term shipment counts remain unspecified. The versioned recipe is visible in the admin and can be saved as a draft; it must not activate unverified prepaid renewal or invent prices. See [the full contract](MASTER_THERAPY_1.md).

## Three priced master therapies (22 October 2026)

The owner authorized creating actual Weight Loss, Sermorelin and Metformin SKU records with editable standard starter pricing. The selected USD monthly references are SEMA 249, TIRZ 449, SERM 199 and METFORM 49; multiply by 1/3/6/12 for full-term upfront amounts, no discount. Separate SUB/non-SUB master records start at equal prices. This supersedes the earlier unset-price decision. Shipment counts for the two new therapies remain unspecified. Save the 32 masters as billing-contract drafts without inventing processor mappings or turning off activation guards. Existing brand prices and owner drafts are preserved. See [the catalog/import contract](MASTER_THERAPY_CATALOG.md).

## Editable upfront shipment setup and PT-141 (22 October 2026)

The owner specified the same prepaid delivery defaults for all master therapies: 6-month plans have two shipments every 90 days; 12-month plans four every 90 days, with the first shipment at purchase. Expose Pay upfront and allow per-SKU shipment count/interval edits. Rebuild the saved product setup from those values and prices; template summaries read saved per-SKU schedules. Keep full-term upfront charges and matching SUB calendar-month renewals independent of shipping. Existing remote offers and subscriptions still need a separate verified assignment.

Add Master Therapy 4, PT-141, with exact `PT141-{1,3,6,12}M` and `-SUB` codes from the screenshot. Use an editable $199 one-month starter reference multiplied by term length. The catalog now contains 40 SKUs and sixteen duration plans. Preserve prices and owner schedule edits during the one-time synthetic shipment-default update.


## Live workspace and exact renewal days (22 October 2026)

The owner explicitly directed work onto the existing live app and asked to stop separate staging and Stripe exploration. The live app is now the shared product workspace; preserve its existing machine, volume, accounts, configuration, subscriptions and payment history. Continue local tests, branches and PRs. Staging remains optional and is not a delivery prerequisite.

SUB terms charge the entire term upfront and renew after **30, 90, 180 or 360 days**, respectively. This supersedes all earlier calendar-month renewal wording. Non-SUB terms charge once. Shipment schedules stay independent; six/twelve-month defaults remain two/four shipments every 90 days starting at purchase.

The owner-authorized live catalog promotion adds missing drafts atomically, preserves existing SKU definitions and all existing records, and never performs Sticky/payment writes. The older live TIRZ-1M definition remains untouched and excluded from new duration-plan selections pending a separate billing review. No existing campaign offers are reassigned automatically.


## Live payment-test activation (22 October 2026)

The owner explicitly authorized provisioning the four therapies into connected campaign 422 on the existing live app and will enter cards/submit real payments themselves. Use forty new, independently priced non-shippable/non-taxable test products/offers, preserving all existing remote catalog, gateway routing and customer payment records. Group them in a separate payment-test brand/site with private previews and explicit real-charge/no-medication notices. Clinical fulfillment remains separate.

The owner separately approved two synthetic products, two prepaid offers, a new Dry Run campaign and eight synthetic orders/forced cycles. Both native two/four-cycle renewal chains passed, with full upfront and renewal charges and $0 intermediate product charges. Campaign 428 access was enabled by the owner. Native prepaid renewal is now supported for this verified simple test configuration; conversion, discounts, physical/taxable prepaid release and advanced combinations remain blocked.

Keep a server-owned activation record bound to each master fingerprint, so a planning save cannot grant processor readiness. Template/site setup may use a current verified non-fulfilling mapping; master edits invalidate it for future setup. Do not rewrite old subscriptions or automatically republish existing checkouts.

The explicitly authorized operator attachment adds only new offers, checking original remote terms/routing before and after; it preserves the older held authorization without retrying, cancelling or capturing it. Normal owner review locks remain unchanged. The operator journal and separate setup audit must retain confirmed IDs and stop on uncertain writes.


## Customer checkout presentation (22 October 2026)

Use a customer-facing plan → treatment → payment-preference flow with clear upfront totals, concise renewal/delivery terms and a visible order summary. Distinct one-time/SUB SKUs can share one treatment card, but the selected payment retains its exact original SKU/offer/model and private child-link boundary. Keep technical catalog identifiers out of rendered customer copy. Hide redundant single-choice controls while retaining their submitted values.

Use the reference's clear layout without inventing savings, included clinical services, outcomes or cancellation benefits. Preserve the explicit real-charge/no-medication notice for live payment-test checkouts. No change to prices, recurring consent, payment processing, clinical rules or access permissions follows from the design.

For this release, publish versioned static files and atomically update HTML without restarting the worker because a customer authorization is open. Retain legacy assets for already-open pages. Store the matching immutable image for the next safe container deployment, with ordinary preflight/reconciliation required before a restart.


## Medication before price; explicit payment preference

On 22 October 2026 the owner requested Medication → plan length/pricing → one-time or subscription, with immediate local selection changes. Only the selected medication's prices appear; changing medication clears duration/payment. Defer Stripe.js until review/payment. Preserve live server validation, full upfront totals, exact renewal intervals and explicit recurring consent. Do not clear an uncertain payment to improve checkout speed: display status/help immediately and require authoritative reconciliation before a new attempt. Use v3 assets while retaining v2 for open pages.


## Scoped catalog checks and independent shared-link visits

Resolve published choices against current campaign membership, fetch only attached products/offers and read independent product/gateway data concurrently. Keep authoritative checks before payment and legacy quote fingerprints. Use request-local prefetching only. Fresh navigation starts a browser-owned anonymous visit; reload/bank return resumes the tab's pinned attempt. Preserve all old pending rows and access/CSRF boundaries. Remove the duplicate catalog read from the plan handoff.

## Preserve the existing Stripe v2 checkout interface

On 22 October 2026 the owner objected to the classic card box introduced during performance work. Restore the original Payment Element/Express Checkout and confirmPayment flow on Sticky-created intents. Do not substitute payment widgets as a performance workaround. The gateway has remained Sticky Stripe Connect v2 throughout. The earlier Card Element rollout is superseded; v6 was never deployed. Fast deferred authorization is not active in v7. The variable upstream delay and full customer experience still need verification; do not claim that passing fake-service tests proves live speed or processing.

## US states are selected by name and sent by code

Use a state dropdown for US billing addresses. Show full state names, submit only the two-letter values, and preserve the same code for Sticky billingState and shippingState. Include all 50 states, DC, territories and military addresses. Preserve free-text regions for other supported countries. Do not change existing held attempts to adopt corrected input.

## Compare non-shippable weight defaults without weakening fulfillment checks

Sticky returns weight 0 and unit 1 when omitted on new non-shippable products. Treat only that observed default as equivalent to an absent weight/unit. Preserve stored contract fingerprints and require every other field to match. Retain strict shipping, tax, restrictions, explicit weights and prices. Before a write, journal its index/stage; never retry an uncertain operation. The legacy first-product failure may resume its previously approved plan only after read-only verification of the recorded ID, unchanged configuration and absence of campaign payments, with a private backup and audit record.

## Two calls for external frontend integrations

Expose site plans and create a hosted checkout link from a server-owned plan_id. Frontend developers do not manage customer/payment steps, set prices, or receive Sticky/Stripe credentials. The first deliverable is an isolated, non-payment local demo with two sample sites and per-site Swagger. It does not expose or publish live site catalogs. Production access rules, real hosted-checkout handoff and authoritative return status require separate implementation.

## Public developer demo uses existing Stripe v2 checkout

- The owner requested a public working demo and explicitly chose the existing
  real Stripe v2 checkout over simulated payments.
- Host the frontend/two-call API in a separate Fly app, without processor
  credentials or a copy of the live database. Read approved prices through a
  separate public payment-test plan publication on campaign 422.
- Preserve original private links and payment attempts. Publish new parent/child
  records only; make no remote product/offer/gateway changes and do not restart
  the existing payment worker.
- Public demo POST accepts only plan_id. Checkout details, quotes, cards and
  payment confirmation remain on the existing hosted checkout. Do not advertise
  a custom return URL or paid status API until authoritative integration exists.
- Local sample mode retains its simulated completion; public mode clearly
  states real charges/no medication fulfillment. No financial action is part
  of automated hosted verification.

## Load customer input independently of live configuration

Show the contact form after fresh-attempt status is confirmed; let people type
while read-only catalog validation runs. Gate plan/country/state/submission on
that validation and preserve entered text. Preload Stripe.js alongside it.
Retain the original intent-first Stripe v2 payment flow and all fresh financial
checks. Publish this UI through versioned static assets without a worker restart.

The demo's public plan display may use a validated snapshot for at most 120
seconds, refreshing after 60 seconds without blocking visitors. Single-flight
refresh avoids redundant full-catalog reads. This does not authorize stale
quotes/payments or relax private link, consent, state or price-drift checks.
Do not report the overall payment speed problem as resolved from an earlier
editable form or a cached catalog response.

## Public API destinations must open without invitation cookies

Public API checkout links must remain usable when a server resolves their
redirects before a clean customer browser opens the final URL. Use a dedicated
public parent with public child records, preserving prior private children and
open attempts. Do not expose private invitation tokens or globally disable
checkout access checks. Tests must cover cookie-free server resolution and
opening the resulting destination in separate browsers, alongside preserved
private access and disabled-parent rejection.

## API-only on-page checkout integration

The owner explicitly clarified that they need APIs rather than another frontend.
Add session/configuration/quote/payment/resume/status/completion APIs with
site-specific OpenAPI; retain the older redirect demo for compatibility. The
customer's frontend renders Stripe Payment Element using only that session's
public key/client secret. No account private keys or Sticky credentials go to
developers. Do not implement a new card widget or an independent Stripe charge.

Use durable, hashed bearer-token bindings to one approved plan and one existing
payment-engine visit. Preserve all financial checks and historical attempts.
Do not persist Stripe client secrets, accept client pricing/routing, retry an
uncertain financial operation or silently create a replacement payment. A
confirmed captured receipt may resolve a lost completion reply.

Run the API adapter in the separate API app, with its own volume. The payment
worker stays running. Use verified HTTPS because its current IPv4 listener
cannot be reached via the direct IPv6 private route. Document the API service
IP attribution. The owner explicitly answered “any” for frontend origins; allow
any origin with session bearer authentication and no cross-origin cookie
credentials. No frontend domain registration is required. Do not weaken live
HTTPS or restart the payment worker to hide the IP limitation. No frontend
changes are included in this API-only release.

## Site API latency (23 October 2026)

Keep public display data warm and share it briefly; do not cache financial
verification or reuse a Stripe key from an older route. Display configuration
may be shared for 60 seconds by link/selection only after each session passes
fresh upstream access checks. Quotes, intent preparation, resume and completion
retain their authoritative checks. Use bounded cookie-free HTTPS connections
and overlap independent read-only preparation checks. Never retry writes after
network uncertainty. Deploy these optimizations in the API app so the existing
payment worker can retain the open card forms and process-local secrets.

## Reference checkout presentation (23 October 2026)

Match the owner's VigMD reference with a white layout, compact self-hosted
Red Hat Display typography (OFL), medication tabs, horizontal duration cards
and a pale order summary. Retain each site's accent/button colors and use
original artwork. Default only the medication; require explicit duration and
payment choices. Show durations longest first and full upfront totals clearly,
with accurate shipment and renewal terms. Preserve the existing Stripe v2
payment logic in checkout-v9.js. Publish through versioned static assets so the
payment worker and database can remain in place. See CHECKOUT_REFERENCE_DESIGN.md
and the final deployment metadata for the implemented scope and verification.

## Patient portal and intake adapters (23 October 2026)

Keep branded patient accounts and records separate per site initially. The owner
will provide intake and doctor-messaging APIs; use clearly marked backend mock
questions and messages until then. The medical team will fetch information from
Sticky, so its intake destination/mapping remains an integration dependency;
do not pretend a mock submission reached a clinician. The initial isolated
order demo was rejected by the owner; the real-order decision below supersedes it. Use the same
site-scoped APIs for the UI and Swagger. Preserve charge-first and individual
SKU refill rules. No clinical approval or medication release follows from
payment, billing cadence or completed intake. Real patient authentication,
medical-data hosting and the paid-but-declined/incomplete intake policy remain
required before connecting real patients.


## Real Sticky member records and configurable requests (23 October 2026)

The owner explicitly rejected demo orders. Member order and subscription views
must use actual Sticky records, including real Sticky test orders. Use the
existing campaign and authentication; do not introduce another fake order store.
Accounts and grants remain separate per site. A public email alone cannot claim
an order; enrollment comes from an owned completed checkout or an owner-issued,
order-bound invitation. External Sticky orders require an explicit verified site
mapping; renewal descendants inherit only the verified parent grant.

The owner approved $1 initial payments AND $1 full subscription renewals when
checkout testing is enabled. Included intermediate prepaid cycles stay $0.
Normal prices stay independent; a request may select test mode but cannot choose
its own amount. Dry Run verification confirmed both two- and four-cycle renewals.

Address updates, card replacement and early-refill requests belong in the portal.
Current order addresses and future subscription addresses are separate actions.
Early-refill windows, minimum days, check-ins and cooldowns belong to individual
SKU policies. Requests go to review and do not themselves bill or ship. Payment
and included delivery schedules do not establish medical approval.

Card replacement must use a verified Stripe Connect v2 hosted/tokenized flow.
The available Sticky docs do not establish that replacement contract; leave it
unavailable until supplied. Intake and doctor messaging remain the explicitly
requested mock adapters. See the member portal README for exact delivered and
pending boundaries.
