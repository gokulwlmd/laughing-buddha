# Sticky member passwords after purchase

Decision, 24 October 2026: Sticky owns membership and passwords. Customers can
choose their password immediately after a verified purchase, without requesting
a membership email. The shared branded portal retains site-scoped clinical and
order records. It does not maintain a second password when Sticky mode is active.

## API and shared UI

Use the current checkout session bearer with:

- `GET /api/v1/sites/{site}/sessions/{session}/account`
- `POST /api/v1/sites/{site}/sessions/{session}/account` with `{ "password": "customer-chosen-password" }`

GET returns `set_password`, `sign_in`, or `needs_review`, plus the portal URL.
POST returns `ready`. Neither returns a provider token, temporary password,
patient record, or Sticky credential. A captured receipt with an exact published
site/order mapping is required. Failed/unconfirmed payments cannot enroll.

The shared `/portal-assets/post-checkout.js` component adds password setup above
the existing intake. This applies to every storefront already loading that
component, without a separate Lovable build. Multiple purchased items are linked
using their independent captured receipt capabilities and the same authenticated
member password. Partial success can be retried without resetting a password.
Intake remains accessible if account setup is unavailable. Returning members
receive the portal link and keep their existing Sticky password.

## Sticky provider boundary

`MEMBER_IDENTITY_PROVIDER=sticky` enables Sticky-only authentication. The live Fly
configuration selects it. Local authentication remains solely a compatibility
mode for existing offline fixtures and unconverted deployments, not a fallback
when Sticky rejects a login. Existing local sessions are rejected in Sticky mode.

The provider checks `member_view`, creates only a missing member through
`member_create`, and replaces the returned initial password with `member_update`.
It omits `event_id`, requesting no member notification. It never calls forgotten
password/reset APIs to overwrite an existing member based on a new receipt.
Existing memberships require `member_login`. Previously auto-created memberships
whose temporary password is unavailable need a separate verified recovery path;
this release does not bypass that protection or invent an initial password.

Provider creation is journaled before the write. An uncertain creation is held
for review. After an uncertain password update, the submitted password is checked
through login, with no blind update retry. Bootstrap secrets are encrypted and
removed after success. No chosen plaintext password or local password hash is
stored for Sticky-enrolled accounts. Patient IDs, order grants and intake drafts
are retained when an existing local record is connected to verified membership.

Portal sessions are bound to the site and expire no later than the Sticky session.
Sticky session validity is checked with a maximum 30-second cache. Logout clears
local access and calls Sticky logout. Separate site/order grants continue to
control visibility; a shared Sticky identity does not grant another brand's data.

Encrypted provider tokens and temporary bootstrap secrets use a private
`member-identity.key` on the existing volume. Preserve this key with database
backups. Never commit it or include it in images, logs, browser storage or URLs.
API user credentials remain only in the existing encrypted Fly secrets.

## Evidence and limits

Official contract: https://developer-prod.sticky.io/ (Members section).
The existing deployed API credentials returned the documented member-not-found
response to a synthetic read-only membership lookup. A private read of one
existing member confirmed the documented member fields without copying its data
into reports. No customer password, membership or order was changed by this check.

Offline tests cover password setup, returning members, provider uncertainty,
restart recovery, encryption, revoked sessions, password whitespace, no local
fallback, receipt scope and site isolation. Browser fixtures cover successful
setup, mismatched passwords, provider failure and continued intake on mobile and
desktop. These checks do not certify a new live member creation/password change;
the customer chooses and submits their password themselves after purchase.

## Published verification

The existing shared Fly app now runs image
`sha256:49141eafb45624363fc2d84f53090c5b81522545f60ff3b77b276e5291a7bc01`.
All 466 backend tests and four shared-component browser checks passed. Public
health and Fortify onboarding returned 200; onboarding reports `sticky`. Hosted
backend and component hashes match source. The same machine and volume remain;
a private pre-release database backup was taken. Payment-state counts and the
existing patient count were unchanged, and verification created no membership.
The shared component update needs no per-site Lovable edit or deployment.
