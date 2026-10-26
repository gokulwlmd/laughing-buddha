# Skin Care topical master additions — 2026-10-26

The owner approved both one-time and subscription options for the 30-day packs and 90-day versions of four products. These are reusable master drafts in the shared Fly admin, not published client checkouts or provider products.

## Exact source and clarified identity

Source: WLMD Offering Catalog Master Oct 23, Catalog rows 744–745, 751–754 and 758–759. Internal costs and patient data are excluded.

| Product | Exact 30-day base SKU | 90-day SKU |
|---|---|---|
| Estriol / Vitamin C / Hyaluronic Acid | `DERM-EST-VC-HYA-TOPICAL` | Same base + `-3M` |
| Hydroquinone / Kojic Acid / Niacinamide | `DERM-HYDROQ-KOJI-NIACIN-TOPICAL` | Same base + `-3M` |
| Salicylic Acid / Zinc Oxide / Niacinamide / Urea | `DERM-SLCYLC-ZOX-NIACIN-UREA-CREAM` | Same base + `-3M` |
| Tretinoin / Niacinamide / Vitamin C | `DERM-TRET-NIACIN-VC-TOPICAL` | Same base + `-3M` |

The sheet labels 30-day entries as packs, not monthly subscriptions. The owner explicitly approved offering subscriptions too. Base SKUs are full-term upfront one-time purchases; each exact base plus `-SUB` is recurring. There are eight product/size combinations and 16 paired master SKUs.

Row 753 omits Urea in its name while including it in the SKU. The owner explicitly confirmed: **Include Urea—the SKU is correct.** Both 30- and 90-day versions therefore include Urea. The source discrepancy and resolution are stored in the catalog metadata. No variant is held after this confirmation.

## Supply and portal rules

- 30-day pack: one 30-gram shipment; subscription renews every 30 days.
- 90-day product: one 90-gram shipment; subscription renews every 90 days.
- No included free refills: the next supply is a paid purchase or renewal. Do not convert Rx-authorized refill counts into prepaid entitlements.
- Initial intake remains required. These rows specify no refill check-in. Existing identity, review, ownership and billing gates remain in place.
- Exact SKU intake bindings point to the existing backend Skin Care mock questionnaire. This does not connect an external medical provider.
- Editable draft prices: $59/30 days and $177/90 days, initially equal across purchase types. Confirm site selling prices before publication. Existing HydraBoost/Copper Peptide prices remain unchanged.

## Admin setup

The new combined `master-therapy-skin-care-topicals` draft has two duration groups. It includes the new products plus existing HydraBoost and Copper Peptide choices: 12 SKUs at 30 days, 10 at 90 days. Existing Skin Care therapy, templates and prices are preserved; four treatments are appended to the existing therapy.

`import_skin_topicals.py` previews by default and applies an additive transaction. It creates 52 configuration records: 16 masters, 16 SKU references, 16 refill policies, two purchase options, one template draft and one source/variant record. Repeat import is a no-op that preserves subsequent price edits. Conflicts fail rather than overwrite existing master billing settings.

No Sticky product/campaign writes, real orders or payment operations are part of this change. Site publication and gateway verification remain separate.

## Validation and release

32 targeted tests passed with the confirmed eight-product catalog: source SKU/quantity contracts, full-term upfront billing, 30/90-day renewal, no included refill entitlement, mock intake bindings, combined template selection, conflict rejection, atomic rollback and edited-price preservation, plus earlier catalog and refill regressions.

The runtime image is `registry.fly.io/wlmd-stripe-test-0f89b1bb@sha256:0c783b542f75193f4611c660b5c390fe5741085be6fddedb3b1f30d4aff4b787`. It reuses the existing shared Fly app, machine and volume, and excludes unrelated AWS/MySQL changes. Preflight preserved the existing unfinished payment records and created a private database backup on the volume. No backup/customer data is stored in GitHub.

Live readback confirmed all 16 new masters and refill policies, 435 platform-wide masters, and 22 SKU choices across the combined template's two duration groups. Both Urea sizes are included. Existing configuration (except the intended Skin Care treatment addition), master prices and all prior purchase/checkout rows were preserved. Repeat import was a no-op. Runtime intake bindings resolved and public health returned HTTP 200.
