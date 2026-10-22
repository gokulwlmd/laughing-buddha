# Hosted checkout design (23 October 2026)

The owner asked to match the presentation of
[the VigMD weight-loss checkout](https://checkout.vigmd.com/wl_checkout/?product=semaglutide).
The redesign follows its white canvas, compact typography, medication tabs,
stacked horizontal plan cards and pale, bordered order summary. It uses the
site's own branding and an original abstract package illustration; it does not
copy the reference's brand, product photographs, claims or savings.

## Customer flow

- Open the plan page with the requested medication selected when `?product=`
  matches an available medication ID or name; otherwise select the first
  available medication. Show plan lengths immediately.
- List available duration groups from longest to shortest. Require an explicit
  duration choice, followed by an explicit one-time or subscription choice.
- Show the full upfront price prominently. An optional monthly equivalent in
  the summary explicitly says that the total is paid in full upfront. Preserve
  configured shipment schedules, renewal intervals and consent requirements.
- Continue to the existing details and payment flow. The redesigned contact
  form, checkout progress and summary use the same compact visual language.

The desktop layout places choices beside the summary. Mobile layouts stack
these sections and keep forms and plan cards within a 390 px viewport. Configured
site accent and button colors remain in use. Red Hat Display is self-hosted;
its font asset and SIL Open Font License are included with the static files.

## Implementation and release

`plans.html` uses `plan-selector-v4.js` and `plan-selector-v4.css`. The payment
page uses the new presentation assets with the existing `checkout-v9.js`.
Both pages load `checkout-font-v1.css` and `brand-design-v2.js`. Selection IDs,
SKU/option handoff, server prices and the existing Stripe v2 flow are preserved.

The release is a versioned static-file overlay on the existing Fly app. It
requires no payment-worker restart, database migration or payment-record edit.
The final deployment evidence is recorded in
[`checkout-reference-deployment.json`](../tools/stripe-v2-checkout/checkout-reference-deployment.json).
Consult that record for actual publication status and final verification counts;
source changes alone do not establish that a release is live.

Browser verification covers medication defaults, descending durations, explicit
payment choice, schedule/renewal copy, checkout handoff and mobile overflow.
Financial flows are exercised only with the local fake payment backend. Hosted
verification is restricted to loading pages and assets; it does not authorize,
confirm or capture a payment. No customer screenshots, private checkout tokens
or payment data belong in the repository.
