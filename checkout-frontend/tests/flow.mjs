// Happy path of the ported checkout (mock API + stub Stripe). PAY=1 enables payments.
import fs from 'node:fs';
import { APP, launch, mockPage, choosePlan, fillDetails } from './mock.mjs';

const OUT = process.argv[2] || 'tests/screenshots';
fs.mkdirSync(OUT, { recursive: true });
const pay = process.env.PAY === '1';
const results = [];
const check = (name, ok, extra = '') => results.push(`${ok ? 'PASS' : 'FAIL'}  ${name}${extra ? '  — ' + extra : ''}`);
const browser = await launch();
try {
  const page = await mockPage(browser, { payments: pay, viewport: { width: 1440, height: 1000 } });
  const shot = (n) => page.screenshot({ path: `${OUT}/${n}.png`, fullPage: true });
  await page.goto(APP + '/');
  await page.getByRole('heading', { name: 'Choose your weight loss plan' }).waitFor();
  check('plan page: first medication preselected, payment step hidden until a length is chosen', (await page.locator('#treatments [aria-pressed=true]').innerText()) === 'Semaglutide' && (await page.locator('#duration-step').isVisible()) && (await page.locator('#payment-step').isHidden()));
  const order = await page.locator('#durations button').evaluateAll((b) => b.map((x) => Number(x.dataset.duration)));
  check('durations listed longest first', JSON.stringify(order) === JSON.stringify([12, 6, 3, 1]), order.join(','));
  check('duration cards show price "paid upfront"', /\$1,494\.00\s+paid upfront/.test(await page.locator('#durations [data-duration="6"]').innerText()));
  await page.locator('#durations [data-duration="6"]').click();
  await page.locator('#payments').getByRole('button', { name: /One-time purchase/ }).click();
  await shot('1-plans');
  await page.locator('#payments').getByRole('button', { name: /Subscription/ }).click();
  check('summary shows prepaid subscription terms', (await page.locator('#selection-details').innerText()).includes('Renews every 180 days'));
  check('summary shows monthly equivalent for multi-month plans', (await page.locator('.monthly-equivalent').innerText()).includes('/month. Paid in full upfront.'));
  // go with a 1-month subscription (consent flow)
  await page.locator('#durations [data-duration="1"]').click();
  await page.locator('#payments').getByRole('button', { name: /Subscription/ }).click();
  page.planId = 'sema-1m-sub';
  await page.locator('#plan-continue').click();
  await page.locator('#contact').waitFor();
  check('details: summary shows medication + plan length + pill', (await page.locator('#product').innerText()) === 'Semaglutide' && (await page.locator('#plan-description').innerText()) === '1-month plan' && (await page.locator('#summary-payment').innerText()) === 'Subscription');
  await fillDetails(page);
  const callsBefore = page.calls.length;
  await page.locator('#contact [name=email]').fill('');
  await page.getByRole('button', { name: /Review my order/ }).click();
  check('empty required field blocks submit (no quote call)', !page.calls.slice(callsBefore).some((c) => c.endsWith('/quote')));
  await page.locator('#contact [name=email]').fill('test@example.com');
  await shot('2-details');
  await page.getByRole('button', { name: /Review my order/ }).click();
  await page.locator('#review').waitFor();
  await page.locator('#authorize').click();
  check('consent required before payment', (await page.locator('#message').innerText()).includes('accept the recurring billing terms') && !page.calls.some((c) => c.endsWith('/payment')));
  await page.locator('#consent').check();
  check('summary total switches to "Total due today"', (await page.locator('#total-label').innerText()) === 'Total due today');
  await shot('3-review');
  await page.reload();
  await page.locator('#review').waitFor();
  check('refresh restores review step', true);
  await page.locator('#consent').check();
  await page.locator('#authorize').click();
  await page.locator('#payment').waitFor();
  await page.waitForTimeout(300);
  const payDisabled = await page.locator('#pay').isDisabled();
  const types = await page.evaluate(() => window.__types || []);
  check(pay ? 'Pay enabled + Express Checkout mounted' : 'Pay locked + no Express Checkout when payments off', pay ? !payDisabled && types.includes('expressCheckout') : payDisabled && !types.includes('expressCheckout'), types.join(','));
  check('Payment Element used (not card element)', types.includes('payment') && !types.includes('card'));
  await shot('4-payment');
  if (pay) {
    await page.locator('#pay').evaluate((b) => { b.click(); b.click(); });
    await page.locator('#success').waitFor();
    check('order confirmed with order number', (await page.locator('#order-id').innerText()) === '777');
    check('double click confirmed once, completed once', (await page.evaluate(() => window.__confirms)) === 1 && page.calls.filter((c) => c.endsWith('/complete')).length === 1);
    check('summary shows "Total paid"', (await page.locator('#total-label').innerText()) === 'Total paid');
    await shot('5-success');
  }
  await page.setViewportSize({ width: 390, height: 844 });
  await page.evaluate(() => window.scrollTo(0, 0));
  check('mobile: no horizontal scroll', !(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)));
  await page.screenshot({ path: `${OUT}/6-mobile.png` });
  check('no page errors', !page.errors.length, page.errors.join(' | '));

  const p2 = await mockPage(browser, { payments: pay, viewport: { width: 1440, height: 1000 } });
  // localhost: 127.0.0.1 has no config of its own, so ?site= picks the brand. Domain mode: SECOND_URL.
  await p2.goto(process.env.SECOND_URL || APP.replace('localhost', '127.0.0.1') + '/?site=checkout.harborwellness.example');
  await p2.getByRole('heading', { name: 'Start your program' }).waitFor();
  check('second brand loads by domain', (await p2.title()).startsWith('Harbor Wellness'));
  await p2.locator('#treatments').getByRole('button', { name: 'Tirzepatide', exact: true }).click();
  await p2.locator('#durations [data-duration="3"]').click();
  await p2.screenshot({ path: `${OUT}/7-second-brand.png`, fullPage: true });

  const p3 = await mockPage(browser, { payments: pay, viewport: { width: 1440, height: 1000 } });
  await p3.goto(process.env.THIRD_URL || APP + '/?site=checkout.glowhealth.example');
  await p3.getByRole('heading', { name: 'Find your plan' }).waitFor();
  check('third brand (stacked layout)', (await p3.title()).startsWith('Glow Health') && (await p3.locator('.lb-plans').getAttribute('data-layout')) === 'stacked');
  await p3.locator('#treatments').getByRole('button', { name: 'Semaglutide', exact: true }).click();
  await p3.locator('#durations [data-duration="3"]').click();
  await p3.locator('#payments').getByRole('button', { name: /Subscription/ }).click();
  await p3.screenshot({ path: `${OUT}/8-third-brand.png`, fullPage: true });
  await p3.locator('#plan-continue').click();
  await p3.locator('#contact').waitFor();
  await p3.screenshot({ path: `${OUT}/9-third-brand-details.png`, fullPage: true });
  check('logo and favicon load from relative paths', await p3.evaluate(async () => {
    const img = document.querySelector('#brand-logo');
    const fav = document.querySelector('link[rel=icon]').href;
    return img.complete && img.naturalWidth > 0 && (await fetch(fav)).ok;
  }));
  {
    const pp = await mockPage(browser, { viewport: { width: 390, height: 900 } });
    await pp.goto(APP + '/?product=tirzepatide');
    await pp.locator('#treatments [aria-pressed=true]').waitFor();
    check('?product= preselects that medication', (await pp.locator('#treatments [aria-pressed=true]').innerText()) === 'Tirzepatide');
    const overflow = await pp.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
    check('390px mobile: no horizontal overflow', !overflow);
    await pp.close();
  }
} finally {
  await browser.close();
}
console.log(results.join('\n'));
if (results.some((r) => r.startsWith('FAIL'))) process.exit(1);
