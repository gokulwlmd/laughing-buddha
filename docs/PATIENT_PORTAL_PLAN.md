# Patient portal: real Sticky orders and care workflows

Updated 23 October 2026. This is a new development track, separate from the
existing live payment engine and its stored orders.

## Owner decisions

- Keep a separate branded portal and patient records for each site initially.
- The medical team will fetch information from Sticky. Do not introduce a new
  medical-network integration as a prerequisite.
- The owner will supply the intake API. For now, serve clearly marked sample
  questions from our backend, with content appropriate to each therapy.
- The owner will supply the doctor-messaging APIs. Use mock messaging for now.
- Preserve earlier charge-first and per-SKU refill-rule decisions. Payment,
  clinical approval, included deliveries and billing renewal remain distinct.

The exact Sticky destination and format for intake handoff have not been
specified. No mock intake is sent to Sticky, and no submission is represented
as clinically reviewed. Refund/decline/incomplete-intake policy remains open.

## Build sequence

| Order | Deliverable | Release boundary |
| --- | --- | --- |
| 1 | Site-specific order view, patient identity and staff permissions | Snapshot site/therapy/SKU/terms at verified purchase; reconcile duplicate/missing events. Production patient authentication is separate from checkout tokens. |
| 2 | Intake, autosave/resume and partial leads | Version questions and preserve submitted answers; distinguish unpurchased leads from paid orders awaiting intake. |
| 3 | Care-team status and messages | Replace mock adapters with the provided APIs and define the Sticky handoff. |
| 4 | Refill requests, check-ins and fulfillment status | Per-SKU approved rules; no medication release or clinical approval inferred from a paid term. |
| 5 | Portal store and repeat-product intake | Reuse only relevant, permitted answers; reconfirm changes and ask new therapy questions. |
| 6 | Reusable funnel builder | Begin with configured steps/conditional questions, then add visual editing, publishing/versioning and conversion reporting. |

Each phase includes patient APIs and per-site Swagger alongside the UI. The
first integrated pilot should use one site and Weight Loss before rollout to
the remaining therapies. Provider APIs, clinical content and operating policies
are dependencies for real-patient release, not for this sample demonstration.

## Superseded first demo

`tools/stripe-v2-checkout/patient_demo` is an isolated FastAPI/SQLite application.
It has no Sticky or Stripe clients and does not import the live payment app.
Every browser creates a separate 24-hour synthetic workspace containing two
sites, sample patients, four sample therapy orders per site, and sample leads.
Patient/admin tokens are role- and site-scoped, stored hashed on the backend.
The persona switch is a demo mechanism, not production authentication.

Working scope: branded patient order views; backend-supplied Weight Loss,
Sermorelin, Metformin and PT-141 questionnaires; conditional questions;
revision-protected autosave/resume; immutable submitted answers; a mock message
thread; site/therapy-filtered admin orders, intake progress and sample leads;
and site-scoped OpenAPI/Swagger. Admin operational views expose intake progress,
not the medical answers themselves.

Explicitly pending: verified patient registration/login, real order ingestion,
actual pre-qualification/lead capture, Sticky intake export, real provider
messages, cross-device account recovery, refill execution, portal store,
clinical answer reuse and the visual funnel builder. Seeded leads are display
fixtures; the UI must not imply they were captured from a working funnel.

See the [demo README](../tools/stripe-v2-checkout/patient_demo/README.md) for local
URLs and verification commands. Existing live checkout/API deployments and
their databases are unchanged by this demo.


## Current implementation

The owner rejected sample orders after reviewing the first UI. Order and
subscription work now uses the existing Sticky integration, verified site-bound
ownership and the real member module. Intake and messaging are the only mocked
provider integrations. Read [the member implementation contract](../tools/stripe-v2-checkout/member_portal/README.md)
for implemented APIs, configuration, test evidence and remaining dependencies.
