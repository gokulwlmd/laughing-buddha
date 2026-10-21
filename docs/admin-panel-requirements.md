# WLMD checkout admin — agreed feature scope

Requirements captured from the owner on 21 October 2026. This document describes the requested admin panel. It does not imply these features are implemented or that all billing flows are currently supported by the deployed checkout.

## Purpose

An owner-operated admin panel for a stable SKU catalog, editable brand/offer pricing, configurable offers and billing options, and checkout links for multiple brands. The panel controls local checkout configuration and can update Sticky after the owner reviews and approves a change preview.

## Confirmed requirements

| Area | Agreed behavior |
| --- | --- |
| Catalog | Maintain stable SKU identifiers shared across brands. Pricing changes do not require changing the SKU. |
| Pricing | The same SKU can have different prices for each brand and offer. |
| Offers | Add and configure offers; select which offers customers can purchase for a SKU. |
| Billing | Support all configured Sticky offer types, including recurring subscriptions, prepaid plans, and free and paid trials. Discover configured models and terms rather than hardcoding a fixed list. |
| Brands and campaigns | Associate brands with existing Sticky campaigns and create new campaigns from the admin. |
| Customer choice | Customers choose among the offers the owner enables for that checkout. |
| Checkout access | Choose public or private access for each generated link. Public checkout links do not require admin authentication. |
| Branding | Configure each brand's logo, colors and support details, with an optional custom checkout domain. |
| Administration | One owner initially, using email and password. Staff roles and brand-restricted staff accounts are outside the initial scope. |
| Sticky changes | Preview proposed changes and their effects, then explicitly apply them with the owner's approval. |

## Catalog and offer relationships

A stable SKU is a catalog identity, not a guarantee of one Sticky product record. Existing Sticky data can contain multiple product IDs for the same SKU. Preserve explicit mappings between SKU, brand, Sticky product, offer, campaign and billing model.

Represent brand/offer pricing independently. A price edit for one brand or offer must not silently change another brand's price. Before choosing whether to update an existing Sticky object or create a separate object, verify which API pricing mechanism preserves that independence. Do not assume a campaign-specific price field exists, silently modify a shared product base price, or silently copy records without showing the proposed operation in the preview.

A customer-facing offer needs an unambiguous product/model mapping, price, quantity rules and relevant billing terms. Show required trial, prepaid-cycle, bundle, variant or schedule selections when the configured offer needs them. A model's name alone is not authoritative billing behavior.

## Suggested screen structure

This is an implementation organization for the agreed features, not an additional owner-selected scope.

1. **Brands:** brand identity, branding/support settings, campaign mappings and optional custom-domain setup/status.
2. **SKU catalog:** stable SKU identifiers and their explicit brand/product mappings.
3. **Offers and pricing:** brand/SKU price, configured billing model and its terms, including trial/prepaid configuration; enabled or disabled state for checkout selection.
4. **Checkout links:** campaign/SKU mapping, offers enabled for customer selection, public/private access, brand appearance, generated URL and preview.
5. **Review changes:** before/after details, affected Sticky objects and campaigns, local checkout effects, explicit approval and apply result.
6. **Account settings:** owner email/password management.

## Master catalog and campaign provisioning

Owner clarification on 21 October 2026: maintain one master setup of every required SKU, including its correct offers and billing models. Apply that setup to campaigns and verify that their customer checkouts work. Prove this workflow on the existing test campaign first. Future campaigns should receive the preset master setup rather than requiring the owner to rebuild each SKU and offer manually.

The master is the reusable SKU/offer/billing configuration. Campaign assignments retain explicit mappings to Sticky product, offer and billing-model IDs, so duplicate SKU records remain distinguishable. Existing requirements for independent brand/offer pricing remain in force; applying a master must show its proposed prices and any brand-specific differences without silently overwriting them.

Campaign payment routing, gateway credentials, countries, shipping, tax and fulfillment integrations need their own verified campaign settings. A complete master catalog alone does not prove a campaign is checkout-ready. Unsupported offer flows remain visibly blocked until implemented and tested.

### Revised core workflow

1. Define or import the master SKU setup and verify the actual offer terms and billing-model settings.
2. Choose the test campaign (422 is the current test fixture, subject to confirmation if a different campaign is intended).
3. Preview the complete assignment: already-correct entries, missing entries, differences, proposed Sticky writes and checkout mappings. Preserve unrelated existing campaign configuration.
4. Approve and apply the assignment, recording each resulting ID and read-back outcome. Re-applying the same setup must not create duplicate products/offers or repeat uncertain writes.
5. Validate every assigned SKU/offer/model combination: campaign attachment, configured terms, server quote, payment eligibility and the correct customer-facing checkout choices. Actual payment tests require verified test routing; no automatic real-card charges.
6. Fix failures and repeat the affected checks until the supported catalog works on the test campaign. Keep unsupported payment types clearly identified rather than marking the whole campaign ready.
7. Apply the verified master to approved existing campaigns. For new campaigns, choose campaign/brand settings and apply the preset master in the same provisioning workflow.
8. Generate or update approved checkout links, retaining each link's public/private setting and customer offer choices.

Show the applied master revision and per-SKU validation outcomes for each campaign. Later master changes should produce a reviewable difference before updating existing campaigns; retain prior purchase/subscription records and independent brand pricing. This revision/difference behavior is an implementation approach for the existing preview-and-approval requirement, not permission for unattended account-wide writes.

The owner chose to build the master together, starting with TIRZ-1M. The owner selected all five existing intervals (30/90/180/270/360 days) and left the first price to implementation judgment. The draft uses USD 449.00 per charge at each interval, with independent brand/offer prices. See master-sku-setup.md for the selected first preset. No live master rollout has been performed.

Keep shared-domain campaign/SKU links available when no custom domain is configured. Verify domain routing and HTTPS before showing a custom domain as ready. Do not publish DNS instructions as proof that routing is already working.

## Approval and payment boundaries

- Distinguish local-only changes from changes sent to Sticky in the preview. Include shared-object impact and identify creation versus modification.
- Apply only the approved change set. If the underlying configuration changes after preview, refresh the preview before applying it.
- Show actual apply/read-back outcomes. Do not imply multiple Sticky API changes are one atomic transaction; reconcile uncertain or partial writes before retrying them.
- Keep admin authentication separate from public customer checkout access. Private links need scoped access; making one link public must not expose the admin or other private links.
- Continue to calculate and validate totals on the server. Customer offer selection cannot authorize an arbitrary amount, gateway, product or PaymentIntent.
- Keep each purchase's state and receipt separate. Reusable links can start a new purchase after completion; unresolved attempts remain protected against replacement or duplicate capture.
- Recurring and trial terms must be visible before payment consent. Billing intervals do not establish medication supply or clinical eligibility.
- The requested first version centers on catalog and checkout management. Refund tools, subscription operations, financial reporting and staff administration have not been selected as initial features.

## Free trials and other integration work

Free trials are explicitly required. The existing Sticky Stripe Connect v2 payment path does not support a zero-dollar initial transaction. Verify a supported card-setup/tokenization and later-billing path, including how Sticky owns the subscription, before enabling a free-trial offer for customers. A nominal charge is not an approved substitute for a free trial. If additional processor credentials or account configuration are necessary, identify the exact requirement after API research.

The current deployed checkout supports standard one-time and day-based recurring offers. It blocks unsupported complex selections, delayed capture and the separate Sticky response-101 completion flow. Supporting all configured offer types requires additional implementation and verification; listing an offer or saving its configuration does not prove it can be purchased successfully.

Determine each configured offer type's required API fields and allowed combinations, and verify its initial total, schedule, fulfillment implications and return/challenge behavior. Preserve existing campaign routing and use the campaign's configured Stripe Connect v2 mapping rather than forcing the original test gateway onto every brand.

## Acceptance criteria for implementation

- One stable SKU can be offered by two brands at different prices; editing one does not alter the other's configured price.
- The owner can add an offer and enable a chosen subset of offers for customer selection.
- Both mapping an existing campaign and creating a new campaign have a preview, approval and verified outcome.
- A public link works without an owner sign-in; a private link enforces its configured access and does not grant admin access.
- Brand logo, colors and support details appear on the correct checkout. Custom-domain readiness requires working routing and HTTPS.
- Owner email/password sign-in protects admin pages and mutations; payment API credentials remain server-side and are never displayed in the UI.
- Sticky writes require the approved preview, and stale/partial/uncertain writes are reported accurately.
- Each supported offer type has meaningful validation for its actual billing behavior, including free and paid trials. Never advertise an unverified payment path as enabled.
- A completed checkout can start a separate purchase, preserve the prior receipt and reject duplicate capture or stale-tab requests.

## Existing implementation references

- [Checkout implementation and limitations](../tools/stripe-v2-checkout/README.md)
- [Checkout and Fly workflow skill](../.agents/skills/stickyio-stripe-checkout/SKILL.md)
- [Sticky catalog and billing skill](../.agents/skills/stickyio-catalog-billing/SKILL.md)

Retain the existing hosted app, secrets and payment records during implementation. This requirements document does not authorize an automated real-card charge, refund or unreviewed change to an existing brand's Sticky configuration.
