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
