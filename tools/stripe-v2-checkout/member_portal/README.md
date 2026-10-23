# Member portal backed by Sticky

The portal reads real Sticky orders and subscriptions through the checkout
application's existing server-side credentials. It never seeds customer orders.
The older `patient_demo` app remains an offline UI fixture; it is not the member
order source. Its questionnaire adapter is reused until the intake API arrives.

## Routes and account access

- `/portal/{site_id}`: branded member login and account enrollment.
- `/portal-admin/{site_id}`: orders, member invitations and refill queue, using
  the existing owner login.
- `/portal/{site_id}/docs` and `/openapi.json`: site-scoped member API contract.
- `/api/v1/sites/{site_id}/portal/*`: patient APIs with site-bound bearer tokens.
- `/api/admin/sites/{site_id}/portal/*`: owner APIs with the existing cookie,
  origin and CSRF checks.
- Checkout `POST /api/portal-enrollment` returns a short-lived account invitation
  only for the requesting browser's captured, site-bound checkout.
- The external checkout API exposes the same handoff at
  `POST /api/v1/sites/{site_id}/sessions/{session_id}/portal` after capture.

Typing an email or order ID is never proof of ownership. Owner-issued invitations
are bound to one verified order/customer/site, expire after one hour and are
single-use. Existing members must sign in before claiming another invited order.
Passwords use scrypt; session and invitation tokens are stored hashed. Accounts
are separate per site. Owner role switching is not available to patients.

## Orders and subscriptions

The owner can sync captured, site-bound checkout receipts. Historical unscoped
receipts require an explicit historical import. Other Sticky orders require an
explicit import with exact campaign, product and SKU validation against that
site's managed offers. One Sticky order cannot be attached to two sites.

Refresh verifies current Sticky state and follows a bounded set of explicit
renewal child references. Each child must match the campaign, customer,
subscription/product and parent or ancestor. Ownership is inherited from its
verified parent, never from an email search. Sync failures retain the previous
snapshot with its last-sync timestamp; they must not appear as a fresh empty
order list. This release has explicit refresh, not a webhook or scheduled sync.

Pause uses Sticky `subscription_order_update` status `stop`; resume uses `reset`
and preserves its date. Resuming an overdue cycle may allow the scheduler to
process it. The immediate-bill `start` operation is not exposed. Pausing cycles
can also pause prepaid included shipments; it is not a clinical instruction.

A next cycle date is not always a next payment date: prepaid intermediate cycles
can be $0. Staff records retain test/non-shippable provenance. Payment status is
read from Sticky, not assumed paid because a local capture once succeeded.

## Delivery updates, notifications and doctor-chat drafts

Authorized order responses expose the existing normalized `tracking_number` and
`shipping_date`. Shipped orders show those recorded details. No carrier, tracking
URL, arrival date or delivery event is inferred from the number alone.

`GET /notifications` returns current shipment and care-action updates from the
patient's already-authorized order snapshots, plus an unread count.
`POST /notifications/{id}/read` stores a durable, idempotent read receipt for that
site and patient. An inaccessible or resolved update returns 404. Included
refill updates are grouped by the original paid term so native children cannot
multiply claim prompts. Opening an update never submits a refill itself.
Updates refresh with the portal's recorded state; email/SMS delivery and provider
push events remain separate integration work.

The dedicated Refills screen groups each treatment purchase independently and
shows its remaining included claims and next action. Claiming and completing a
check-in stay explicit per-order actions. A paid-plan link is a separate purchase.

The doctor-chat section has a private account-backed draft composer while the
medical messaging adapter is disconnected. `GET /messages/draft` returns
`body`, `revision`, `updated_at` and `provider_connected`.
`PUT /messages/draft` accepts `body` (up to 2000 characters) and the current
`revision`; a stale save returns 409 without overwriting the saved draft.
Drafts are scoped to site and patient, and saving one sends no provider message
and creates no automated clinician reply. Existing message history is preserved.

## Address, card and refill controls

Current-order address changes require an unshipped, unposted order with no child
orders. Future subscription address changes use Sticky's subscription address
override API, with subscription/contact/product ownership checks and read-back.
They do not rewrite an already-shipped order. Both operations journal request
IDs; uncertain writes are held rather than automatically retried.

Card replacement is deliberately unavailable until Sticky supplies a verified
Stripe Connect v2 tokenized replacement contract (hosted update link or
SetupIntent creation plus binding to the existing subscription). Generic card
fields and a payment authorization are not substitutes. No portal endpoint
accepts raw card numbers or CVV.

Master SKUs have independent refill policies at
`/api/admin/master-refill-rules/{sku}`: enablement, minimum days, request window,
check-in requirement, test-request permission and early-request rules/cooldown.
Policies have their own revisions so edits cannot change prices or invalidate
payment mappings. The earlier review-only requests remain in history with their
original rule snapshots. They are not native Sticky orders. When included claims
are enabled, the customer uses the claim flow below instead of creating another
local review request. Neither an intake nor a claim constitutes medical approval.
Test orders and simulated care evidence cannot qualify a live medication release.

## $1 checkout testing

The owner can enable the checkout toggle for the existing non-fulfilling campaign
422 site. It is off by default. The browser sends only a boolean; the server
selects $1 for a full term, asks Sticky to calculate the amount, uses that total
for Stripe authorization and captures with `preserve_price=1`. For two/four
prepaid cycles the per-cycle units are $0.50/$0.25. Capture verifies the next
full subscription renewal price, or holds the result for review. Normal catalog prices
and existing subscriptions are never repriced. Disabling the toggle prevents new
test authorizations but preserves a previously authorized test price at capture.

Actual Dry Run campaign 428 verification on 23 October 2026 used non-shippable
products and the verified test gateway. Orders 507822–507824 produced $1/$0/$1;
orders 507825–507829 produced $1/$0/$0/$0/$1. These are actual Sticky test orders,
not locally fabricated orders. No real card was charged or medication shipped.
Test cards must not be used on campaign 422's live Stripe Connect v2 gateway.

## Remaining provider dependencies

- Approved intake API/questions and the Sticky intake handoff destination.
- Medical messaging API, medical review/refill handoff, and a fulfillment hold
  that prevents physical release before the required clinical decision.
- Verified Stripe Connect v2 saved-card replacement contract.
- Email delivery/recovery, scheduled order reconciliation and site-specific staff
  roles are not included in this initial owner-managed release.

Intake autosave/submission and message storage work. Staff records and API
capabilities retain the disconnected provider state; patient presentation uses
saved-form and draft language. Submitted mock data is not sent to clinicians.

## Verification

Run the existing backend suite with the project virtualenv. New files are
`test_member_provider.py`, `test_member_portal.py`, `test_refill_rules.py`, and
`test_dollar_testing.py`. Browser coverage is `qa/member-portal.spec.cjs` with an
injected offline Sticky adapter. That fixture is test-only and cannot call the
external gateway. Preserve the original Fly volume and inspect pending payment
forms before restarting its one-worker checkout process.

Private preview status and validation: see `../member-portal-preview.json`.
The current preview uses the real database through a localhost tunnel. Sign
into `/portal-admin/master-therapy-test-422` with the existing owner account.
Patient accounts are enrolled from an owned receipt or an owner-issued invite.
The public checkout and API processes have not yet received this release.

## Product intakes and care timeline

Master refill settings also hold `intake_template_id`,
`initial_intake_required` and `check_in_days`. Exact bindings in
`intake_templates.py` connect the 40 known SEMA/TIRZ/SERM/METFORM/PT141 SKUs to
their four product-specific mock questionnaire families. A 12-month term has
an initial intake and independent day-90, day-180 and day-270 check-ins. A
six-month term has an initial intake and day-90 check-in. Questions, policies
and care dates are snapshotted per patient, site, product and verified paid term.

Patient API additions, below the site's `/portal` API prefix:

- `GET /orders/{order_id}/care-plan`
- `GET/PATCH /orders/{order_id}/care-tasks/{task_id}/intake`
- `POST /orders/{order_id}/care-tasks/{task_id}/intake/submit`
- `GET /orders/{order_id}/care-tasks/{task_id}/intake-history`
- `POST /orders/{order_id}/care-tasks/{task_id}/claim` with a stable
  `client_request_id` for the selected included checkpoint.
- `GET /store` for the site's public, enabled paid checkout options.

Task IDs are `initial` or `checkin-{day}`. Drafts autosave independently; stale
revisions and edits to submitted answers are rejected. Completing one intake
does not complete another. Initial intake remains available after purchase when
it has not been completed. Included-claim check-ins are tied to the resulting
native child order; an earlier review-only submission cannot satisfy that new
check-in. Existing master disable switches remain authoritative even when older
care plans have snapshots. Both initial and later submissions retain their
actual save/submission timestamps and simulation provenance.

Owner APIs include `POST /orders/{id}/verify-care-schedule` for imported original
prepaid orders and `POST /orders/{id}/care-clock` for isolated Dry Run testing.
Verification uses original paid-order evidence plus the exact purchased offer
and fixed-day model, never today's SKU label alone. The care clock expires after
24 hours and is restricted to verified non-shippable gateway-1 test orders. The
clock is scoped to the original paid term, so its native included children share
the same displayed day while a paid renewal has an independent term. Changing
this clock alone never calls Sticky or changes billing. An explicit claim made
afterwards is a separate operation that can create an actual $0 Dry Run order.
Simulated submissions cannot qualify a later non-test entitlement.


## Included shipment claims and paid alternatives

The current requested sequence is **initial intake → claim an included shipment
→ complete that shipment's fresh check-in**. A 12-month / 360-day term with four
shipments opens its three included claims on days **80, 170 and 260**, ten days
before the original day-90/180/270 shipment anchors. A six-month / 180-day term
opens its single included claim on day 80. One- and three-month terms have the
purchase intake and no additional included shipment. Master policy fields
`included_refills_enabled` and `claim_window_days` control the claim feature;
the default claim window is ten days. These care settings never rewrite paid
billing terms or turn a one-time SKU into a subscription.

The server requires the initial intake and any required earlier claimed-shipment
check-ins. It then verifies the original paid term, exact product, offer, fixed-day
model, customer, subscription, native cycle, and current configuration. Each claim
consumes the next included cycle of that existing prepaid subscription. It does
not create a separate sale or force the next paid renewal. The current adapter
is limited to verified non-shippable, non-taxable configurations without external
fulfillment or other automatic integrations and without recurring shipping fees.
That supports actual $0 test orders; physical medication fulfillment remains an
integration dependency.

`member_refill_claims` journals one intent per paid term/cycle and a unique
patient request ID before a provider write. The adapter uses the native Sticky
included-cycle operation, verifies the returned $0 child and exact lineage, and
preserves the following cycle's original paid-term anchor. Current UTC due-date
checks and existing child detection protect against a scheduler duplicate. A
network timeout or ambiguous read-back becomes `uncertain`; a retry may reconcile
by reads but cannot submit another write automatically. The prepaid final-cycle
boundary is enforced before any operation that could reach a paid renewal.

Only a verified `claimed` result unlocks its new check-in. These answers live in
`member_claim_intakes`, scoped by care plan, logical checkpoint, claim ID and
native child order. Earlier `member_care_intakes` and `member_refills` records are
preserved. The read-only intake-history endpoint exposes the account's own old
and claim-scoped forms. Staff summaries distinguish checkpoint and claim/order
references without returning questionnaire answers. Patient care timelines can
use `care_plan.id` / `term_order_id` to show one journey while retaining every
actual Sticky order in order history.

`GET /store` returns only this site's enabled public published plans and their
currently available paid choices. It includes the full upfront amount, currency,
product/therapy labels and a URL into the existing checkout selection flow.
Private invitation tokens and processor credentials are excluded. Display
catalog data may be cached for 60 seconds with configuration invalidation; the
existing checkout still verifies availability and price. The private preview
uses the original public checkout origin for these links. Browsing or selecting
a plan never automatically makes a purchase or assigns medical eligibility.

Release evidence for this change must be recorded separately from code readiness.
The native-claim offline tests and read-model checks do not by themselves prove
that the latest bundle has been published or that a real Sticky claim succeeded.
See `../member-portal-preview.json` and the project handoff for the latest verified
process, remote test result and remaining deployment work.

Actual private-preview verification on 23 October 2026 created all three included
$0 native Sticky orders on the authorized existing Dry Run term. Each has a fresh
submitted mock check-in, and its following cycle keeps the original term anchor.
The initial intake was preserved, repeated claims were idempotent, and no paid
renewal or physical shipment was triggered. The current public payment worker
was not restarted. Markrx repurchases remain unavailable because its four
checkout plans are private; the store exposes public published choices only.
