---
name: stickyio-catalog-billing
description: Inspect Sticky.io products, duplicate SKUs, offers, campaigns, and billing models; create isolated synthetic billing fixtures and verify test orders across configured billing models for WLMD Core.
---

# Sticky catalog, billing, and test orders

Use this skill when asked to understand Sticky's catalog or SKU mappings, set up a similar product and offer, or create test orders across billing models. Follow the workflow through actual API requests and order read-back. A plan or prepared payload is not a completed test.

Use the existing checkout. Cloud tasks are already isolated; do not create a worktree unless the user requests one.

## Establish the requested operation

- Catalog inspection is read-only. Creating a fixture or submitting orders requires a user request for that work. Such a request authorizes the necessary synthetic product, offer, and campaign setup; do not ask for confirmation of every step.
- Use existing project decisions: Sticky stores billing subscriptions; inactive billing disables refill access only. Refill rules are independent for each SKU, with no inherited or overriding therapy rules. Billing intervals do not establish medication supply, dose, or clinical eligibility.
- For "all billing models", discover the models currently configured in Sticky. Distinguish those payment intervals from Core's proposed one-time, subscription, prepaid, and pay-per-refill workflows.
- Preserve existing brand configuration. Work on a uniquely named synthetic fixture for order tests. Live sales, real payment methods, prescription requests, pharmacy orders, refunds, and changes to existing billing models require their own user instructions.

Read [the verified API workflow](references/api-workflow.md) for exact endpoint and payload shapes. Read [the baseline](references/verified-baseline.md) for previously verified objects, order IDs, and account-specific findings. Baseline IDs are evidence, not permission to submit duplicate orders or reuse the fixture without checking it.

## Authentication and network

The WLMD account is `https://whitelabelmd.sticky.io`. Use HTTPS with HTTP Basic authentication from `STICKY_API_USERNAME` and `STICKY_API_PASSWORD`. Check binding names and presence before requesting credentials; never print their values, auth headers, or the process environment. Keep credential values out of files, commands, reports, and this skill. A saved binding can be proxy-backed; use its supported HTTPS route rather than extracting or inspecting the underlying secret.

Use `STICKY_BASE_URL` only after validating it as an HTTPS account URL without embedded credentials. Send credentials only to the account hostname authorized in environment settings. Reject redirects outside that HTTPS hostname. Keep TLS verification enabled.

If access is missing, distinguish an unset binding, a network-proxy denial, HTTP authentication failure, and a Sticky campaign permission error. A saved environment draft does not prove runtime configuration has changed. Recheck after a meaningful change. When cloud configuration tools are available, preserve existing custom network rules and secret bindings; declare missing credentials securely with the exact account destination, never in chat.

## Inspect the catalog

1. Read the relevant product and offer, then their campaign and billing models as needed.
2. Trace the relationship explicitly: **SKU → Sticky product ID → offer ID → campaign ID**, with the selected billing-model ID. A SKU can occur on several distinct product records across brand-named offers.
3. Prefer a known product ID or a narrowed offer's product list. Inspect candidate product records to confirm an exact SKU. Do not assume a product-name match proves the SKU or that the first match is unique.
4. Check pagination and report search coverage. This account accepted `per_page` values from 1 through 15; larger requests returned validation errors. Recheck limits if the API changes.
5. SKU/search filters previously returned unrelated, unfiltered results. Do not silently trust a filter or repeatedly scan the whole account before narrowing by brand or offer.
6. Report the returned base price separately from the final checkout price. Inspect configured billing intervals and offer settings rather than inferring behavior from display names.

## Prepare an isolated test fixture

1. Generate a run identifier such as `WLMD-CORE-TEST-<random suffix>` and record intent before each write in a local state file outside application source. Retain returned IDs and explicit outcomes.
2. Inspect the reference product, the current billing models, and the account's test gateway. Discover and verify gateway identity; do not assume that ID 1 is a test gateway in every account.
3. In this account, profile 1 was verified as the built-in **Dry Run Testing** provider. Check it again before attaching it to the new campaign. Do not change the mode or credentials of an existing live gateway.
4. Create a clearly named synthetic, non-shippable product based on the requested reference and a new offer containing that product and the selected models. Use the reference price or the user's requested test price; do not hardcode 449 for unrelated products.
5. Create a dedicated campaign with the new offer, dry-run gateway, compatible payment method, country, and shipping profile. Omit unused optional provider IDs: passing zero explicitly triggered validation errors. Leave fulfillment, membership, email, tax, fraud, and postback integrations disconnected for these tests.
6. Read back product, offer, campaign, and gateway settings before orders. Verify that only the intended test product and offer are selected, the product is non-shippable, and the campaign routes to the dry-run provider with no external integrations.
7. Sticky may allow creating a campaign while denying this API user subsequent access. Report the exact campaign ID for the user to enable in Sticky; continue independent work and retry access after it is granted. Do not work around the denial or automatically change credential privileges.

## Submit and verify test orders

1. Submit one synthetic order first. The verified payment path combines the built-in Dry Run Testing gateway with Sticky test card `1444444444444440`, a future expiry, and synthetic contact details. Never substitute a real card. A missing gateway failed even with the test card.
2. Before submission, record the model and status `pending`. Do not retry an uncertain write automatically. An HTTP 200 can contain a payment failure and even an allocated order ID; inspect the body and reconcile before retrying.
3. Require creation response `response_code=100`, `error_found=0`, and `test=1`. Read back only the orders from this authorized test run using `order_view`.
4. Verify `is_test_cc=1`, the expected campaign and dry-run gateway, product, offer, billing model, quantity, total, shipping, and non-shippable flag. For this dry-run path, transaction and authorization IDs were both `Not Available`.
5. For a one-time purchase, confirm it is not recurring and has no next billing date. For the cycle-based models tested here, compare the returned creation date plus the configured `days` with the stored next date. Use a different documented calculation for other model types. Do not convert date-only schedules into a user timezone or infer clinical refill dates from them.
6. After the first order passes, run the remaining selected models sequentially, reading each back before continuing. Stop the batch on an unexplained failure or unverified test status.
7. Preserve a result matrix with model ID/name, configured interval, order ID, amount/currency, test flags, recurring status/date, and pass/fail/unrun outcome. Existing verified runs do not authorize or require repeating submissions.

For hosted Stripe Elements payments, campaign/SKU checkout links and Fly deployment, use [stickyio-stripe-checkout](../stickyio-stripe-checkout/SKILL.md).

## Processor-specific tests, including Stripe Connect v2

Confirm the requested processor and version before submitting payments. This account exposes **Stripe Connect** provider 180 and **Stripe Connect v2** provider 250. A successful payment through provider 180 does not validate v2. When the user asks for Stripe Connect v2, use the [specified v2 guide](https://support.sticky.io/en/articles/12694259-stripe-connect-v2) and inspect the v2 configuration rather than reusing the older provider's test-mode toggle.

Read [Stripe Connect v2 checkout requirements](references/stripe-connect-v2.md), extracted from the article text supplied by the user. Include the required `three_d_redirect_url` and handle response 101 / the documented 3DS completion call. Stripe Link/Express Checkout uses `authorize_payment` → Stripe frontend authorization → `new_order` with `creditCardType: "stripe_link"`, `tranType: "Capture"`, and the PaymentIntent in `transactionId`. The previous raw-card Sale diagnostic did not exercise those flows. Zero-value initial transactions are unsupported. Confirm capture-on-shipment and delayed-capture behavior before interpreting pending orders.

Sticky's own test card/dry-run workflow above bypasses the real processor. For a processor sandbox test, verify sandbox routing and use that processor's documented test method. The earlier provider-180 sandbox tests returned Stripe `ch_` transaction IDs and Sticky `test=0` / `is_test_cc=0`; those flags differ from Sticky's bypass tests and must be explained accurately. Do not submit a payment to a live connection to discover whether its test settings work.

The v2 field schema inspected here had OAuth/access/refresh-token fields and a publishable key, with no `test_mode` toggle. Check field presence without displaying or extracting stored secret values. Classify a publishable key as test/live without printing it; a live publishable key does not establish an available sandbox. Profiles 147 and 254 exposed live publishable keys at inspection. A verified v2 sandbox connection is a prerequisite for a v2 test payment. Do not change the existing connection or reuse its stored tokens to manufacture a sandbox.

## Report the completed work

Lead with the number of actual approved, verified test orders. Include the product, offer, campaign, and gateway IDs and link the result matrix. Distinguish failed attempts from approved orders; an allocated ID is not proof of approval or persistence. State what was not exercised, especially future rebill execution, prepaid shipments, and pay-per-refill orchestration.

Flag configuration mismatches for the user without silently changing existing models. The baseline model named "180 days billing, 90 days shipping" actually billed on a 90-day schedule. Report current evidence rather than assuming that historical finding still applies.

Do not claim an application, clinical integration, live checkout, or production payment flow is ready because test orders passed.
