# Shared post-purchase experience — 26 October 2026

Follow-up: [multi-product recovery, release verification and remaining card-update dependency](POST_PURCHASE_QA_2026-10-26.md).

## Implemented contract

- The shared storefront component saves health answers before identity verification. Both ordinary and care-checkpoint APIs enforce SSN verification or an attached ID photo at final submission, including when a caller bypasses the UI.
- Password creation still authenticates through Sticky membership. It returns a site-bound, single-use portal handoff, valid for at most 30 minutes and never beyond the underlying session. The handoff is stored encrypted, consumed atomically, removed from the portal URL immediately, and checked against Sticky before access. Existing membership passwords are never reset by a purchase.
- Completion directs patients to the care plan, order/tracking status and refill information. Actual provider/order status is preserved; saving intake is not represented as clinician review or treatment approval.
- The shared component remains the source for all storefronts. The FortifyHP Lovable wrapper only provides branding, receipt verification and a compact receipt summary.

## Weight-loss reference

Source: https://www.coreagerx.com/onboarding/ → the publicly embedded weight-loss form. Read without submitting patient answers.

`member_portal/weight_loss_questions.json` contains 67 patient-facing questions across treatment, demographics, history, goals, conditions, preferences and review. Conditional branches are interpreted by both backend and frontend. `WEIGHT_LOSS_INTAKE_SOURCE=coreage` selects this version for newly generated initial weight-loss intakes; refill forms remain short. Saved intake/care-plan snapshots retain their existing versions and answers.

`docs/coreage-question-inventory.json` inventories all labelled source fields and identifies the questions included in this adapter. Hidden tracking/calculation fields and obsolete duplicates are not copied into patient forms. Source-specific dose-upgrade sales, prescription/body-photo/video upload widgets, state-specific disclosures, and clinical/marketing consent documents are **not connected by this adapter**. The source contains incomplete/ambiguous labels; this extraction is a demo questionnaire, not clinical approval. Clinical submission remains disconnected until the real intake API is supplied. Existing SSN/ID integration supplies the final identity step.

Stable DOB/height answers may be reused for authenticated same-site patients; other mapped answers require confirmation. Receipt capabilities do not expose account-wide previous answers.

## Optional offers

Owner UI: Sites → Post-purchase offers. Configure up to three published one-time plans and placements: thank-you, before intake, after intake. Settings default off. New subscriptions/prepaid upsells are deliberately not enabled in this version.

API: authenticated purchase session `GET /offers?placement=...` returns optional fresh quotes; `POST /offers` accepts only the quote ID and explicit confirmation. Product, price, campaign, gateway, payment source and address are derived on the backend. A source order must belong to this site and have an account grant; other sites' products/quotes cannot be purchased.

Sticky's `new_order_card_on_file` uses the original captured order's payment method with `initializeNewSubscription=1` and `step_num=2`. A durable sale record is written before calling Sticky. Timeouts, non-success/3DS responses or mismatched readback stay held; subsequent clicks do not retry a charge. A successful order is read back and connected to the same site's member account.

**External readiness gate:** `STICKY_CARD_ON_FILE_VERIFIED_GATEWAYS` must contain only gateway IDs independently verified for this flow. It is empty by default. No live gateway is approved merely by turning on admin settings. Existing Stripe v2 authorize/confirm/capture evidence does not prove its saved-card/3DS behavior. No new real payment has been made for this change. Until that contract is verified, offers are omitted and normal checkout/intake continues.

Provider reference: https://support.sticky.io/en/articles/3772905-submitting-upsells-in-sticky-io and the official Sticky API `new_order_card_on_file` definition.

## Preservation

No migration of patients, resets of passwords, provider intake submissions, medication release, renewal changes, retries of held payments or live test charges. AWS/MySQL work already in the working tree is preserved separately from the Fly release.

## Validation and release

- Clean Fly release built from committed source plus this change, excluding unrelated AWS/MySQL work.
- Full backend run: 677 tests, with four old fixture failures also reproduced on unmodified HEAD. Those cloned orders incorrectly retained another order's lineage. Fixtures now identify independent orders correctly; the 34-test affected suite passes after correction. The original run's remaining 673 checks passed.
- Shared-component browser checks: 14 passed, including desktop/mobile identity-last, partial saves, conditional questions, all seven reference sections, saved ID reuse, explicit upsell price and no repeat after an uncertain purchase.
- Lovable wrapper: 28 affected tests, build and offline desktop/mobile layout checks passed.
- Fly image: `registry.fly.io/wlmd-stripe-test-0f89b1bb@sha256:880ef19373d647b269400b2fd7655d9aabb0061472d72f56c91fbe6c47ab2663`.
- Lovable wrapper commit: `1e6ae052c1c61c99ef5ad144f12f2c72141a2de1`.
- No live purchases, identity submissions, patient password changes or clinical submissions were performed by this verification.
