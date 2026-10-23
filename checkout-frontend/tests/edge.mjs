// Edge cases: recovery, holds and errors (mock API + stub Stripe). Never touches a real gateway.
import { APP, launch, mockPage, toReview } from './mock.mjs';

const results = [];
const check = (name, ok, extra = '') => results.push(`${ok ? 'PASS' : 'FAIL'}  ${name}${extra ? '  — ' + extra : ''}`);
const seen = (loc, timeout = 8000) => loc.first().waitFor({ timeout }).then(() => true, () => false);
const browser = await launch();

try {
  { // 1. backend down during refresh -> hold screen, then recovers
    const state = { status: 'new' }; const p = await mockPage(browser, { state });
    await toReview(p); await p.locator('#review').waitFor();
    state.down = true; await p.reload();
    check('refresh while backend down shows the payment-status screen (no endless spinner)', await seen(p.getByText('We couldn’t load your checkout')));
    check('…and hides Start over while payment state is unknown', !(await p.getByRole('button', { name: 'Start over' }).isVisible()));
    state.down = false; await p.locator('#check-payment-status').click();
    check('Check payment status recovers once the backend is back', await seen(p.locator('#contact, #review')));
    await p.close();
  }
  { // 2. Stripe returns "processing" -> hold, never completes, no start over
    const state = { status: 'new' }; const p = await mockPage(browser, { state, piStatus: 'processing' });
    await toReview(p); await p.locator('#authorize').click(); await p.locator('#pay:not([disabled])').click();
    check('non-authorized Stripe status shows "Your payment needs a check"', await seen(p.locator('#hold-title', { hasText: 'Your payment needs a check' })));
    check('…with no Start over', !(await p.getByRole('button', { name: 'Start over' }).isVisible()));
    check('…and /complete is not called', !p.calls.some((c) => c.endsWith('/complete')));
    await p.close();
  }
  { // member portal: hidden by default; when enabled, opens the one-time invitation
    const state = { status: 'new' }; const p = await mockPage(browser, { state });
    await toReview(p); await p.locator('#authorize').click(); await p.locator('#pay:not([disabled])').click(); await p.locator('#success').waitFor();
    check('no "Create your patient account" unless the site enables memberPortal', !(await p.locator('#create-account').count()));
    await p.close();
    const s2 = { status: 'new', portal409: true }; const q = await mockPage(browser, { state: s2, memberPortal: true });
    await q.route('https://portal.test/**', (r) => r.fulfill({ contentType: 'text/html', body: '<h1>Portal invite</h1>' }));
    await toReview(q); await q.locator('#authorize').click(); await q.locator('#pay:not([disabled])').click(); await q.locator('#success').waitFor();
    await q.locator('#create-account').click();
    check('portal 409 keeps the receipt and explains', await seen(q.getByText(/can’t be created from this order yet/)) && (await q.locator('#order-id').isVisible()));
    s2.portal409 = false;
    await q.locator('#create-account').click();
    await q.waitForURL('https://portal.test/**', { timeout: 8000 }).catch(() => {});
    check('Create your patient account opens the invitation link', q.url().startsWith('https://portal.test/portal/master-therapy#invite='), q.url());
    check('…after exactly one successful /portal call', q.calls.filter((c) => c.endsWith('/portal')).length === 2);
    await q.close();
  }
  { // 3. refresh after captured order -> same receipt, complete once
    const state = { status: 'new' }; const p = await mockPage(browser, { state });
    await toReview(p); await p.locator('#authorize').click(); await p.locator('#pay:not([disabled])').click(); await p.locator('#success').waitFor();
    await p.reload();
    check('refresh after a captured order shows the same receipt', await seen(p.locator('#order-id', { hasText: '777' })));
    const n = p.calls.filter((c) => c.endsWith('/complete')).length;
    check('/complete called exactly once', n === 1, String(n));
    await p.close();
  }
  { // 4. refresh on payment step -> /resume, not a second /payment
    const state = { status: 'new' }; const p = await mockPage(browser, { state });
    await toReview(p); await p.locator('#authorize').click(); await p.locator('#pay').waitFor(); await p.reload();
    await p.locator('#payment').waitFor({ timeout: 8000 });
    const prep = p.calls.filter((c) => c.endsWith('/payment')).length, res = p.calls.filter((c) => c.endsWith('/resume')).length;
    check('refresh on the payment step resumes the same payment', prep === 1 && res === 1, `payment=${prep} resume=${res}`);
    await p.close();
  }
  { // 5. payment setup fails and status is uncertain -> hold (original CUS-02)
    const state = { status: 'new', prepare502: true }; const p = await mockPage(browser, { state });
    await toReview(p); await p.locator('#authorize').click();
    check('uncertain payment setup shows "Your payment setup needs a check"', await seen(p.locator('#hold-title', { hasText: 'Your payment setup needs a check' })));
    const before = p.calls.length; await p.locator('#check-payment-status').click();
    check('Check payment status says still unconfirmed', await seen(p.locator('#hold-help', { hasText: 'still unconfirmed' })));
    check('…and never submits another payment', !p.calls.slice(before).some((c) => /\/(payment|complete|resume)$/.test(c)) && p.calls.filter((c) => c.endsWith('/payment')).length === 1);
    await p.reload();
    check('hold persists across refresh', await seen(p.locator('#payment-hold')));
    await p.close();
  }
  { // 6. plan became unavailable -> back to plans with message
    const state = { status: 'new' }; const p = await mockPage(browser, { state });
    await toReview(p); await p.locator('#review').waitFor();
    state.unavailable = true; await p.reload();
    check('unavailable plan on refresh returns to plan selection', await seen(p.getByText(/not available right now/)) && (await p.locator('#treatments').isVisible()));
    await p.close();
  }
  { // 7. expired session
    const state = { status: 'new' }; const p = await mockPage(browser, { state });
    await toReview(p); await p.locator('#review').waitFor();
    state.expired = true; await p.reload();
    check('expired session (410) restarts with a clear message', await seen(p.getByText(/checkout expired/)));
    await p.close();
  }
  { // 8. readable 422
    const p = await mockPage(browser, { state: { status: 'new', quote422: true } });
    await toReview(p);
    check('422 validation error is shown readably', await seen(p.locator('#message', { hasText: 'contact › phone: String should have at least 7 characters' })));
    await p.close();
  }
  { // 9. change plan from details keeps the selection
    const p = await mockPage(browser);
    await toReview(p); await p.locator('#review').waitFor();
    await p.locator('#change-plan').click();
    check('Change plan returns to plan page with the selection kept', await seen(p.locator('#payments button[aria-pressed=true]')));
    await p.close();
  }
  { // 9b. double click on "Continue to payment" prepares the payment once
    const p = await mockPage(browser);
    await toReview(p); await p.locator('#review').waitFor();
    await p.locator('#authorize').evaluate((b) => { b.click(); b.click(); });
    await p.locator('#payment').waitFor();
    const n = p.calls.filter((c) => c.endsWith('/payment')).length;
    check('double click on Continue to payment prepares the payment once', n === 1, String(n));
    await p.close();
  }
  { // 10. unknown site
    const p = await browser.newPage();
    await p.goto(APP + '/?site=does-not-exist');
    check('unknown site shows "Checkout unavailable"', await seen(p.getByText('Checkout unavailable')));
    await p.close();
  }
} finally {
  await browser.close();
}
console.log(results.join('\n'));
if (results.some((r) => r.startsWith('FAIL'))) process.exit(1);
