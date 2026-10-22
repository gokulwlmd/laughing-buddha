# Master Therapy 1 — Weight Loss

This is the reusable setup skeleton agreed on 22 October 2026. It is available in the admin under Checkout Templates and linked from Therapies. Its versioned source is `tools/stripe-v2-checkout/therapy_skeletons.py`; it is planning data, not an active payment catalog.

Customers choose a treatment, a duration and whether to renew. Every choice charges the entire term upfront. Subscription renewals charge the full term again after the same number of calendar months. Shipments within an already-paid term do not create extra charges.

| Duration | Semaglutide, no renewal | Semaglutide, renews | Tirzepatide, no renewal | Tirzepatide, renews | Shipments per term |
| --- | --- | --- | --- | --- | --- |
| 1 month | SEMA-1M | SEMA-1M-SUB | TIRZ-1M | TIRZ-1M-SUB | Not specified |
| 3 months | SEMA-3M | SEMA-3M-SUB | TIRZ-3M | TIRZ-3M-SUB | Not specified |
| 6 months | SEMA-6M | SEMA-6M-SUB | TIRZ-6M | TIRZ-6M-SUB | 2 |
| 12 months | SEMA-12M | SEMA-12M-SUB | TIRZ-12M | TIRZ-12M-SUB | 4 |

Each `-SUB` SKU renews after its stated duration: 1, 3, 6 or 12 months. Non-SUB SKUs stop after that paid term. Shipment dates/intervals are unspecified and independent of billing. Do not silently substitute 30/90/180/360-day billing models for calendar-month terms.

## Using the skeleton

Open **Checkout Templates → Master Therapy 1 · Weight Loss → Open skeleton draft**. The four duration plans are prefilled and the complete 16-SKU contract stays visible. Save through the existing review flow to persist a local draft and, if absent, its Weight Loss therapy. Reopening keeps the skeleton reference. The built-in recipe is available without creating or overwriting any database records. It does not alter existing Weight Loss therapies, master SKUs, prices, sites or published checkouts.

Editable starter prices have now been assigned; see [the three-therapy catalog](MASTER_THERAPY_CATALOG.md). Processor mappings remain unset. Planned SKU codes are distinct from selected, approved master products; no processor assignments are created. The draft cannot be activated while this contract remains unverified. Existing independent templates continue working normally.

## Before activation

Review each SKU's starter full-term price/currency; configure and verify master product/offer mappings, exact billing renewal and shipment schedules. Native prepaid renewal and real fulfillment remain unsupported by the currently verified payment path. Preserve those payment gates. No live Sticky objects, orders, medication fulfillment or production database changes are authorized by saving this skeleton.

Once those requirements are implemented and verified, the complete template should be included when creating a site, inheriting that site's branding. Existing site prices and published settings must continue to require explicit reviewed updates.
