# Patient portal loading — 26 October 2026

The portal waited for `/portal/store` alongside orders, refill history and notifications before leaving its full-page loading state. That catalog resolves published therapy pricing against Sticky; the expanded FortifyHP catalog also rendered hundreds of product cards. This made optional shopping block access to existing care.

## Change

- Login and ordinary order refresh no longer request or wait for the store catalog.
- Refills loads next-supply choices using the existing `therapy_id` filter, only for the patient's displayed therapies. Pricing loads independently of navigation and patient forms.
- The complete catalog is available through **Browse treatment plans**, with twelve cards initially and **Show more treatments**.
- Pricing failures/timeouts offer a local retry. They do not block care. Concurrent duplicate catalog requests are suppressed and successful scope reads are reused for 60 seconds; checkout still verifies actual prices.
- Late responses cannot cross a site/session boundary or repopulate a signed-out session. Background catalog completion does not replace an intake, message editor or open dialog.
- No billing, identity verification, order/refill authorization or data schema changes. Unrelated AWS/MySQL changes excluded from Fly release.

## Verification

Browser regressions cover delayed catalog requests while navigating/editing, no catalog fetch at login, therapy-scoped refill reads, retry and progressive catalog rendering, logout while a catalog read is outstanding, and existing portal functions. Tests use isolated offline provider fixtures and do not submit live financial or clinical operations.

The speed release is live as image `sha256:b4991bb040e197dfa1b5afdf5f2be01f68a87f393dfe60670c346b469ad8719d`. Health passed, served JavaScript matched, and aggregate checkout/patient counts stayed unchanged. All 35 browser scenarios passed (34 in the full run and the corrected existing card-copy assertion in a targeted rerun).

Live browser observation: signed-in reload to visible dashboard took 6.24 seconds including automation overhead; opening Refills took 0.324 seconds. Published next-supply choices loaded independently. This is one observed signed-in reload, not a benchmark of credential authentication or all networks. Provider pricing latency remains separate.
