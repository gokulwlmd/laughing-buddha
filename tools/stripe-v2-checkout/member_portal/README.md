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
can be $0. Test/non-shippable orders are labeled accordingly. Payment status is
read from Sticky, not assumed paid because a local capture once succeeded.

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
payment mappings. Requests snapshot the applied rule, require review and cannot
charge, ship medication or approve treatment. Early requests require a reason.
Existing pending requests prevent duplicates. Payment-test requests are marked
as tests and cannot represent medication fulfillment.

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
- Medical messaging API and medical review/refill handoff.
- Verified Stripe Connect v2 saved-card replacement contract.
- Email delivery/recovery, scheduled order reconciliation and site-specific staff
  roles are not included in this initial owner-managed release.

Intake autosave/submission and message storage work, but their provider adapters
are clearly marked disconnected. Submitted mock data is not sent to clinicians.

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
- Existing refill requests additionally identify `task_id` for mapped plans.

Task IDs are `initial` or `checkin-{day}`. Drafts autosave independently; stale
revisions and edits to submitted answers are rejected. Completing one intake
does not complete another. Refill requests are tied to the applicable checkpoint
and preserve its rule and intake evidence. Existing master disable switches
remain authoritative even when older care plans have snapshots.

Owner APIs include `POST /orders/{id}/verify-care-schedule` for imported original
prepaid orders and `POST /orders/{id}/care-clock` for isolated Dry Run testing.
Verification uses original paid-order evidence plus the exact purchased offer
and fixed-day model, never today's SKU label alone. The care clock expires after
24 hours, is restricted to verified non-shippable gateway-1 test orders, and
never changes provider billing or shipment state. Simulated submissions cannot
qualify a later non-test entitlement. Every refill stays a review request.
