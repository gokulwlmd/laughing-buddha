# DHEA / Pregnenolone SR master additions — 2026-10-26

The owner approved all three blends, four durations and paired one-time/subscription SKUs under the existing HRT therapy. The master template is `master-therapy-dhea-preg-sr`. The existing DHEA-only template, products, prices and policies are preserved.

## Source and identity

Source: WLMD Offering Catalog Master Oct 23, Catalog rows 368–379. Only product metadata is stored; no private costs, credentials or patient data.

| DHEA | Pregnenolone | Exact base SKU prefix |
|---|---|---|
| 25 mg | 25 mg | `DHEA-PREG-SRCAP-25-25MG` |
| 25 mg | 50 mg | `DHEA-PREG-SRCAP-25-50MG` |
| 50 mg | 100 mg | `DHEA-PREG-SRCAP-50-100MG` |

Each prefix has `-1M`, `-3M`, `-6M`, `-12M`, plus the corresponding exact base plus `-SUB`: 12 product combinations and 24 master SKUs. Four duration options contain six SKU choices each. Selection is blend strength, duration, then purchase type. Both ingredient amounts are explicit in the product label and catalog metadata.

## Billing and care

Each shipment contains 30 sustained-release capsules / 30 days of supply. Plans contain 1/3/6/12 monthly shipments, with 0/2/5/11 later included $0 deliveries. Both purchase types charge the entire term upfront. Base SKUs do not renew; subscriptions renew after 30/90/180/360 days. Monthly deliveries must not become monthly paid charges on a prepaid term.

Claims open 20 days before the current supply ends; refill child orders retain the purchased SKU. Initial intake is required and bound to the existing HRT mock questionnaire. The sheet says no refill check-in for these rows. Existing identity, ownership, review, entitlement and duplicate-protection gates remain.

Editable draft prices are $59 per 30-day supply multiplied by the full term: $59/$177/$354/$708, equal for one-time and subscription. These are placeholders, not source retail prices. Confirm client prices and provider mappings before publication.

## Import and tests

`import_dhea_preg.py` validates all exact source SKUs, both ingredient strengths, monthly quantities and term math. Preview is the default; application is one additive transaction. It creates 78 records (24 masters, 24 SKU references, 24 refill policies, four purchase options, one template and one variant catalog) and appends three treatments to HRT. Repeat imports do not duplicate records or overwrite subsequent price edits.

21 targeted tests passed across the new blends, prior DHEA/skin masters and refill rules. Coverage includes all purchase pairs, quantity/delivery math, source check-in rules, rollback, price preservation, admin template and refill-policy editing, and an offline annual portal journey with 11 duplicate-protected $0 claims and no twelfth included refill. No provider/real-payment operation is part of these tests or the import.

The release uses the existing shared Fly app, machine and persistent volume, excluding unrelated AWS/MySQL work. A private pre-change database backup is retained on the volume. Existing unfinished payments are preserved under prior owner authorization.

These are master drafts. Client checkout publication, Sticky product/campaign provisioning and live billing acceptance remain separate steps.

## Live result

Deployed image: `registry.fly.io/wlmd-stripe-test-0f89b1bb@sha256:4eadb8480ae326798b3a8fadd2b68599c1bd81064040f3889782f28e256f87c8`.

Live readback verified 24 masters/refill policies, four plans, eight total HRT treatment variants (five DHEA-only and three blends), monthly annual shipment days and the 360-day paid renewal. Platform-wide master count is 499. All prior configuration matched the backup except the approved additive HRT treatment list. Prior payment records were unchanged. Repeat import was a no-op, runtime intake bindings resolved, and public health returned HTTP 200.
