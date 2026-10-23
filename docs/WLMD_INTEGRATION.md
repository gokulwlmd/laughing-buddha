# WLMD integration contract

Owner direction, 24 October 2026: WLMD will supply identity verification,
medical intake, order stages and later clinical services. Sticky remains the
membership and commerce provider. This is one shared application; configure
each site's WLMD tenant ID separately from its Sticky campaign ID.

## Current implementation status

Site setup accepts `wlmd_site_id` and shows a corresponding field in the site
editor. Existing checkout edits preserve the mapping when older clients omit
it. An existing nonempty mapping cannot be reassigned through ordinary checkout
setup, because doing so could associate patient information with another tenant.
Existing sites remain compatible without a mapping. Missing mappings must be
resolved before activating WLMD services; never infer one from a Sticky campaign.

The application's existing `member_verified_facts` table and `AnswerProfile`
adapter already support trusted ID and SSN verification assertions scoped to a
site and patient. They do not currently call WLMD. Their status comes from a
trusted backend adapter, never from patient answer updates. No live identity
gate or WLMD credential transport is enabled by this change. The production
Fly secret-name inventory contained only Sticky credentials when checked.

## Owner-supplied endpoint

`POST /v1/site/{site_id}/identity-check/{order_id}`

Known body fields:

- `which`: `crosscheck`, `ssn`, or `id-image`.
- `ssn`: exactly four decimal digits when `which` is `ssn`.
- `user`: present in the provider implementation; meaning is unconfirmed.
- `debug`: present in the provider implementation; never enable for patient traffic.

The supplied code does not define the base URL, credential transport, success
status values, pending/failed outcomes, expiry, response reference, user mapping,
or ID-image transport. Do not guess these, treat HTTP 200 as identity success,
or send real patient data to a guessed endpoint.

## Agreed intake behavior to connect after contract confirmation

1. Resolve the site's WLMD ID on the backend. Authenticate the patient or the
   existing verified post-purchase receipt and derive the owned Sticky order;
   never accept an arbitrary customer/order association from the frontend.
2. Before opening initial or refill intake, check the patient's stored identity
   result for this site. Reuse a valid trusted verification rather than repeatedly
   submitting identity data. Respect explicit revocation/expiry once defined by
   WLMD. A failed or pending result is not a verified result.
3. If verification is absent or no longer valid, invoke the authenticated WLMD
   adapter using the confirmed check sequence. Collect SSN last four or an ID
   image only when that method is required. Never assume the three methods are
   equivalent, or that `crosscheck` success implies SSN verification.
4. Store only normalized status, method, provider reference and verified/expiry
   timestamps against the site's patient account and WLMD mapping. Do not store
   SSN digits, ID images or raw responses in account settings, answer profiles,
   logs, browser storage or Git. Account settings shows the verification status.
5. Apply the same shared intake component and API guard to portal, refill and
   post-checkout intake. Do not copy a separate integration into every Lovable
   site. Do not expose account-wide history to a checkout receipt without the
   existing ownership/account-linking checks.

Credentials belong in server-side encrypted Fly secrets after the authentication
scheme is confirmed. They must never be sent to Lovable or patient browsers.
New site onboarding must request the WLMD site ID explicitly.

## Information still required

- HTTPS API base URL and authentication scheme; credentials supplied securely.
- FortifyHP's WLMD site ID.
- Sanitized successful, failed and pending response examples, including the
  meaning of `user`, verification reference and any expiry/revocation semantics.
- Which check runs first, fallback sequence, which results satisfy the intake
  requirement, and how `id-image` receives its image.

Until supplied, preserve the existing live intake behavior. Do not claim the
identity service is connected or mark a patient verified with mock responses.
