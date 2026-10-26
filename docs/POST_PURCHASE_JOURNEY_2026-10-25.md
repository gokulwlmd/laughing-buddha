# Shared post-purchase journey

## Scope

Adds a shared after-purchase checklist to the existing intake component and an evidence-based order timeline to the member portal. Applies to sites using the shared component; no per-site frontend fork or database migration is needed. Existing Sticky membership, identity, intake, refill, subscription, card and address flows remain in place.

- Show member account setup, identity and intake completion together.
- Switch between purchased products without losing unsaved answers; completed intakes stay completed.
- Display the recorded payment, intake, review, prescription and shipping stages, including tracking when available.
- Explicitly refresh order progress without submitting or retrying a payment.
- Preserve partly entered password/identity fields during unrelated progress renders, in memory only.
- Serialize overlapping intake autosaves and navigation saves so concurrent requests do not use the same revision.
- Focus the current intake section after navigation rather than jumping back to the purchase summary.

## API

`GET /api/v1/sites/{site_id}/sessions/{session_id}/journey`

Uses the existing checkout session Bearer token. The session must belong to that site and resolve to a captured receipt. Returns only `id`, `product_name`, `intake_status` and `journey` for that receipt's order. It does not return patient records, answers, identity documents or account-wide order history.

`?refresh=true` requests a Sticky order snapshot refresh if the saved snapshot is at least 30 seconds old. This does not create orders, charge cards, submit intake or advance clinical status. The frontend bounds concurrent progress reads to two.

The member orders API also includes `journey`. Existing portal order-refresh authorization remains unchanged. Scoped OpenAPI discovers the new session route.

## Evidence rules

Payment confirmation is not clinical approval. Submitted intake means answers were saved, not that a clinician received or approved them. Shipping evidence does not infer missing review or prescription events. Unknown clinical stages remain unconfirmed. Real clinical progress still requires the provider status integration.

## Validation and release

Backend tests cover evidence mapping and receipt/site/token isolation. Browser checks cover desktop/mobile multi-product completion, partial-save failures, password preservation, concurrent saves, identity and photo flows, configured prepaid refill cycles, subscriptions and shipment tracking.

Release from a clean copy of the current Fly source plus this feature only. The working tree also contains separate AWS/Python 3.9/MySQL compatibility work, which must not enter this Fly release. No live transactions or patient submissions were made to verify this feature. A local test result does not establish deployment or live provider connectivity.

Validation results: the clean Fly-source backend run executed 546 tests; 544 passed initially, with two journey route/Swagger integration failures. After fixing those, all 45 tests in the affected API and journey modules passed. All 47 distinct browser scenarios passed after correcting the autosave race and updating the shipment fixture to avoid contradictory old/new timeline data. The five new journey scenarios were rerun after the final focus adjustment and passed. JavaScript syntax and staged whitespace checks passed.
