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
