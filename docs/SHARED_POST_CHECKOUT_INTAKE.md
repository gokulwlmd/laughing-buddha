# Shared post-checkout intake

Decision recorded 2026-10-24: show the intake on the purchasing site without asking the patient to log in there. Account setup/sign-in belongs in the separate branded member portal. Unfinished intake must resume there. All sites use the same hosted component and backend contract; questionnaires are not copied into 200 storefronts.

## Storefront integration

Load the classic script from the shared application's `/portal-assets/post-checkout.js`, wait for `customElements.whenDefined('wlmd-purchase-intake')`, then append `<wlmd-purchase-intake>` and call:

```javascript
await element.configure({
  siteId: 'your-published-site-id',
  sessions: capturedSessions.map(({session_id, session_token}) => ({session_id, session_token}))
});
```

Supply only the current buyer's verified completed checkout sessions. Pass tokens in memory, never in a URL, analytics event or log. The component handles product-specific questions, conditional fields, partial saves, revision conflicts, submission, multiple purchased products and the member-portal link. It inherits the storefront font; `--intake-accent` optionally sets the button color. Future component changes deploy once on the shared application.

APIs (the existing scoped checkout bearer token is required):

- `GET /api/v1/sites/{site_id}/sessions/{session_id}/intake`
- `PATCH /api/v1/sites/{site_id}/sessions/{session_id}/intake` with `{revision, answers, current_step}`
- `POST /api/v1/sites/{site_id}/sessions/{session_id}/intake/submit` with `{revision}`
- Existing `POST .../portal` produces the separate private account-setup link.

The engine checks the exact captured receipt and its site/order mapping. No caller-supplied order ID, patient account, Sticky credential or Stripe credential grants intake access. API documentation includes the new routes. Checkout capabilities retain the existing expiration; after expiry the patient uses authenticated portal access.

## Draft ownership and account handoff

Before enrollment, an order-scoped intake is saved with an internal receipt owner, without creating an account or patient grant. After a verified order invitation is connected to an authenticated/enrolled patient, its draft is adopted into that patient's record. It is never matched by email alone and never overwrites another patient intake. The care-plan adapter adopts the same initial questionnaire when a verified care schedule becomes available.

The member-portal link can carry a bounded list of order invitation tokens in its URL fragment. The portal removes the fragment, keeps pending invitations in site-scoped session storage and connects each after enrollment/sign-in. Tokens and intake answers must never be committed to source control.

Initial health intake can open while shipping-schedule verification is incomplete. This does not relax shipment claims, billing entitlement checks, check-in windows or medical approval. The questions remain supplied by the existing mock backend adapter; no clinician delivery or medical approval is fabricated. Replace that provider when the clinical API becomes available.

## Refill and navigation corrections

A one-delivery term has no included refill checkpoint. Its initial intake must not qualify another free delivery. The portal shows a subscription-management or paid-plan route; multi-shipment terms retain their scheduled included refill claims. Explicit task IDs are passed for configured review requests.

Portal navigation and intake steps focus and scroll to visible content. Modals lock background scrolling and restore focus without jumping the document. Initial-intake actions remain available when a care schedule is awaiting verification.

## Verification

456 backend tests passed, including captured receipt scope, account-free drafts, enrollment adoption, required answers, revision conflicts, cross-site rejection and one-shipment eligibility. Shared-component desktop/mobile browser checks cover conditional questions, autosave, required answers and submission. Portal browser checks cover themed routes, mobile reflow, scroll position and modal focus. Lovable reports 51 focused checkout/cart and wrapper checks plus a production build.

No real payment, medical submission, shipment or refill was created by these tests. Existing production payment records and the Fly database are preserved. A pre-release database backup is stored privately on the existing volume. This is shared UI reuse, not a claim that the single-worker deployment has been load-tested for 200 sites.

## Published release

Shared Fly image: `sha256:fed77ec4806cf2c822d210d1384d2750a51b3b937aae6595cf011816e5955eee`. Health and both deployed JavaScript assets were verified against local source. Fortify frontend commit: `04df458b6a37c322291e08057b0eda923ea2bf4e`, deployment `17fd1fa8-b139-4fb5-ba2b-5381e52fd430`. Public `/checkout-complete` was verified to show the member-portal link without embedded account setup. No authenticated completed purchase was available in the verification browser; full intake save/submit was verified with synthetic automated fixtures.

GitHub implementation commit: `125d9a0667eb25eeb8c610160030961577aeae95`. Local checks passed; the GitHub Actions run was still in progress at handoff.
