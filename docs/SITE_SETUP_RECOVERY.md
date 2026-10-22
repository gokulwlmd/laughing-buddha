# Site setup recovery — 22 October 2026

The setup stopped after creating its first product because Sticky filled absent weight/unit fields with 0/unit 1 for a non-shippable item. All other checked product fields matched. The old code necessarily stopped at that read-back, before the first offer request. The guard correctly prevented a second review from duplicating the partial setup, but exposed only a generic reconciliation error.

The approved setup on campaign 423 has now finished: product 55906 was reused, 40 product IDs and 40 offer IDs are recorded, and four private therapy checkouts are ready. No price override, payment, refund, cancellation or medication fulfillment was submitted. The existing owner account and prior payment rows remain preserved.

`product_contract_matches` accepts only the observed empty-weight defaults for non-shippable products. Stored contracts and fingerprints retain their serialization. Explicit weights, nondefault units, shipping, tax, SKU, category and restrictions remain checked. Admin execution records operation index/stage before each write and retains created IDs after failures. It performs no automatic write retry. A request-local cache is used only for read-back/finalization after the writes finish.

`tools/stripe-v2-checkout/reconcile_site.py REVIEW_ID` is an operator-only read-only preflight. `--apply` resumes only the verified legacy failure with exactly the first product recorded, the original product matching all other fields, unchanged local/remote guards, and no campaign payment in progress. It backs up SQLite privately, reuses the product ID, and runs the remaining original approved operations. It cannot approve a draft, resume other uncertain stages, change approved payloads or fabricate an owner/session. The audit table is admin_recoveries. Never use it as a general retry command.

200 backend tests passed. Five targeted browser cases passed (CUS-06, SITE-01/02/03/06), covering site creation/update/reuse, mobile customization, unavailable gateway handling, saved connection/publication and state-code transmission. Two obsolete duration-first assertions were corrected for the existing medication-first flow; no application selection behavior changed for those assertions. Fake-service tests do not certify real payments.

The permanent image is built but not yet deployed because a new live card form opened during the work. Await the owner's response to the restart question. The recovered site is already saved and available on the current worker. No external credentials or account setup are required.
