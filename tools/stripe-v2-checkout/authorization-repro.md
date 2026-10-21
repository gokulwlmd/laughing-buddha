# Resolved Stripe Link authorization request

Account: `whitelabelmd.sticky.io`. Endpoint: `POST /api/v1/authorize_payment`, JSON body, existing HTTP Basic API authentication. Credentials are deliberately omitted.

Campaign 422 was read back immediately before this request: primary gateway 254; payment methods Visa and Stripe Link; Stripe Link mapped to profile 254, Stripe Connect v2 provider 250. Offer 706 contains only non-shippable product 54537, USD 2.00, one-time billing model 2. Profile 254 has capture-on-shipment and delayed capture disabled.

The corrected synthetic request below returned HTTP 200, response code 100 and status OK, with a valid client secret and matching PaymentIntent ID. No card or payment method was supplied and no capture was requested. Secret values are omitted from this record.

```json
{
  "creditCardType": "stripe_link",
  "ipAddress": "192.0.2.1",
  "productId": 54537,
  "campaignId": 422,
  "forceGatewayId": 254,
  "auth_amount": "2.00",
  "firstName": "WLMD",
  "lastName": "Payment Check",
  "email": "billing-check@example.com",
  "phone": "2025550100",
  "shippingAddress1": "1 Test Way",
  "shippingAddress2": "",
  "shippingCity": "San Francisco",
  "shippingState": "CA",
  "shippingZip": "94105",
  "shippingCountry": "US",
  "billingSameAsShipping": "YES",
  "billingFirstName": "WLMD",
  "billingLastName": "Payment Check",
  "billingAddress1": "1 Test Way",
  "billingAddress2": "",
  "billingCity": "San Francisco",
  "billingState": "CA",
  "billingZip": "94105",
  "billingCountry": "US"
}
```

The earlier incomplete request used `amount`/`productPrice` and omitted `auth_amount`, forced gateway selection and explicit billing fields. It returned HTTP 500 with `Whoops, something went wrong`. The user-supplied working Lovable implementation established the corrected format. Campaign and gateway configuration were preserved.

`digitalWalletToken` is the Stripe client secret. `transactionID`, falling back to `transId`, is the PaymentIntent ID. Verify they identify the same intent. Authorization setup does not prove browser authorization, card capture, or order approval.

The checkout uses this format. HTTPS hosting remains needed for user card entry and browser authentication. This records an already executed diagnostic; it is not a request to create another PaymentIntent or submit a capture.
