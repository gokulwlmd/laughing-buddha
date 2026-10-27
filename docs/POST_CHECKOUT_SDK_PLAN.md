# Post-checkout SDK: proposed developer implementation

This is a **plan**, not a published SDK. Read the [current handoff](DEVELOPER_HANDOFF_2026-10-28.md) for implementation and release limits.

## Start with the working shared component

The application already hosts `/portal-assets/post-checkout.js` and registers `<wlmd-purchase-intake>`. Its current integration contract is:

```js
// Load the shared backend's /portal-assets/post-checkout.js first.
await customElements.whenDefined('wlmd-purchase-intake');
const element = document.createElement('wlmd-purchase-intake');
container.append(element);
await element.configure({
  siteId: publishedSiteId,
  sessions: capturedSessions.map(({session_id, session_token}) => ({
    session_id,
    session_token
  }))
});
```

Pass only the current customer's verified captured sessions, up to the component's current bound of 20. These tokens are purchase capabilities, not Sticky/WLMD credentials. This example describes the existing component; its unversioned hosted asset is not yet a stable SDK release channel.

It already supplies order confirmation, new-member Sticky password setup, per-product health intake, autosave/resume, supported identity/ID steps, order progress, optional offers and portal handoff. Provider connectivity and site flags still determine which actions work. A control appearing does not establish clinical delivery or saved-card charging capability.

## Two supported integration levels

| Level | Developer receives | Intended use |
| --- | --- | --- |
| Hosted UI wrapper first | Versioned mount/unmount API around the shared component | Fast Lovable, plain HTML or React integration; our team owns the patient flow |
| Headless client second | Typed functions for the same verified session/account/intake APIs | A client builds its own UI while our backend owns state and authorization |

Implement the wrapper first and preserve one shared experience. Do not distribute questionnaires, prices or refill rules as hardcoded SDK logic. Do not create a new Stripe charge implementation as part of the post-checkout package.

## Proposed public API

Illustrative API, **not available today**:

```ts
const flow = await mountPostCheckout(container, {
  apiBaseUrl: configuration.apiBaseUrl,
  siteId: configuration.siteId,
  sessions: capturedSessions,
  theme: { accent: '#245844' },
  onEvent(event) {
    // Non-sensitive UI lifecycle events only.
  }
});

flow.unmount();
```

The exact package name and distribution method are owner/team decisions. Required deliverables: a framework-neutral TypeScript client, a versioned browser entry point, type definitions, changelog, compatibility policy, optional React wrapper, plain-HTML and React examples, and a short Lovable integration recipe. Lock the loaded component/SDK versions together; pin releases rather than silently swapping behavior behind a stable package version.

Site bootstrap should return only public presentation and allowed capabilities: API base URL, site ID, published catalog/API version, portal URL, theme and supported features. No provider secrets or global admin token belongs in that response. The browser supplies no WLMD tenant, arbitrary provider order, gateway or price override.

Known prerequisite: the current component assumes the public API site ID equals the portal site ID when constructing/validating `/portal/${this.site}`. The backend supports a different `portal_site_id`. Resolve this through trusted backend-provided routing and an explicit allowed portal origin/path contract, not arbitrary redirect URLs supplied by the browser.

## End-to-end lifecycle

1. Frontend creates one checkout session for each selected approved plan and retains its customer-scoped session capability.
2. Existing quote/payment/Stripe-confirmation/completion flow runs. A browser success screen is insufficient: the backend must return the verified `captured` state and exact receipt.
3. Mount the post-checkout experience with the captured sessions. Never pass an uncertain or declined item as confirmed.
4. Show confirmed products/order numbers. Offer Sticky password setup for a genuinely new member. Do not reset an existing member's password because they made another purchase.
5. Load API-supplied questions, resume the saved step and reuse only compatible authorized answers. Save partials locally through revision-checked PATCH.
6. Complete identity at the final required step. Final clinical submission must use the separate validated delivery contract when that integration is ready.
7. Offer continue-later and the branded member portal. New-account auto-login uses the existing short-lived single-use encrypted handoff; it is not a reusable login token in a query string.
8. On expiry, preserve saved server state and direct the patient to authenticated portal access. Never replay a payment, password write, upload or medical submission after login automatically.

Multi-product behavior must preserve each successful receipt if a sibling fails. Keep product/order-specific questionnaires and submissions, while common questions use server-defined semantic reuse. Matching labels alone are not proof two medical questions mean the same thing.

## Existing APIs to wrap

Prefix: `/api/v1/sites/{site}/sessions/{session}`. Check the generated contract for the deployed site; the older separate-demo-host guide is historical.

| Path | Purpose |
| --- | --- |
| Session status, `/configuration`, `/quote`, `/payment`, `/complete`, `/resume` | Existing checkout lifecycle; outside the first post-checkout UI package's payment implementation scope |
| `/journey` | Scoped order progress and next steps |
| `/account` | Sticky account setup state/password action and verified portal handoff |
| `/intake` GET | Resume this purchased item's saved questions, answers and step |
| `/intake` PATCH | Save `{revision, answers, current_step}` without clinical submission |
| `/intake/submit` | Existing local submission path; remote delivery must be integrated and reported separately |
| `/identity`, `/id-photo`, `/id-photo/reuse` | Provider-gated identity and ID attachment actions |
| `/portal` | Verified portal transition |

The signed-in portal exposes equivalent owned-order and refill-checkpoint paths. Refill forms bind the actual child order and configured form kind. Both entry points should use the same intake-session service rather than maintain competing drafts.

Per-site Swagger/OpenAPI is served under `/sites/{site}/docs` and `/sites/{site}/openapi.json`; use the site's published routing. Example reference site: `/sites/fortifyhp/openapi.json` on the shared backend. Treat the generated schema and tested source as authority for request fields.

## Errors, events and lifecycle management

Return typed application errors such as `session_expired`, `revision_conflict`, `provider_unavailable`, `action_pending`, `action_needs_review` and `validation_failed`. These are proposed normalized SDK codes; map existing backend responses explicitly before publishing them as contract.

Expose non-sensitive events: `ready`, `progress_saved`, `account_ready`, `intake_complete`, `action_required` and `error`. Event payloads must exclude health answers, identity material, passwords, purchase/session tokens, provider tokens and raw provider responses. Avoid emitting order identifiers to analytics by default.

Cancel stale reads on unmount/site change. Clean up timers, listeners, camera streams and pending render work. Never send a late response from the prior site/account into a new screen. Debounce autosave, flush before step changes, and show Saved/Saving/Retry states without treating a failed save as success. A `409` preserves unsaved input and offers conflict recovery.

Bounded retry may be appropriate for safe reads. Financial/clinical/account mutations require their explicit journal/idempotency rules, not a generic HTTP retry interceptor. Final submit needs `client_request_id` or a provider-recognized submission key plus readback before uncertain attempts can be reconciled.

## Acceptance for SDK v1

- Two independently branded sites and two frontends use the identical pinned package without copied forms or provider credentials.
- At least one site uses distinct public API and portal IDs, and its validated account/invitation handoff reaches the correct portal.
- A refresh, remount, bank-return or expired capability cannot create a second charge or submission.
- Multi-product receipt isolation, partial saves, revision conflicts and authenticated portal resumption pass.
- Returning-member passwords are unchanged; handoffs expire, are consumed once, and cannot cross sites.
- Shared answers respect semantic versioning and changing-health confirmation; guest access never reveals another order's history.
- Desktop, 390px mobile, keyboard navigation, readable errors and unmount cleanup pass browser checks.
- Automated examples use synthetic providers. Separately recorded provider acceptance establishes which live capabilities are certified.

Suggested delivery order: stabilize source/API contract → versioned post-checkout wrapper → headless client → onboarding generator/integration snippets → broader checkout SDK only if needed. This reduces work while improving the part each new frontend otherwise has to repeat.
