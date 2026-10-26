# Shared checkout and member platform

This is the active WLMD Core application. The directory name comes from its original Stripe Connect v2 integration; it now contains site administration, master therapies, checkout APIs, post-purchase intake and member portals.

Start with the repository [overview](../../README.md), [local development](../../docs/LOCAL_DEVELOPMENT.md), [contribution guide](../../CONTRIBUTING.md) and [security practices](../../SECURITY.md). Development uses synthetic providers and isolated state. Never copy a hosted environment file or customer database into a development session.

## Application map

| Module | Responsibility |
| --- | --- |
| `app.py`, `catalog.py` | Checkout lifecycle, provider validation, attempt state and reconciliation |
| `admin.py` | Owner authentication, admin views and catalog management |
| `master.py`, `plans.py`, `sites.py`, `commerce_admin.py` | Master templates, site configuration, purchase options, prices and coupons |
| `publication_snapshot.py`, `demo/` | Published site catalogs, public APIs and checkout sessions; these are runtime dependencies |
| `member_portal/` | Site-bound accounts, order grants, intake, identity, refills and provider adapters |
| `patient_demo/` | Synthetic preview and question-template dependencies still used by the application |
| `web/`, `member_portal/web/` | Hosted UI and shared frontend assets |
| `test_*.py`, `qa/` | Offline backend and browser verification |

Do not remove versioned browser assets or rename modules without tracing imports, routes and Docker packaging. Older open checkout pages can still reference older assets. The external Lovable storefront is maintained separately.

## Entry points

- `/admin`: owner administration. Customer checkout access does not grant admin access.
- `/plans/{site_id}` and `/c/{choice_id}`: published plan selection and checkout links.
- `/api/v1/sites/{site_id}/…`: site-scoped checkout APIs. Use the generated contract for the configured site and current source for request details.
- `/portal/{site_id}`: branded member portal with server-enforced site and order ownership.
- `/health`: process health and selected configuration flags; it does not establish successful settlement or full provider readiness.

The older private `/checkout/{campaign_id}/{sku}` route remains an integration entry point. Its invitation mechanism is not the access model for public storefronts. Never publish private invitation or owner setup tokens.

## Payment and persistence contract

Sticky's configured Stripe Connect v2 gateway owns payment authorization and capture. The browser uses the provider-hosted card interface; this backend must never receive raw card numbers or CVV. Provider secrets remain server-side. Supported plans must pass the current configuration, quote and ownership checks; a catalog listing alone does not establish payment eligibility.

Catalog reads use local publications and scoped snapshots. Payment totals and financial transitions retain authoritative provider validation. The browser cannot choose an arbitrary amount, gateway or payment intent. Uncertain results remain durable and require reconciliation; they must not cause an automatic replacement charge.

Fly uses SQLite under `CHECKOUT_STATE_DIR` and one machine/worker. Coordination locks and parts of payment readiness remain process-local. A restart can affect unfinished payment forms. Preserve databases, keys and unresolved attempts; never clear an uncertain result merely to let a customer retry. Inspect the deployed recovery behavior before planning a restart.

See [capture setup reuse](../../docs/CAPTURE_SETUP_REUSE_2026-10-26.md) and [site API performance](../../docs/SITE_API_SPEED.md). These explain which reads are cached and which payment checks must remain authoritative.

## Feature references

- [Owner administration](ADMIN.md)
- [Therapy purchase options](../../docs/THERAPY_PLAN_CHECKOUTS.md)
- [Brand prices and coupons](../../docs/BRAND_COMMERCE.md)
- [Member portal](member_portal/README.md)
- [Sticky membership and password setup](../../docs/STICKY_MEMBER_PASSWORDS.md)
- [Shared post-checkout intake](../../docs/SHARED_POST_CHECKOUT_INTAKE.md)
- [SKU refill policy](../../docs/STICKY_REFILL_SKU_CONTRACT.md)

Dated reports describe what was verified at that time. They are not a guarantee that every optional capability is enabled for every site. In particular, a rendered control does not establish a connected provider operation; read capability responses and integration limits.

## Validation and release

Follow [local development](../../docs/LOCAL_DEVELOPMENT.md) for reproducible setup and focused or full test commands. Backend/browser fixtures use controlled providers. Sticky Dry Run order tests still create provider records and need explicit authorization for their scope. A browser stub is not a live payment verification.

Use [collaboration and releases](../../docs/COLLABORATION.md) and [Fly operations](FLY.md) for deployment. AWS/MySQL compatibility work is a separate target. A passing local suite or a GitHub merge does not deploy either environment. Historical release images in `deployment.json` must be compared with the actual deployed image and newer release evidence before rollback or release decisions.
