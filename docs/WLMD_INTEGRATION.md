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
gate or WLMD credential transport is enabled by this change. The owner confirmed the live origin `https://api.whitelabelmd.com`
and FortifyHP WLMD site ID `288`. The header is `authtoken` with the
value `key=secret`; the complete value belongs only in the encrypted Fly
secret `WLMD_AUTHTOKEN`. `WLMD_API_URL` selects the backend origin.
WLMD membership is not used; Sticky remains the account identity provider.

## Owner-supplied endpoint

`POST /v1/site/{site_id}/identity-check/{order_id}`

Known body fields:

- `which`: `crosscheck`, `ssn`, or `id-image`.
- `ssn`: exactly four decimal digits when `which` is `ssn`.
- `user`: present in the provider implementation; meaning is unconfirmed.
- `debug`: present in the provider implementation; never enable for patient traffic.

The later Postman screenshot shows a different route:
`POST /v1/site/{site_id}/order/{order_id}/identity_ssncheck`.
The correct identity route still needs confirmation. The provided examples
also use different body shapes (`ssn` versus `last4` and demographics). Success
status values, pending/failed outcomes, expiry, response reference, user mapping
and ID-image transport remain unconfirmed. Do not guess these, treat HTTP 200 as identity success,
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

Credentials belong in server-side encrypted Fly secrets. The authentication
header format is confirmed; no credential is included in this document. They must never be sent to Lovable or patient browsers.
New site onboarding must request the WLMD site ID explicitly.

## Information still required

- Which of the two provided identity routes/body formats is current.
- Sanitized successful, failed and pending response examples, including the
  meaning of `user`, verification reference and any expiry/revocation semantics.
- Which check runs first, fallback sequence, which results satisfy the intake
  requirement, and how `id-image` receives its image.

Until supplied, preserve the existing live intake behavior. Do not claim the
identity service is connected or mark a patient verified with mock responses.

Configuration deployed on 24 October 2026: FortifyHP maps to WLMD site 288;
`WLMD_API_URL` and `WLMD_AUTHTOKEN` are configured on the existing shared Fly
app. The credential has not yet been validated by an identity request. Site
configuration tests: 31 backend and one browser scenario passed. Hosted source
hashes match, health is 200 and existing checkout/patient counts are preserved.
No identity request or patient-data transfer was performed. Identity gating
is still inactive pending the confirmed route/body/result contract.

## Authorized live routing test — 24 October 2026

The owner supplied a specific site/order and SSN last four for one integration
test; those identifiers and digits are deliberately omitted here. Requests used
the configured live origin and encrypted authtoken. The Postman-shaped path
returned HTTP 200 with a non-JSON body. The PHP-shaped identity-check path
returned HTTP 200 with `status: error` and nested error code `404`. A subsequent
OPTIONS diagnostic located the not-found exception in `RoutingMiddleware.php`,
consistent with an unresolved route rather than an SSN mismatch.

No successful verification was observed and no local patient was marked
verified. HTTP 200 alone must never be used as the success rule. The complete
resolved Postman `api_url` (including any base path) has been requested. Do not
retry an identity write automatically or copy request data/raw responses into
logs or fixtures. No raw response, SSN digits or personal data was saved.

Follow-up: the owner confirmed the resolved origin is exactly
`https://api.whitelabelmd.com`. A targeted POST to the Postman SSN route with
the supplied SSN field returned HTTP 200 / text/html containing a fatal PHP
`TypeError`; it was not a web page or JSON verification result. Sanitized stack
metadata referenced Identity.php and controller/routing files. No embedded JSON
result was present. An OPTIONS diagnostic returns a routing fatal error, so
OPTIONS must not be used to infer that this POST route is absent. The hostname
is settled; the SSN handler/request contract is now the blocker. The observed
POST used the `ssn` body field; the earlier example also used `last4` plus `user`,
whose required meaning remains unspecified. No patient was marked verified and
no success rule was inferred. Do not repeat the SSN submission for diagnostics.
