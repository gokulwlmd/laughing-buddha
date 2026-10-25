# Refill policy release — 26 October 2026

Published on the existing Fly app `wlmd-stripe-test-0f89b1bb`, preserving its
machine, volume, secrets and database. No AWS deployment or customer payment.
Image: `registry.fly.io/wlmd-stripe-test-0f89b1bb@sha256:686b827b44204fd2b6212acb7fad0e7f01cb08a8357803e4960be4bee95f4b14`.

The owner explicitly rejected separate refill SKUs. Original base/`-SUB` codes
stay unchanged. Verified Sticky lineage identifies an initial purchase, included
$0 delivery or paid renewal. Refills/renewals receive a short check-in only when
the exact SKU's policy requires it. A new unrelated purchase remains initial.
The sync traverses direct parents so an ancestor's all-descendants list cannot
assign a renewed term to the original term.

Added 34 source-derived master policies for 17 Hair Growth, NAD+ and Glutathione
products, including both purchase types. Sixteen have included refills; their
claim windows open 20 days before the next 90-day supply boundary. One included
refill for six months, three for twelve. All 34 source policies explicitly skip
refill check-ins; original intake remains required. Existing therapy rules and
saved care/answer snapshots are preserved. These new templates remain drafts;
this release does not activate them on a customer's site or configure new
Sticky production products/offers.

## Verification

- Clean Fly-source backend regression suites passed, including six/twelve-month
  entitlement boundaries, initial intake preservation, paid renewal routing,
  same-SKU/site/subscription validation, no-form claims, duplicate/uncertain
  requests, API ownership and existing care/subscription behavior.
- Five Chromium scenarios passed on the clean release: enrollment/site isolation,
  address/refill controls, admin policy editing, required check-in delivery flow,
  and no-check-in delivery flow at desktop/390px/320px widths.
- Fly deployment succeeded and HTTPS `/health` returned running with the existing
  authorization contract enabled. A private on-volume database backup preceded
  deployment. The additive importer previewed and then inserted exactly 34
  policies with zero Sticky writes.
- The separate-SKU Dry Run experiment is archived in STICKY_REFILL_SKU_CONTRACT.md;
  its provider setup is not used by this runtime. No new live payment, fulfillment
  or identity requests were made as deployment checks.

The image was assembled from current Fly source plus scoped portal/refill changes;
unrelated local AWS/Python 3.9/MySQL work was excluded. Rollback image:
`registry.fly.io/wlmd-stripe-test-0f89b1bb@sha256:33f2fed43a58bf7adbaf2f584e2e2583188fb87706b22285eabf060ecde77021`.
Do not restore the full database over later customer activity. The new policies
are additive master defaults; pause new site activation if rolling runtime back.
