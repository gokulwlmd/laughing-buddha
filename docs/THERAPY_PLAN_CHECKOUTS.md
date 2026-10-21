# Therapy plan checkouts

The catalog now groups master SKUs under **Therapy → Treatment**, with product duration independent of billing frequency. A brand can publish a combined checkout where customers see Tirzepatide and Semaglutide, select a configured duration, and choose one-time, subscription or an otherwise supported prepaid option.

## Owner workflow

1. Open **Therapies → Start Weight Loss setup**. This fills a draft containing Tirzepatide and Semaglutide. Review and approve it.
2. In **Master SKUs**, assign each product to its therapy and treatment and set its product duration. Configure the actual approved prices and purchase options. Therapy grouping does not establish dose, clinical eligibility, fulfillment quantity or refill policy.
3. Assign the master products to the brand's campaign using **Campaigns**. Existing brand prices remain separate.
4. Open **Checkout links → brand → New plan checkout**. Select its campaign and therapy, load available plans, and enable the purchase options customers may choose. Choose public or private access, review, and approve.
5. Copy the combined link. Customers choose a treatment, duration and payment option before the existing secure checkout quotes the final amount.

The eight proposed TIRZ/SEMA 1/3/6/12-month products are not automatically seeded or priced. Only real configured campaign choices can be published. Unavailable treatments stay visible with an availability message. Listed prices are not final totals: shipping, taxes and applicable billing adjustments are calculated by Sticky at checkout. Unsupported trials and complex billing configurations remain blocked by the existing payment capability checks.

## Implementation and boundaries

- `plans.py` stores `therapy` and `plan_checkout` records in the existing configuration table. No schema migration or existing data rewrite is needed.
- Plan links use `/plans/{id}`. Private invitations exchange a revision-bound token for an HttpOnly cookie and remove the token from the address bar.
- Each selected SKU has an internal private managed child link. Children are hidden from the ordinary standalone checkout list. Their purchase choices are allowlisted and checked against current campaign data.
- `/plans/{id}/choose` validates access, SKU membership and the selected option, then grants access only to that child. It does not authorize or capture payment. The existing quote/authorization/capture state machine handles payment and duplicate protection.
- Editing a plan rotates invitations and child access. Disabling the parent or therapy also blocks child access. Removed members are disabled. Existing pending payments block affected configuration changes.
- Brand design is read dynamically. Managed price replacement updates the selected child option mappings. Plan editors load those current mappings.
- Therapy/treatment/duration-only master edits retain the billing revision. They cannot bypass an open child payment. Used treatments cannot be removed before reassignment.
- New configuration kinds participate in stale-preview detection. Older draft approvals must be refreshed after this release.
- Owner authentication, CSRF, server prices and clinical/refill separation remain in effect. No live treatment recommendation, prescription approval or new Sticky order is implied by browsing a plan.

## Verification

`test_plans.py` covers local-only publication, public/private access, isolated child grants, invalid membership, exact SKU/model payment handoff and idempotent capture, invitation rotation, removal/disable behavior, pending payment guards, metadata revisions, stale previews and price replacement.

`qa/therapy.spec.cjs` creates both treatments through the admin UI, assigns fixture products to a campaign, publishes public/private plan links, checks mobile layout and editing, and completes one synthetic one-time payment. The subscription path verifies the selected recurring model reaches checkout. Fake Sticky and Stripe services are used; no real payment or production catalog write is performed by these tests.

Full regression result: **133 backend tests and 61 Chromium browser scenarios passed**. The container smoke test also confirmed startup, non-root execution, restricted state permissions, absence of runtime credentials in the image, and persistence across restart.

Hosted verification: the new assets match the tested source; health and admin return 200; admin data and plan configuration endpoints require owner authentication; test hooks are absent. Desktop/mobile sign-in checks pass. The running machine uses the recorded immutable image and existing volume. Before/after hashes match for owner, configuration, reviews, checkout attempts and purchase-successor records. No live catalog or payment writes were made.
