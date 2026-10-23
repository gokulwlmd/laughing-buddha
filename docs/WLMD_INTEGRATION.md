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
trusted backend adapter, never from patient answer updates. No live intake identity gate is enabled yet. The authorized SSN test below
verified the WLMD credential and request contract. The owner confirmed the live origin `https://api.whitelabelmd.com`
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
The SSN route is now confirmed by the successful test below. It takes
`last4` and a system/caller identifier in `user`. The generic identity-check
route and the crosscheck/ID-image contracts remain unconfirmed. Do not guess these, treat HTTP 200 as identity success,
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

- Failure/pending response semantics and any expiry/revocation semantics.
- Crosscheck/ID-image request contracts and any required fallback sequence.
  The successful SSN contract below is confirmed.

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

## Confirmed SSN success contract — 24 October 2026

The owner corrected the request field to `last4` and clarified that `user`
identifies our calling system, not the patient. The explicitly authorized test
then returned HTTP 200, Content-Type application/json, and an object containing
`status: "success"`. Elapsed time was approximately 6 seconds. The response also
contained a message, which was not retained because it may include personal data.

Confirmed request:

- Origin: `https://api.whitelabelmd.com`.
- Method/path: `POST /v1/site/{wlmd_site_id}/order/{owned_order_id}/identity_ssncheck`.
- Header: `authtoken: <key>=<secret>`, sourced from `WLMD_AUTHTOKEN` on the backend.
- JSON: `{"user":"laughing-buddha","last4":"<four digits>"}`.
- The system identifier `laughing-buddha` was accepted in this authorized test.

Success requires a successful HTTP response, a JSON object and the explicit
string `status == "success"`. HTTP 200 alone, HTML/PHP errors, malformed JSON,
missing/unknown status, timeout or `status: "error"` must never mark an account
verified. Do not derive verification from the message or apply this rule to
other WLMD methods without their contracts. No incorrect SSN was submitted as
a negative live test. The owner authorized this specific successful test;
repeat verification writes are not needed for QA.

The credential and SSN contract are now verified. Portal/receipt identity gating,
account-settings status and the reusable WLMD adapter remain to be implemented;
this test did not create a local verified fact or change FortifyHP's mapping.
No SSN digits, patient identifiers or raw response are stored in this record.

## Identity gate and Account settings — 24 October 2026

Implemented the confirmed live SSN contract in `member_portal/wlmd.py`.
FortifyHP uses its saved WLMD mapping; other mapped sites use their own mapping.
Sites without a mapping keep their existing intake behavior. Missing credentials
on a mapped site leave verification unavailable rather than bypassing the gate.

- Account settings shows personal details, verification status/date and a
  last-four-only form. Successful checks resume the selected intake/check-in.
- Shared `wlmd-purchase-intake` asks inline after purchase. Existing frontends
  loading this shared component need no per-site Lovable implementation.
- Portal: GET `/api/v1/sites/{site}/portal/account/identity`; GET/POST
  `/api/v1/sites/{site}/portal/orders/{order}/identity`, using patient bearer auth.
- Checkout: GET/POST `/api/v1/sites/{site}/sessions/{session}/identity`, using
  the order-bound receipt bearer. POST body is `{"last4":"<four digits>"}`.
  Upstream identity credentials, WLMD mapping and order IDs come from the backend.
- Initial and care/check-in intake reads and mutations enforce verification.
  Existing drafts remain saved. Verification does not change clinical approval,
  fulfillment, subscriptions or payments.
- Store only verification status, timestamps and internal site/subject/order
  references. Never store last-four digits, request bodies or provider messages.
  Exact JSON `status: "success"` is required; unknown results stay unconfirmed.
- Reuse a verified assertion within the same site and WLMD mapping. No arbitrary
  expiry is invented because the provider has not supplied expiry semantics.
  A changed mapping requires a new check. Server assertions can satisfy version-1
  `identity.ssn_verified` intake questions, but never imply ID-image verification.
- Receipt holders can only read their own order assertion. Verified receipt
  assertions are adopted into the patient account after exact authenticated order
  ownership is established, retaining the receipt result. A receipt alone cannot
  retrieve another order's/account's identity status or stored answers.
- No automatic provider retry. Durable reservations limit repeated submissions
  to five per 15 minutes and enforce a 30-second minimum gap. Requests use a fixed
  HTTPS origin, no redirects, bounded timeout/body and redacted errors.

Automated verification uses synthetic fixtures: patient/receipt ownership,
site/mapping isolation, trusted fact reuse, failure/timeout handling, rate limits,
intake gates, API forwarding, no SSN persistence and desktop/mobile UI flows.
37 browser scenarios passed. Targeted backend batches passed (64 tests, then
2 new session contract tests, then 66 regression tests; batches overlap).
No new live SSN submission or payment was made for this release. Crosscheck,
ID-image and the real clinical intake/questionnaire APIs still need contracts.

Release deployed and verified on the existing shared Fly app in image
`sha256:ae2496fd8f355659e8f82809e7d15db98f5eebbc3bf550b83f13a8112c2f8675`.
Hosted JS/CSS/backend hashes match, health is 200, unauthenticated identity
access is 401, and existing checkout/patient counts are unchanged.
