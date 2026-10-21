# Sticky prepaid: 12-month plan, four quarterly shipment orders

Researched 21 October 2026. Documentation research only; no account configuration, orders or payments changed.

## Finding

Sticky Core has a native Prepaid Offer: charge for a configured number of shipments upfront, then fulfill orders on the selected cycle. The Core offer guide explicitly defines prepaid terms as a number of orders, calculates the initial product charge as product price multiplied by those orders less any term discount, and offers stop/hold or prepaid renewal at term end. Core release notes also refer to recurring prepaid orders displaying $0. This supports the requested commercial model; it has not yet been validated through our account's Stripe Connect v2 flow.

For the requested plan, the intended structure is four total shipment cycles, including the initial shipment, each supplying three months. A product's per-shipment quantity/content must actually represent that supply; neither the duration label nor prepaid cycle count changes pharmacy quantities.

| Event | Product payment | Shipment/order |
| --- | --- | --- |
| Initial purchase | Full prepaid plan amount | Order 1; first three-month supply |
| Three months later | No additional product charge | Order 2; second supply |
| Six months later | No additional product charge | Order 3; third supply |
| Nine months later | No additional product charge | Order 4; fourth supply |
| End of term | Stop, or renew only under selected renewal terms | No fifth shipment in the original four-shipment plan |

Zero total on subsequent orders requires shipping/taxes/fees to be handled accordingly. The table describes intended behavior to test, not observed orders. Documentation does not establish that four order IDs are allocated immediately at initial checkout; verify subsequent creation timing and subscription lineage in an isolated test.

## Mapping and pricing

- Offer: Prepaid, with four prepaid cycles/orders. Four orders, not twelve, because delivery is quarterly.
- Cadence: quarterly shipment interval. Our existing 90-day model means every 90 days, not every three calendar months; four 90-day cycles cover 360 days. Confirm which promise to sell and configure accordingly.
- Product: reviewed three-month shipment SKU, or an explicitly configured quantity/bundle of monthly units. Do not assume TIRZ-1M quantity one supplies three months.
- Price: Sticky's Core example uses per-cycle product price × number of prepaid cycles, then term discount. For an illustrative $1,200 plan with no discount, this is $300 × 4. Do not supply $1,200 as a per-cycle price and accidentally charge $4,800. Derive the final gateway amount from a validated server quote.
- End of term: stop/hold for a fixed purchase; prepaid renewal is a separate explicit choice. A standard recurring expiry rule can have a last-product extra-cycle behavior, so do not use it as an untested substitute for prepaid term handling.
- Order API: official JSON Orders documentation marks `offers[].prepaid_cycles` as required for prepaid offers. Proposed value here is 4, accompanied by the selected offer, product, billing model and per-shipment quantity. This is not yet a validated request for our account.
- Track four fulfillment order IDs under the prepaid subscription/plan, each with its shipment status. Use native prepaid recurrence rather than four independently charged new-order requests.

## Shipping, cancellation and refill controls

Sticky's SFCC prepaid guide describes shipping charged per shipment by default, with prepaid shipping available (base shipping × cycles). It also documents $0 prepaid-order notifications and cancellation choices: finish the paid shipments then stop, or cancel remaining shipments with refunds handled manually. Those details come from the SFCC integration guide; confirm their exact settings/behavior in our Core API/account rather than assuming every integration is identical.

For WLMD, payment entitlement and clinical refill approval remain independent. A scheduled order must not automatically release medication without the required refill/clinical approval. The implementation must distinguish order creation, fulfillment hold, clinical approval and shipment release. Pause/cancel/skip effects on prepaid entitlements, renewal timing and refunds need explicit validation.

## Current app gap

`tools/stripe-v2-checkout/catalog.py` deliberately blocks prepaid offers because their additional selections and calculations are not implemented. The current master editor supports standard one-time and day-based recurring purchases only. The new duration label does not implement prepaid fulfillment.

Suggested future admin wording: **Pay upfront** → **12-month plan** → **Ship every 3 months** → **4 shipments** → **Total upfront price** → **Renew automatically: on/off**. Internally retain separate product/supply units, shipment cadence, prepaid cycle count, term total and renewal behavior.

## Required test cases before enabling

1. Initial order charges the expected complete plan total once; records four prepaid cycles and one initial shipment order.
2. Execute subsequent cycles in a properly isolated test setup; confirm three additional distinct order IDs, correct parent/subscription lineage and no extra product payment.
3. Verify each order's SKU, quantity, fulfillment payload and eligibility gate; prepaid cycle count must not multiply the initial shipment quantity.
4. Confirm stop after four total shipments and no fifth charge/order for a non-renewing term. Separately validate explicit prepaid renewal.
5. Test shipping/tax/fee totals at initial and later cycles; prove $0 subsequent totals where that is the marketed promise.
6. Validate cancellation, hold/resume and clinical deferral without forfeiting or duplicating prepaid shipments. Confirm documented/API restrictions on modifying prepaid recurring details.
7. Validate server quoting, Stripe v2 initial authorization/capture, order read-back, recovery and retries without duplicate payment or fulfillment. A positive upfront payment is distinct from subsequent $0 fulfillment orders; do not assume the current checkout's zero-value limitation describes Sticky's internal prepaid recurrence.

## Sources

- [Sticky Core: Create an Offer](https://support.sticky.io/en/articles/3770102-create-an-offer), updated July 15, 2025: prepaid definition, order counts, price multiplication, renewal and recurring behavior.
- [Sticky JSON API: Orders](https://developer-prod.sticky.io/#7da6cb71-5770-4581-9a5e-9a7227ad7b9c), collection `sticky.io JSON API & Integration v2026.08.07`, retrieved from the site's official collection endpoint: required `offers[].prepaid_cycles`; code 359 documents an inability to update prepaid recurring details through the relevant operation.
- [Sticky Core: Release Notes 2021](https://support.sticky.io/en/articles/4772639-release-notes-2021): recurring prepaid orders displaying $0 and prepaid product swapping fixes. Historical evidence, not a current account test.
- [SFCC: Creating a Prepaid Offer](https://support.sticky.io/en/articles/6174056-step-2b-creating-a-prepaid-offer), May 4, 2022: scheduled prepaid orders, optional prepaid shipping, renewal choices, cancellation, refunds and $0 order notifications. Integration-specific details require Core verification.

## Implemented test setup — 22 October 2026 (IST)

The user requested setup and explicitly chose **every 90 days (360-day plan)**. A separate synthetic, non-shippable, non-taxable product was created at $300 per cycle: SKU `WLMD-PREPAY-cfef3de8`, product **55098**, offer **712**, campaign **422**, model **4**. The offer has a single four-cycle term, zero discount, `is_subscription=0` and `is_convert_to_standard=0`. Existing campaign routing and offer attachments were preserved; only this new offer was appended. The authoritative quote returned $1,200 and `line_items[0].prepaid.term=4`.

Four actual Sticky dry-run orders were created and read back:

| Cycle | Order ID | Total | Recurring afterward |
| --- | --- | --- | --- |
| 1 | 506291 | $1,200 | Yes |
| 2 | 506295 | $0 | Yes |
| 3 | 506299 | $0 | Yes |
| 4 | 506300 | $0 | No |

All four orders have `is_test_cc=1`, gateway **1 (Dry Run Testing)**, the same subscription ID and common ancestor 506291. Each order has quantity one and a separate ID. The last order records cycle 4 of 4, renewal 0, `is_recurring=0`, no next recurring date/product, and a subscription-complete system note. Subsequent cycles were advanced manually through `order_force_bill`, forcing and preserving gateway 1; the calendar scheduler and elapsed 90-day intervals were not exercised. No real card charge or physical shipment occurred. Full sanitized results: [sticky-prepaid-test-results.json](sticky-prepaid-test-results.json).

The application extension supports a fixed prepaid term for non-shippable/non-taxable test products. Admin prices are the whole prepaid amount; Sticky product prices are calculated per cycle using exact cents. Quotes must return matching prepaid term/count/total before authorization. Capture sends the same `prepaid_cycles`, and read-back checks the first cycle, total cycles and no-renewal flag. Physical medication fulfillment remains blocked until its clinical release workflow is verified. Renewal, combined trial/seasonal/series behavior, term discounts and multiple terms on one offer remain outside this implementation.

The one-time import script adds this already-created fixture to the existing test brand, master catalog, assignment and a private link. It creates no owner/session and performs no Sticky write. The test master is disabled for bulk assignment to future campaigns; its existing test checkout can still be used. The script records the user's setup authorization in `admin_setup_runs`, preserves existing reviews and records, and refuses partial collisions rather than overwriting them. Deployment/import results are recorded separately in the app's deployment metadata.
