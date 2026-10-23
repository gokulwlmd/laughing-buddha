// Per-domain config against a real nginx (deploy/ snippet + per-domain server blocks).
// Run with: CHROMIUM_ARGS="--host-resolver-rules=MAP *.example 127.0.0.1, MAP test-ip.local 127.0.0.1" BASE_PORT=8080 node tests/domains.mjs
import { launch } from './mock.mjs';

const port = process.env.BASE_PORT || '80';
const url = (host, q = '') => `http://${host}:${port}/${q}`;
const results = [];
const check = (name, ok, extra = '') => results.push(`${ok ? 'PASS' : 'FAIL'}  ${name}${extra ? '  — ' + extra : ''}`);
const brands = [
  ['checkout.mastertherapy.example', 'Master Therapy', '#245844'],
  ['checkout.harborwellness.example', 'Harbor Wellness', '#1d4e89'],
  ['checkout.glowhealth.example', 'Glow Health', '#7a2e5c'],
];
const browser = await launch();
const plansJson = { site_id: 'payment-test', site_name: 'x', color: '#000', plans: [{ plan_id: 'sema-1m', name: 'Semaglutide — 1-month plan', medication: 'Semaglutide', duration_months: 1, purchase_type: 'once', price: '249.00', currency: 'USD', renewal_days: null, shipment_days: [0], terms: 't' }] };
async function open(u) {
  const p = await browser.newPage();
  await p.route('https://wlmd-site-api-demo-0f89b1bb.fly.dev/**', (r) => r.fulfill({ json: plansJson, headers: { 'access-control-allow-origin': '*' } }));
  await p.goto(u);
  await p.locator('#treatments button, #plan-error').first().waitFor({ timeout: 10000 }).catch(() => {});
  const info = await p.evaluate(() => ({ title: document.title, color: getComputedStyle(document.querySelector('.lb-plans') || document.body).getPropertyValue('--brand-color').trim(), logo: !!document.querySelector('#brand-logo')?.naturalWidth, err: document.querySelector('#plan-error')?.innerText || '', link: document.querySelector('a.wordmark')?.href || '' }));
  await p.close();
  return info;
}
try {
  for (const [host, name, color] of brands) {
    const i = await open(url(host));
    check(`${host} loads ${name} with its own colour + logo`, i.title.startsWith(name) && i.color === color && i.logo, `${i.title} ${i.color}`);
  }
  const ignored = await open(url(brands[0][0], '?site=checkout.glowhealth.example'));
  check('?site= is ignored on a real brand domain', ignored.title.startsWith('Master Therapy'), ignored.title);
  const ip = await open(url('test-ip.local', '?site=checkout.harborwellness.example'));
  check('unknown host (IP test block) + ?site= loads that brand', ip.title.startsWith('Harbor Wellness'), ip.title);
  const none = await open(url('test-ip.local'));
  check('unknown host without ?site= shows "No site is configured"', /No site is configured/.test(none.err), none.err);
  const wordmark = await open(url(brands[1][0]));
  check('wordmark links to websiteUrl', wordmark.link === 'https://harborwellness.example/', wordmark.link);
} finally {
  await browser.close();
}
console.log(results.join('\n'));
if (results.some((r) => r.startsWith('FAIL'))) process.exit(1);
