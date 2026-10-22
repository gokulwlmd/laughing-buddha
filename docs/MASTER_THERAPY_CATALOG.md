# Master therapy starter catalog

The owner requested actual database SKUs and two additional therapies from screenshots on 22 October 2026. The catalog contains 32 exact SKUs, three therapies, twelve duration plans and associated checkout drafts:

- Master Therapy 1: Weight Loss — Semaglutide (`SEMA`) and Tirzepatide (`TIRZ`), 16 SKUs.
- Master Therapy 2: Sermorelin — `SERM`, 8 SKUs.
- Master Therapy 3: Metformin — `METFORM`, 8 SKUs.

For each prefix, create `PREFIX-1M`, `PREFIX-3M`, `PREFIX-6M`, `PREFIX-12M` and the corresponding `-SUB` versions. All charge the full term upfront. Non-SUB has one charge and no renewal; SUB charges the full term again after the same number of calendar months. These are separate SKU records.

## Editable starter prices

Prices below are implementation-selected USD starter defaults authorized by the owner, not claims about market prices or medical value. Tirzepatide's monthly reference retains the earlier $449 catalog starting point. All other rates are new starter assumptions. Multiply the monthly reference by term length, without a discount. One-time and SUB begin with the same full-term amount, but are independent editable master records.

| Treatment | 1 month | 3 months | 6 months | 12 months |
| --- | ---: | ---: | ---: | ---: |
| Semaglutide | $249 | $747 | $1,494 | $2,988 |
| Tirzepatide | $449 | $1,347 | $2,694 | $5,388 |
| Sermorelin | $199 | $597 | $1,194 | $2,388 |
| Metformin | $49 | $147 | $294 | $588 |

Edit **Advanced → Master SKUs → Edit default price**. This saves a master catalog revision through the existing owner review flow. It never replaces an existing brand offer price. After verified campaign assignment is supported for these contracts, the existing brand/campaign price workflow retains independent prices and preserves old subscriptions.

## Billing and delivery boundaries

Weight Loss six-month terms include two shipments; twelve-month terms include four, with no additional charge inside a paid term. Counts for one/three-month Weight Loss plans and all Sermorelin/Metformin plans are unspecified. The new screenshots provide no shipment schedule, so none is inherited from Weight Loss. Exact shipment timing remains unset for every recipe. Do not infer dosage, supply, medical eligibility or fulfillment approval.

These are real saved master catalog records with prices and `planning_contract`, not executable processor offers. `billing_models` is empty for these drafts. The backend blocks campaign assignment and template activation until calendar-month billing, fulfillment and any prepaid renewal are verified. It also rejects replacing an existing active SKU with a planning draft or removing an existing draft's contract to bypass verification. Standard masters still require configured billing models.

## Reproducible database import

`tools/stripe-v2-checkout/import_master_therapies.py` is an explicit, additive, atomic import. It accepts only synthetic staging or localhost. Run from the checkout directory with the existing synthetic application's environment:

```sh
python -m import_master_therapies
```

For the local import command, set `CHECKOUT_ENVIRONMENT=development`, `CHECKOUT_PUBLIC_URL=https://localhost` and `CHECKOUT_STATE_DIR=.state/development`. The import makes no HTTP calls; the local server still runs using `dev.py` at `http://localhost:8081`. It creates no owner or session and makes no Sticky/payment requests. Compatible existing therapy definitions and owner-created drafts are preserved. Any SKU or plan collision stops the whole import. An `admin_setup_runs` marker prevents duplicate imports or overwriting later price edits; missing recorded rows require explicit reconciliation.

The import is not automatic on startup. It must never run against production or replace a live catalog. The staging release records import counts and verifies that pre-existing configuration, owners, reviews and checkouts remain unchanged. The source, import and tests are committed so collaborators can reproduce the same setup locally.
