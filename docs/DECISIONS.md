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
