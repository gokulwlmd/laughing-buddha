# Site API speed — 23 October 2026

The API performance update is deployed to the existing separate API machine and
volume. It needs no frontend changes. The live payment worker was not restarted;
preflight found no API financial operation in flight, and saved session access
still worked afterward. No authorization, Stripe confirmation or capture was
called during verification.

| Operation | Before | After |
| --- | --- | --- |
| First plan-list request | 6.843 s | 0.312–0.335 s |
| Session creation | 0.453 s | 0.331–0.372 s |
| First uncached configuration | 5.452 s | 3.447 s |
| Cached configuration | 3.851 s (previously refetched) | 0.312–0.321 s |
| Fresh quote | 3.680 s | 3.205–7.643 s |

These are one before run and two after runs from the same client, not a load
test or latency guarantee. The first after configuration was uncached; the
second customer's configuration reused the same plan's public display data.
After-deployment server time was about 1 ms for plans, 36–56 ms for session
creation and 14–17 ms for cached configuration. Network transit added roughly
300 ms from this client. Fresh quote time is still variable and is not claimed
to have improved. Complete live payment duration remains unmeasured.

## Changes and boundaries

- A lifecycle worker maintains the plan catalog every 15 seconds, refreshing
  after its existing 60-second freshness interval. The 120-second hard maximum
  display age remains; an outage never extends it. Initial startup may still
  wait for its first catalog read.
- A bounded, per-link/selection display cache shares only public configuration
  for 60 seconds. It coalesces concurrent misses and checks each session/link
  upstream before reusing a cached value. It holds no contact, CSRF, cookies,
  payment status, client secrets or authoritative quotes.
- Eight exclusive-use HTTPS connections can be reused. Cookies are supplied
  separately per request, connections idle for four seconds are retired, and
  failures never trigger automatic retries.
- Payment preparation overlaps only the configuration and status reads. Both
  must finish successfully before authorization/resume. Fresh quote, route,
  consent, intent ownership and capture/read-back checks are unchanged.
- Server-Timing exposes application duration for integrations to measure.

The original engine still resolves campaign, offer, product and gateway data
from Sticky and serializes financial routes. Those checks explain the remaining
fresh-pricing/payment work; this release does not remove them or replace the
Stripe Payment Element. Account credentials and existing attempts are preserved.

## Verification

All 255 backend tests passed, including bounded cache expiry, access after a
link is disabled, two-session isolation, concurrent misses, TLS reuse without
shared cookies, no network retries, read/write ordering, price/route drift,
consent, lost replies and restart recovery. Hosted checks verified two new
sessions, draft totals, cached responses, the retained prior test session,
bearer protection and any-origin CORS. Swagger remains unchanged.

Reproduce from the repository root:

```sh
.venv/bin/python scripts/benchmark_site_payment_api.py --rounds 2 --output /private/tmp/site-api-latency.json
```

The script creates only isolated sessions and synthetic draft quotes. Its output
contains timings and public totals, with no tokens, session IDs or contact data.
The deployed digest, runtime hashes and sanitized raw observations are recorded
in `tools/stripe-v2-checkout/site-api-speed-deployment.json`.
