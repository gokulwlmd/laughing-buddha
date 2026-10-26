# Refined post-checkout experience — 26 October 2026

The previous version had too much vertical space, oversized headings and repeated provenance panels. This release consolidates the confirmation and password form into one restrained desktop surface and removes its outer frame on phones. A warm receipt area lists each product and order number; the password action remains prominent. Desktop password fields sit side by side, while mobile fields stack.

Saved contact information now shares one bordered summary, with an Edit disclosure for each value. Provenance appears once per group (checkout, previous intake, or mixed saved details). Questions that require fresh answers or confirmation remain explicit. Changing health information is never silently accepted. The step title is no longer repeated in the progress line. Multi-product navigation uses compact treatment names; full order descriptions remain on the receipt.

The shared component retains API contracts, password/handoff rules, owned receipt linking, conditional questions, draft persistence, identity last, error recovery and submission. No backend, Sticky, billing, medical or fulfillment logic changed. No new orders, real payments or real identity uploads were performed.

## Verification

All 26 component browser tests passed. The expired-handoff test was updated to the concise password-saved status; its assertions for preserving every purchase invitation and avoiding an expired handoff are unchanged.

The actual published Fortify shell was exercised at 390px and 1440px using fully intercepted synthetic checkout/account/intake responses. Single and multiple product layouts passed. The mobile component spans exactly 390px without horizontal overflow, and the password CTA fits within the 900px desktop viewport. Screenshots show synthetic records, not live patient transactions.

The existing Fly app and volume are reused. The release is built from committed source plus only these UI/test changes, excluding unrelated local AWS/MySQL work. Private pre-release backup: /data/backups/intake-steps-1793031317 (39 SQLite databases and two keys; 22 unfinished payment records preserved).

Final four multi-product/handoff checks passed after shortening treatment labels. Image: registry.fly.io/wlmd-stripe-test-0f89b1bb@sha256:c24ead25fdfdc04140c53fac614faa8bf77395367cc769cb34b101ed053fe658.
