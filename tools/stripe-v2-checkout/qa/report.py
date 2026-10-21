"""Build a readable QA report from actual runner results."""
import json
from pathlib import Path
from datetime import datetime, timezone, timedelta
ROOT=Path(__file__).resolve().parents[1]
results=ROOT/'qa/results'
backend=json.loads((results/'backend.json').read_text())
browser=json.loads((results/'results.json').read_text())

def specs(suites):
    for suite in suites:
        yield from suite.get('specs',[])
        yield from specs(suite.get('suites',[]))

rows=[]
for spec in specs(browser['suites']):
    tests=spec.get('tests',[])
    ok=all(t.get('status')=='expected' for t in tests)
    title=spec['title'];case_id,title=title.split(' ',1)
    rows.append(f'| {case_id} | {title} | {"Pass" if ok else "Fail"} |')
started=datetime.fromisoformat(browser['stats']['startTime'].replace('Z','+00:00')).astimezone(timezone(timedelta(hours=5, minutes=30), 'IST'))
passed=backend['failures']==0 and backend['errors']==0 and browser['stats']['unexpected']==0
report=f'''# Admin and checkout QA report

Run: {started.strftime('%d %B %Y, %I:%M %p IST')}.

Status: **{'Passed' if passed else 'Failed'}** for the implemented workflows below.

- Backend: **{backend['tests']} tests**, {backend['failures']} failures, {backend['errors']} errors.
- Browser: **{browser['stats']['expected']} passed**, {browser['stats']['unexpected']} failed, {browser['stats']['skipped']} skipped, {browser['stats']['flaky']} flaky.
- Browser engine: Chromium; desktop 1440×1000 and mobile 390×844.
- Environment: disposable loopback server, synthetic owner/customer data, fake Sticky API and a Stripe.js contract stub. Production credentials are removed from the test process. External browser requests are blocked except the locally fulfilled Stripe stub.
- No real card, processor authorization/capture, live refund, or live Sticky configuration write is made by this suite.

## Browser test cases

| ID | Scenario | Result |
| --- | --- | --- |
'''+ '\n'.join(rows)+'''

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
'''
deployment_path=ROOT/'deployment.json'
if deployment_path.exists():
    deployment=json.loads(deployment_path.read_text())
    if deployment.get('deployed_image_verified'):
        hosted_section=f"""## Hosted release checks

Deployed on {deployment['deployed_at_date']} to [the owner admin]({deployment['admin_url']}). The running Fly machine uses the verified immutable image recorded in `deployment.json` and the existing encrypted volume.

Read-only checks passed: health/admin pages, current assets, configured owner, anonymous admin-data rejection, friendly private/missing-link pages, absent test hooks, and the existing campaign/SKU configuration. The owner's account, admin records and original receipt were preserved. The live sign-in page passed desktop and mobile Chromium checks with no page errors or horizontal overflow. Browser verification pinned the public keys of the environment's installed proxy CA certificates; HTTPS checks also passed with the system trust store.

Live authenticated admin mutations and payment processing were not exercised: the owner's password remains private, and QA did not submit live Sticky writes or charges. Complete admin/payment interactions above were exercised locally with simulated services.

"""
        report=report.replace('## Release limits',hosted_section+'## Release limits')
candidate_path=ROOT/'release-candidate.json'
if candidate_path.exists():
    candidate=json.loads(candidate_path.read_text())
    if not candidate.get('deployed'):
        report=report.replace('Status: **Passed** for the implemented workflows below.', 'Status: **Passed locally** for the implemented workflows below. The latest release candidate is **not deployed yet**; its status is recorded in the release metadata. See `tools/stripe-v2-checkout/release-candidate.json`.')
        report=report.replace('## Hosted release checks', '## Previously deployed version')
        report=report.replace('Read-only checks passed: health/admin pages', 'For the previously deployed version, read-only checks passed: health/admin pages')

(ROOT.parent.parent/'docs/QA_REPORT.md').write_text(report)
print(f'QA report written: {backend["tests"]} backend tests, {browser["stats"]["expected"]} browser scenarios.')
