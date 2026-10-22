const {test: base, expect} = require('playwright/test');
const {spawn} = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const net = require('node:net');

async function freePort() {
  const server = net.createServer();
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
  const port = server.address().port;
  await new Promise(resolve => server.close(resolve));
  return port;
}

const test = base.extend({
  portal: [async ({}, use) => {
    const port = await freePort();
    const stateDir = fs.mkdtempSync(path.join(os.tmpdir(), 'patient-portal-qa-'));
    const origin = `http://127.0.0.1:${port}`;
    const child = spawn(process.env.QA_PYTHON || 'python3', [
      path.join(__dirname, '../patient_demo/run.py'), '--port', String(port), '--state-dir', stateDir,
    ], {stdio: ['ignore', 'pipe', 'pipe']});
    let errors = '';
    child.stderr.on('data', data => errors += data);
    try {
      await expect.poll(async () => {
        if (child.exitCode !== null) throw Error(`Portal exited ${child.exitCode}: ${errors}`);
        try { return (await fetch(origin + '/health')).status; } catch { return 0; }
      }, {timeout: 15000}).toBe(200);
      await use({origin});
    } finally {
      child.kill('SIGTERM');
      await new Promise(resolve => {
        if (child.exitCode !== null) return resolve();
        child.once('exit', resolve);
        setTimeout(() => { child.kill('SIGKILL'); resolve(); }, 2000).unref();
      });
      fs.rmSync(stateDir, {recursive: true, force: true});
    }
  }, {scope: 'worker'}],
});

async function openPortal(page, portal) {
  await page.goto(portal.origin + '/portal/willow-health');
  await expect(page.locator('#site-select')).toHaveValue('willow-health');
  await expect(page.locator('[data-action="open-intake"]').first()).toBeVisible();
}

async function openFirstIntake(page) {
  await page.locator('[data-action="open-intake"]').first().click();
  await expect(page.locator('#intake-form')).toBeVisible();
  await expect(page.locator('[data-question="weight_goals"]')).toBeVisible();
}

async function saved(page) {
  await expect(page.locator('#save-status')).toHaveText('Saved');
}

async function assertNoOverflow(page) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)).toBe(false);
}

test('PATIENT-01 intake autosaves, resumes, validates conditional answers and freezes submission in admin queue', async ({page, portal}) => {
  await openPortal(page, portal);
  await openFirstIntake(page);
  await page.locator('[data-question="weight_goals"]').fill('Fictional goals retained after reload');
  await page.locator('[data-question="previous_weight_treatment"][value="yes"]').check();
  await expect(page.locator('[data-question="previous_weight_details"]')).toBeVisible();
  await page.locator('[data-question="previous_weight_details"]').fill('Fictional prior treatment');
  await saved(page);
  await page.reload();
  await page.locator('[data-action="open-intake"]').first().click();
  await expect(page.locator('[data-question="weight_goals"]')).toHaveValue('Fictional goals retained after reload');
  await expect(page.locator('[data-question="previous_weight_details"]')).toHaveValue('Fictional prior treatment');
  await page.locator('[data-action="sample-answers"]:visible').click();
  await saved(page);
  await page.locator('[data-action="intake-next"]').click();
  await expect(page.locator('[data-question="current_medications"]')).toBeVisible();
  await page.locator('[data-action="intake-next"]').click();
  await expect(page.locator('[data-action="submit-intake"]')).toBeVisible();
  await expect(page.locator('.review-box')).toContainText('No medications or supplements in this fictional example.');
  await page.locator('[data-action="submit-intake"]').click();
  await expect(page.getByRole('heading', {name: 'Sample intake submitted'})).toBeVisible();
  await expect(page.locator('#intake-form')).toHaveCount(0);
  await expect(page.getByText('Awaiting review · demo', {exact: true})).toBeVisible();
  await page.getByRole('button', {name: 'Admin', exact: true}).click();
  await page.getByRole('button', {name: 'Intake queue', exact: true}).click();
  await expect(page.locator('main')).toContainText('Weight Loss');
  await expect(page.locator('main')).toContainText('Submitted');
  await expect(page.locator('main')).not.toContainText('Fictional prior treatment');
  await expect(page.locator('main')).not.toContainText('current_medications');
});

test('PATIENT-02 site switching keeps drafts and mock messages separate and admin filters therapy', async ({page, portal}) => {
  await openPortal(page, portal);
  await openFirstIntake(page);
  await page.locator('[data-question="weight_goals"]').fill('Willow sample only');
  await saved(page);
  await page.getByRole('button', {name: 'Messages', exact: true}).click();
  await page.locator('#message-body').fill('Willow fictional care message');
  const sent = [];
  page.on('request', request => {
    if (request.method() === 'POST' && request.url().endsWith('/messages')) sent.push(request);
  });
  await page.locator('#message-form button[type="submit"]').click();
  await expect(page.locator('#message-list .message.patient')).toHaveCount(1);
  await expect(page.locator('#message-list')).toContainText('Automated demo acknowledgement');
  expect(sent).toHaveLength(1);
  await page.locator('#site-select').selectOption('harbor-wellness');
  await expect(page.locator('.brand-name')).toHaveText('Harbor Wellness');
  await page.getByRole('button', {name: 'Messages', exact: true}).click();
  await expect(page.locator('#message-list .message')).toHaveCount(0);
  await page.getByRole('button', {name: 'Medical intake', exact: true}).click();
  await expect(page.locator('[data-question="weight_goals"]')).toHaveValue('');
  await page.getByRole('button', {name: 'Admin', exact: true}).click();
  await page.getByRole('button', {name: 'Orders', exact: true}).click();
  await page.locator('#therapy-filter').selectOption('metformin');
  await expect(page.locator('tbody tr')).toHaveCount(1);
  await expect(page.locator('tbody')).toContainText('Metformin');
  await expect(page.locator('tbody')).not.toContainText('Semaglutide');
  await expect(page.locator('main')).not.toContainText('Willow sample only');
  await page.getByRole('button', {name: 'Patient', exact: true}).click();
  await page.locator('#site-select').selectOption('willow-health');
  await page.getByRole('button', {name: 'Messages', exact: true}).click();
  await expect(page.locator('#message-list .message.patient')).toHaveCount(1);
  await expect(page.locator('#message-list')).toContainText('Willow fictional care message');
});

test('PATIENT-03 failed autosave reports unsaved changes and retry preserves the entered answer', async ({page, portal}) => {
  await openPortal(page, portal);
  await openFirstIntake(page);
  let fail = true;
  await page.route('**/api/v1/sites/*/intakes/*', route => {
    if (route.request().method() === 'PATCH' && fail) {
      return route.fulfill({status: 503, contentType: 'application/json', body: JSON.stringify({detail: 'Sample save unavailable. Retry now.'})});
    }
    return route.continue();
  });
  await page.locator('[data-question="weight_goals"]').fill('This fictional answer must survive a failed save');
  await expect(page.locator('#save-status')).toContainText('Not saved');
  await expect(page.locator('#intake-error')).toContainText('Sample save unavailable');
  await expect(page.locator('[data-question="weight_goals"]')).toHaveValue('This fictional answer must survive a failed save');
  fail = false;
  await page.locator('[data-action="retry-save"]').click();
  await saved(page);
  await page.reload();
  await page.locator('[data-action="open-intake"]').first().click();
  await expect(page.locator('[data-question="weight_goals"]')).toHaveValue('This fictional answer must survive a failed save');
});

test('PATIENT-04 desktop and mobile overview, intake and admin remain usable without horizontal overflow', async ({page, portal}, testInfo) => {
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  for (const width of [1440, 390]) {
    await page.setViewportSize({width, height: width === 390 ? 844 : 1000});
    await openPortal(page, portal);
    await assertNoOverflow(page);
    const navFits = await page.locator('nav[aria-label="Patient navigation"] .nav-link').evaluateAll(links => links.every(link => {
      const rect = link.getBoundingClientRect(); return rect.left >= 0 && rect.right <= innerWidth;
    }));
    expect(navFits).toBe(true);
    await page.screenshot({path: testInfo.outputPath(`overview-${width}.png`), fullPage: true});
    await openFirstIntake(page);
    await assertNoOverflow(page);
    await expect(page.locator('[data-action="sample-answers"]:visible')).toBeVisible();
    await page.screenshot({path: testInfo.outputPath(`intake-${width}.png`), fullPage: true});
    await page.getByRole('button', {name: 'Admin', exact: true}).click();
    await expect(page.locator('tbody tr')).toHaveCount(4);
    await assertNoOverflow(page);
    await page.screenshot({path: testInfo.outputPath(`admin-${width}.png`), fullPage: true});
  }
  expect(errors).toEqual([]);
});

test('PATIENT-05 a delayed response from a previous site cannot replace the current site messages', async ({page, portal}) => {
  await openPortal(page, portal);
  await page.getByRole('button', {name: 'Messages', exact: true}).click();
  await page.locator('#message-body').fill('Willow delayed message must stay in Willow');
  await page.locator('#message-form button[type="submit"]').click();
  await expect(page.locator('#message-list .message.patient')).toHaveCount(1);
  await page.getByRole('button', {name: 'Overview', exact: true}).click();
  let release;
  const released = new Promise(resolve => { release = resolve; });
  let intercepted;
  const pending = new Promise(resolve => { intercepted = resolve; });
  let delivered;
  const delivery = new Promise(resolve => { delivered = resolve; });
  await page.route('**/api/v1/sites/willow-health/messages', async route => {
    if (route.request().method() !== 'GET') return route.continue();
    const response = await route.fetch();
    intercepted();
    await released;
    await route.fulfill({response});
    delivered();
  });
  await page.getByRole('button', {name: 'Messages', exact: true}).click();
  await pending;
  await page.locator('#site-select').selectOption('harbor-wellness');
  await expect(page.locator('.brand-name')).toHaveText('Harbor Wellness');
  await expect(page.locator('[data-action="open-intake"]').first()).toBeVisible();
  await page.getByRole('button', {name: 'Messages', exact: true}).click();
  await expect(page.locator('#message-list .message')).toHaveCount(0);
  const oldResponse = page.waitForResponse(response => response.url().endsWith('/willow-health/messages'));
  release();
  await delivery;
  await (await oldResponse).finished();
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
  await expect(page.locator('#site-select')).toHaveValue('harbor-wellness');
  await expect(page.locator('#message-list .message')).toHaveCount(0);
  await expect(page.locator('#message-list')).not.toContainText('Willow delayed message');
});
