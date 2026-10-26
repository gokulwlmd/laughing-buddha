# Fortify checkout price updates — 24 October 2026

The final-price delay was dominated by repeatedly reading Sticky campaign 195.
An instrumented live read took 6.59–6.67 seconds for the campaign, while Sticky's
actual total calculation took 0.26–0.36 seconds. Complete uncached server quote
resolution took 7.32 seconds without a coupon and 7.81 seconds with one.

The live Lovable cart reproduced the user-visible delay: 6.31 seconds from the
last address field to the total, and 6.85 seconds to apply the existing test
coupon. These were synthetic contact details and read-only price calculations;
no payment authorization, card confirmation, order or identity submission.

## Implementation and financial boundary

- The shared backend reuses campaign setup in process for at most 120 seconds,
  bounded to 64 campaign entries. Concurrent cart items share a single campaign
  lookup. Nothing is persisted or shared between application/API instances.
- Configuration loading warms this snapshot. Every quote still reads the
  selected offer and billing terms, product and gateway, any coupon profile,
  and Sticky's authoritative tax/shipping/discount total. No browser price,
  catalog display price or previously calculated customer total substitutes for it.
- Local site publication, link access and allowed options are checked for every
  request. Expired snapshots and failed forced refreshes have no stale fallback.
  A newly published choice that cannot resolve triggers one fresh setup read.
- Authorization, resume and capture force a fresh campaign read. Changed
  fingerprints, terms, discounts or amounts require a fresh quote and consent;
  they never silently change the amount or bypass existing payment holds.
- Explicit $1 testing retains fresh campaign integration checks on quotes too.
  The separate percentage coupon continues to use Sticky calculation.

Campaign-only edits made directly in Sticky can take up to two minutes to affect
the display/quote setup. They are always rechecked before financial writes.
An empty or expired cache still needs Sticky's slower setup read; the fix targets
repeated final-price updates, not a promise that all external calls are instant.
The Lovable two-step UI and its stale-response/contact binding are unchanged.

## Verification

Targeted backend checks cover setup expiry and failure, concurrent cart access,
current prices/coupons/products, site isolation and changed configuration before
authorization/capture. The older entry-concurrency fixture now checks concurrent
product/gateway reads instead of requiring a redundant campaign read. The API
schema expectation also includes the already-shipped identity/photo routes.

A candidate-code probe against live Sticky returned the current price in 0.84
seconds without a coupon and 1.25 seconds with it. It also confirmed that the
snapshot-backed quote fingerprint matched the forced-fresh financial read.

Release image, final test counts and post-deployment timings are recorded in
`tools/stripe-v2-checkout/deployment.json`. Preserve the existing app and volume.

## Live result

Published to the existing shared app and verified matching backend source hashes.
In a fresh browser on the published Fortify Lovable site, after setup was loaded:

| Measurement | Before | After |
| --- | ---: | ---: |
| Last address field → final price visible | 6.31 s | 2.31 s |
| Apply coupon → discounted price visible | 6.85 s | 2.33 s |
| Quote HTTP response, no coupon | 5.05 s | 1.30 s |
| Quote HTTP response, coupon | 5.85 s | 1.44 s |

The first uncached configuration request after restart took 5.06 seconds. It
runs while customers enter their details; it is not eliminated by this change.
Browser timings include the existing debounce and network latency. These are
individual observed runs, not percentile or load-test guarantees.

The full 516-test run passed 512 cases; four older admin fixtures lacked the
now-explicit offer-detail read. After correcting that fake endpoint, all 34
admin/brand checks passed, including those four. The 110 targeted financial,
prepaid, coupon, cache and API checks and eight Chromium scenarios also passed.
Financial status counts and patient count were unchanged. Browser measurements
created only new quote sessions with synthetic contact details; no card, payment,
order, medical intake or identity operation was submitted.
