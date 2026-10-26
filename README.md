# WLMD Core

WLMD Core is a shared backend for branded treatment catalogs, checkout, post-purchase intake and member portals. FortifyHP is one connected storefront. Each site has its own branding, catalog mappings and patient access boundaries; Sticky.io supplies order and subscription records, Stripe Connect v2 handles card payment through Sticky, and WLMD adapters connect identity and care workflows.

The active application is [`tools/stripe-v2-checkout/`](tools/stripe-v2-checkout/). Its directory name is historical. It contains the shared application, not a disposable checkout experiment.

## Start here

- **Develop locally:** [Local development](docs/LOCAL_DEVELOPMENT.md) — synthetic data, no provider credentials required.
- **Make a change:** [Contributing](CONTRIBUTING.md) — review, tests and release boundaries.
- **Handle sensitive data:** [Security](SECURITY.md) — credentials, patient information and private reports.
- **Deploy:** [Collaboration and releases](docs/COLLABORATION.md) — Fly staging, live release responsibilities and AWS status.

## Repository map

| Path | Responsibility |
| --- | --- |
| [`tools/stripe-v2-checkout/app.py`](tools/stripe-v2-checkout/app.py) | FastAPI application and checkout/payment lifecycle |
| [`tools/stripe-v2-checkout/admin.py`](tools/stripe-v2-checkout/admin.py), [`web/`](tools/stripe-v2-checkout/web/) | Site and master catalog administration; hosted checkout assets |
| [`tools/stripe-v2-checkout/demo/`](tools/stripe-v2-checkout/demo/) | **Active** site checkout API, publication registry and checkout sessions, alongside older demo assets |
| [`tools/stripe-v2-checkout/member_portal/`](tools/stripe-v2-checkout/member_portal/) | Member accounts, orders, intake, refills and provider adapters |
| [`tools/stripe-v2-checkout/patient_demo/`](tools/stripe-v2-checkout/patient_demo/) | Synthetic preview and question-template code still imported by the application |
| [`tools/stripe-v2-checkout/qa/`](tools/stripe-v2-checkout/qa/) | Browser fixtures and automated checks |
| [`scripts/`](scripts/) | Repository, staging and operational checks |
| [`docs/`](docs/), [`.agents/skills/`](.agents/skills/) | Feature decisions, dated verification evidence and integration procedures |

Do not delete or rename a directory based on “demo” or “test” in its name. Trace imports, routes and packaging first. The separate Lovable storefront is not fully represented by this repository's hosted UI files.

## Environments and data

The current shared live application runs on **Fly.io**, using Python 3.12, FastAPI and persistent SQLite databases. Local development uses isolated synthetic data. The optional Fly staging workflow also uses synthetic mode with payments blocked.

AWS/MySQL migration is a separate workstream; see the AWS plan below. Compatibility packages being prepared elsewhere are not included in this cleanup branch. Do not replace the Fly database or deploy an AWS package as part of an ordinary code cleanup.

Catalog browsing uses local publications and scoped snapshots. Payment totals, authorization, capture and order reconciliation retain their provider checks. A fast catalog response is not evidence that a charge succeeded.

## Working references

- [Admin workflows](tools/stripe-v2-checkout/ADMIN.md)
- [Capture setup reuse](docs/CAPTURE_SETUP_REUSE_2026-10-26.md)
- [Site API performance](docs/SITE_API_SPEED.md)
- [Payment confirmation timing](docs/PAYMENT_CONFIRMATION_TIMING_2026-10-26.md)
- [AWS migration plan](docs/AWS_PLATFORM_PLAN.md)

Dated feature reports and older module READMEs record the implementation at that time. Use the current source, tests and verified release record together when deciding what is available. Test counts, infrastructure settings and release images in historical reports are not current guarantees.
