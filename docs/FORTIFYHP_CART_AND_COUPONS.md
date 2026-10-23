# FortifyHP cart and coupon release — 2026-10-23

## Owner decisions

- Continue the new storefront at https://fortifyhp-care.lovable.app; do not change fortifyhp.com.
- Products are selected on existing product pages, added to a cart and checked out together.
- Each cart item creates its own Sticky order and payment. Share contact/address entry and agreement presentation; retain explicit per-item renewal terms.
- Remove the explicit Review total step. Quote automatically, revoke consent when purchase inputs change, and preserve uncertain payments rather than retrying them.
- The requested test discount applies to the first payment **and subscription renewals**.

## Coupon

`FORTIFYTEST99`, Sticky profile **3126**, is assigned additively to campaign **195** only. Existing coupon assignments and Stripe v2 gateway **269** were preserved. It discounts product prices by **99%**, with lifetime subscription applicability, a limit of **100 initial uses**, and expiration **2026-10-30** (America/New_York). This expiration limits new applications; lifetime discounts on subscriptions are a separate setting.

Only quote calculations were used for live verification. No payment authorization, capture or order was submitted by this release work.

Verified Sticky totals:

| Plan | Regular upfront price | Discounted initial total |
| --- | ---: | ---: |
| SEMA-1M-SUB | $199.00 | $1.99 |
| SEMA-6M-SUB | $1,014.90 | $10.15 |
| SEMA-12M-SUB | $1,428.00 | $14.28 |
| METFORM-1M | $69.00 | $0.69 |

Six-month and twelve-month plans retain two/four deliveries at 90-day intervals; renewals remain every 180/360 days. One/three-month subscriptions renew every 30/90 days. A discounted live-gateway purchase remains a real order, potentially picked up by the client's external fulfillment system.

## API contract

The site session quote endpoint accepts optional `coupon_code` (maximum 30 characters). It returns `coupon_code`, `discount_amount` in cents, `subtotal_amount` (total before coupon, including any other calculated components), `discount_applies_to_renewals`, and explicit `payment_terms` alongside its existing fields. Frontends must never submit an amount or discount percentage.

The backend resolves only campaign-assigned percentage order coupons, asks Sticky to calculate the discount for the customer's email, and rejects invalid/expired/exhausted/non-applicable codes. It revalidates discount amount and lifetime applicability before authorization and capture. Capture passes Sticky's documented `promoCode`, without price overrides; read-back checks the coupon profile and discount actually retained on the order.

Usage counters are excluded from the catalog configuration fingerprint: one successful cart item must not invalidate another item's quote merely by incrementing coupon usage. Sticky still validates current usage limits on each calculation.

A cart uses one existing API session, PaymentIntent and Sticky order per item. Never reuse one captured PaymentIntent for another product. Preserve successful item receipts when another item fails. Refresh/retry must inspect existing session state first.

## Validation and release status

- Backend suite: **445 tests passed**, including 11 coupon, prepaid rounding, cart usage and concurrent-quote boundary tests.
- Initial checkout simplification: 47 Lovable tests passed; desktop/mobile mocked checks and build/type checks passed.
- Final multi-item storefront verification and deployment: pending completion below.
- Backend image: `sha256:c484a779f7898cd7ba31c5f41a2b60d1b5b5ac5066b0ac8dfeb2a997eabc6ed7`.
- Database backup remains on the existing Fly volume at `/data/fortify-before-cart-20261023.sqlite3`. Never export it into the repository.

Provider contracts: [Sticky REST API](https://developer-v2.sticky.io/), [Sticky JSON API](https://developer-prod.sticky.io/), [Stripe Payment Element manual PaymentMethod creation](https://docs.stripe.com/payments/payment-element/migration).

Quote calculations now perform read-only Sticky work outside the global payment lock; their final quote/contact write still holds that lock and requires the checkout to remain new. Authorization/capture retain their existing locking. This lets independent cart items calculate concurrently without allowing contact changes beneath an authorization.
