# Hair Growth, NAD+ and Glutathione master templates

Installed and read back on the existing live Fly app
`wlmd-stripe-test-0f89b1bb` on 25 October 2026. The additive transaction created
88 configuration records. All pre-existing configuration values were verified
unchanged. Repeat preview confirmed an already-installed result with zero new
records. No application restart was required.

Owner-approved scope: reproduce the selected Anuwell product structures using
the WLMD catalog's exact SKU codes, with one-time and `-SUB` purchase pairs.
Reference Anuwell commit: `5e49a9532316abddb26e979c98242c29dc390665`.
Prices are editable starter values from that reference, not live brand quotes.

## Included catalog

| Therapy | Products and terms | Base variants | Paired master SKUs |
| --- | --- | --- | --- |
| Hair Growth | Finasteride 1 mg: 3/6/12 months; Finasteride/Minoxidil topical: 3 months; Minoxidil 1 mg/Spironolactone 60 mg: 3 months | 5 | 10 |
| NAD+ | Injectable and nasal, each 1/3/6/12 months | 8 | 16 |
| Glutathione | Injectable, 1/3/6/12 months | 4 | 8 |

Three therapies, eleven duration purchase options and three template drafts.
Each base SKU charges the full term once with no renewal. Its exact `-SUB`
counterpart charges upfront and renews after 30/90/180/360 days for the
corresponding 1/3/6/12-month term. Both purchase types start at the same price.

Source rows specify one shipment for 1/3-month plans, two for 6-month plans,
and four for 12-month plans. Later included deliveries cost $0 and are spaced
90 days apart. Source rows list no required check-in; this does not establish
clinical eligibility or approve treatment. Site intake policies remain separate.

Hair products shared by men's and women's navigation use one master SKU pair,
not duplicated products. Collection membership is reference navigation metadata,
not a clinical eligibility rule. Format and variant metadata live in the
`therapy_variant_catalog` records. Customer selector changes require site
publication; importing these drafts alone does not add a public API or checkout.

## Explicit source discrepancies and exclusions

- `MIN-1MG-FINA-1.25MG`: Anuwell describes an oral combination (90 count,
  3 months); workbook row 278 describes Liquid, 90 mL, with topical directions.
  Excluded pending owner confirmation rather than assigning the wrong form.
- `FINA-10-MINO-6`: retained under the source name Finasteride/Minoxidil
  topical. Anuwell has a 0.1%/6% label under a different SKU. No concentration
  is inferred from our SKU. Verify concentration before site activation.
- NAD uses `NAD-INJ-*` and the exact source nasal codes (`NAD-NASAL-1M`,
  `NADNASAL-3M`, `NADNASAL-6M`, `NADNASAL-12M`). The separately listed
  `NAD-INJ-200MG-10ML-*` and `NAD-RDT-100MG-*` families are not substituted.
- Finasteride's source 9-month plan and Anuwell's coming-soon Minoxidil and
  Dutasteride variants are outside this approved reference selection.
- Package strings are retained verbatim because the source varies between
  term quantities and shipment quantities. Do not infer vial concentrations
  or dispensing totals from them.

## Installation and limits

`tools/stripe-v2-checkout/wellness_master_catalog.json` contains only product
metadata, editable reference prices and source-row identifiers. No internal
costs, patient data, credentials or provider product IDs are included.

`import_wellness_masters.py --database /path/to/checkout.sqlite3` previews the
88-record addition. `--apply` installs atomically on the authorized target.
The importer rejects collisions, never creates a missing database, and preserves
owner edits on a repeated run. A changed source or incomplete import requires
explicit reconciliation. Run marker: `owner-approved-hair-nad-glutathione-v1`.

This is master configuration only. Templates remain drafts until site-specific
fulfillment mappings, pricing and billing have been verified and published.
No Sticky products/offers, campaign routing, orders or payments are changed.
The schema's legacy fulfillment-source default is not an approved mapping.
There is no app restart and no AWS or Lovable deployment in this operation.

## Validation

Twenty tests passed across `test_wellness_masters` and `test_ed_master`.
Coverage includes complete purchase pairs, exact source codes, shipment and
renewal schedules, admin API visibility and editing, collision refusal,
transaction rollback, preservation of existing records and no provider calls.
These checks validate catalog behavior, not payment processing or fulfillment.
