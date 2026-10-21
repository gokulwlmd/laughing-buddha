# Simple master catalog workflow

Use the four primary admin screens: **Brands → Master SKUs → Campaigns → Checkout links**.

- Create the brand and save its shared checkout design. One brand can own multiple campaigns.
- Save a master SKU in our database with name, editable checkout category, default price, currency and billing intervals. Existing Sticky product import is optional. New SKUs use reviewed fulfillment defaults copied from product 2856 unless another template is selected.
- Select any accessible existing campaign or create a named campaign using an existing campaign’s payment/country/shipping settings. One preview assigns all enabled master SKUs and creates their private checkout links. Choose the owning brand; identifiers and private links are generated automatically.
- Open Checkout links, select the owning brand, and browse the generated links by category. Choose Make public or Make private with a review, or create additional links by choosing brand, campaign and SKU. Title, address and ready master offer choices are filled automatically.
- Existing prices per brand, customer selections and disabled states survive reassignment. Repeated assignments reuse verified objects. Partial/uncertain operations hold recorded IDs and block duplicate setup.

The simplified campaign setup is `campaign_setup` in the existing review/apply API. Local master creation accepts `product_id: null` and `fulfillment_product_id` (defaults to 2856). An explicit existing product ID still requires an exact SKU match. Saved fulfillment settings are snapshotted locally; imported products are reverified during assignment. Advanced per-brand pricing and selective assignment remain available.

New campaign creation may require granting Sticky API access or correcting its Stripe Link mapping. The app verifies created product/offer/campaign records before publishing ready links. It does not copy unrelated fulfillment, email or postback integrations from the template. All configuration writes still require owner review and approval.

## First catalog entry

Owner-selected approach: build the reusable catalog together, starting with TIRZ-1M. Apply and validate on test campaign 422 first; extend to other campaigns through explicit previews and approval. This document is a draft, not an applied Sticky configuration.

## TIRZ-1M reference inspection

Read-only API verification on 21 October 2026:

| Field | Inspected value |
| --- | --- |
| Source product | 2856 |
| SKU | TIRZ-1M |
| Name | Compounded Tirzepatide - 1 month supply |
| Base price | 449.00; checkout currency must come from campaign gateway |
| Quantity limit | 1 |
| Shippable | Yes |
| Variants enabled | No |
| Source offer | 1, v4ever offer |
| Offer type | Standard; no trial/prepaid/series/seasonal flags enabled |
| Configured billing models | 3: 30 days; 4: 90 days; 5: 180 days; 6: 360 days; 7: 270 days |

The offer contains multiple products; the owner explicitly selected the five intervals below for this SKU. Other products with the same SKU exist; product 2856 is the inspected reference, not a claim of uniqueness.

## Selected first preset

The owner selected all five existing intervals. They left the initial price to implementation judgment; use **USD 449.00 per charge for every selected interval**, with brand/offer prices independently editable. The amount is not multiplied by months or days.

| Preset offer | Billing model IDs | Actual intervals | Default amount per charge |
| --- | --- | --- | --- |
| Standard subscription (`standard`) | 3, 4, 5, 7, 6 | 30, 90, 180, 270, 360 days | USD 449.00 |

The admin's **Master SKUs** page loads this agreed preset for review. Saving a master revision changes local catalog configuration; it does not silently change existing campaign offers. Assigning it to a brand/campaign has a separate preview and approval.

## First campaign workflow

1. Create/select the brand in `/admin#brands`. Open `/admin#master`, choose **Load agreed TIRZ-1M preset**, then review and approve the master entry.
2. Open **Campaigns**, select the brand and existing campaign **422**, then review and approve the full catalog assignment. The campaign is attached to that brand and private checkout links are included automatically.
3. Inspect the read-back results and choose **Copy checkout links**. Links become active only when their configuration checks pass.
4. Optional quote validation is in Master SKUs → Advanced assignment & validation tools. It calculates each option’s total for an enabled shipping method and location without submitting a payment.

For future campaigns, select their brand and use **Create a new campaign**, enter its name and choose the routing template. One review includes the full catalog and links. Existing assignments reuse recorded objects. Use Advanced settings → Offers & pricing for explicit prices per brand; master price edits preserve previously assigned brand prices.

Master revisions and applied revisions are shown separately. Changed Sticky billing schedules, prices or product shipping/tax settings require review/reconciliation. Partial/uncertain assignment writes retain object IDs, and block another assignment to that campaign until reconciled. Removed models/offers still selected on a checkout must be adjusted explicitly before applying a revision.

The first implementation provisions standard one-time/day-based recurring offers. Trial, prepaid and other complex master offer types remain outside this provisioning flow until verified.

Preserve clinical/refill rules separately from billing intervals. Do not infer medication eligibility, dose or supply duration from the chosen subscription model.

## Validation before campaign rollout

Resolve explicit Sticky mappings, preview any object creation/attachment, approve, read back, validate server quotes and customer offer choices. Test payments require verified test routing; campaign 422 currently has live Stripe Connect v2 routing, so its name alone does not make card submissions test-mode transactions. Do not change routing or create a real charge merely to run catalog checks.

A real API read-only preview verified the source product and all five configured intervals for campaign 422. See [the proposed operations](test-campaign-master-preview.json). The preview used disposable local state; saving or assigning catalog configuration uses the owner’s review/apply actions. No Sticky objects or payment orders were changed during the inspection or preview.

Checkout categories are local master-catalog labels. They do not alter Sticky fulfillment categories or billing settings. Existing links regroup automatically; no campaign reassignment is required.

## Admin purchase terms

Define the product duration separately (for example, 1-month product), then add One-time purchase and/or Subscription options with a price per payment. Subscription frequencies show their exact configured number of days. Separate options permit different one-time and recurring prices. The interface generates internal names/IDs and retains existing mappings when editing. The TIRZ-1M preset has product duration 1 month and its five original day-based charge intervals; changing the duration label does not change those schedules or medication/refill rules.
