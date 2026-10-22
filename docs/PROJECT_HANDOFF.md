# Laughing Buddha project handoff

Laughing Buddha contains WLMD Core, a FastAPI and SQLite checkout administration application in `tools/stripe-v2-checkout`. Resume here and in [the decision record](DECISIONS.md). This handoff carries the product decisions from the earlier “Set up laughing-buddha” conversation, retrieved on 22 October 2026, without copying credentials, private invitations, payment receipts or customer records.

## Repository and protected live service

Repository: `gokulwlmd/laughing-buddha`. The starting checkout was clean at `f109e5151b840687d9a0731d8611acf73048b979`. The Sites and Checkout Templates implementation was still unimplemented in that starting commit.

The existing Fly application is `wlmd-stripe-test-0f89b1bb`, with one worker on machine `84e117f290dd38` and volume `vol_40o3gdk37mo7zy24` mounted at `/data` in `iad`. Treat it as live: it contains owner configuration and payment records, and its Sticky routing can use a live processor. Preserve the app, volume, SQLite database, owner, reviews, links and historical attempts. Never copy this database into development or staging. Production deployment remains a separate operation governed by [FLY.md](../tools/stripe-v2-checkout/FLY.md), including inspection and reconciliation of current pending payments before any restart.

The previous cloud workspace failed to start. That failure did not replace the repository or Fly storage. This continuation uses a writable local checkout; it does not depend on recovering the old cloud machine.

## Product decisions

The everyday admin has two primary screens: **Sites** and **Checkout Templates**. Catalog, therapies, plans, campaign management, prices, billing, existing checkout links and history remain available in **Advanced settings**, including their established hash routes.

The template editor now combines therapy selection or creation, editable duration plans, matching catalog products, payment choices and a customer selection preview. It displays product names and default catalog prices. Incomplete templates can be saved and resumed as drafts; drafts are excluded from new sites and never replace an existing published template. A new therapy saved with a draft becomes available for catalog assignment. The editor owns copies of its plans, so it does not rewrite shared legacy plans.

A Checkout Template is a complete therapy checkout. It contains duration **Plans**, which are the existing `purchase_option` records. A plan contains alternative master SKUs representing treatments. The customer selects **one SKU**, then one of its enabled **Payment choices**. A checkout may display one plan or several. SKU product duration must match the plan exactly. Each duration card shows every treatment's configured price before treatment selection.

Adding a site is a two-step flow: branding, then included checkouts. New branding is the default; reusing an existing brand is optional. A reviewed payment setup can be remembered for future sites, each with independent campaign pricing. The first site requires choosing that payment setup (synthetic staging supplies its demo source). Adding a site includes all enabled templates automatically. The owner selects an existing brand or supplies a new brand design, then selects an accessible Sticky campaign or creates one from reviewed payment and shipping settings. One consolidated preview lists the brand, templates, required SKUs, prices, intervals and exact catalog operations. Only an explicit owner approval applies those operations. Read-back validates configuration before plan links become ready. A missing gateway, inaccessible campaign or unsupported choice must remain incomplete.

Site checkouts inherit brand logo, colors and support details. They initially use hosted URLs and private previews. The site dashboard separates Ready to preview, Published, Paused and Needs attention, with Preview, Copy private preview, Edit checkout and explicit Publish actions. Copy public link appears only after publication. Synthetic public checkouts remain labelled test mode with payments blocked. An owner can explicitly make a checkout public. A custom domain is only pending configuration until DNS and HTTPS have actually been verified.

Later template, plan or master changes show **Update available**. Applying them requires a new review. Preserve customized titles, enabled plans, payment choices, campaign prices, published URL paths, existing subscriptions and legacy brand assignments. Saving a master or template is not permission to modify a campaign automatically.

Do not invent missing treatment SKUs, prices or clinical rules. Billing intervals never establish medication supply, dose, clinical eligibility or refill approval. Existing trial, physical prepaid, shipping/tax, advanced-schedule and processor-verification restrictions still apply.

## Implementation map

| Area | Responsibility |
| --- | --- |
| `admin.py` | Owner authentication, CSRF, configuration, guarded review/apply and reconciliation |
| `sites.py` | Checkout templates, site setup, snapshots, customizations and current readiness |
| `master.py` | Master SKU catalog, independent campaign offers, provisioning and read-back |
| `plans.py` | Therapies, duration plans, parent checkouts and isolated private child links |
| `catalog.py` | Authoritative campaign/SKU, gateway, pricing and payment-choice resolution |
| `app.py` | Quotes and durable payment state machine; staging payment gate |
| `synthetic.py` | Persistent offline demo catalog with payment writes rejected |
| `web/sites-admin.js` | Primary Sites and Checkout Templates screens |

Published plan checkouts retain reviewed snapshots. A private child link is unique to each checkout, plan and SKU, preserving payment-choice access boundaries. Open payments block affected configuration edits. Pending or uncertain writes remain held for reconciliation and must not be automatically resubmitted.

## Resume and collaborate

Read the repository checkout and catalog skills under `.agents/skills`, then [local development](LOCAL_DEVELOPMENT.md), [collaboration and staging](COLLABORATION.md), [the therapy plan architecture](THERAPY_PLAN_CHECKOUTS.md), and the application README, ADMIN and FLY guides. Inspect the actual branch and working tree before changing code.

Check existing Fly authentication, GitHub connector permissions and local Git authentication before requesting credentials. Hosted Sticky secrets already exist on the live app; leave them there. Secrets, setup links, invitation URLs, real contact information and gateway profiles must not enter commits, reports or chat handoffs.

Run backend tests and browser scenarios with disposable state and fake services. Passing offline tests does not verify live processor payments or future rebills. No real charge, owner impersonation, clinical action or live catalog setup is part of routine QA.

## Latest: Master Therapy 1 skeleton

Weight Loss is now a built-in versioned skeleton in Checkout Templates, linked from Therapies. It includes the 16 exact SEMA/TIRZ SKUs and upfront/renewal/fulfillment rules in [MASTER_THERAPY_1.md](MASTER_THERAPY_1.md). The four-plan draft is saved only through the normal owner review flow; deployment itself does not modify stored owner/catalog/review/checkout records. No prices are invented. Activation remains blocked pending prices, exact schedules and verified renewing prepaid support. Existing site creation uses only completed published templates.

## Latest: three therapies and 32 priced master SKUs

The user authorized actual master database records with editable starter prices, adding Sermorelin and Metformin to Weight Loss. See [MASTER_THERAPY_CATALOG.md](MASTER_THERAPY_CATALOG.md) for all 32 SKU codes, price assumptions, term/renewal rules, missing delivery details and the atomic idempotent synthetic-only import. These priced master drafts use `planning_contract`; processor mappings remain empty and activation blocked pending verification. Default prices can be edited through the normal owner-reviewed master form. Existing brand prices, therapy records and saved drafts must not be overwritten.
