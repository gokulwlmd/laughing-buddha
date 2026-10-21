# Verified WLMD baseline

Historical evidence from the original setup, not current runtime readiness or a command to replay orders. Recheck object identity and settings before reuse.

## Catalog observations

The account returned 54,072 product records and 670 offers during initial inspection. These counts can change and are not the number of unique master SKUs.

Exact SKU `TIRZ-1M` appeared on these separate product records. Each returned the name "Compounded Tirzepatide - 1 month supply" (spacing varied) and base price 449.00. This is a verified sample, not an exhaustive SKU search.

| Brand-named offer | Offer ID | Product ID |
| --- | --- | --- |
| v4ever offer | 1 | 2856 |
| LevelUpMeds Lifetime Offer | 2 | 2012 |
| BigedsMeds Lifetime Offer | 6 | 1840 |
| JulyMD Lifetime offer | 18 | 3171 |
| PrideMD Lifetime offer | 19 | 4891 |

The generic monthly product had no configured variants. Separate dose-specific product records existed, including `TIRZ-2.5MG-30-1B`, `TIRZ-5MG-30-1B`, and `TIRZ-7.5MG-30-1B`. Do not infer how prescribing chooses between these SKUs from their names alone.

## Created fixture

- Run: `WLMD-CORE-TEST-70f992bad7`.
- Synthetic product: **54536**, SKU `WLMD-CORE-TEST-70f992bad7-TIRZ-1M`, non-shippable, USD 449.00.
- Offer: **705**, Standard/Self Recurring, containing the synthetic product and all 13 then-configured models.
- Campaign: **422**, isolated from fulfillment, membership, email and postbacks.
- Gateway profile: **1**, alias and provider name **Dry Run Testing**, provider/account ID **10**, USD.
- Gateway identity was discovered on existing `CHECKOUT-DEV` campaign 5 and `TEST` campaign 390, then verified directly. Existing campaigns were not modified.

The API user initially needed campaign 422 access granted by the user before it could read the new campaign. A request before gateway attachment failed at payment routing. The 13 approved orders below were created after that issue was resolved and were individually read back.

## Approved test orders

All rows returned `test=1` at creation, `is_test_cc=1` on read-back, the correct fixture and billing model, USD 449.00 total, zero shipping, and `Not Available` transaction/authorization IDs. Dates are Sticky's returned account dates, not user-local timestamps.

| Model ID | Billing model | Configured days | Order ID | Next billing date |
| --- | --- | --- | --- | --- |
| 2 | One Time Purchase | None | 504603 | None |
| 3 | 30 days subscription | 30 | 504605 | 2026-11-19 |
| 4 | 90 days Subscription | 90 | 504606 | 2027-01-18 |
| 5 | 180 days subscription | 180 | 504607 | 2027-04-18 |
| 6 | 360 days subscription | 360 | 504608 | 2027-10-15 |
| 7 | 270 days subscription | 270 | 504609 | 2027-07-17 |
| 11 | test_subscription | 30 | 504610 | 2026-11-19 |
| 12 | TRACK-21 | 360 | 504611 | 2027-10-15 |
| 13 | 60 days subscription | 60 | 504612 | 2026-12-19 |
| 14 | 15 days subscription | 15 | 504613 | 2026-11-04 |
| 15 | 180 days billing, 90 days shipping | 90 | 504614 | 2027-01-18 |
| 16 | 120 days Subscription | 120 | 504615 | 2027-02-17 |
| 17 | 150 days | 150 | 504616 | 2027-03-19 |

**Model 15 mismatch:** Its name says 180-day billing, while its configured `days`, description, and test-order schedule all indicated 90 days. The existing model was left unchanged.

Future rebill execution, clinical workflows, shipping, prepaid-bundle releases and pay-per-refill orchestration were not tested. Test orders were left available for inspection. The original run state and full synthetic response evidence were saved under `/workspace/scratch/sticky_test_run`; this skill's instructions and baseline do not depend on that scratch directory surviving future tasks.

## Stripe Connect v2 diagnostic

The user subsequently authorized using live v2 profile **254** for a diagnostic. A single request through `POST /api/v1/new_order`, routed to **Stripe Connect v2 provider 250**, used Stripe's published test card ending 4242 and the synthetic, non-shippable fixture above. It produced Sticky order **504690**.

The response identified gateway 254, provider `STRIPE CONNECT V2`, source `External`, response code 10800, and this Stripe error: **"Your card was declined. Your request was in live mode, but used a known test card."** Order read-back confirmed status 7 (declined), an empty transaction ID, and the same error.

This establishes that the v2 request reached the processor and an external decline was returned. It is not an approved payment, sandbox-charge result, or webhook test. The existing profile's configuration was not changed. Campaign 422 was temporarily routed to 254, then restored to gateway 1 and read back. The live-profile diagnostic was explicitly requested by the user; it is historical evidence, not permission to submit another live-profile request.

The user-supplied v2 guide is <https://support.sticky.io/en/articles/12694259-stripe-connect-v2>. The runtime proxy blocked the URL with CONNECT 403 during the diagnostic. The user subsequently supplied the full article text, now studied and captured in [v2 checkout requirements](stripe-connect-v2.md). Diagnostic 504690 omitted the required `three_d_redirect_url` and did not exercise 3DS completion or Stripe Link's authorization/frontend/capture sequence. Diagnostic evidence was saved under `/workspace/scratch/sticky_stripe_v2_test`.

## Current $2 checkout fixture

The user subsequently requested a real one-time USD 2.00 payment using their own card. Product **54537** is non-shippable, with a `WLMD-CORE-2USD-` SKU; offer **706** contains only that product and billing model **2**. The offer was added to synthetic campaign **422**.

The user configured campaign 422 with primary gateway **254**, payment types **Visa and Stripe Link**, and the Stripe Link alternative mapped to profile **254**, provider **250**. A fresh API read confirmed this configuration. **Preserve this saved configuration; gateway 1 is a historical dry-run setting, not the current baseline.** The checkout harness now verifies routing without sending campaign PUT requests.

After this mapping was confirmed, the initial incomplete `authorize_payment` request returned **HTTP 500**. The user subsequently supplied their working Lovable integration, establishing the complete authorization payload: explicit billing fields, `forceGatewayId: 254`, `productId: 54537`, and **`auth_amount: "2.00"`**, rather than `amount`/`productPrice`. One corrected request returned **HTTP 200, response code 100, status OK**, a valid `digitalWalletToken` client secret, and a `transactionID` matching its PaymentIntent. No card or payment method was supplied and no capture was requested. No client secret was persisted or logged.

The harness is under `tools/stripe-v2-checkout`, with 12 passing offline tests covering financial boundaries, PaymentIntent consistency and campaign preservation. It is now deployed privately on Fly.io at `https://wlmd-stripe-test-0f89b1bb.fly.dev`, with one machine and persistent encrypted SQLite storage. The owner entered the Sticky credentials through Fly's secure secret controls. Hosted health returned 200, unauthenticated page access returned 401, and authenticated read-only fixture validation returned ready, amount 200 cents USD, live publishable-key mode and new purchase state. Private invitations belong only in the owner delivery channel, never this baseline or logs.

Authorization setup and HTTPS deployment are verified. Deployment validation submitted no card or capture, so it does not establish completed live card authorization or a paid $2 order. No additional Stripe secret key was retrieved or requested. The Lovable document's reported earlier $1 order 489098 belongs to campaign 167 / offer 227 / product 21946; it was not freshly verified here and those IDs must not replace the isolated $2 fixture. See the harness's `FLY.md` for the deployed resources and update procedure. Do not redeploy or restart an active payment without reconciliation.
