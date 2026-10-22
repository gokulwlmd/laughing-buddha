# WLMD Core

Master SKU catalog, branded campaign setup, and Sticky.io Stripe Connect v2 checkout administration.

The current application lives in [`tools/stripe-v2-checkout`](tools/stripe-v2-checkout). It uses FastAPI, SQLite, and a browser-based admin panel, with Stripe Elements handling card entry. It is deployed on Fly.io.

## Continue development

- [Sanitized project handoff](docs/PROJECT_HANDOFF.md) and [decision record](docs/DECISIONS.md)
- [Local development with synthetic data](docs/LOCAL_DEVELOPMENT.md)
- [GitHub collaboration and manual Fly staging](docs/COLLABORATION.md)

The everyday admin starts with **Sites** and **Checkout Templates**. Add a site to prepare branded therapy checkouts from predefined plans and master SKUs in one reviewed setup. Detailed catalog and billing tools remain under Advanced settings.

## Current workflows

- Group master SKUs by therapy and treatment, with editable categories, product duration, and purchase options.
- Define duration purchase options, assign matching SKUs, and build branded checkouts showing each treatment’s price.
- Offer one-time purchases and subscriptions together or with separate prices.
- Configure fixed prepaid test plans with an upfront price, delivery interval, and completion after the selected number of cycles.
- Assign master presets to existing or new brand campaigns after preview and approval.
- Manage branded public/private checkout links, grouped by category.

The project remains an integration harness. Medication fulfillment, trial flows, and other unverified payment configurations retain the limitations described in the application documentation.

## Start here

- [Application setup and payment architecture](tools/stripe-v2-checkout/README.md)
- [Therapy and multi-SKU checkout setup](docs/THERAPY_PLAN_CHECKOUTS.md)
- [Admin workflows and supported features](tools/stripe-v2-checkout/ADMIN.md)
- [Fly deployment and persistent-state requirements](tools/stripe-v2-checkout/FLY.md)
- [Deployment version and verification evidence](tools/stripe-v2-checkout/deployment.json)
- [QA baseline](docs/QA_REPORT.md), [combined purchase choices](docs/COMBINED_PURCHASE_OPTIONS_QA.md), and [category dropdown](docs/CATEGORY_DROPDOWN_QA.md)
- [Reusable project skills](.agents/skills)

Credentials are supplied through environment variables or Fly secrets. Runtime databases, private invitations, installed dependencies, and generated browser artifacts are excluded from version control. Test fixtures use synthetic credentials and fake payment providers.
