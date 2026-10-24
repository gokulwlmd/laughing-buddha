# Brand coupon creation and price management

Implemented 24 October 2026. Entry point: Admin → Prices & coupons, or
Sites → Prices & coupons. This release has not been deployed to Fly.

## Owner workflow

Select a brand and one of its assigned campaigns. Prices list only its managed
offerings. Edit the whole upfront amount for prepaid plans, review, then approve.
This creates replacement Sticky products/offers, updates the affected checkout
choices and records a scoped replacement for the public API publication. Existing
customers/subscriptions retain their original products, prices and agreements.
Master prices and other brands are unchanged. Existing billing and delivery
configuration is retained by the price-only endpoint.

Create a percentage coupon with a code, 1–99% discount, first-payment-only or
continuing renewal applicability, expiration date/timezone, maximum uses and
optional per-customer limit (0 = unlimited). Each separate cart order counts as
a use. Expiration is the start of the selected date, in its selected timezone;
expiration of new redemptions does not remove an already-applied lifetime discount.
Shipping and tax remain calculated by the existing checkout contract.

Coupon creation produces a review, not an immediate provider write. Approval
creates a separate profile, verifies its saved terms and adds it through Sticky's
single-profile assignment endpoint. Existing assignments are preserved and checked.
Uncertain creation/attachment or mismatched read-back is held for reconciliation;
created IDs are retained and another write is blocked. No automatic retries.
Shared campaigns assigned to multiple local brands cannot receive a new
brand-only coupon; separate campaign ownership is required.

Existing campaign coupons can be listed, including externally created coupons.
This release does not edit/delete existing profiles, support fixed-amount/BOGO
discounts, bulk-reprice active subscriptions, or bypass provider checkout limits.

## Private API contract

Authentication: the existing owner Secure HttpOnly `__Host-admin` cookie. POSTs
also require the configured admin `Origin` and current `X-CSRF-Token`. These are
management APIs, not public browser storefront endpoints or per-brand staff roles.
Never ship owner credentials or administrative sessions in a storefront.

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/api/admin/brands/{brand_id}/prices` | Managed prices for this brand, with campaign IDs |
| POST | `/api/admin/brands/{brand_id}/prices/{offering_id}/reviews` | Preview a price-only change |
| GET | `/api/admin/brands/{brand_id}/coupons?campaign_id=195` | Current campaign coupon summaries |
| POST | `/api/admin/brands/{brand_id}/coupons/reviews` | Preview a new coupon |
| GET | `/api/admin/brands/{brand_id}/commerce/openapi.json` | Owner-authenticated, brand-specific OpenAPI specification |
| POST | `/api/admin/apply` | Approve the returned review ID |

Price request (decimal strings):

```json
{"price":"249.00","expected_price":"199.00"}
```

Coupon request (illustrative, not an instruction to create this coupon):

```json
{
  "campaign_id":195,
  "code":"WELCOME10",
  "percent":10,
  "applies_to_renewals":false,
  "expires_on":"2026-12-01",
  "timezone":"America/New_York",
  "max_uses":100,
  "max_uses_per_customer":1
}
```

Both POST review endpoints return `id` and `preview`. Approval body:

```json
{"review_id":"RETURNED_REVIEW_ID","approve":true}
```

Repeat approval of an applied review returns its existing result. An interrupted
write returns a reconciliation hold, not a new attempt. Configuration drift,
stale expected prices and affected open payments block changes. Existing review
expiry, refresh/discard and auditing remain in effect.

Public checkout consumers still submit only `coupon_code` to their session quote
endpoint. They cannot choose the discount or charge amount. Price replacements
are followed only within the exact approved brand/campaign mapping; refreshing
the publication invalidates its catalog cache. Existing sessions must refresh
their quote if their selected offer changes.

## Evidence and rollout

- Full backend regression at the initial implementation: 527 tests passed.
- Additional targeted prepaid and commerce checks cover full-term prices,
  provider failures, brand isolation, stale reviews, coupon read-back and
  public publication replacement chains.
- All 14 selected commerce, brand and prepaid browser scenarios passed using
  a local synthetic provider, including three new commerce scenarios.
  Desktop/mobile screenshots inspected; no horizontal overflow.
- Synthetic staging supports persisted coupon creation without network access;
  real payment writes remain disabled there.
- Live read-only preflight found 19 awaiting-card and 2 authorization-pending
  checkouts. The live worker was not restarted and no coupon, product, order,
  payment or subscription was changed for QA. Publication is a separate step.

Provider contract: [Sticky REST API](https://developer-v2.sticky.io/), Create
Coupon Profile and Assign Campaign Coupon Profile. Verified against its published
Postman collection on 24 October 2026; new live coupon writes were not exercised.
