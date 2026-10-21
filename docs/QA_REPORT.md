# Admin and checkout QA report

Run: 22 October 2026, 12:44 AM IST.

Status: **Passed** for the implemented workflows below.

- Backend: **122 tests**, 0 failures, 0 errors.
- Browser: **55 passed**, 0 failed, 0 skipped, 0 flaky.
- Browser engine: Chromium; desktop 1440×1000 and mobile 390×844.
- Environment: disposable loopback server, synthetic owner/customer data, fake Sticky API and a Stripe.js contract stub. Production credentials are removed from the test process. External browser requests are blocked except the locally fulfilled Stripe stub.
- No real card, processor authorization/capture, live refund, or live Sticky configuration write is made by this suite.

## Browser test cases

| ID | Scenario | Result |
| --- | --- | --- |
| BRD-01 | one brand, two campaigns, matching checkout and payment design, reusable links after design edit | Pass |
| BRD-02 | unattached campaign guides the selected brand to campaign setup | Pass |
| BRD-03 | mobile brand preview and inherited checkout fit the viewport | Pass |
| GRP-01 | brand directory scopes links and creation to the selected brand and groups categories | Pass |
| GRP-02 | category edit regroups existing checkouts without reassignment or URL changes | Pass |
| GRP-03 | design shortcut targets the owning brand and existing links retain independent colors | Pass |
| GRP-04 | mobile brand directory and grouped checkout links fit the viewport | Pass |
| MST-01 | agreed preset saves five intervals without a Sticky write | Pass |
| MST-02 | test brand, assignment preview, private link and repeated assignment | Pass |
| MST-03 | quote validation checks each assigned billing choice without charging | Pass |
| MST-04 | every preset interval can complete a distinct simulated checkout | Pass |
| MST-05 | new master revision shows update available without changing assigned checkout | Pass |
| MST-06 | partial assignment holds created IDs and blocks a fresh attempt | Pass |
| MST-07 | mobile master setup and approval remain usable | Pass |
| PLAN-01 | product duration, one-time price and subscription price map without naming offers | Pass |
| PLAN-02 | legacy five intervals retain IDs, names and exact schedules when duration changes | Pass |
| PLAN-03 | mobile purchase setup needs no offer labels and changing type clears incompatible schedules | Pass |
| PRE-01 | prepaid setup shows upfront price, produces a private link and captures the whole term once | Pass |
| PRE-02 | changing prepaid type preserves one interval and validates cent-exact total | Pass |
| PRE-03 | mobile prepaid setup displays total and fixed shipment count without overflow | Pass |
| PRE-04 | add prepaid to an existing product preserves its original option and edits without duplication | Pass |
| PRE-05 | mobile prepaid shortcut keeps unsaved product fields and updates schedule and currency | Pass |
| PRE-06 | physical product saves a prepaid catalog option with an explicit assignment limitation | Pass |
| PRE-07 | missing 90-day model never substitutes a different schedule or erases the draft | Pass |
| SIM-01 | four primary screens, local master and one-review existing campaign assignment | Pass |
| SIM-02 | new campaign name and template include every master SKU and ready links | Pass |
| SIM-03 | automatically selected choices and generated link address with public/private control | Pass |
| SIM-04 | uncertain campaign creation cannot duplicate through a fresh setup | Pass |
| SIM-05 | mobile master campaign and links need no advanced settings | Pass |
| SIM-06 | choose a brand before checkout creation and retain all accessible campaign choices | Pass |
| SIM-07 | existing Sticky SKU creates a checkout under the selected brand | Pass |
| AUTH-01 | first setup needs its invitation and matching passwords | Pass |
| AUTH-02 | wrong password is recoverable and sign-out clears workspace | Pass |
| AUTH-03 | expired session returns to login and preserves the unapplied draft | Pass |
| CAT-01 | campaign search, immutable identifiers and clean new forms | Pass |
| CAT-02 | find duplicate SKU products and explicitly select a mapping | Pass |
| CAT-03 | lookup failure preserves entered values and can be retried | Pass |
| REV-01 | no change without consent; discard removes only the draft | Pass |
| REV-02 | stale preview can be refreshed and approved once | Pass |
| OFF-01 | billing checkboxes and invalid advanced JSON preserve the form | Pass |
| OFF-02 | dollar-prefixed names create offers without reference substitution | Pass |
| OFF-03 | brand price edits update only selected checkout choices | Pass |
| OFF-04 | partial Sticky write is held and cannot be blindly retried | Pass |
| CAM-01 | copy routing selections and preview a new campaign | Pass |
| PAY-01 | public branded checkout and reusable link capture once per attempt | Pass |
| PAY-02 | recurring consent is required before authorization | Pass |
| PAY-03 | declined card can be retried using the same authorization | Pass |
| PAY-04 | Stripe-style redirect return removes secret and captures same intent | Pass |
| PAY-05 | page refresh resumes the existing card authorization | Pass |
| PAY-06 | unavailable session secret holds payment instead of creating another | Pass |
| PAY-07 | price change requires a fresh reviewed total | Pass |
| PAY-08 | uncertain capture stays held after refresh and is never repeated | Pass |
| LINK-01 | private invitation is scoped and revocation is visible | Pass |
| LINK-02 | inactive link cannot be opened and can be reactivated with approval | Pass |
| UX-01 | mobile setup, review and catalog fit without horizontal overflow | Pass |

## Backend coverage

The suite covers owner setup/sign-in/session storage, CSRF/origin checks, exact SKU mapping, duplicate SKU choices, server-owned pricing/tax calculations, separate brand offer prices, live-preview guards, explicit approval, refresh/discard, uncertain and partial-write holds, public/private access, invitation revocation, stale tabs, quote expiry, consent, resume after refresh, hold after a restart, captured receipts and repeat purchases. `test_brands.py` covers multiple campaigns per brand, distinct provisional IDs for new campaigns, price isolation, legacy mappings, design propagation, quote stability and target-campaign payment locks. `test_qa.py` contains checkout/admin regressions. `test_master.py` verifies versioned master saves, all five TIRZ intervals, independent brand prices, multiple SKUs/offers, assignment idempotency, private generated links, source/currency/model drift and partial-write holds.

`test_prepaid.py` verifies full upfront pricing, per-shipment price conversion, cycle counts, consent, capture read-back, renewal rejection and independent brand prices.

## Usability and correctness changes

- Use four primary screens: Brands, Master SKUs, Campaigns and Checkout links. Preview a shared brand design; attach multiple campaigns while preserving existing checkout destinations.
- Apply brand logo, colors, font and layout to checkout, payment and receipt screens; scope offer price edits to the intended campaign.
- Set product duration independently from one-time/subscription purchase options, per-payment prices and exact charge frequencies; generate internal names/IDs and preserve legacy billing mappings.
- Maintain versioned master SKU presets, apply reviewed assignments to campaigns without duplicate objects, and validate each assigned billing choice and optional server quote.
- Browse checkout links by brand, then by editable master-catalog category; retain Uncategorized for legacy SKUs. Category-only edits regroup existing URLs without changing billing revisions or Sticky settings.
- Show the owning brand’s saved color and an Edit brand design shortcut; separate brands sharing a campaign retain independent presentation.
- Search accessible campaigns and reuse existing campaign payment/routing selections.
- Find products by brand and exact SKU; choose explicitly among duplicate product records.
- Select billing models with checkboxes instead of keyboard-dependent multi-selects.
- Lock identifiers when editing and provide clear New actions; reset forms after approval.
- Show readable before/after summaries, affected checkout links, approval state and next-step actions; keep technical API details collapsed.
- Refresh stale previews safely, or discard unapplied drafts. Applied/uncertain operations cannot be replayed as drafts.
- Preserve form input after API or JSON errors, provide useful validation messages, and recover cleanly after session expiry.
- Keep link options bound to the chosen brand/SKU even if selection changes while a request is loading.
- Block publishing unready payment choices; retain inactive configuration for future setup.
- Treat dollar-prefixed offer names as literal text, independent of internal object references.
- Preserve documented shipping/tax/weight fields when creating separately priced product records.
- Resume the same in-memory authorization after a customer refresh; hold unresolved/restarted payments without creating another intent.
- Show friendly private/unavailable checkout pages, keep customer plan labels free of internal product IDs, and retain duplicate-capture protection.
- Make all navigation and sign-out accessible on mobile; use readable stacked approval summaries.

## Hosted release checks

Deployed on 2026-10-22 to [the owner admin](https://wlmd-stripe-test-0f89b1bb.fly.dev/admin). The running Fly machine uses the verified immutable image recorded in `deployment.json` and the existing encrypted volume.

Read-only checks passed: health/admin pages, current assets, configured owner, anonymous admin-data rejection, friendly private/missing-link pages, absent test hooks, and the existing campaign/SKU configuration. The owner's account, admin records and original receipt were preserved. The live sign-in page passed desktop and mobile Chromium checks with no page errors or horizontal overflow. Browser verification pinned the public keys of the environment's installed proxy CA certificates; HTTPS checks also passed with the system trust store.

Live authenticated admin mutations and payment processing were not exercised: the owner's password remains private, and QA did not submit live Sticky writes or charges. Complete admin/payment interactions above were exercised locally with simulated services.

## Release limits

Passing this suite verifies application behavior against a fake payment service. It does not certify live Stripe processing, real 3DS/Link/Express Checkout/browser-wallet behavior, future rebill execution, or every Sticky campaign's fulfillment/tax integrations.

Fixed-term prepaid test products support upfront totals, cycle counts and stop-at-term behavior. Physical/taxable prepaid fulfillment, renewal, discounts, trials, seasonal/series/bundle/variant/custom schedules remain blocked where unverified. Free trials require a supported card-setup/later-billing integration. Custom domains remain pending DNS and HTTPS provisioning. These are open product/integration work, not features claimed as passing.

Read-only live deployment checks and the deployed image are recorded separately in `tools/stripe-v2-checkout/deployment.json`. The existing order 505015 is preserved; its later Sticky status 6 is not independently interpreted as settlement approval.

## Repeat the checks

From `tools/stripe-v2-checkout`, install runtime/dev requirements, then:

```sh
npm --cache /workspace/.cache/npm --prefix qa ci --ignore-scripts
/workspace/.venvs/stripe-v2-checkout/bin/python qa/run.py
```

Set `QA_PYTHON` to another virtualenv Python if needed. Chromium defaults to `/usr/bin/chromium`; set `QA_CHROMIUM_EXECUTABLE` for another installed Chromium or install Playwright's Chromium. Raw results and failure screenshots are ignored under `qa/results/`; the test definitions, lockfile and this report are saved in the repository.
