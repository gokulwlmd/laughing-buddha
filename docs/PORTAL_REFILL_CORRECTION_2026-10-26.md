# Portal purchase and refill correction — 26 October 2026

Two production defects hid next-supply options:

- Sticky returns an internal subscription identifier even for a one-time sale. The portal previously rendered every identifier as a subscription. Verified one-time, non-prepaid, non-recurring purchases now omit that subscription card. Stopped recurring subscriptions and prepaid delivery cycles retain their existing representation.
- Published catalogs return lowercase currency codes such as `usd`. The portal rejected these instead of normalizing them to `USD`, discarding valid purchase options. Currency normalization restores same-site public plans without loosening price, publication or ownership checks.

The care timeline also acknowledges a completed intake instead of continuing to instruct the patient to complete it. The card-update dialog now displays the capability API's actual explanation.

## Verification and release

- 38 backend tests passed against the isolated Fly release source: member portal, care claims/catalog discovery and native renewals.
- Three browser scenarios passed: paid native early renewal, locked included refill instructions, and a one-time purchase selecting either a new one-time plan or subscription. The latter also covers 390px and desktop layouts and verifies no provider order/charge calls.
- Live read-only investigation confirmed a one-time billing model and valid published options with lowercase currency. No patient identifiers, credentials, raw provider payloads or medical answers are included here.
- Deployed to the existing Fly app and volume using image `sha256:cd37c18bcc8ce1a23ecd9d7334973bbf9e0756ba7b7af0ae0812ab10ff39bd2e`. Private database backups taken before restart. Unrelated AWS/MySQL work excluded.

Live health returned 200 and the served portal JavaScript matched the release. The signed-in FortifyHP portal showed the corrected one-time plan and eight Semaglutide next-supply choices (1/3/6/12 months, one-time and subscription). No live order, refill or payment was submitted.

## Remaining work

Secure self-service Stripe Connect v2 card replacement is still unavailable. The current adapter returns an unavailable capability. Sticky's generic `order_update` token fields do not establish the token-creation and subscription-attachment contract for this gateway. A confirmed hosted/tokenized replacement flow and readback are needed; do not substitute raw card collection or a new charge.

Combined multi-product intake remains the next requested implementation. Reuse must preserve site/patient ownership, canonical question meaning, conditional branches and a complete per-order submission. Changing health information needs confirmation on a new assessment.
