# Checkout speed work and correction — 22 October 2026

The owner reported roughly 40 seconds to card entry. Performance remains unresolved. An earlier managed-catalog benchmark improved 5.883 seconds / 46 reads to 2.435 seconds / 3 reads with identical choices/prices, but a later sample measured 8.380 seconds for catalog and 6.304 seconds for a fresh review quote. These are individual read-only samples, not full customer timings or an SLA.

## Current payment interface

checkout-v8.js retains the original Stripe Payment Element and Express Checkout. Continue to payment creates the intent through Sticky authorize_payment after quote/consent checks. Stripe confirmPayment confirms that same intent; Sticky new_order captures it and read-back verifies the result. Card data stays in Stripe's iframe. No independent Stripe charge or new gateway was introduced.

The classic Card Element was briefly deployed in v5. It was an unnecessary widget change and is superseded. v6 was built but never deployed. The deferred Payment Element experiment in v4 did not finish rendering in the live browser, despite stub tests passing. Do not claim those tests established successful live rendering. v8 keeps the original intent-first interface, mounts it visibly, registers readiness before mounting, and shows load failures. Older deployed scripts remain for open pages. The backend's deferred capability remains for compatibility but the active frontend ignores it; future Fly config disables it.

## Preserved improvements

Published managed choices resolve only their configured offer/product/model keys after checking live campaign membership. Product/gateway reads run concurrently, and missing offer details use bounded concurrency. Unmanaged discovery retains complete exact-SKU resolution. No cross-request price cache is used. Quote, authorization and capture still recheck live pricing/configuration and consent. Quotes marked catalogVersion 2 use scoped fingerprints; older saved quotes retain legacy semantics.

Multi-plan prices are prefetched and reused within the same request. The plan handoff validates local published membership before redirecting, avoiding a duplicate live lookup; child configuration and payment endpoints still validate live. HTML bootstraps CSRF, and a fresh visit's start response supplies status.

Each fresh shared-link navigation starts its own anonymous visit. Reload/bank return resumes the attempt saved in that tab. An HttpOnly Secure browser cookie owns the attempt through a stored SHA-256 hash and pinned request header. Private-link access and CSRF still apply. No customer identity is inferred by email, no visit identifier is added to shared URLs, and old held attempts remain intact.

## Validation and release limits

The backend/session/catalog changes passed 196 offline backend tests before the widget correction; backend code is unchanged by v7. The v7 targeted browser checks use fake Sticky services and a Stripe contract stub. They cover the original widget, exact intent/capture behavior, incomplete input, declines, redirect, refresh, uncertainty, price drift, branding and fresh visits. They do not certify live card processing or speed.

The earlier backend releases used the owner's approved restarts, preserving all pre-existing database rows and making on-volume backups. Existing unresolved attempts remain held; their old in-memory client secrets do not survive a restart. The v7 static correction preserves the payment worker and database. Release evidence is recorded in checkout-speed-deployment.json. No authorization/capture is submitted as a hosted health check. No new external credentials or setup are currently required; the remaining problem is checkout latency and end-to-end verification.

## State input correction

The US state dropdown shows full names and submits two-letter codes before quotes and authorization. All 50 states, DC, territories and military addresses are included. Other supported countries retain free-text regions. Three targeted fake-service browser checks passed; the state case verifies CA/NY in quotes and NY in both Sticky billingState/shippingState. The static update preserves the worker/database and existing held attempts. This input fix does not establish the original upstream error or live payment success.

## Nonblocking customer entry and demo catalog refresh

checkout-v9.js is live as a static update without restarting the payment worker.
A new attempt reveals contact/address inputs as soon as its browser-owned state
is confirmed, while the remote configuration loads. Country/state, plan
selection and submission remain gated on validated configuration. Enter cannot
submit early, and text already entered is retained. Held, captured, resumed and
bank-return paths keep their existing state handling. Stripe.js downloads in
parallel with configuration; the original Payment Element, consent,
authorization and capture sequence is unchanged.

The separate demo service now returns its last validated catalog immediately
while a refresh runs in the background. Refreshes are single-flight; the fresh
window is 60 seconds, with a hard 120-second display-data age limit. Failures do
not extend that deadline. This reduces repeated 16-product catalog reads and
prevents a refresh from freezing all demo requests. This cache is only for the
demo's public plan display/handoff mapping. It never caches a payment quote,
authorization, client secret or capture, and it changes no financial validation
in the existing checkout.

Hosted read-only comparison on 22 October: retained v8 reached a typable form in
6.878 seconds; v9 reached it in 2.517 seconds, measured from the demo Continue
click, including cross-app navigation. These are single samples, not an SLA.
The full validated configuration took 6.881 seconds in the v8 run and 17.919
seconds in the v9 run, showing significant upstream variability. Do not claim
that time to card entry or the complete payment flow is solved.

A separate in-machine breakdown measured campaign GET 4.257 seconds, selected
product 0.766 seconds, gateway 0.437 seconds (the latter two concurrent), and
read-only total calculation 0.309 seconds. A legacy campaign read took 1.215
seconds but lacks the active/archive and alternative-payment fields needed for
the existing guards; it was not substituted. Requesting gzip returned the same
110,030-byte identity response and roughly 5-second timing, so no transport
change was made. These checks submitted no authorization or order.

Validation: seven customer browser cases passed, including a deliberately held
catalog response, early-Enter prevention, retained inputs, state codes and held
attempts. Eight additional payment cases passed, covering consent, decline,
redirect, refresh, lost secrets, price drift, duplicate capture and uncertainty.
Fifteen targeted demo backend cases passed, including nonblocking refresh,
single-flight reads and hard expiry. Fake-service checks do not certify live
processor timing. Original worker identity and database hashes matched across
the static deployment. Legacy assets remain for already-open pages.
