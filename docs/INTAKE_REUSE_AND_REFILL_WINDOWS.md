# Saved intake answers and refill windows

Owner decision, 24 October 2026: reuse stable details and verified identity
results; explicitly confirm changing health information. Included refills open
20 days before the current supply ends and remain claimable afterward within
the purchased term, subject to unused entitlement and existing care rules.

## Answer reuse

Submitted intake snapshots are the durable answer history. `AnswerProfile` in
`tools/stripe-v2-checkout/member_portal/answer_profile.py` reads only records
granted to the same authenticated patient at the same site. Draft answers are
never another intake's source. Simulated care answers are excluded; test-card
and ordinary order histories are separated. Submitted snapshots are immutable.

New and untouched authenticated drafts reuse compatible answers. Typed draft
answers win over saved values. Guest receipts do not unlock profile history by
email or by the existence of an order grant. After portal authentication, an
existing guest draft may gain saved values without losing its typed answers.
The same response contract is rendered by the portal and shared storefront
intake component; no per-Lovable-project implementation is required.

The question-provider adapter supplies:

| Field | Meaning |
| --- | --- |
| `reuse_key` | Stable semantic identifier across questionnaires, independent of question ID |
| `reuse_version` | Meaning/version of the answer; incompatible versions ask again |
| `reuse_policy` | `stable`, `confirm`, `verified`, or `never` |
| `reuse_max_age_days` | Optional maximum age of a submitted answer |

Current mock templates map adult height to `stable`; medications, allergies and
medical history use `confirm`. Other questions ask again unless explicitly
mapped by the provider. Symptoms and treatment-progress questions remain new
questions. Check-in change questions are not equivalent to the original full
medication/allergy history and do not overwrite it.

Stable values appear in a saved summary with an edit control. Changing health
answers are initially unanswered and show their previous value with a **Still
correct** button. Required answers must be confirmed or updated before submit.
The response includes `reused_fields` and question-level `reuse_status`,
`saved_value`, and `saved_at`. No provider reference is sent to the browser.

## Identity provider integration boundary

The actual external ID/SSN APIs have not been supplied. The trusted backend hook
`AnswerProfile.record_verification(...)` accepts only ID/SSN verification status,
provider name, an opaque reference, version, verification time and expiry.
It is not a public patient-write endpoint. The future adapter must authenticate
the provider response and map its subject to the exact site/patient before
calling it. Do not store raw SSNs, ID numbers or ID images in this table.

Provider questions use `identity.id_verified` or `identity.ssn_verified`,
policy `verified`, and an answer schema accepting the string `verified`.
Patients cannot assert/change these answers. Submission checks current trusted
status and expiry again. No fake verified identity questions are added to the
current mock questionnaires. Wiring the real provider and its verification UI
remains external setup, not evidence of completed ID or SSN verification.

## Refill behavior

The default and existing enabled included-refill policies move to a 20-day
window through the once-only `included-claim-window-20-days-v1` local migration.
Policy revisions increment; future owner edits remain authoritative. No Sticky
billing dates, orders, paid-term snapshots or submitted intakes are rewritten.
Any configured minimum waiting period and verified term expiry still apply.

For a 12-month/four-shipment plan with 90-day supplies, included claims open on
days **70, 160 and 250**. A six-month/two-shipment plan opens its single included
claim on day **70**. A single-shipment 30-day plan does not gain a free refill:
the 20-day rule only moves the opening date of an existing included entitlement.

Claims retain the existing real Sticky native prepaid-cycle implementation,
initial-intake requirement, preceding check-in requirement, durable duplicate
protection and uncertain-write reconciliation. Claiming creates the verified
$0 child order, then opens its check-in. It cannot force a paid renewal or
create more included shipments than were purchased.

Every order has a **Refill options** button. Unavailable included claims stay
visible as a gray disabled button, with the opening date, blocking reason and
steps for intake, claiming and check-in. Single-shipment plans show a compact
“Not included in this plan” explanation instead of an irrelevant disabled free
refill button. Exhausted prepaid plans retain their completed schedule.

For one-time purchases, the portal offers same-site/product paid plans. Existing
standard subscriptions instead use **Request refill sooner**, with a verified
recurring total and following payment date before explicit confirmation. This
advances the existing subscription and does not open a separate checkout.
See [Native early renewals](NATIVE_EARLY_RENEWALS.md) for supported plans, APIs,
policy gates, read-only reconciliation and live-test limitations.

**Manage subscription** scrolls directly to existing controls. Medication names
no longer repeat slash-delimited duration/payment labels.

## Verification

Backend checks cover semantic IDs/version/type/age compatibility, required
reconfirmation, patient/site separation, draft adoption, provider-only
verification/expiry, once-only migration, and real-order-shaped native claims
at the 20-day boundary with duplicate protection. Browser checks exercise saved
summaries, editing, confirmation, autosave and mobile layout. All order and
provider writes in these tests use offline fixtures.

Release: deployed to the existing shared Fly app on 24 October 2026 as image
`sha256:4e01838320f9368c68283f23757d9a08d7db30c49a50f1e692e83bcdcc5c1683`.
473 backend tests and 10 targeted browser checks passed; an additional timezone
recheck confirmed date-only refill dates display correctly in Los Angeles.
Hosted source/asset hashes match, health returned 200, unauthenticated patient
access returned 401, and all 40 existing enabled included-refill policies now
use 20 days. Order and patient counts were unchanged across deployment. The
private SQLite backup stays on the existing volume. No live payment, refill or
identity-verification write was performed as a test.
