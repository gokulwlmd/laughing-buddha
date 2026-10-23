// Shared mock Site API + stub Stripe.js for the browser tests. No network, no real payments.
import { chromium } from 'playwright';

export const APP = process.env.APP_URL || 'http://localhost:4173';

// CHROMIUM_PATH: custom browser binary. CHROMIUM_ARGS: e.g.
// "--host-resolver-rules=MAP *.example 127.0.0.1" to test real domain names against local nginx.
export function launch() {
  return chromium.launch({
    ...(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {}),
    args: process.env.CHROMIUM_ARGS ? [process.env.CHROMIUM_ARGS] : [],
  });
}
export const API = 'https://wlmd-site-api-demo-0f89b1bb.fly.dev/api/v1/sites/payment-test';

const meds = [['sema', 'Semaglutide', { 1: 249, 3: 747, 6: 1494, 12: 2988 }], ['tirz', 'Tirzepatide', { 1: 449, 3: 1347, 6: 2694, 12: 5388 }]];
export const plans = [];
for (const [id, med, prices] of meds) for (const m of [1, 3, 6, 12]) for (const t of ['once', 'subscription']) {
  const ship = m >= 6 ? Array.from({ length: m / 3 }, (_, i) => i * 90) : [0];
  const price = prices[m].toFixed(2);
  plans.push({ plan_id: `${id}-${m}m${t === 'subscription' ? '-sub' : ''}`, name: `${med} — ${m}-month plan`, medication: med, duration_months: m, purchase_type: t, price, currency: 'USD', renewal_days: t === 'subscription' ? m * 30 : null, shipment_days: ship, terms: `Pay $${price} upfront. ${t === 'subscription' ? `Renews every ${m * 30} days.` : 'One-time purchase. No automatic renewal.'}` });
}

export function stripeStub(piStatus = 'requires_capture') {
  return `window.Stripe=function(){return{elements(){return{create(type){window.__types=(window.__types||[]).concat(type);const h={};return{mount(){setTimeout(()=>h.ready&&h.ready({}),20)},on(e,c){h[e]=c},off(){},destroy(){},unmount(){},update(){}}},getElement(){return null},update(){},fetchUpdates(){return Promise.resolve({})},submit(){return Promise.resolve({})}}},
  confirmPayment(){window.__confirms=(window.__confirms||0)+1;return Promise.resolve({paymentIntent:{id:'pi_t1',status:'${piStatus}'}})},
  retrievePaymentIntent(){return Promise.resolve({paymentIntent:{id:'pi_t1',status:'requires_capture'}})},
  registerAppInfo(){},_registerWrapper(){},createToken(){},createPaymentMethod(){},confirmCardPayment(){}}};`;
}

// state: {status, down, expired, unavailable, quote422, prepare502, pending}
export async function mockPage(browser, { state = { status: 'new' }, piStatus, payments = true, viewport, memberPortal = false } = {}) {
  const page = await browser.newPage(viewport ? { viewport } : {});
  page.errors = [];
  page.calls = [];
  page.on('pageerror', (e) => page.errors.push(e.message));
  await page.route('https://js.stripe.com/**', (r) => r.fulfill({ contentType: 'application/javascript', body: stripeStub(piStatus) }));
  // Site configs (config.json or sites/<domain>.json): force paymentsEnabled for the test.
  await page.route(/\/(config\.json|sites\/[^/]+\.json)(\?.*)?$/, async (r) => {
    // FETCH_VIA=127.0.0.1: reach a local nginx by IP, keeping the domain in the Host header
    // (Node doesn't use the browser's --host-resolver-rules).
    const u = new URL(r.request().url());
    const via = process.env.FETCH_VIA;
    const res = via
      ? await r.fetch({ url: `${u.protocol}//${via}${u.port ? ':' + u.port : ''}${u.pathname}${u.search}`, headers: { ...r.request().headers(), host: u.host } })
      : await r.fetch();
    if (!res.ok() || !(res.headers()['content-type'] || '').includes('json')) return r.fulfill({ response: res });
    const j = await res.json();
    j.paymentsEnabled = payments;
    if (memberPortal) j.memberPortal = true;
    r.fulfill({ response: res, json: j });
  });
  await page.route(`${API}/**`, async (r) => {
    const req = r.request(); const path = new URL(req.url()).pathname.replace('/api/v1/sites/payment-test', '');
    const body = req.postData() ? JSON.parse(req.postData()) : null;
    page.calls.push(`${req.method()} ${path}`);
    const json = (j, s = 200) => r.fulfill({ status: s, json: j, headers: { 'access-control-allow-origin': '*' } });
    if (path === '/plans') return json({ site_id: 'payment-test', site_name: 'Master Therapy Payment Test', color: '#245844', demo: true, plans });
    if (path.startsWith('/sessions/') && req.headers()['authorization'] !== 'Bearer tok_1') return json({ detail: 'Use the checkout session_token as a Bearer token' }, 401);
    if (state.down && path.startsWith('/sessions/')) return json({ detail: 'Bad gateway' }, 502);
    if (state.expired && path.startsWith('/sessions/')) return json({ detail: 'Session access expired' }, 410);
    if (path === '/sessions') return json({ session_id: 's_1', session_token: 'tok_1', expires_at: 9e9, plan_id: body.plan_id, status: 'new' }, 201);
    if (path.endsWith('/configuration')) {
      if (state.unavailable) return json({ detail: 'This plan is not currently available for payment' }, 409);
      return json({ publishable_key: 'pk_test_x', currency: 'usd', countries: [{ code: 'US', name: 'United States' }, { code: 'CA', name: 'Canada' }], shipping: [{ id: 2, name: 'Free shipping' }], plan: { recurring: true, shippable: false }, payment_test_only: true });
    }
    if (path.endsWith('/quote')) {
      if (state.quote422) return json({ detail: [{ loc: ['body', 'contact', 'phone'], msg: 'String should have at least 7 characters', type: 'x' }] }, 422);
      const sub = (page.planId || '').endsWith('-sub');
      return json({ quote_id: 'q_1', amount: 24900, currency: 'usd', payment_terms: sub ? 'Pay 249.00 USD today. Renews every 30 days.' : 'Pay 249.00 USD today. One-time payment. No automatic renewal.', terms_consent_required: sub });
    }
    if (path.endsWith('/payment')) {
      if (state.prepare502) { state.status = 'authorization_pending'; return json({ detail: 'The checkout service did not return a confirmed result' }, 502); }
      state.status = 'awaiting_card'; return json({ payment_intent_id: 'pi_t1', client_secret: 'pi_t1_secret_a', publishable_key: 'pk_test_x', amount: 24900, currency: 'usd', status: 'awaiting_card' });
    }
    if (path.endsWith('/portal')) {
      if (state.status !== 'captured') return json({ detail: 'Complete the checkout before creating a member account' }, 409);
      if (state.portal409) return json({ detail: 'This receipt needs a site assignment before portal enrollment' }, 409);
      return json({ site_id: 'payment-test', portal_site_id: 'master-therapy', enrollment_url: 'https://portal.test/portal/master-therapy#invite=t', expires_at: null });
    }
    if (path.endsWith('/resume')) return json({ payment_intent_id: 'pi_t1', client_secret: 'pi_t1_secret_a', publishable_key: 'pk_test_x', amount: 24900, currency: 'usd', status: 'awaiting_card' });
    if (path.endsWith('/complete')) { state.status = 'captured'; return json({ session_id: 's_1', plan_id: 'sema-1m', status: 'captured', amount: 24900, currency: 'usd', payment_intent_id: 'pi_t1', order_id: '777' }); }
    if (path === '/sessions/s_1') return json({ session_id: 's_1', plan_id: 'sema-1m', status: state.status, amount: state.status === 'new' ? null : 24900, currency: state.status === 'new' ? null : 'usd', payment_intent_id: null, order_id: state.status === 'captured' ? '777' : null });
    return json({ detail: 'nf' }, 404);
  });
  return page;
}

export async function choosePlan(page, { med = 'Semaglutide', months = 1, type = /One-time purchase/ } = {}) {
  page.planId = `${med === 'Semaglutide' ? 'sema' : 'tirz'}-${months}m${String(type).includes('Subscription') ? '-sub' : ''}`;
  await page.locator('#treatments').getByRole('button', { name: med, exact: true }).click();
  await page.locator(`#durations [data-duration="${months}"]`).click();
  await page.locator('#payments').getByRole('button', { name: type }).click();
  await page.locator('#plan-continue').click();
}

export async function fillDetails(page) {
  await page.locator('#contact button[type=submit]').waitFor();
  await page.waitForFunction(() => !document.querySelector('#contact button[type=submit]').disabled);
  const f = page.locator('#contact');
  await f.locator('[name=name]').fill('Test User');
  await f.locator('[name=email]').fill('test@example.com');
  await f.locator('[name=phone]').fill('+12025550100');
  await f.locator('[name=address]').fill('1 Test Way');
  await f.locator('[name=city]').fill('San Francisco');
  await f.locator('#state').selectOption('CA');
  await f.locator('[name=postal_code]').fill('94105');
}

export async function toReview(page, opts) {
  await page.goto(APP + '/');
  await choosePlan(page, opts);
  await fillDetails(page);
  await page.getByRole('button', { name: /Review my order/ }).click();
}
