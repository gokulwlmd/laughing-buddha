# FortifyHP NAD+ annual subscription test

## Subsequent owner clarification

Site deployments must show both one-time and subscription for each finalized
paired plan. The subscription-only test below is historical scope, not the
deployment default. FortifyHP still needs the exact `NAD-INJ-12M` one-time master
mapped and published alongside `NAD-INJ-12M-SUB`. Preserve the existing subscription
and its prices. One-time means the full 12-month term upfront, four quarterly
deliveries, three included refills, and no renewal. This documentation update
does not change live provider objects or the published API.

The owner selected only the 12-month NAD+ injectable subscription for FortifyHP testing. Other wellness drafts remain unpublished for this site. No new app, AWS migration, separate refill SKU, or changes to existing subscriptions were requested.

## Published configuration

- Site/brand: `fortifyhp`; Sticky campaign 195, existing Stripe Connect v2 profile 269.
- Exact master SKU: `NAD-INJ-12M-SUB`.
- Sticky product 56625, offer 837, billing model 4 (90-day delivery cycles).
- Source product 33363 has the verified legacy alias `NADINJ-12M`; its existing price and offer were preserved. A new campaign product carries the approved master SKU.
- Price: $1,668 upfront, renewing every 360 days. Four deliveries at days 0/90/180/270; product allocation $417 per delivery.
- Three included $0 refill cycles retain the same SKU. Claim windows open at days 70/160/250, subject to remaining entitlement and verified order state.
- Initial intake required. No additional refill check-in for this SKU, following its approved source policy. Identity/intake completion does not establish clinical approval.
- Existing external fulfillment integration remains responsible for collecting and fulfilling Sticky orders.

Public checkout: `/c/choice-22dd94df6897bcb5dec91167d3692793`.
Plan selector: `/plans/site-api-fortifyhp-nad-plus`.
Site API now returns 41 plans; new `plan_id` is `nad-inj-12m-sub`.
Portal: `/portal/fortifyhp`.
All paths use the existing `https://wlmd-stripe-test-0f89b1bb.fly.dev` origin.

The existing FortifyHP 99% test coupon was verified through Sticky's authoritative quote: $16.68 initial and $16.68 renewal, lifetime discount. Coupon expiry and usage limits remain governed by its existing provider profile. No payment was submitted to verify this quote.

## Implementation and evidence

- `external_fulfillment.py` adds only this exact SKU to FortifyHP's existing guarded prepaid scope. Campaign, gateway, physical product, tax, shipping, cycle count and billing-model checks remain enforced.
- `fortifyhp_nad_test.py` journals provider writes before submission, validates readbacks and the full-term quote, then inserts eleven new local configuration records and appends one therapy to the publication manifest. Uncertain writes require reconciliation; existing records are never overwritten.
- Thirteen focused automated checks passed in the working checkout and clean release: additive setup/idempotency, uncertain-write protection, exact scope, and portal same-SKU $0 refill behavior with the required initial intake and no extra check-in.
- The shared checkout now accepts a coupon code and displays server-confirmed renewal pricing; resumed forms retain their discount disclosures. Twelve coupon backend tests and one browser checkout test passed, covering expired-code blocking and no payment authorization during quote review.
- Live provider readbacks and the full-price/discounted quotes passed. Public site API exposes the expected price, subscription interval and shipment schedule.
- Existing configuration records, checkout/payment records, patient/order records, care intakes and refill claims matched the private pre-release backup after provisioning.
- No live order, card authorization, charge, refill, identity check or patient password operation was performed. Live purchase-to-portal testing awaits the owner's manual payment.
- The Lovable Available Products UI was not changed; this release provides the branded direct checkout and shared API plan for the requested test.

## Release and recovery

Deployed on the existing Fly machine and volume:
`registry.fly.io/wlmd-stripe-test-0f89b1bb@sha256:eecfd35251429645dba5cb135140fd15564e8e13d943a604f95bd9d46487e28c`.

Previous image: `sha256:686b827b44204fd2b6212acb7fad0e7f01cb08a8357803e4960be4bee95f4b14`.
Private database/manifest backups and the setup journal remain on `/data`; never commit them. If rolling back runtime support, disable this new publication first so it cannot advertise an unsupported plan. Do not delete or replay payment records.

The release used a clean Fly build context, excluding unrelated in-progress AWS/MySQL changes. Only the scoped implementation, tests and this sanitized handoff belong in this change.
