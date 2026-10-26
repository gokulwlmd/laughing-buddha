# Refill identity and SKU policy

Decision updated 26 October 2026: **no separate refill SKUs**. The owner rejected
that approach after its isolated provider test. Keep the original product/SKU
through its subscription chain. Base means one-time upfront; `-SUB` means
recurring upfront, never a refill indicator.

## Order role

The backend distinguishes initial purchase, included refill and paid renewal
using verified Sticky parent/ancestor, site, customer, product, subscription,
cycle and paid-term history. Traverse direct parents: Sticky's ancestor list
contains every descendant and must not reset a renewal to the original term.
Unknown lineage cannot open an arbitrary refill questionnaire or grant supply.
A separate purchase of the same SKU remains a new purchase.

- Initial purchase: the configured initial intake.
- Included $0 delivery: the refill check-in only when that SKU requires it.
- Paid renewal: the refill check-in only when that SKU requires it.
- No check-in required: display the delivery/order state without another form.

Existing saved care plans and submitted answers remain immutable. No provider
product renaming, custom recurring-product migration or subscription rewrite.
Clinical review and fulfillment status require their own evidence.

## Source-derived master policies

The 17 approved Hair Growth, NAD+ and Glutathione products have 34 exact
base/`-SUB` policies. All these source rows explicitly require no refill check-in;
initial intake remains required. Existing therapies retain their own rules.
`MIN-1MG-FINA-1.25MG` and its subscription pair remain excluded pending the
oral/topical source conflict. These masters remain drafts until assigned and
published through the site's existing setup/review process.

Six-month terms have two deliveries: one included refill. Twelve-month terms
have four deliveries: three included refills. Deliveries are 90 days apart;
claims open 20 days beforehand (day 70; or days 70, 160 and 250). One/three-month
single-delivery terms have no included refill. Renewing terms charge upfront
again at their configured 30/90/180/360-day boundary. Paid early renewal remains
an explicit, quoted, confirmed action where supported; it is not a free claim.

The additive policy installer validates saved masters against the approved
source, refuses conflicting existing policies and records an idempotent import.
It does not change existing care snapshots or activate drafts on customer sites.

## Archived provider experiment

The owner approved two non-shippable synthetic products (56623/56624), offers
835/836 and Dry Run campaign 429. After campaign access was enabled, eight
synthetic orders verified $0 intermediate deliveries and full upfront renewals
across two/four-cycle terms. Forced cycles did not verify elapsed-time scheduling.
The separate-SKU design was subsequently rejected and is not part of the release.
Retain the fixture journal for audit; do not repeat it or use it for production.
The opt-in verifier remains a QA utility only, outside the runtime image.

## Release verification

Offline provider tests cover unchanged SKU identity, same-site/subscription
lineage, 6/12-month entitlements, exact 20-day windows, duplicate and uncertain
claims, original intake preservation, no-form deliveries and paid-renewal routing.
Browser checks cover required check-ins and no-check-in refills at desktop,
390px and 320px widths. See the release record for deployment outcome.
