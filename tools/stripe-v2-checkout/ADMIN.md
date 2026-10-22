# Owner admin

Admin URL: `https://wlmd-stripe-test-0f89b1bb.fly.dev/admin`.

The brand design/multiple-campaign update is deployed and verified. The image and test evidence are recorded in `deployment.json`.

## Sites and Checkout Templates

Start in **Checkout Templates** to create a complete therapy checkout. Choose a therapy or create one inline, add duration plans, select matching products by name, and choose payment types. The customer preview shows selected products and catalog prices. Missing products appear beside the plan; Save draft preserves unfinished work without including it in site setup or changing a published template. Shared catalog product creation and detailed billing remain under Advanced.

In **Sites → Add a site**, enter its name, logo, color and support email, then continue to the included checkouts. All enabled, valid templates are included automatically. Choose a payment setup for the first site; an approved setup can be reused for future sites with independent campaign prices. Existing branding and campaign connections remain optional settings. One review prepares the brand, campaign catalog and checkouts.

The site dashboard opens after approval. Ready to preview means the link is private. Publish opens the checkout settings for an explicit publication review; Copy public link appears afterward. Paused and Needs attention are separate states. Synthetic staging labels public checkouts as test mode and always blocks payments. Template changes require reviewed site updates; saved site customizations, independent prices, subscriptions and stable URL paths are preserved.

See [the current handoff](../../docs/PROJECT_HANDOFF.md), [decision record](../../docs/DECISIONS.md) and [local/staging setup](../../docs/COLLABORATION.md). The historical release notes below describe prior deployments; the new implementation is not automatically deployed to the live app.

## First owner setup

The app creates `/data/admin-setup-token` with mode 0600. It is separate from the checkout invitation and is excluded from the image/source. An authorized operator can retrieve the owner setup URL privately through Fly machine exec: `/admin?setup=TOKEN`. Deliver it only to the owner; do not put its token in documentation, logs, screenshots, deployment metadata or startup instructions.

The URL exchanges the token for a short-lived Secure HttpOnly setup cookie and redirects to `/admin`. The owner enters their own email and a password of at least 12 characters. The app hashes passwords with scrypt and stores only session-token hashes in SQLite. Once an owner exists, setup links open the ordinary sign-in screen and cannot grant access. Subsequent visits to `/admin` use email/password sign-in. Failed sign-ins are limited, and mutations require the owner session, matching origin and CSRF token. Admin access is separate from customer checkout access.

No real owner account/password is preconfigured by automated deployment checks. Do not create a dummy owner in the hosted production database. A password reset currently requires an authorized operator; self-service email recovery is not implemented.

## Available features

- Brands: name, generated stable identifier, multiple campaigns, logo URL, primary/background/text/button colors, three font choices, two layouts, live design preview, support details and pending custom-domain hostname. Every managed checkout inherits the approved brand design, including its payment screen and receipt.
- SKU catalog: exact stable SKU to source Sticky product mapping.
- Accessible Sticky campaign index and all 13 currently configured billing models are loaded read-only. Campaign-scoped SKU inspection shows matching product/offer/model choices and payment limitations.
- Offers: create a product record with the same SKU and separate brand/offer pricing, create its offer and attach it to the selected campaign. Advanced offer JSON is previewed explicitly.
- Managed offer price/term edits create a replacement product/offer and move the listed brand checkout choices to it after approval. Shared source prices, prior purchases and existing subscriptions retain their original records. Other brand offers are unaffected. Removing a billing model still enabled on a link is blocked until the link is adjusted.
- Checkout links: open a brand, then browse its links grouped by editable master-catalog category. The group displays its saved brand color and offers an Edit brand design shortcut. Choose enabled offer choices, public/private visibility, active/disabled state and title. Published links use `/c/{identifier}` and the selected brand/campaign/SKU. Public links require no owner login; private invitations are scoped to their specific link and revision.
- Review queue: readable before/after preview, collapsed exact Sticky operations, affected links, explicit approval, apply/read-back result, draft refresh/discard and retained created IDs after uncertain operations. Stale previews and automatic retries are blocked.
- New Sticky campaigns can copy payment, country, shipping and offer settings from an accessible campaign, or use explicit IDs. Integrations must be checked separately. Their Stripe Link mapping and API access depend on Sticky accepting and exposing the configuration. Failures/partial outcomes are held for reconciliation rather than silently repeated.

Each local or Sticky configuration change must first be previewed and approved in the panel. Admin mutation and payment locks coordinate with each other; edits affecting an open payment are blocked. Original `/checkout/{campaign}/{sku}` routes and previous payment records remain available.

## Current limits

Trial, prepaid, seasonal, series, bundle, variant and custom-schedule payment paths remain blocked where the required checkout flow is unverified. Admin inspection/configuration is not proof a customer can pay through those paths. Free and paid trials remain requested requirements; free trials need a supported card-setup and later-billing integration. No nominal charge is substituted for a free trial.

A custom-domain hostname can be saved, but is explicitly pending until DNS routing and HTTPS are provisioned and verified. Generated links currently use the working shared Fly hostname. The panel does not yet provision custom domains automatically.

Creating/editing offers is verified with a fake Sticky service in offline tests, not by unapproved writes to existing live brands. Actual Sticky changes occur only after the owner approves a preview in the admin. Missing campaign API access or rejected Stripe Link mappings require resolving the indicated Sticky configuration.

## Master setup

Open `/admin#master` for reusable SKU presets. Each master entry contains its SKU, optional existing product, fulfillment defaults, currency, preset offers, prices and configured billing models. The agreed TIRZ-1M draft is available through **Load agreed TIRZ-1M preset**: USD 449.00 per charge at 30/90/180/270/360-day intervals.

Save/approve the local master first, then open Campaigns and select an existing campaign or name a new one. Choose the brand that owns the campaign. The assignment creates or reuses managed offers, attaches missing choices and creates private checkout links. Existing brand prices, link access and enabled customer choices are retained. Already-correct assignments do not create duplicate products/offers. Campaign gateways/integrations and unrelated offers are preserved.

Per-SKU validation checks the assigned product/model mappings, price currency, schedule and shipping/tax contract. Optional quote validation calculates the Sticky total for every assigned billing choice at the entered location/shipping method. Neither validation submits a payment. A generated link is activated only when its configuration is ready; real processor processing is a separate validation step.

The master and applied revisions are shown separately. Source/model drift, retired choices used on links and partial-write holds require explicit resolution. The initial master provisioner supports standard one-time/day-based recurring presets; advanced/trial provisioning remains unverified.

See [the first master entry and workflow](../../docs/master-sku-setup.md) and [the read-only campaign 422 plan](../../docs/test-campaign-master-preview.json). No hosted owner credentials or approvals are synthesized by deployment.

## Everyday workflow

For the existing detailed workflow, open **Advanced settings → Brands → Master SKUs → Campaigns → All checkout links**. Offer pricing, source SKU mappings, diagnostics and change history remain under Advanced settings.

1. **Brands**: create a brand and preview its logo, colors, font and layout. Support details and a pending custom domain are optional. Review and save. Manage campaigns and Checkout links shortcuts select that brand in the next form.
2. **Master SKUs**: enter the SKU, display name, default price and billing options, then review and save. An existing Sticky product ID is optional. New SKU fulfillment defaults come from the reviewed template (initially product 2856); this step saves local configuration only.
3. **Campaigns**: choose the owning brand, then attach an existing campaign or create a new one from a routing template. One preview includes every enabled master SKU, its offers and private branded links. Adding another campaign preserves the brand’s existing campaigns, prices and checkout destinations. New campaigns copy only payment, country and shipping selections; other integrations require separate setup.
4. **Checkout links**: choose a brand from the directory, then browse its category groups and copy a generated link. Create additional links within that brand by choosing campaign and SKU. The campaign dropdown still lists every accessible Sticky campaign, including unattached campaigns. Unattached choices guide you to campaign setup for the selected brand. Ready master choices, title and address are generated automatically. Choose public or private and approve. Each link stores its own campaign; design comes from its brand.

Saving an approved brand design updates all its managed checkouts without changing their URLs or private invitations. Existing legacy links without an explicit campaign continue using the brand’s preserved original campaign. Offer price edits are scoped to the selected brand and campaign. Adding another campaign does not invalidate a quote on an unrelated existing link; changing that link’s design does require a fresh quote review.
Repeated assignments reuse verified objects. A master revision does not update live campaigns until its assignment is reviewed. Uncertain writes block duplicate setup attempts, including attempts using a newly recorded campaign ID. Open payments block affected configuration changes. These flows do not change medication doses, supply or refill eligibility.

Forms preserve entered data after errors. Stable identifiers are locked during edits. The mobile layout includes sign-out and the same four primary actions.

## Validation

```sh
npm --cache /workspace/.cache/npm --prefix qa ci --ignore-scripts
/workspace/.venvs/stripe-v2-checkout/bin/python qa/run.py
```

**122 backend tests and 55 Chromium browser scenarios passed**, covering desktop/mobile owner administration, approvals, stale drafts, independent pricing, public/private access and simulated payment recovery. The browser suite uses disposable state, fake Sticky responses and a Stripe.js contract stub; it makes no live charges or configuration changes. See [the case-by-case QA report](../../docs/QA_REPORT.md). Container checks verify non-root execution, restricted state permissions and persistence.

## Checkout categories and brand colors

Set **Category** on a master SKU using the dropdown. Select an existing category, **Uncategorized**, or **+ Add new category** to enter a new name. The new category is saved after review and approval. All links for that SKU are grouped under the current category in each owning brand, including existing links. Blank or legacy values appear under **Uncategorized**. Renaming a category on a SKU moves that SKU’s links only; edit other SKUs if they should move too. Category-only saves do not change billing revisions, Sticky product categories, prices, assignments or checkout URLs.

Color comes from the link’s explicit owning brand, never from another brand merely sharing its campaign. The checkout directory displays each brand’s saved color. Open the brand and use **Edit brand design** to change the right design, review, and approve. Changing TESTRO cannot recolor a link owned by the older campaign brand. The owner chose to retain those existing brand assignments. Their current palette is green (#245844); TESTRO’s is purple (#6260c3).

## Plain-language purchase setup

In Master SKUs, set **Product duration** (for example **1-month product**) independently from billing. Under **How customers can buy**, add one or more purchase options:

- **One-time purchase** with its price per payment.
- **Subscription** with its price per payment and the charge frequencies customers may choose.
- **One-time + subscription at the same price** when intentionally sharing one price; use separate options for different prices.

Purchase-option names and underlying identifiers are generated; a custom plan label is optional. Existing identifiers and labels are preserved unless edited, and existing model selections load into these controls. Exact 30/90/180/270/360-day schedules remain day-based, not calendar-month subscriptions. Checkout-link option selection and change previews use purchase terms and prices; technical integration settings remain in advanced tools.

Product duration is catalog metadata. Editing it does not change price, billed quantity, shipping, medication dose, supply eligibility or refill protocols. Duration/category-only edits retain the billing revision and existing links. Missing duration in legacy records remains unset; the inspected TIRZ-1M preset explicitly describes a one-month product. This is not a new trial/payment integration.

Purchase setup release verified on 21 October 2026: 110 backend tests and 48 browser scenarios passed, including slow billing-settings loading, separate one-time/subscription prices and preserved legacy billing mappings. The immutable image was deployed to the existing Fly machine and volume. Hosted checks confirmed the updated assets, desktop/mobile sign-in, unchanged owner/configuration records and existing brand colors. No live catalog configuration or payment was submitted.

## Pay upfront test plans

Select **Pay upfront** in a master purchase option. Enter the **total upfront price**, shipment count and one shipment interval. The first shipment counts toward the total; the plan stops after its final shipment. The backend calculates the per-shipment product price and validates Sticky's full quote. An upfront price must divide into exact cents for the chosen count.

The initial verified fixture is **WLMD-PREPAY-cfef3de8**, four 90-day cycles, $1,200 upfront, no renewal, on campaign 422. Its master is excluded from bulk assignment to new campaigns, and its managed checkout is private. Find it under the existing campaign brand → **Test plans**. The standalone master editor also has **Load prepaid test setup**.

This release supports non-shippable/non-taxable test products. Four Sticky dry-run orders proved the prepaid sequence and stop behavior; no live Stripe payment or medication shipment was performed. Physical medication release, renewal, tax/shipping and advanced prepaid variations require separate verification. Campaign 422's customer checkout still uses its existing live Stripe connection; a synthetic SKU name does not switch it into processor test mode.

Prepaid release verified on 22 October 2026 (IST): the deployed image passed 120 backend tests, 51 browser scenarios, container checks and hosted read-only checks. Five authorized prepaid setup records were imported; the owner account, existing configuration and five applied owner reviews were preserved.

## Add a prepaid plan to a product

In **Master SKUs**, use **Add prepaid plan** on a saved product, or the same button in the current product form. The shortcut adds an independent option with four deliveries every 90 days and no renewal. It leaves the upfront price blank for you to enter and preserves the SKU, existing purchase options, product duration and availability setting. Products with a prepaid option instead show **Edit prepaid plan**, which opens the existing option without adding a duplicate. Additional prepaid options can be added deliberately in the form.

The live preview shows the full plan length, the first delivery at purchase, subsequent delivery days, and completion after the final delivery. Change the count, interval, currency or price to update the preview. The total must divide into exact cents per delivery. The four-by-90-day preset covers 360 days; it is not twelve calendar months. It never infers medication quantities or refill approval from this duration.

**Review & save SKU** stores the local preset. **Campaigns → assign master SKUs** separately previews the Sticky changes and checkout choices for approval. Existing brand prices and already-enabled checkout choices remain preserved by assignment; enable a new purchase option on an existing link through its checkout editor after assignment.

Shipping/taxable products can store prepaid catalog plans with an explicit readiness notice, but campaign assignment is blocked before any Sticky write until that flow is verified. Saving a plan does not activate it on existing checkouts. Non-shippable, non-taxable test products retain the verified prepaid path. This update creates no orders or live catalog records automatically.

Prepaid product shortcut deployment verified: 122 backend tests, 55 Chromium scenarios, container persistence, matching hosted assets and desktop/mobile sign-in. Owner, catalog, reviews and checkout rows matched their pre-deployment hashes. No Sticky records or orders were created by this release.

## One-time and subscription together

In a master purchase option, choose **One-time / subscription** under Payment setup, then tick **One-time purchase**, **Subscription**, or both under How customers buy. When both are selected, that option's price applies to the one-time payment and each subscription charge. Select the subscription intervals below. Use separate purchase options for different prices.

The selected combinations survive saving, reopening and campaign assignment, and appear as separate customer checkout choices. Adding one-time purchase does not remove selected subscription intervals. Pay upfront remains a separate payment setup with its own prepaid rules. The editor waits for presets to finish loading before allowing changes, so a late response cannot overwrite newly selected options.

Combined purchase choices are deployed. All 26 affected desktop/mobile browser scenarios passed; container, hosted asset and saved-state checks passed. See [targeted QA](../../docs/COMBINED_PURCHASE_OPTIONS_QA.md). No live pricing, catalog or order changes were made.

Category dropdown is deployed and verified with 12 affected category/master browser scenarios, container checks and hosted asset/state checks. See [category QA](../../docs/CATEGORY_DROPDOWN_QA.md).


## Master Therapy Payment Test — 22 October 2026

On the existing live app, Sites → Master Therapy Payment Test has four private therapy previews and all forty requested SKU choices on campaign 422. These are live-charge payment tests with non-shippable products; each checkout displays that no medication is shipped. The owner supplies their card and submits charges. Native prepaid renewal is supported for the verified simple two/four-cycle test configuration, preserving full upfront pricing and 180/360-day renewal. The earlier historical renewal limitations above are superseded for that configuration only; physical/taxable prepaid release, discounts and conversion remain unsupported. See [the applied setup and evidence](../../docs/MASTER_THERAPY_LIVE_TESTS.md).
