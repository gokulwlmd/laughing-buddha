# Verified Sticky API workflow

These shapes were exercised against the WLMD Sticky account. Use environment-backed Basic authentication, HTTPS, and the account's authorized hostname. Do not embed credential values in examples or store complete production patient/order responses in the repository.

## Read operations

| Operation | Method and path | Request |
| --- | --- | --- |
| Product detail | `GET /api/v2/products/{product_id}` | None |
| Products | `GET /api/v2/products?page=1&per_page=15` | None |
| Offer detail | `GET /api/v2/offers/{offer_id}` | None |
| Offers | `GET /api/v2/offers?page=1&per_page=15` | None |
| Billing models | `GET /api/v2/billing_models` | None |
| Billing-model detail | `GET /api/v2/billing_models/{model_id}` | None |
| Campaign detail | `GET /api/v2/campaigns/{campaign_id}` | None |
| Active campaign index | `POST /api/v1/campaign_find_active` | `{}` |
| Gateway profile identity | `GET /api/v2/providers/payment/profiles/{profile_id}` | None |
| Shipping profiles | `GET /api/v2/shipping` | None |
| Campaign channels | `GET /api/v2/campaigns/channels` | None |
| Supported payment methods | `GET /api/v2/campaigns/payment_methods` | None |
| Order read-back | `POST /api/v1/order_view` | `{"order_id":["CREATED_ORDER_ID"]}` |

Successful v2 reads generally return `{"status":"SUCCESS","data":...}`. Lists include pagination metadata. The v1 active campaign index returned `response_code=100` and a `campaigns` dictionary keyed by campaign ID, each with `campaign_id` and `campaign_name`.

`order_view` returned a flat order object for a single valid ID in this run; support a `data` object keyed by order ID if returned. Read `response_code` before using either shape. Response 350 did not establish that the earlier failed order existed; do not interpret an empty/error response as a successfully read order.

A campaign or gateway response can include provider credential fields. Select only IDs, aliases, provider identity, and test-mode status for inspection. Never dump the complete gateway object, account fields, or authentication data.

## Create the synthetic product

`POST /api/v2/products`:

```json
{
  "name": "RUN_ID - TIRZ-1M synthetic billing test",
  "sku": "RUN_ID-TIRZ-1M",
  "category_id": 10,
  "description": "Synthetic billing fixture. No patient or medication fulfillment.",
  "price": 449.00,
  "cost_of_goods": 0,
  "restocking_fee": 0,
  "max_quantity": 1,
  "is_shippable": 0,
  "is_taxable": 0,
  "auto_create_variants": 0,
  "attributes": []
}
```

Replace run ID, reference SKU, category, and price with current inspected values. Save the returned `data.id`. Read the product back to verify the server applied the non-shippable flag.

## Create the offer

`POST /api/v2/offers` (substitute the real numeric IDs):

```json
{
  "name": "RUN_ID - selected billing models",
  "type_id": 1,
  "products": [{"id": 54536}],
  "billing_models": [{"id": 2}, {"id": 3}],
  "recurring": {"cycle_type_id": 1, "terminating_cycle_type_id": 2},
  "is_trial": 0
}
```

Populate `billing_models` from the current discovered selection; this two-model example is abbreviated. Save the returned ID and verify the product/model associations. `type_id=1` was a Standard offer; `cycle_type_id=1` was Self Recurring. Do not apply these settings to an unrelated prepaid/custom-recurring test without inspecting that offer type.

## Create and verify the campaign

`POST /api/v2/campaigns`:

```json
{
  "name": "RUN_ID - isolated API test campaign",
  "description": "Synthetic billing tests only. No fulfillment or notifications.",
  "channel_id": 1,
  "gateway_id": 1,
  "payment_methods": ["visa"],
  "offers": [705],
  "countries": [223],
  "shipping_profiles": [2],
  "return_profiles": [],
  "coupon_profiles": [],
  "postback_profiles": [],
  "is_prepaid_blocked": 0
}
```

Use the new offer ID. Verify gateway 1's Dry Run Testing provider identity first. In this account country 223 was US and shipping profile 2 was Free Shipping. Inspect actual settings instead of assuming these IDs in another account.

The exercised creation omitted a gateway initially, then successfully attached the verified dry-run gateway with `PUT /api/v2/campaigns/{new_campaign_id}`, body `{"gateway_id":1}`. All other fixture settings were read back. Creating with the gateway already supplied is the intended next-run setup, but that combined creation payload was not separately exercised in the baseline.

Omit unused optional integration/provider IDs. Explicit zeros were rejected with "must be at least 1". Omitted providers returned zero/disconnected. Verify this after creation. If campaign read-back returns HTTP 422 and "Unauthorized to access campaign", have the user grant the API user campaign access; do not proceed by guessing or broadening credentials yourself.

## Create one test order per model

`POST /api/v1/new_order` (IDs below identify the baseline, not a request to repeat it):

```json
{
  "firstName": "WLMD",
  "lastName": "SyntheticTest",
  "shippingAddress1": "1 Synthetic Test Way",
  "shippingCity": "San Francisco",
  "shippingState": "CA",
  "shippingZip": "94105",
  "shippingCountry": "US",
  "phone": "2025550100",
  "email": "RUN_ID-model-MODEL_ID@example.invalid",
  "creditCardType": "visa",
  "creditCardNumber": "1444444444444440",
  "expirationDate": "1230",
  "CVV": "123",
  "tranType": "Sale",
  "ipAddress": "192.0.2.1",
  "campaignId": 422,
  "shippingId": 2,
  "billingSameAsShipping": "YES",
  "offers": [{
    "offer_id": 705,
    "product_id": 54536,
    "billing_model_id": 3,
    "quantity": 1
  }],
  "notes": "RUN_ID synthetic billing-model test; no medication fulfillment."
}
```

Use a future expiry at execution time. The card and CVV above are synthetic test data. Use the new fixture IDs and a unique run/model email. Do not submit on a gateway whose test identity has not been verified.

Creation succeeded with `response_code="100"`, `error_found="0"`, `test="1"`, and `resp_msg="Approved"`. An earlier attempt without a gateway returned HTTP 200, `response_code=10800`, `error_found="1"`, an allocated `order_id`, and "Cannot process order". This demonstrates why HTTP status or an ID alone is insufficient.

Read back each approved order and check:

- `response_code=100`, `is_test_cc=1`, correct `campaign_id` and `gateway_id`.
- Exactly the intended product, offer and `billing_model.id`, quantity and `is_shippable=0` in `products`.
- Expected `order_total`, shipping, and currency from the verified gateway profile. Use decimal arithmetic.
- `transaction_id` and `auth_id` both `Not Available` for this dry-run path.
- One-time model: `is_recurring=0`, `recurring_date="0000-00-00"`.
- Tested cycle models: `is_recurring=1`, next date equals the returned order's creation date plus configured `days`. The baseline returned account timestamps in `America/New_York`; date-only schedules must be preserved as returned.

These are initial-order and stored-schedule checks. They do not prove a future rebill, pharmacy shipment, clinical approval, prepaid release, or patient-triggered refill has executed.

## References

- Official v1 API documentation: <https://developer-prod.sticky.io>.
- Official support: <https://support.sticky.io>.
- Public v1 payload example consulted: <https://github.com/webforcehq/stickyio> (`tests/OrderTest.php`).
- Test behavior and the baseline were verified directly against Sticky responses. Official documentation domains were blocked at the time; saved network additions did not establish live access. Research current official docs when available and use current account evidence for configuration.
