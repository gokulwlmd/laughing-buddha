# Weight-loss intake and thank-you flow — 26 October 2026

The shared post-purchase component now leads with confirmation and a clear intake action. Weight-loss questions use short, conditional steps in checkout and the member portal. State and other long single-choice lists use selects; email, phone and date fields use appropriate input types. Identity remains the final submission step.

The API seeds name, email, phone, physical address and state from the exact owned order/checkout. These values can be reviewed and edited without re-entry. No email-based cross-order lookup is used. Existing draft answers and their step anchor are preserved when the versioned form is upgraded. Submitted forms remain unchanged. Historical profile answers retain their original question metadata when deciding reuse.

## Reference and scope

Inspected the public CoreAge onboarding page and its embedded form on 26 October:
- https://www.coreagerx.com/onboarding/
- https://forms.whitelabelmd.com/253315445837966

The existing 67-question adapter is arranged into 18 small sections; irrelevant sections are skipped, so the displayed step count depends on answers. Enabled show rules whose dependencies exist in this adapter are represented as data. Checkbox membership is evaluated consistently in the backend and both frontends. Exclusive “none” selections cannot coexist with positive choices.

Seven legacy follow-up IDs whose source fields are always-hidden and have no enabled supported show rule remain in the versioned schema but are not displayed: ca_240, ca_241, ca_242, ca_243, ca_247, ca_442 and ca_252. This is a repair of the existing adapter, not certification of full parity with every source widget, external script, clinical decision or provider submission. No clinical approval rules or live medical submissions were added.

## Validation

- 85 backend checks passed, including first-response checkout prefill, edited-answer persistence, draft migration, submitted-record preservation, receipt/site isolation, account handoff and identity/upload boundaries.
- 22 shared-component browser scenarios passed across the full run and targeted rerun; 2 member-portal save/resume and responsive scenarios passed.
- Visual inspection covered desktop and 390px mobile screenshots; automated reflow also covered 320px.
- Browser/provider transports were synthetic. No payment, SSN verification, ID upload or clinical submission was made for QA.

## Release

Shared Fly app: `wlmd-stripe-test-0f89b1bb`.
Image: `registry.fly.io/wlmd-stripe-test-0f89b1bb@sha256:b33d423895d7342848cd41c4fd052a7a1c7d0af7d83e03243c98b48d690bd5d9`.

Pre-deploy backup: `/data/backups/intake-steps-1793024928` (39 SQLite files and 2 encryption keys, private on-volume backup). All 22 unfinished legacy payment rows exactly matched the previously preserved demo snapshot. Records were retained; no payment retry or cancellation occurred. Available volume space after backup was approximately 1.87 GB.

Unrelated AWS/MySQL/Python-3.9 working changes were excluded from the Fly build and scoped commit. Card-update integration is outside this release and remains subject to the separate provider contract.

Hosted verification completed: `/health` and `/portal/fortifyhp` returned 200; unauthenticated portal `/me` remained 401. Both served JavaScript assets and all seven changed backend source files matched the tested release by SHA-256.
