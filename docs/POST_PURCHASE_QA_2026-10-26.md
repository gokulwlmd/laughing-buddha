# Shared post-purchase verification and recovery

The owner approved finishing the shared post-purchase experience and checking portal subscription, address, card and refill management. This continues the [post-purchase contract](POST_PURCHASE_EXPERIENCE_2026-10-26.md).

## Changes

- Keep each product's authoritative intake status independently of ancillary order-status reads. Failed refreshes must not erase a successful submission or send customers through completed products again.
- Track successful account linking per verified receipt. After a partial failure, retry only remaining receipts using the same password; never overwrite an existing Sticky password.
- Use automatic portal entry only after every receipt is linked and the single-use handoff is valid. Otherwise retain invitations for every purchased order and use portal sign-in. Validate the destination against the configured site.
- Cap handoff expiration at the earlier of 30 minutes and Sticky session expiration. Passwords and handoff tokens stay out of persistent browser storage.
- Update older portal tests to identity-last submission and the current “See my next steps” button. Health answers are saved before SSN verification or ID upload.

The flow remains: purchase confirmation → password setup and saved health intake → identity at final submission → care-plan, tracking and refill next steps. Existing members keep their password and sign in in the separate portal. Shared APIs/component serve all connected sites; no per-site Lovable edit is needed.

## Validation and release

- Isolated release from committed source; unrelated AWS/MySQL working-tree changes excluded.
- 127 backend checks passed: membership, site/order isolation, handoff expiry/replay/revocation, receipt intake, identity, subscription adapters, early renewal and refill rules.
- 18 shared-component browser scenarios passed, including four new multi-product recovery cases. A missing `Bearer` prefix in the new test fixture was corrected before those four cases passed.
- 31 portal browser scenarios passed across the original run and six corrected reruns. Older tests expected identity first and the previous return-button label. Coverage includes pause/resume, current/future address edits, monthly paid renewal, quarterly included claims, per-SKU no-check-in rules, saved drafts, tracking, keyboard focus and mobile layout.
- Provider writes used isolated fake adapters. No live patient, payment, order, renewal, refill or identity submission was made for QA; these tests do not certify a fresh live provider transaction.
- Private database backups were created on the encrypted volume. The same Fly machine, volume, identity keys and credentials were retained.
- Published image: `registry.fly.io/wlmd-stripe-test-0f89b1bb@sha256:fcff24d7a18249d55daad248bf7ef9638f14db3e1a171b418d0b2f719380e6e4`.
- Public health and FortifyHP portal returned 200; the served component matched the release. Hosted source confirmed the expiry cap. Aggregate patient and captured/unfinished-payment counts were unchanged; payment readiness stayed enabled.

## Remaining dependency: secure card replacement

The card-update action still reports that secure replacement is not connected. Do not describe it as functional or show a card form that cannot update the subscription.

Reviewed Sticky's [Stripe Connect v2 guide](https://support.sticky.io/en/articles/12694259-stripe-connect-v2), [v1 API reference](https://developer-prod.sticky.io/) (`order_update`) and [v2 reference](https://developer-v2.sticky.io/) (`tokenize_payment`). The v1 reference lists `payment_token` and `wallet_token`, but does not specify how a Stripe Connect v2 replacement token is created and attached to an existing Stripe Link subscription. The documented v2 tokenization flow accepts card data and describes a new-order use case. This does not establish that a generic token or SetupIntent updates subsequent renewals.

Required from Sticky: the supported hosted/tokenized replacement flow for a Stripe Connect v2 `stripe_link` order, client-token creation without a payment, exact update payload, subscription scope and readback proving replacement. Do not substitute an authorization/new order or collect raw card data on this backend. No support message was sent.

Clinical delivery/messaging and saved-card upsell verification remain separate previously documented dependencies; this release does not enable them.
