# Four master therapies: live payment-test setup

Completed on 22 October 2026 at the owner's explicit request. Use the existing [live admin](https://wlmd-stripe-test-0f89b1bb.fly.dev/admin#sites), sign in with the existing live owner account, and open **Sites → Master Therapy Payment Test → Preview** for Weight Loss, Sermorelin, Metformin or PT-141. Previews remain private; obtain invitations inside the admin, never from source control.

## Applied catalog

Campaign **422** retains its existing gateway **254**, Stripe Connect v2 provider **250**, USD, US and Free Shipping settings. It now includes forty new products **55866–55905** and offers **715–754**, one independently priced offer for each of the forty requested SKU codes. All previous campaign offers/products and gateway routing were read back unchanged. All forty full-term prices were verified through Sticky's order-total calculation without authorization or capture. The manifest is in [the sanitized release record](../tools/stripe-v2-checkout/master-therapy-payment-deployment.json).

| Term | Non-SUB | SUB | Included schedule for longer terms |
| --- | --- | --- | --- |
| 1 month | Full price once | Full price every 30 days | Short-term fulfillment count remains unspecified |
| 3 months | Full price once | Full price every 90 days | Short-term fulfillment count remains unspecified |
| 6 months | Full price upfront; no renewal | Full price upfront and again every 180 days | Two cycles, days 0/90; intermediate product charge $0 |
| 12 months | Full price upfront; no renewal | Full price upfront and again every 360 days | Four cycles, days 0/90/180/270; intermediate product charges $0 |

Short SUB terms use the existing 30/90-day standard billing models. Longer terms use native prepaid offers with one configured 90-day cycle model and two/four cycles. Native product price is the full upfront amount divided by cycle count; the checkout quote and authorization use the verified full upfront total. Renewing prepaid uses `is_subscription=1`, without conversion or discounts. Non-SUB prepaid uses `is_subscription=0`.

The default prices remain editable master defaults. No existing customer price or subscription was changed. Original TIRZ-1M retains its approved legacy offers. Its new one-time payment-test product is **55874**, offer **723**; only therapy/treatment/duration organization metadata was added to its saved master, and its SKU was included in the saved one-month duration plan. New assignments belong to the separate `master-therapy-test-422` brand so the new one-time choice cannot expose the legacy subscription choices through these plan checkouts.

## Verification and limits

Eight approved synthetic Dry Run orders on the separately approved campaign **428**, gateway **1**, verified both renewal chains:

- Two-cycle term: orders **507023/507024/507025**, totals **$20/$0/$20**, cycles **1/2/1**.
- Four-cycle term: orders **507026–507030**, totals **$40/$0/$0/$0/$40**, cycles **1/2/3/4/1**.

The same subscription and ancestor were checked within each chain; gateway identity and `is_test_cc=1` were verified on every order. Subsequent cycles were forced manually with the Dry Run gateway explicitly preserved. This proves the native prepaid amount/cycle/renewal behavior in that test path, not elapsed-time scheduling or a live processor capture. No real card was used by the agent. The owner explicitly approved these fixture writes and enabled API access to campaign 428 after Sticky initially denied it.

All new campaign-422 products are non-shippable/non-taxable payment-test records. Campaign fulfillment, tax, email and membership integrations remain disconnected. Both the duration selection and card checkout display **Live payment test: your card will be charged. No medication will be shipped.** The owner enters a card and submits any real charge. Do not use processor test cards on this live gateway. These payment tests do not establish clinical eligibility or pharmacy/refill fulfillment.

All four private hosted plan APIs verified availability for their 16/8/8/8 SKU entries, correct renewal metadata and rejection without a private invitation. Owners, sessions, reviews, historical receipts, purchase successors and pending attempts matched the on-volume pre-activation backup exactly. All other pre-existing configuration remained unchanged except the explicit TIRZ organization metadata and one-month plan membership update.

183 backend tests and 34 affected browser scenarios passed. The browser suite uses fake services; its renewal service was corrected to return the configured renewal flag instead of hardcoded zero. A full synthetic setup test covers forty products/offers, four private site checkouts, retained configuration and repeat publication. Runtime hashes match the deployed source.

## Operator continuation

`therapy_campaign_setup.py` is an explicitly invoked, exact-host `/data` operator action, never a startup import or an owner impersonation. Its durable journal is `/data/master-therapy-422-20261022-v1.json`; it contains no API credentials or customer data. The phases are `Setup(app).verify_renewal()`, `.provision()`, `.publish()` and `.report()`. Do not run a new proof sequence or repeat orders by default. Confirmed catalog IDs are reused, pending/uncertain writes stop for reconciliation, repeat publication returns the saved result, and a separate `admin_setup_runs` record audits the explicit owner request.

Live attachment appends only the new offer IDs after checking original offer/product hashes and campaign routing. It does not clear or retry the older held authorization. Existing application review locks remain in place for normal edits/replacements. All old payment rows stay unchanged and captures still fail closed after configuration drift.

`test_catalog_activation` binds the verified payment-test mapping to the master fingerprint. Template/site setup can use that mapping without converting a physical medication product into a test product. Changing a master invalidates that binding; later updates need review. The ordinary guards for physical/taxable prepaid products remain enforced. Published checkouts retain their approved terms until explicitly updated.

Sticky's [native prepaid offer description](https://support.sticky.io/en/articles/3770102-create-an-offer) and [prepaid renewal configuration guide](https://support.sticky.io/en/articles/6174056-step-2b-creating-a-prepaid-offer) supplied the configuration reference; the account-specific verification above is the execution evidence.
