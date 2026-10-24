# Native paid early renewals

Owner-approved behavior, 24 October 2026: a monthly subscription's “Request
refill sooner” advances that existing subscription, rather than selling a second
one-time plan. The patient sees the verified charge and following payment date
and explicitly confirms before the backend calls Sticky. No charge is made by
opening the portal, viewing a price or closing the confirmation.

## Provider contract

Official references inspected on 24 October 2026:

- [Recurring total calculation](https://developer-v2.sticky.io/#f9cb0170-1d33-4766-bc6c-2637ca60af6a)
- [Get subscription](https://developer-v2.sticky.io/#a734bdaa-6362-4231-a7c0-5d27eedc0d88)
- [Force bill an existing order](https://developer-prod.sticky.io/#efdf6132-ff70-4f17-8ce4-40d6ab81af43)
- [Update subscription order](https://developer-prod.sticky.io/#9c2253fb-d8e2-437b-a184-4f21d0ba994c)

`RenewalProvider` in `tools/stripe-v2-checkout/member_portal/renewals.py` reads
the owned order, its subscription, the existing gateway, and
`POST /api/v2/recurring_total/calculate` with tax and shipping calculation enabled.
The price comes from the recurring calculation, including current discounts,
not the initial charge, catalog base price, or the forecast alone. A read-only
check on the owner's referenced FortifyHP subscription verified this distinction:
the recurring calculation included its recurring test discount.

Initially supported: one active non-trial, non-prepaid product, quantity one,
USD, ordinary 30/90-day billing, non-taxable and free shipping, Stripe Connect v2
or isolated Dry Run. Changed products, variants, bundles, credits, unknown
pricing, paused/retrying subscriptions and imminent scheduled renewals are
blocked with an explanation. Included prepaid $0 claims keep their existing
separate path and cannot enter this paid-renewal operation.

After confirmation, the backend re-quotes and rechecks the schedule, product,
policy and patient grant. It reserves a durable intent before a single native
`order_force_bill` for the exact source order/product and existing verified
gateway. It reads the native child and verifies the same subscription, lineage,
paid amount, currency, gateway and product. The following payment is anchored
at the current UTC date plus the verified billing interval; if Sticky returned
a different date, `subscription_order_update` updates that child's date, then
both order and subscription are read back. No new sale or subscription is
created by the application.

A provider timeout, decline/ambiguous response, mismatched child or failed date
update is held as uncertain. Repeat requests only reconcile by reads; absence
of a child does not authorize a second payment. Pending intents block other
subscription actions across the same subscription, including on a new child.
The provider performs the charge at its current price; application preflight
checks are not a provider-side atomic price lock.

## Portal API and persistence

Authenticated, site/order-grant-scoped endpoints:

- `GET /api/v1/sites/{site}/portal/orders/{order}/subscriptions/{subscription}/renewal`
  returns availability/reason, verified amount/currency and dates; an eligible
  response includes a five-minute opaque `quote_id`.
- `POST` to the same path accepts only `{quote_id, confirmed: true}`. It cannot
  accept customer IDs, gateway IDs, amounts, products or requested dates.
  Repeating an uncertain quote performs status reconciliation only.

`member_renewal_quotes` is a durable quote/intent/result journal. A partial unique
index reserves one charge for each site/source order/subscription. Existing
`member_actions` also reserves the subscription against conflicting writes.
Confirmed children are imported through existing verified lineage/grant logic;
the portal then opens the new order's existing health-intake API. Saved stable
answers reuse the established profile rules; changing health answers still need
confirmation. This is not clinical approval or a pharmacy-release operation.

## Policies and rollout

`allow_paid_early_renewal` is a per-site/SKU setting, separate from included
refills and review-only early requests. Existing minimum waiting periods,
initial intake requirements, test-order permissions and cooldown between
successful early renewals apply. The site settings editor exposes the toggle.
The owner-authorized FortifyHP rollout enables the flag only when absent on its
existing 1/3-month subscription SKUs. Later explicit admin edits are preserved.
Other sites remain off until configured. Disabled refill policies stay disabled.

The portal loads renewal pricing in the background on the Refills view. It
shows the price even when an intake or policy prevents payment, and disables
the action with that reason. Existing subscriptions no longer show a separate
paid-supply picker or the irrelevant “included refills not included” paragraph.
Secure card replacement remains unconnected; its existing action reports that
limitation and does not accept card data in the portal.

## Verification boundary

Tests exercise provider contracts with offline fixtures: discounted quotes,
price drift, expiry, site/patient scope, consent, one native child, idempotency,
uncertain-result adoption, next-date repair and blocked repeated charges,
required intake, unsupported schedules, trials, prepaid exclusions and action
conflicts. Browser tests cover price/confirmation, no charge before confirmation,
uncertain-state handling, paused plans, required intake, and included refills.
Live checks are read-only. No real card, subscription or included refill was
charged or advanced during implementation. A provider-successful paid early
renewal has not been exercised end-to-end against the live processor.

Release verified 24 October 2026 on the existing shared Fly app: image
`sha256:c2711bff95fa3ebbe7462ae72f4dadcfd27f9a1c1c1feba835ca5f4e4978bbd9`.
118 member backend tests, 48 targeted tests (overlapping renewal coverage), and
26 portal browser scenarios passed. Hosted source hashes match; health returned
200 and unauthenticated member data returned 401. Saved checkout/patient counts
were unchanged. Ten existing FortifyHP 1/3-month SKU policies were enabled.
Read-only live recurring pricing included the continuing discount; no live
charge, subscription advance or included-refill claim was submitted as QA.
