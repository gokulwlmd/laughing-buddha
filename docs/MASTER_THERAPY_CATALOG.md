# Master therapy starter catalog

The owner requested actual database SKUs and two additional therapies from screenshots on 22 October 2026. The catalog contains 40 exact SKUs, four therapies, sixteen duration plans and associated checkout drafts:

- Master Therapy 1: Weight Loss — Semaglutide (`SEMA`) and Tirzepatide (`TIRZ`), 16 SKUs.
- Master Therapy 2: Sermorelin — `SERM`, 8 SKUs.
- Master Therapy 3: Metformin — `METFORM`, 8 SKUs.
- Master Therapy 4: PT-141 — `PT141`, 8 SKUs, using the exact screenshot codes.

For each prefix, create `PREFIX-1M`, `PREFIX-3M`, `PREFIX-6M`, `PREFIX-12M` and the corresponding `-SUB` versions. All charge the full term upfront. Non-SUB has one charge and no renewal; SUB charges the full term again after 30/90/180/360 days for 1/3/6/12-month plans. These are separate SKU records.

## Editable starter prices

Prices below are implementation-selected USD starter defaults authorized by the owner, not claims about market prices or medical value. Tirzepatide's monthly reference retains the earlier $449 catalog starting point. All other rates are new starter assumptions. Multiply the monthly reference by term length, without a discount. One-time and SUB begin with the same full-term amount, but are independent editable master records.

| Treatment | 1 month | 3 months | 6 months | 12 months |
| --- | ---: | ---: | ---: | ---: |
| Semaglutide | $249 | $747 | $1,494 | $2,988 |
| Tirzepatide | $449 | $1,347 | $2,694 | $5,388 |
| Sermorelin | $199 | $597 | $1,194 | $2,388 |
| Metformin | $49 | $147 | $294 | $588 |
| PT-141 | $199 | $597 | $1,194 | $2,388 |

Edit **Advanced → Master SKUs → Edit upfront plan**. The editor exposes **Pay upfront**, **Total upfront price**, **Number of shipments** and **Ship every (days)**, with a live shipment timeline. This saves a master catalog revision through the existing owner review flow. It never replaces an existing brand offer price. After verified campaign assignment is supported for these contracts, the existing brand/campaign price workflow retains independent prices and preserves old subscriptions.

## Billing and delivery boundaries

All four therapies now use the owner's explicit default: **6 months = 2 shipments every 90 days; 12 months = 4 shipments every 90 days**. Shipment 1 is at purchase, so the six-month timeline is days 0/90 and the twelve-month timeline is days 0/90/180/270. Later shipments inside the term cost $0. Counts and intervals for one/three-month terms remain unset.

Shipment count and interval are editable per master SKU. Saving rebuilds its persisted `product_setup`: prepaid cycle count, shipment days, total upfront price, currency, per-shipment product price when divisible into exact cents, and the fixed-term processor configuration where applicable. The review shows these before and after. Templates display each SKU's currently saved schedule, including overrides. Removing a schedule does not invent an alternative. Edits preserve the agreed full-term charge and SUB renewal term; renewing prepaid remains unverified. This changes the saved product plan only; existing brand offers, subscriptions and remote Sticky objects retain their approved setup.

Renewal uses the explicitly agreed day intervals. Do not infer dosage, supply, medical eligibility or fulfillment approval from either billing or shipping.

These are real saved master catalog records with prices and `planning_contract`, not executable processor offers. `billing_models` is empty for these drafts. The backend blocks campaign assignment and template activation until day-based billing, fulfillment and any prepaid renewal are verified. It also rejects replacing an existing active SKU with a planning draft or removing an existing draft's contract to bypass verification. Standard masters still require configured billing models.

## Reproducible database import

`tools/stripe-v2-checkout/import_master_therapies.py` is an explicit, additive, atomic import. It accepts only synthetic staging or localhost. Run from the checkout directory with the existing synthetic application's environment:

```sh
python -m import_master_therapies --all
```

For the local import command, set `CHECKOUT_ENVIRONMENT=development`, `CHECKOUT_PUBLIC_URL=https://localhost` and `CHECKOUT_STATE_DIR=.state/development`. The import makes no HTTP calls; the local server still runs using `dev.py` at `http://localhost:8081`. It creates no owner or session and makes no Sticky/payment requests. Compatible existing therapy definitions and owner-created drafts are preserved. Any SKU or plan collision stops the whole import. Separate `admin_setup_runs` markers preserve the historical three-therapy import, the additive PT-141 import and the shipment-default update, and prevent duplicate imports or overwriting later price edits; missing recorded rows require explicit reconciliation.

The default import is not automatic on startup and remains synthetic-only. The separate, explicitly authorized `promote_live(application)` entry point accepts only the existing live hostname, adds missing drafts, and preserves existing SKUs rather than replacing their setup. The staging release records import counts and verifies that pre-existing configuration, owners, reviews and checkouts remain unchanged. The source, import and tests are committed so collaborators can reproduce the same setup locally.


## Shipment default migration

The original three-therapy import keeps its historical scope. `add_pt141()` adds only the eight PT141 masters, their mappings, therapy, four plans and checkout draft. `upgrade_shipments()` fills missing schedules on unassigned six/twelve-month catalog drafts and enables Pay upfront in their imported duration plans. It preserves prices, unrelated records and already-configured owner schedules. The update runs once; subsequent imports never reset later shipment edits. The import and update are local/synthetic-only and create no owner/session, approval or remote payment/catalog writes.


## Owner-authorized live promotion

The owner explicitly switched the shared workspace to the existing live app. After deploying this source there, an authenticated operator can run `from app import app; from import_master_therapies import promote_live; promote_live(app)` in the application directory. This is deliberately separate from the default synthetic import and is restricted to the existing live hostname. It adds missing SKU drafts and their plans atomically, creates no owner/session/approval, never contacts Sticky and preserves existing SKU definitions. Existing TIRZ-1M is kept with its earlier billing setup and omitted from the newly generated one-month duration plan. Review that conflict separately before enabling the new intended one-time choice. Existing checkout links, prices, offers and pending payments retain their records. Repeat promotion uses its persisted setup marker rather than resetting later edits.
