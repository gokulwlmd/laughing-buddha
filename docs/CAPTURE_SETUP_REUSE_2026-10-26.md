# Same-authorization campaign setup reuse

The final payment step repeatedly fetched the entire Sticky campaign after it
had already been verified for that authorization. A recent transaction spent
35.4 seconds on this configuration read and 3.0 seconds creating the order.
Read-only probes also measured 7.9–10.5 seconds before response headers, versus
roughly 30–55 milliseconds reading the body. Compression did not remove the delay.

The shared checkout engine now retains a sanitized campaign snapshot from the
forced-fresh authorization check for one capture of that exact attempt, campaign,
quote and PaymentIntent. Its absolute lifetime is 30 seconds from completion of
the campaign read, including authorization and any subsequent card challenge.
It is bounded to 128 entries, process-local, consumed once and never returned to
the browser. Display snapshots cannot grant this reuse. Resume discards it.

Capture still fetches the selected offer, product, gateway profile, coupon and
authoritative total. It still checks local publication/access, the fingerprint,
price, currency, renewal terms, consent and owned intent. Missing/expired tickets,
restart and resumed payments use the complete campaign read. If other reads
exhaust the window, capture performs full validation before the financial write.
Existing state claims, uncertain-write holds and verified order readback remain.

Tradeoff: an external campaign-only configuration edit can take up to 30 seconds
to affect this already-authorized payment. This is deliberately not a claim that
every campaign field is reread immediately before capture. Gateway profile,
selected product/offer, coupon and actual order total are still checked live.
Authorization always reads the full current campaign; legacy unscoped checkouts
retain their prior validation path.

A read-only comparison on the live Fly machine measured full configuration
resolution at 9,348 ms versus 1,273 ms using the same authorization setup, with
identical fingerprints and selected options. This measures configuration only,
not end-to-end payment latency or a new live charge.

Validation covers ticket expiry/isolation/one-use/bounded memory, actual selected
reads, expired windows during calculation, missing tickets, resume, product and
offer drift, gateway key drift, local link disabling, changed totals, invalid
coupons, captured retries and uncertainty without another order submission.
All 218 targeted backend tests passed. No customer payment was submitted for testing.

Pre-release backup: `/data/backups/capture-speed-1793034740`, 39 SQLite files and
two encryption keys. All 22 previously unfinished payment records matched the
prior preserved snapshot. This release does not migrate or delete any records.

Released to the existing shared Fly app with immutable image:
`registry.fly.io/wlmd-stripe-test-0f89b1bb@sha256:f68af9803a2acdde88deb881b50723b49649ddec91a8ad109dbf0549daaa21a5`.
Public health returned HTTP 200 with authorization verified and payments enabled.
The previous image remains available for rollback:
`registry.fly.io/wlmd-stripe-test-0f89b1bb@sha256:6f1131dc5d8a2d5a0f51505ccaca30a1767020cce52ad36f9ae8128d3312f2ee`.
