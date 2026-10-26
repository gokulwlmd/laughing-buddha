# Remaining catalog review — 26 October 2026

The owner authorized batching clear catalog products and retaining unclear items
as disabled drafts, with a final spreadsheet identifying every unresolved question.

## Scope and decisions

All 788 product rows in the workbook's Catalog sheet are accounted for:

- 306 new product/term combinations: 612 exact base / `-SUB` master SKUs and
  26 draft checkout templates. These have mapped source identity, supply,
  shipment count and refill check-in flags.
- 239 source rows already represented by existing masters: preserved unchanged.
- 243 clarification records: saved as disabled `catalog_review` drafts, without
  executable master SKUs, purchase options, provider mappings or refill rights.

Clear additions include the remaining reviewed HRT formulations, Sermorelin
1 mg RDT, Sirolimus/Zinc, Apomorphine troches, Oxytocin sublingual tablets,
Dutasteride and Minoxidil tablet variants, and the dose-specific testosterone
cypionate rows. Existing therapy umbrellas are retained. Larger strength lists
are split into selector groups to retain the 20-SKU purchase-option limit.
The therapy model now accepts up to 256 distinct treatments; uniqueness remains
validated. Biest transdermal and vaginal gels remain separate product families.

Source names and SKUs are retained. No concentration is inferred from vial
volume. Twice-weekly patch rows whose carried source directions say once weekly
are held. Other held groups include incomplete peptide formulations, ambiguous
ED blends, legacy aliases, source form mismatches, urgent-care course definitions,
and labs/packs that require a distinct one-time service or pack workflow.
Previously excluded Minoxidil/Finasteride remains held. Existing ASTV holds and
all historical master decisions are untouched.

Base SKU means full-term upfront, one-time. Exact base plus `-SUB` means the
same term upfront and renewal after term months multiplied by 30 days. Shipment
timing is independent. Included refills equal shipments per charge minus one,
not the prescription's authorized refill count. Claim lead time remains 20 days.
Initial intake stays required. Source refill check-in flags are preserved.
TRT and Longevity gain explicit mock-intake bindings, not a clinical integration.

New prices are editable placeholders of USD 59 per term month, equal for both
purchase types. "Finalized" concerns master structure only. Site selling prices,
provider mappings and publication still require their existing setup workflow.
This task does not create Sticky products, payment offers, subscriptions or orders.

## Implementation and review

- `remaining_master_catalog.json` contains approved recipe metadata and all
  source review rows. It excludes internal costs, credentials and patient data.
- `import_remaining_masters.py` performs an atomic additive import with a
  catalog fingerprint and idempotent run marker. It only extends existing therapy
  treatment lists; existing masters, prices, templates and assignments are preserved.
- Authenticated `GET /api/admin/catalog-review` returns the review records.
- The master catalog has a searchable, collapsed clarification list. It has no
  activation button and no path from a review draft into a checkout selector.
- `outputs/catalog-review-20261026/Master-catalog-review.xlsx` provides an overview,
  new finalized recipes, clarification questions with editable answer cells, and
  existing source rows. Spreadsheet answers do not automatically activate anything.

## Validation and release

Seven catalog tests verify all-row accounting, pairs, exact schedules and renewal
intervals, intake bindings, held-item exclusion, selector limits, existing-record
preservation, repeat import behavior, admin authentication and template editing.
58 core master/plan/refill tests passed. One browser check verifies the searchable
243-item clarification list, the held Minoxidil/Finasteride entry, 16 patch holds,
and absence of publish controls. No live provider order was submitted.

The workbook was recalculated, inspected for formula errors, rendered on every
sheet and read back after export. Source-row totals, native filter tables and
cached summary values were verified.

Shared Fly image:
`registry.fly.io/wlmd-stripe-test-0f89b1bb@sha256:d7ca938650a2c5a4468dc26e6802d03ad68f4c16c3402ed23ede2a39e558cb0d`

Private pre-import backup remains on the existing volume at
`/data/remaining-catalog-20261026-before.sqlite3`. No database was copied into the
repository. The pre-release inspection found 21 unfinished forms and no capture
in progress. The same machine and database volume are retained. Health returned
200; the served admin asset matched the local SHA256; anonymous review API access
returned 401. Unrelated AWS/MySQL work was excluded from the clean release.

Post-import read-back confirmed 1,111 total master SKUs, all 612 new bindings,
26 new templates and 788 review rows. The repeat import created zero records.
Only four existing therapy treatment lists were extended (Sermorelin, ED, Hair
Growth and HRT). All previous master/template/config records outside those lists,
and all previous checkout/purchase rows, were preserved.
