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
- GitHub Actions run `39992718744` passed its backend and browser test job for backend commit `128c38e4e6195c1f11d8a79f36a1b3f138a345e9`.
- Final storefront: **102 focused tests passed**, with build/type checks and mocked desktop/mobile verification. This includes multi-order payment orchestration, a frozen payment component during processing, partial failures, original-intent retries, nonfinancial session-creation retries, bounded parallel preparation and direct cart checkout.
- Cart storefront published at Lovable commit `c7b4f6b795d748ba3b075ec11ba79df003de8e6a`. Follow-up commit `550d7a804a742a9e4d71062c59709a131218857c` fixes zero-day delivery wording in both checkouts; 93 relevant regression tests and build passed for that display-only patch.
- Backend image: `sha256:c484a779f7898cd7ba31c5f41a2b60d1b5b5ac5066b0ac8dfeb2a997eabc6ed7`.
- Database backup remains on the existing Fly volume at `/data/fortify-before-cart-20261023.sqlite3`. Never export it into the repository.

Provider contracts: [Sticky REST API](https://developer-v2.sticky.io/), [Sticky JSON API](https://developer-prod.sticky.io/), [Stripe Payment Element manual PaymentMethod creation](https://docs.stripe.com/payments/payment-element/migration).

Quote calculations now perform read-only Sticky work outside the global payment lock; their final quote/contact write still holds that lock and requires the checkout to remain new. Authorization/capture retain their existing locking. This lets independent cart items calculate concurrently without allowing contact changes beneath an authorization.

## Live API verification

The deployed API quoted SEMA-12M-SUB at $14.28 with explicit $14.28 / 360-day renewal terms, METFORM-1M at $0.69 with no renewal, and rejected invalid codes with HTTP 422. All 40 current catalog prices remain above Stripe’s $0.50 minimum after the test discount (lowest $0.69). Two concurrent quotes completed together in 11.41 seconds, rather than waiting for one another; provider latency still exists and subsecond checkout is not claimed.

The frontend tokenizes a separate card PaymentMethod for every item before starting any financial request, then confirms/captures one original intent per order sequentially. It never passes the aggregate cart amount to an individual charge. Repeated tokenization, real 3DS and actual captures have mocked coverage but were not tested with a live card. The owner must perform the live payment test.

## Public storefront verification

Verified in the published storefront: Metformin and Semaglutide product pages offer Add to cart; a two-product cart opens the contact/address form directly without an extra review step. With synthetic contact details and `FORTIFYTEST99`, live quotes showed Metformin one-time at $0.69 and Semaglutide subscription at $1.99, a combined $2.68. The subscription text explicitly states $1.99 every 30 days until cancelled. One agreement remains unchecked; Stripe Payment Element loads and Place orders stays disabled pending consent/payment input. No card was entered, consent accepted, payment authorized, or order placed during verification.
