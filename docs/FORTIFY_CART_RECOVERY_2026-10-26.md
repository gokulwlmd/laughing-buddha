# Fortify cart payment recovery

## Problem

A prepayment failure could leave the storefront item in `review` even when the
backend still reported a fresh, quoted checkout with no payment intent or order.
The recovery code accepted a fresh backend result only for local `cart`/`ready`
items. Consequently, checking status could never unblock the failed item.

The reported case was inspected with narrowly scoped read-only queries. The
checkout engine was `new`; the API session was `quoted`, with no busy operation,
hold, payment intent or order. No customer identifiers or raw diagnostic data are
included here. A later read-only pricing check found the same amount and plan but
a different configuration fingerprint from the saved quote. Repeated fresh reads
were stable. The original HTTP failure was not retained, so that fingerprint
difference is not conclusive evidence of the original trigger.

## Recovery contract

- Recover the same session after an exact backend `new`/`quoted` result only when
  there is no local or backend payment intent, order, receipt or capture evidence.
- Refresh the quote and require an explicit customer payment click. Status
  checks must not create sessions, authorize, confirm or capture payments.
- A confirmed card decline can retry the same payment intent with another card.
- Unknown confirmation/capture results remain held. Preserve partial successes
  and never recharge a confirmed item.
- A retryable error should retain the current form and payment step in memory.
  Contact and card data must not be added to browser persistent storage.
- Use “Processing your payment” and “Pay [total]”. Do not show internal order
  splitting in the primary CTA or a single-product cart. For multiple products,
  retain a discreet, truthful disclosure about separate charges.

## Scope

The fix belongs to the existing Fortify Lovable storefront. The shared Fly
payment engine, provider configuration and customer records are preserved.
No live payment, provider order, subscription change or clinical write is part of
this verification.

Backend guard verification on the deployed release source: 27 session API and
parallel-request tests passed. These use offline providers.

Lovable source commit: `97d903845c7d7cf674e5265772be312631e2a71d`.
Source review confirmed the same-session recovery, durable capture evidence,
preserved payment component and partial-success exclusion. Lovable reported
131 passing tests across eight checkout/cart/intake files, a successful build,
and twelve intercepted browser scenarios at 320, 390 and 1280px. Those scenarios
cover prepayment failure, unknown confirmation, decline and partial success;
provider requests are mocked and no live card confirmation was submitted.

Published to `https://fortifyhp-care.lovable.app` (deployment
`282dfbd6-25f4-4bd2-9a9a-eabe7d3d7b1f`). The reported browser cart was reloaded
and recovered through the normal interface: the status-check warning disappeared,
the item became editable, and checkout displayed its details form. No journal
was cleared and no new payment was submitted. Contact fields are empty after a
full reload by design; preserving details applies within the same mounted flow.
The shared Fly app was not restarted or redeployed for this frontend fix.
