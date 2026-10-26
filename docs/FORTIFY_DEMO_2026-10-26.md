# Fortify demo readiness — 26 October 2026

## Demo entry points

- Storefront: https://fortifyhp-care.lovable.app/available-products
- Patient portal: https://wlmd-stripe-test-0f89b1bb.fly.dev/portal/fortifyhp
- Backend remains on the shared Fly app; this release does not migrate AWS or modify its database.

## Suggested demonstration

1. Open Available products. Weight loss includes Semaglutide and Tirzepatide; ED is one therapy with medication choices inside its product page.
2. Select medication, duration and one-time/subscription. Confirm the total and renewal terms, then add to cart.
3. Complete the two-step checkout. The existing private Fortify 99% test coupon produced a $1.99 quote on the $199 one-time Semaglutide plan during this audit. It is a real discount on a live gateway, not a simulated payment. Only the presenter should enter a card and submit payment.
4. After a successful purchase, demonstrate the shared API-driven intake and account flow. A new member can set their Sticky password; existing members keep their password. Intake drafts can also be continued from the member portal. Identity is the final intake requirement, not the first question.
5. In the portal, show Orders & plans, the care timeline, saved intake, Refills and Account settings. Patient-specific clinical and shipment statuses must reflect actual provider data.
6. A newly purchased monthly plan is not immediately eligible for an upgrade. Show its disabled action and opening date. Do not change live order dates or fabricate refill eligibility just to demonstrate an enabled button.

## Changes in this release

- Next-plan checkout opens inside the authenticated patient portal, with a large Stripe Payment Element and no external checkout redirect in the normal flow.
- The backend requires zero remaining included refills and opens plan changes 20 days before the paid supply ends; eligibility remains open afterward. One-time plans use the same window.
- Monthly supply opens on day 10. For 180/360-day prepaid plans the final next-plan window opens on day 160/340, after included refills have been claimed. Included refill claims retain their separate shipment-specific windows and SKU check-in requirements.
- The selected medication, duration and purchase type are tied to the exact published plan. Server-side ownership, schedule and consent checks apply again before payment.
- A new captured order is attached to the signed-in account. Only then are future renewals on the old subscription stopped. Uncertain completion or subscription changes stay recorded for review and cannot automatically charge or stop again.
- Delivery-address updates retain the existing provider integration. A regression found during the release audit was corrected before deployment.
- The Lovable storefront header now switches to its compact menu below 1280px rather than splitting navigation words. Helper text correctly describes on-site intake after purchase and continuation in the member portal.

## Verification and limits

Live read/quote verification covered the public catalog, product selection, two-step cart, an ordinary quote, the 99% coupon, and the authenticated portal's existing order/intake display. Only synthetic contact details were used for quote calculation. The added QA cart item was removed. No new live card authorization, charge, subscription change, identity upload or intake submission was made during this audit.

Backend and browser tests exercise provider failures, order isolation, refill windows, replacement sequencing, exact plan selection, autosave, post-purchase intake, address updates and mobile checkout. They use offline provider fixtures; they do not certify a fresh live payment or live subscription replacement.

Lovable reported 62 targeted tests, a successful build and menu/overflow checks at 320, 390, 768, 1024, 1152, 1280 and 1440px. The published compact menu and catalog were independently checked in the browser.

### Demo limitations to state plainly

- Secure saved-card replacement is not connected. Its current action directs the patient to support. A verified Sticky Stripe v2 payment-method replacement contract is still required; the ordinary purchase form is not evidence that card replacement works.
- Live clinician messaging and medical-team workflow depend on the external integrations. Do not present a saved questionnaire as a clinician-reviewed or fulfilled order.
- The new inline upgrade checkout and stopping the previous subscription are verified with offline tests, not a new live charge during this audit.
- Old unresolved payment attempts are retained. They must not be retried as part of the demo.

## API handoff

All endpoints require the existing site-bound patient session:

- `GET /api/v1/sites/{site}/portal/orders/{order}/upgrade`: eligibility, opening/end dates, remaining included refills and any existing checkout.
- `POST` on the same path with `{"plan_id":"..."}`: start or resume the exact chosen plan.
- `GET /api/v1/sites/{site}/portal/upgrades/{id}/configuration` and `/status`.
- `POST .../{id}/quote`, `/payment`, `/complete`, `/resume`, `/abandon`.

These wrap the existing site checkout APIs. Provider credentials and the internal checkout bearer remain server-side; the bearer is encrypted with the existing private identity key. An abandoned checkout is allowed only before payment starts. Keep the journal and encryption keys with backups. This implementation follows the current single-machine/single-worker SQLite deployment contract.

## Verified release

- Backend: **725 tests passed**. Portal + shared post-checkout browser suite: **58 passed**, zero failures. Additional viewport-position checks passed at 1440, 390 and 320px (three checks).
- Deployed image: `registry.fly.io/wlmd-stripe-test-0f89b1bb@sha256:7cd13c7a951149ea9001d596f77dfa83952f4892fcf313b8ec0d29eef20649bc`.
- Hosted health: 200. Anonymous patient and upgrade APIs: 401. Three frontend asset hashes and four affected backend module hashes match the tested release.
- Checkout status counts and patient count were unchanged across deployment; no upgrade orders were created. Database integrity check returned `ok`.
- The first startup hit a full disk after the backup. The existing encrypted volume was expanded from 1 GB to 3 GB and the same machine restarted. This adds hosting storage cost. Verification found approximately 1,930 MiB free. No records or backups were deleted.
- The pre-release private backup includes 38 databases and two encryption keys; all backup database integrity checks passed. Do not download or commit these private files into this repository.
- The signed-in portal's order/intake view was inspected before release. After release, browser sessions were signed out; the live sign-in screen was verified, but authenticated refill eligibility was not re-exercised on a real account. The user needs to sign in before the demo.
- Storefront publication was confirmed by Lovable and then checked at its public URL. Public screenshot: [published catalog](images/fortify-demo-catalog-20261026.png).

## Required capacity check for subsequent deployments

Before making an on-volume backup, check filesystem free space and the estimated backup size. Require at least that size plus 256 MiB working headroom (more for larger databases/WALs). Check space again after the backup and before restarting. Do not rely on a successful backup as evidence that enough space remains for SQLite migrations. Do not remove historical backups automatically to make a release fit. Establish a reviewed retention/off-volume backup policy as separate operations work.

The current shared app remains a single machine and single Uvicorn worker. A successful local test run does not replace hosted startup, source-hash, integrity and capacity verification.
