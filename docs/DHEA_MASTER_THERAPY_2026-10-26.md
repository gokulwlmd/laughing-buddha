# DHEA sustained-release master therapy — 2026-10-26

The owner approved all five DHEA strengths and four source terms with paired one-time and subscription SKUs. The new master draft is `master-therapy-dhea-sr`, under therapy `hrt` (HRT). This is reusable master configuration, not client publication or live Sticky billing acceptance.

## Source catalog

Source: `WLMD_Offering_Catalog_Master_Oct 23_INTERNAL ONLY.xlsx`, Catalog rows 348–367. The saved catalog includes product metadata only, with no internal costs, credentials or patient information.

- Strengths: 5, 10, 15, 25 and 50 mg.
- Exact base pattern: `DHEA-SRCAP-{strength}MG-{1|3|6|12}M`.
- Subscription is each exact base plus `-SUB`: 20 product combinations, 40 master SKUs.
- Form: sustained-release capsule. Every shipment contains 30 capsules / 30 days of supply.
- Four duration options contain all five strengths and both purchase types: 10 SKUs per option.
- Customer choice order is strength, duration, purchase type. Strength choice does not establish clinical approval.

## Billing, delivery and portal rules

| Term | Capsules per shipment | Shipments | Included later deliveries | Subscription renewal |
|---|---|---|---|---|
| 1 month | 30 | 1 | 0 | 30 days |
| 3 months | 30 | 3 | 2 | 90 days |
| 6 months | 30 | 6 | 5 | 180 days |
| 12 months | 30 | 12 | 11 | 360 days |

Both purchase types charge the full term upfront. Base SKUs do not renew. Monthly intermediate deliveries are included at $0; they are not additional monthly payments. Refill claims open 20 days before each supply ends (annual plan: days 10, 40, …, 310). Existing entitlement, ownership, identity, review and duplicate-protection gates remain. Refill orders retain the purchased SKU.

Every source row marks refill check-in No. Initial intake remains required, bound by exact SKU to the backend HRT mock questionnaire. The admin policy editor includes HRT. This does not connect an external medical provider or certify a clinical questionnaire.

Prices are editable placeholders: $49 per 30-day supply, multiplied by the term ($49/$147/$294/$588), initially equal for one-time and subscription. Confirm client selling prices and provider mappings before publication.

## Import and validation

`import_dhea_masters.py` verifies the complete source matrix and monthly supply math. It previews by default and applies one additive transaction with a unique run marker. Repeated imports preserve subsequent price changes and create no duplicates.

127 new configuration records: 40 masters, 40 SKU references, 40 refill policies, four purchase options, one HRT therapy, one template draft and one source/variant catalog. No existing therapy, site, checkout or master is replaced.

22 targeted tests passed, including prior skin/catalog/refill regressions and an authenticated admin template/policy edit. Offline annual portal verification exercised 11 $0 monthly claims, early-window blocking, duplicate protection, same-SKU child orders and exhaustion of entitlement. Pair validation covers full-term upfront one-time versus renewing contracts. JavaScript syntax passed. No real card, order, pharmacy or provider action is part of this work.

Release image: `registry.fly.io/wlmd-stripe-test-0f89b1bb@sha256:32e4f1dc261155eaf0bb804752529a33645d90e5e6d9ca5f2c657084ecbb4eec`.

The release reuses the existing shared Fly app, machine and volume. Unrelated AWS/MySQL work is excluded. A private database backup remains on the persistent volume; it must not be copied to GitHub. Existing unfinished payments are preserved under prior owner authorization.

Live readback verified all 40 masters and refill policies, four plans, five strengths and the annual monthly-delivery/360-day renewal contract. There are 475 master records platform-wide. All prior configuration and purchase/checkout rows were preserved; repeat import was a no-op. Runtime intake bindings resolved. Public health and the served HRT admin asset were verified.
