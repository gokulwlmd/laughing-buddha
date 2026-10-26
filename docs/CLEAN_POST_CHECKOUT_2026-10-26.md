# Clean post-checkout and mobile intake — 2026-10-26

The receipt now starts with “Congratulations! Your order is placed,” the order number and treatment, followed immediately by password creation. Password success opens a focused intake screen. Patients can continue without setting a password and return to the receipt without losing answers.

The shared component retains captured-order checks, secure Sticky account setup, draft persistence, conditional questions, checkout-data reuse, multi-product completion, identity last, and portal handoff. An account lookup failure does not block starting the intake. No payment, medical, identity-provider or billing behavior was changed in this release.

On phones the intake spans the viewport, with 20px inner padding, large controls and a sticky Back/Continue row. Desktop forms use a narrower centered column. The Fortify completion page removes the duplicate orders sidebar and uses a compact logo/header.

## Verification

- Component browser suite: all 26 scenarios passed on the final source, including account-error recovery and 320px, 390px and 1440px layouts. Five focused regression scenarios also passed.
- Real published Fortify shell exercised at 390px and 1440px with all checkout/account/draft backend traffic intercepted using synthetic data. Both passed; mobile component width was exactly 390px with no horizontal overflow. No orders or charges were created.
- Fortify frontend agent reported 18 tests and production build passing; actual hosted shell screenshots independently verify the deployed layout.
- Screenshots under outputs/clean-intake-20261026 show synthetic order DEMO-1234, not a real patient/order.

## Deployment

Fortify Lovable project 96958a3b-eaee-48b8-a1e7-6d6853a7a467 frontend commit: 8f2fb35e8a073819f8758302851a75ec6e46292d. Published at https://fortifyhp-care.lovable.app.

Shared Fly release is built from an isolated archive of committed code plus this release's scoped UI changes. Unrelated local AWS/MySQL/Python 3.9 changes are excluded. Pre-deployment backup /data/backups/intake-steps-1793028346 contains 39 SQLite databases and two encryption keys; 22 unfinished payment records were verified unchanged. No payments were retried or cancelled.

Card replacement remains a separate provider integration task; this release does not claim to enable it.

Final shared image: registry.fly.io/wlmd-stripe-test-0f89b1bb@sha256:efde4292a8c829433f34e99ab58284b0a4a6fc04b73c974f25a463f19fa5c0a2.
