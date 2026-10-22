# Patient portal demo

An isolated, local preview of site-specific orders, intake and care messages.
Uses synthetic patients/orders and backend-served mock questions. No payment,
clinical decision, prescription, shipment or provider transmission occurs.

From the repository root:

```sh
.venv/bin/python tools/stripe-v2-checkout/patient_demo/run.py
```

- Patient portal: <http://127.0.0.1:8873/portal/willow-health>
- Sample admin: <http://127.0.0.1:8873/admin-demo/willow-health>
- Willow Swagger: <http://127.0.0.1:8873/sites/willow-health/docs>
- Harbor Swagger: <http://127.0.0.1:8873/sites/harbor-wellness/docs>

Use only sample information. The UI can fill sample answers for each therapy.
Switch sites to inspect independent branding and records. Switch the demo
persona to inspect admin orders, intake progress and sample partial leads.
The first visit creates a private 24-hour workspace; its tokens are held in
browser session storage. Reloading the same tab resumes its saved drafts.
Closing the browser session or losing the tokens does not provide account
recovery; a real patient identity provider is a later integration.

## API contract

Create a workspace with `POST /api/demo/workspaces` and `{}`. This returns one
patient and admin token for each sample site. Set `Authorization: Bearer TOKEN`
on private requests. This bootstrap is only for the synthetic demo; it must
never be used to grant access to real patient or admin records.

All routes below begin with `/api/v1/sites/{site_id}`:

| Route | Access | Purpose |
| --- | --- | --- |
| `GET /configuration` | Public | Site branding and available therapies |
| `GET /me` | Patient | The site's sample patient |
| `GET /orders` | Patient/admin | Site-specific orders; optional `therapy_id` filter |
| `GET /intakes/{order_id}` | Patient | Resume or initialize a draft and its frozen question template |
| `PATCH /intakes/{order_id}` | Patient | Merge `answers`, `current_step` and the last `revision` |
| `POST /intakes/{order_id}/submit` | Patient | Validate and freeze answers using the last `revision` |
| `GET /messages` | Patient | Site-specific sample conversation |
| `POST /messages` | Patient | Save `body` once per `client_message_id`; explicit automated demo acknowledgement |
| `GET /admin/overview` | Admin | Orders, intake summaries and seeded partial leads; optional `therapy_id` |

Question types and conditional visibility come from the backend. `provider.py`
is the sample provider boundary to replace once the owner supplies the intake
API. Current questions are illustrative, not approved clinical protocols.
Each draft snapshots a template version; later provider changes cannot silently
rewrite an existing intake. `current_step` is a zero-based section index.
Stale writes return 409 instead of overwriting another save. Submitted answers
are immutable. No answers are automatically reused across products or sites.

Order `total` values are major-unit decimal strings. All seed orders are
`paid_demo`; they are not receipts from the existing payment app. Submitting an
intake changes only the demo's intake/review status. No message reaches a doctor.
Partial leads are seeded examples, not a connected acquisition funnel.

SQLite state is under ignored `.state/patient-demo` by default, separate from
payment databases. Tokens are stored hashed and expired workspaces are removed
when a new workspace is created. The runner binds only to loopback and disables
access logs. Swagger alone uses FastAPI's standard external Swagger assets;
the portal's font and UI assets are local.

## Verification

```sh
cd tools/stripe-v2-checkout
../../.venv/bin/python -m unittest -v test_patient_demo
QA_PYTHON=../../.venv/bin/python qa/node_modules/.bin/playwright test patient-portal.spec.cjs
```

The tests use disposable state and no production records. See
`docs/PATIENT_PORTAL_PLAN.md` for agreed decisions and remaining production work.

Verified 23 October 2026: all 271 backend tests passed, including 16 patient
demo cases. Five patient-portal browser scenarios passed on the final UI,
covering save/resume/submit, site isolation, failed-save recovery, delayed
responses after site changes, final answer review and 1440/390 px layouts.
Six desktop/mobile screenshots were reviewed locally; they contain sample
records only and are not committed. No hosted release or live integration was
performed for this demonstration.
