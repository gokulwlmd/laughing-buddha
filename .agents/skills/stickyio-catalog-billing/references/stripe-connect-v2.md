# Stripe Connect v2: checkout requirements

Source: the user-provided text of Sticky's [Stripe Connect V2 guide](https://support.sticky.io/en/articles/12694259-stripe-connect-v2). The pasted article was read in full. Images and the targets of its inline "here" / Stripe reference links were not included in the excerpt. Use the linked API reference for complete endpoint schemas before implementing or executing new flows; the excerpt alone does not supply them.

## Integration and profile

Stripe Connect v2 supports standard cards, Stripe Link, Apple Pay, Google Pay, and automatic/dynamic 3DS. Sticky must enable the integration in the account. Creating a profile is followed by Stripe Connect login/authorization so Sticky can send transactions on behalf of the connected Stripe account. It is an OAuth connection, not merely a pasted secret key.

Assign the profile to the relevant campaigns. Required merchant settings in the guide are Descriptor, Customer Service Number, and Global Monthly Cap. Supported currencies listed are USD, AUD, BRL, CAD, CNY, EUR, and GBP.

Capture settings change the order lifecycle:

- **Capture on shipment:** authorize initially, keep the order pending, and capture when marked shipped. Setting it to No selects the standard authorization-and-capture process.
- **Delayed capture:** authorize first, capture after the configured number of hours, and keep the order pending/out of fulfillment until capture and approval. The prose labels this field "Delayed Capture Days" but explicitly describes hours; the inspected API schema uses `delayed_capture_hours`. Confirm the actual API value and unit rather than trusting a display label.
- The documented delayed-capture behavior applies to initial and recurring orders.
- **Zero-value initial transactions are unsupported.** Use a valid nonzero amount.

Do not modify an existing profile's capture settings merely to make a test pass. Inspect and explain the current settings first.

## Standard cards and dynamic 3DS

The guide requires `three_d_redirect_url` in the `new_order` request. This is the customer's return/thank-you URL after authentication; use the actual checkout's configured return URL, not an invented localhost endpoint.

3DS is automatic and decided dynamically by the processor/bank:

1. Submit `new_order` with the required return URL and the appropriate card/payment data.
2. If authentication is unnecessary, the API returns order and transaction IDs for the normal processing outcome.
3. If authentication is required, Sticky returns response code **101** and an ACS URL.
4. The checkout must handle that response and complete the documented **3DS API call with the order ID** to finalize the sale, including the customer authentication/redirect handling.
5. After verification, the customer returns to the supplied return URL. Verify the resulting order/payment state; do not treat the initial 101 as a completed sale or submit a duplicate order to bypass authentication.

The excerpt does not provide the complete 3DS call schema or ordering of all browser/API steps; obtain those details from Sticky's linked 3DS API reference before implementation. A bank can also require 3DS on a rebill, so future recurring-payment validation must cover customer action when required, not just a stored next-charge date.

## Express Checkout / Stripe Link

This is a distinct authorization-and-capture flow. It is not the same as sending a raw card with `tranType: "Sale"`.

Configure `stripe_link` as a campaign payment type and associate it with the intended Stripe Connect v2 profile. Then:

1. Call **`authorize_payment`** with `creditCardType: "stripe_link"` and a valid email, plus the fields required by its API schema. Sticky creates a Stripe PaymentIntent with `capture_method: manual` and returns **`digitalWalletToken`**, a client secret.
2. Use that client secret in the Stripe frontend component/Express Checkout integration. Complete the applicable browser authorization and authentication steps and obtain the PaymentIntent ID (`pi_...`). Consult the linked Sticky/Stripe API documentation for exact frontend confirmation behavior.
3. Submit `new_order` with:

   ```json
   {
     "creditCardType": "stripe_link",
     "tranType": "Capture",
     "transactionId": "pi_FROM_THE_FRONTEND_AUTHORIZATION"
   }
   ```

   This is the payment-specific fragment, not a complete order payload. Include the applicable campaign, offer/product/model, patient/customer, and return-URL fields required by the API.

4. Read back the capture and order outcome. A PaymentIntent ID alone does not prove authorization, capture, or order approval.

Do not include a card number in this Stripe Link `new_order` request: it captures the prior authorization. Keep client secrets, OAuth credentials, and wallet tokens out of saved reports and logs. The pasted guide does not give the full `authorize_payment` path/schema; do not guess those fields or fabricate a client secret or PaymentIntent ID.

## Verified request format from the owner's working implementation

The owner later supplied a detailed implementation from their Lovable project. It uses `src/pages/StickyCheckout.tsx` and the Supabase function `sticky-direct-order`, with config/authorize/create actions. It creates the PaymentIntent through Sticky, confirms it in Stripe.js, and captures the same intent through Sticky. It does not require a separate Stripe secret for this path. Its original campaign 167 / offer 227 / product 21946 and $1 amount are examples from another setup; preserve the isolated fixture IDs for new work.

One concrete authorization request using this format was successfully verified on the isolated fixture: HTTP 200, response code 100, status OK, valid client secret and matching PaymentIntent ID. No card was supplied and no capture was requested.

`POST /api/v1/authorize_payment` uses the explicit customer/shipping/billing fields below plus:

```json
{
  "creditCardType": "stripe_link",
  "forceGatewayId": 254,
  "campaignId": 422,
  "productId": 54537,
  "auth_amount": "2.00",
  "ipAddress": "SERVER_OBTAINED_CUSTOMER_IP"
}
```

**Use `auth_amount` in dollars.** The earlier incomplete requests used `amount` / `productPrice` and returned generic HTTP 500; that was not proof of a gateway failure. Include `firstName`, `lastName`, normalized `email`, digits-only `phone`, `shippingAddress1`, `shippingAddress2`, `shippingCity`, `shippingState`, `shippingZip`, `shippingCountry`, `billingFirstName`, `billingLastName`, `billingAddress1`, `billingAddress2`, `billingCity`, `billingState`, `billingZip`, `billingCountry`, and `billingSameAsShipping: "YES"`. The explicit billing fields were included in the verified request even with billingSameAsShipping set.

Require response code 100 and a nonempty valid `digitalWalletToken`. Read the PaymentIntent ID from **`transactionID`**, falling back to **`transId`**, and check it matches the ID in the client secret. The request's `transactionId` spelling used for capture is different from the authorization response's `transactionID` spelling. Store only nonsecret reconciliation identifiers, not the client secret in logs or reports.

The capture body reuses customer details and adds `creditCardType: "stripe_link"`, `tranType: "Capture"`, the same intent in `transactionId`, `forceGatewayId: 254`, `campaignId: 422`, `shippingId: 2`, the real HTTPS `three_d_redirect_url`, and:

```json
{
  "offers": [
    {"offer_id": 706, "product_id": 54537, "billing_model_id": 2, "quantity": 1, "price": "2.00"}
  ],
  "creditCardNumber": "",
  "expirationDate": "",
  "CVV": ""
}
```

Empty card fields carry no card data. The owner completed the hosted browser flow, and the harness recorded captured order 505015. A later Sticky read-back returned status 6; its current settlement state has not been independently verified. See [the checkout skill](../../stickyio-stripe-checkout/SKILL.md) for the preserved evidence, generalized campaign/SKU links and deployment workflow. Keep amount, model, product and intent server-owned; do not copy the prototype's browser-selected price or mutable create details. Only `requires_capture` should proceed to capture; reconcile an already `succeeded` intent rather than capturing again. Use the gateway's matching publishable key; do not derive a connected Stripe account ID from a publishable key. The article's separate Sticky response-101 completion API remains undocumented in the supplied excerpts; hold and reconcile that response.

The Lovable document reports an earlier live $1 order 489098, but that historical result was not freshly checked here. It does not establish wallet success, recurring execution, production readiness or downstream WLMD ingestion. The isolated harness is now privately deployed on Fly.io with verified HTTPS and authenticated Sticky fixture read-back; the owner can enter their card using its private invitation. Deployment verification itself submitted no card or capture.

## Older direct wallet-token methods

The article separately documents these alternatives after configuring the frontend wallet and campaign payment types:

| Wallet | `new_order.creditCardType` | Token field |
| --- | --- | --- |
| Apple Pay | `applepay` | `apple_pay_token` |
| Google Pay | `googlepay` | `google_pay_token` |

Both support subscriptions according to the guide. Tokens must come from the configured frontend wallet output. These fields are not interchangeable with Stripe Link's `transactionId` or `digitalWalletToken`.

## What the existing tests prove

- The 13 Dry Run Testing orders validate Sticky's initial order creation and stored billing schedules, not Stripe processing.
- The two gateway-165 sandbox orders validate the older Stripe Connect provider, not v2.
- V2 diagnostic **504690** used profile **254**, a direct `visa` / `Sale` request and a published Stripe test card. Stripe returned a live-mode/test-card decline. This proves the request reached the v2 processor and returned an external decline.
- That diagnostic omitted `three_d_redirect_url` and did not exercise response 101, frontend 3DS, `authorize_payment`, Stripe Link/Express Checkout, wallet tokens, successful capture, delayed capture, or recurring customer authentication. It is not end-to-end v2 checkout validation.

Plan the next test around the specific requested payment method and its documented flow. Existing authorization to inspect/use profile 254 does not supply a real payment instrument or authorize an unspecified live charge. Preserve the prior diagnostic evidence; do not repeat a known live-mode/test-card decline just to obtain another order ID.
