const {test:base,expect}=require('playwright/test');
const {spawn}=require('node:child_process');
const fs=require('node:fs');
const os=require('node:os');
const path=require('node:path');
const net=require('node:net');

async function freePort(){const server=net.createServer();await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));const port=server.address().port;await new Promise(resolve=>server.close(resolve));return port;}
const test=base.extend({careMode:[false,{option:true}],member:async({careMode},use)=>{
  const port=await freePort(),directory=fs.mkdtempSync(path.join(os.tmpdir(),'member-portal-qa-')),origin=`http://127.0.0.1:${port}`;
  const child=spawn(process.env.QA_PYTHON||'python3',[path.join(__dirname,'member_server.py'),'--port',String(port),'--state-dir',directory,...(careMode?['--care-plan']:[])],{stdio:['ignore','pipe','pipe']});let errors='';child.stderr.on('data',data=>errors+=data);
  try{await expect.poll(async()=>{if(child.exitCode!==null)throw Error(errors);try{return(await fetch(origin+'/health')).status;}catch{return 0;}},{timeout:15000}).toBe(200);await use({origin});}
  finally{child.kill('SIGTERM');await new Promise(resolve=>{if(child.exitCode!==null)return resolve();child.once('exit',resolve);setTimeout(()=>{child.kill('SIGKILL');resolve();},2000).unref();});fs.rmSync(directory,{recursive:true,force:true});}
}});

async function ownerLogin(page,member){await page.goto(member.origin+'/portal-admin/site-a');await page.locator('#auth-email').fill('owner@example.invalid');await page.locator('#auth-password').fill('owner-only-test-password');await page.getByRole('button',{name:'Sign in',exact:true}).click();await expect(page.locator('#site-select')).toHaveValue('site-a');await expect(page.getByRole('button',{name:'Sync captured orders',exact:true})).toBeVisible();}
async function enroll(page,member){
  await ownerLogin(page,member);await expect(page.getByRole('heading',{name:'No synced orders yet'})).toBeVisible();await page.getByRole('button',{name:'Sync captured orders',exact:true}).click();await expect(page.locator('.data-table')).toContainText('9001');
  await page.getByRole('button',{name:'Create invitation',exact:true}).click();const invitation=await page.locator('#enrollment-url').inputValue();await page.goto(invitation);await expect(page.getByRole('heading',{name:'Create your patient account'})).toBeVisible();await page.locator('#auth-password').fill('patient-only-test-password');await page.locator('#auth-confirm').fill('patient-only-test-password');await page.getByRole('button',{name:'Create account',exact:true}).click();await expect(page.getByRole('heading',{name:'Welcome, Sample.'})).toBeVisible();
}
async function orders(page){await page.getByRole('button',{name:'Orders & plans',exact:true}).click();await expect(page.locator('.full-order')).toContainText('9001');}
async function proof(page,member){const result=await(await page.request.get(member.origin+'/__member_qa')).json();expect(result.calls['POST /api/v1/new_order']||0).toBe(0);expect(result.calls['POST /api/v1/authorize_payment']||0).toBe(0);expect(result.calls['POST /api/v1/order_force_bill']||0).toBe(0);return result;}

test('MEMBER-01 actual-order sync, invitation enrollment and site isolation without fabricated orders',async({page,member})=>{
  const requests=[];page.on('request',request=>requests.push(request.url()));await enroll(page,member);await orders(page);
  await expect(page.locator('.full-order')).toContainText('$1.00');await expect(page.locator('#site-select')).toHaveCount(0);await expect(page.locator('.persona-switch')).toHaveCount(0);expect(requests.some(url=>url.includes('/api/demo/workspaces'))).toBe(false);
  await page.goto(member.origin+'/portal/site-b');await expect(page.getByRole('heading',{name:'Welcome back.'})).toBeVisible();await expect(page.locator('body')).not.toContainText('9001');await proof(page,member);
});

test('MEMBER-02 pause and resume require confirmation and use the real adapter contract',async({page,member})=>{
  await enroll(page,member);await orders(page);await page.getByRole('button',{name:'Pause scheduled cycles',exact:true}).click();await expect(page.getByRole('dialog')).toContainText('Included prepaid shipments may also be affected');
  let stats=await proof(page,member);expect(stats.calls['POST /api/v1/subscription_order_update']||0).toBe(0);
  await page.getByRole('button',{name:'Confirm pause',exact:true}).click();await expect(page.getByRole('button',{name:'Resume scheduled cycles',exact:true})).toBeVisible();
  await page.getByRole('button',{name:'Resume scheduled cycles',exact:true}).click();await page.getByRole('button',{name:'Confirm resume',exact:true}).click();await expect(page.getByRole('button',{name:'Pause scheduled cycles',exact:true})).toBeVisible();
  stats=await proof(page,member);expect(stats.calls['POST /api/v1/subscription_order_update']).toBe(2);
});

test('MEMBER-03 early-refill review, current-order address and blocked payment method are explicit',async({page,member})=>{
  await enroll(page,member);await orders(page);await page.getByRole('button',{name:'Request early refill',exact:true}).click();await expect(page.getByRole('dialog')).toContainText('does not move a billing date');await page.locator('#action-reason').fill('Fictional travel timing for browser QA');await page.getByRole('button',{name:'Send early refill request',exact:true}).click();await expect(page.getByRole('dialog')).toHaveCount(0);
  await page.getByRole('button',{name:'Refill requests',exact:true}).click();await expect(page.locator('.refill-row')).toContainText(/Awaiting review/i);await page.getByRole('button',{name:'Orders',exact:true}).click();
  await page.getByRole('button',{name:'Update delivery address',exact:true}).click();await expect(page.locator('#address-region option')).toHaveCount(60);await page.locator('#address-region').selectOption('CA');await page.locator('#address-city').fill('San Francisco');await page.locator('#address-postal_code').fill('94105');await page.getByRole('button',{name:'Save this order’s address',exact:true}).click();await expect(page.getByRole('dialog')).toHaveCount(0);
  await page.getByRole('button',{name:'Future delivery address',exact:true}).click();await expect(page.getByRole('dialog')).toContainText('current order stays unchanged');await expect(page.locator('#address-first_name')).toHaveAttribute('readonly','');await page.locator('#address-region').selectOption('NY');await page.locator('#address-city').fill('New York');await page.locator('#address-postal_code').fill('10001');await page.getByRole('button',{name:'Save future delivery address',exact:true}).click();await expect(page.getByRole('dialog')).toHaveCount(0);
  await page.getByRole('button',{name:'Future delivery address',exact:true}).click();await expect(page.locator('#address-region')).toHaveValue('NY');await expect(page.locator('#address-city')).toHaveValue('New York');await page.getByRole('button',{name:'Go back',exact:true}).click();
  await page.getByRole('button',{name:'Payment method options',exact:true}).click();await expect(page.getByRole('dialog')).toContainText('Secure payment-method updates are not connected');await expect(page.locator('input[autocomplete="cc-number"]')).toHaveCount(0);const stats=await proof(page,member);expect(stats.shipping_state).toBe('CA');expect(stats.subscription_state).toBe('NY');
});

test('MEMBER-04 partial intake autosaves and resumes, provider remains explicitly disconnected',async({page,member})=>{
  await enroll(page,member);await page.getByRole('button',{name:'Medical intake',exact:true}).click();await page.getByRole('button',{name:'Start initial intake',exact:true}).click();await expect(page.locator('#intake-form')).toBeVisible();await expect(page.locator('main')).toContainText('medical intake provider is not connected');await expect(page.locator('[data-action="sample-answers"]')).toHaveCount(0);
  await page.locator('[data-question="weight_goals"]').fill('Fictional browser QA goal');await expect(page.locator('#save-status')).toHaveText('Saved');await page.reload();await page.getByRole('button',{name:'Medical intake',exact:true}).click();await page.getByRole('button',{name:/Start initial intake|Continue form/,exact:true}).click();await expect(page.locator('[data-question="weight_goals"]')).toHaveValue('Fictional browser QA goal');
  await page.getByRole('button',{name:'Messages',exact:true}).click();await expect(page.locator('main')).toContainText('No doctor receives these messages');await page.locator('#message-body').fill('Where will order updates appear?');await page.getByRole('button',{name:'Send preview message',exact:true}).click();await expect(page.locator('.message.patient')).toContainText('Where will order updates appear?');await expect(page.locator('.message:not(.patient)')).toBeVisible();await proof(page,member);
});

test('MEMBER-05 desktop and mobile expose all navigation with no horizontal page overflow',async({page,member},testInfo)=>{
  await page.setViewportSize({width:1440,height:1000});await page.goto(member.origin+'/portal/site-a');await page.screenshot({path:testInfo.outputPath('login-desktop.png'),fullPage:true});await enroll(page,member);
  for(const width of [1440,390]){await page.setViewportSize({width,height:1000});await page.getByRole('button',{name:'Overview',exact:true}).click();expect(await page.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth)).toBe(false);await page.screenshot({path:testInfo.outputPath(`overview-${width}.png`),fullPage:true});await orders(page);expect(await page.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth)).toBe(false);await page.screenshot({path:testInfo.outputPath(`orders-${width}.png`),fullPage:true});for(const item of await page.locator('.nav-link').all()){const box=await item.boundingBox();expect(box.x).toBeGreaterThanOrEqual(0);expect(box.x+box.width).toBeLessThanOrEqual(width);}}
  await proof(page,member);
});


test('MEMBER-06 owner checkout testing toggle follows server capability and confirmed setting',async({page,member})=>{
  let enabled=false,updates=0;
  await page.route('**/api/admin/sites/site-a/checkout-testing',async route=>{if(route.request().method()==='PUT'){expect(route.request().headers()['x-csrf-token']).toBeTruthy();enabled=route.request().postDataJSON().enabled;updates++;}await route.fulfill({json:{enabled,available:true,initial_total:'1.00',renewal_total:'1.00',terms:'Test checkouts charge $1 upfront and $1 at renewal. Included prepaid cycles remain $0.'}});});
  await ownerLogin(page,member);await expect(page.locator('#checkout-testing')).not.toBeChecked();await expect(page.locator('main')).toContainText('Included prepaid cycles remain $0');await page.locator('#checkout-testing').check();await expect(page.locator('#checkout-testing')).toBeChecked();await expect(page.locator('main')).toContainText('$1 checkout testing is enabled');await page.locator('#checkout-testing').uncheck();await expect(page.locator('#checkout-testing')).not.toBeChecked();expect(updates).toBe(2);await proof(page,member);
});


test('MEMBER-07 owner session never exposes staff controls on a patient route',async({page,member},testInfo)=>{
  await ownerLogin(page,member);await expect(page.getByTestId('staff-banner')).toContainText('Administration · staff only');
  const patientLink=page.getByRole('link',{name:'Open patient portal',exact:true});await expect(patientLink).toHaveAttribute('href','/portal/site-a');
  await page.locator('#site-select').selectOption('site-b');await expect(patientLink).toHaveAttribute('href','/portal/site-b');
  await page.locator('#site-select').selectOption('site-a');await expect(patientLink).toHaveAttribute('href','/portal/site-a');
  for(const width of [1440,390]){await page.setViewportSize({width,height:1000});await expect(patientLink).toBeVisible();expect(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)).toBe(false);await page.screenshot({path:testInfo.outputPath(`staff-${width}.png`),fullPage:true});}
  const patientRequests=[];page.on('request',request=>patientRequests.push(request.url()));await patientLink.click();
  await expect(page).toHaveURL(member.origin+'/portal/site-a');await expect(page.getByRole('heading',{name:'Welcome back.',exact:true})).toBeVisible();
  await expect(page.getByTestId('staff-banner')).toHaveCount(0);await expect(page.getByRole('navigation',{name:'Admin navigation',exact:true})).toHaveCount(0);
  await expect(page.locator('#site-select,#checkout-testing,#import-form,[data-action="sync-orders"],[data-action="create-invite"]')).toHaveCount(0);
  await expect(page.locator('body')).not.toContainText('Administration · staff only');await expect(page.locator('body')).not.toContainText('Sticky');
  expect(patientRequests.some(url=>url.includes('/api/admin/'))).toBe(false);
  const ownerAuth=await page.evaluate(async()=>await(await fetch('/api/admin/auth')).json());expect(ownerAuth.authenticated).toBe(true);
  const patientStatus=await page.evaluate(async()=>(await fetch('/api/v1/sites/site-a/portal/orders')).status);expect(patientStatus).toBe(401);
  await page.reload();await expect(page.getByRole('heading',{name:'Welcome back.',exact:true})).toBeVisible();await expect(page.locator('#site-select,#checkout-testing,#import-form')).toHaveCount(0);
  await proof(page,member);
});


async function patientData(page,suffix,site='site-a'){
  return page.evaluate(async({suffix,site})=>{const auth=JSON.parse(sessionStorage.getItem('member-portal-session:site-a'));const response=await fetch(`/api/v1/sites/${site}/portal${suffix}`,{headers:{Authorization:`Bearer ${auth.access_token}`}});return{status:response.status,body:await response.json()};},{suffix,site});
}
async function finishCareForm(page,taskId){
  const form=(await patientData(page,`/orders/9001/care-tasks/${taskId}/intake`)).body;
  for(const section of form.template.sections){
    await expect(page.locator('.intake-card h2')).toHaveText(section.title);
    for(const question of form.template.questions.filter(item=>item.section_id===section.id)){
      const fields=page.locator(`[data-question="${question.id}"]`);if(!await fields.count())continue;
      const sample=question.id==='weight_goals'?'INITIAL QA ONLY':question.sample;
      if(question.type==='single_choice'){const value=sample??question.options[0].value;await page.locator(`[data-question="${question.id}"][value="${value}"]`).check();}
      else if(question.type==='multi_choice'){for(const value of(Array.isArray(sample)?sample:[question.options[0].value]))await page.locator(`[data-question="${question.id}"][value="${value}"]`).check();}
      else await fields.fill(String(sample??(question.type==='number'?180:'MOCK TEST: browser journey only.')));
    }
    const next=page.getByRole('button',{name:'Save & continue',exact:true});if(await next.count())await next.click();
  }
  await page.getByRole('button',{name:/^Submit (intake|check-in) preview$/}).click();await expect(page.locator('.submitted-hero')).toBeVisible();
}

test.describe('Configured 12-month care journey',()=>{
  test.use({careMode:true});
  test('MEMBER-08 separate initial and quarterly check-ins gate each refill and preserve earlier answers',async({page,member},testInfo)=>{
    test.setTimeout(90000);await enroll(page,member);await page.getByRole('button',{name:'Medical intake',exact:true}).click();
    const timeline=page.locator('[data-care-order="9001"]');await expect(timeline.locator('.care-task')).toHaveCount(4);
    for(const day of [90,180,270]){const task=timeline.locator(`[data-care-day="${day}"]`);await expect(task).toContainText('Upcoming');await expect(task.getByRole('button',{name:'Start check-in',exact:true})).toHaveCount(0);}
    await expect(page.locator('[data-action="care-simulation"],#checkout-testing,#site-select')).toHaveCount(0);
    for(const width of [1440,390]){await page.setViewportSize({width,height:1000});await page.screenshot({path:testInfo.outputPath(`care-start-${width}.png`),fullPage:true});}await page.setViewportSize({width:1440,height:1000});
    await timeline.getByRole('button',{name:'Start initial intake',exact:true}).click();await finishCareForm(page,'initial');
    const initial=(await patientData(page,'/orders/9001/care-tasks/initial/intake')).body;expect(initial.answers.weight_goals).toBe('INITIAL QA ONLY');
    await page.getByRole('button',{name:'Back to my care plan',exact:true}).click();await expect(timeline.locator('[data-care-day="0"]')).toContainText('Completed');
    const admin=await page.context().newPage();await admin.goto(member.origin+'/portal-admin/site-a');
    async function simulate(day){await admin.getByRole('button',{name:'Simulate care timeline',exact:true}).click();await admin.locator('#care-simulation-day').selectOption(String(day));await admin.getByRole('button',{name:'Apply timeline preview',exact:true}).click();await expect(admin.getByRole('dialog')).toHaveCount(0);await page.reload();await page.getByRole('button',{name:'Medical intake',exact:true}).click();await expect(timeline).toContainText(`Timeline simulation · day ${day}`);}
    await simulate(90);const day90=timeline.locator('[data-care-day="90"]');await expect(day90).toContainText('Ready');await expect(day90.getByRole('button',{name:'Request refill review',exact:true})).toHaveCount(0);
    await day90.getByRole('button',{name:'Start check-in',exact:true}).click();await page.locator('[data-question="weight_progress"]').fill('DAY 90 DRAFT ONLY');await expect(page.locator('#save-status')).toHaveText('Saved');await page.reload();await page.getByRole('button',{name:'Medical intake',exact:true}).click();await day90.getByRole('button',{name:'Continue form',exact:true}).click();await expect(page.locator('[data-question="weight_progress"]')).toHaveValue('DAY 90 DRAFT ONLY');
    await finishCareForm(page,'checkin-90');await page.getByRole('button',{name:'Back to my care plan',exact:true}).click();await day90.getByRole('button',{name:'Request refill review',exact:true}).click();await page.getByRole('button',{name:'Request refill',exact:true}).click();await expect(page.getByRole('dialog')).toHaveCount(0);await expect(day90).toContainText('Awaiting review');await expect(day90.getByRole('button',{name:'Request refill review',exact:true})).toHaveCount(0);
    const intakeIds=new Set([initial.id,(await patientData(page,'/orders/9001/care-tasks/checkin-90/intake')).body.id]);
    for(const day of [180,270]){
      await simulate(day);const task=timeline.locator(`[data-care-day="${day}"]`);await expect(day90).toContainText('Completed');await expect(task).toContainText('Ready');await expect(task.getByRole('button',{name:'Request refill review',exact:true})).toHaveCount(0);
      await task.getByRole('button',{name:'Start check-in',exact:true}).click();await expect(page.locator('[data-question="weight_progress"]')).toHaveValue('');const later=(await patientData(page,`/orders/9001/care-tasks/checkin-${day}/intake`)).body;expect(intakeIds.has(later.id)).toBe(false);intakeIds.add(later.id);expect(later.answers).toEqual({});
      await finishCareForm(page,`checkin-${day}`);await page.getByRole('button',{name:'Back to my care plan',exact:true}).click();await task.getByRole('button',{name:'Request refill review',exact:true}).click();await page.getByRole('button',{name:'Request refill',exact:true}).click();await expect(page.getByRole('dialog')).toHaveCount(0);await expect(task).toContainText('Awaiting review');
    }
    expect(intakeIds.size).toBe(4);const retained=(await patientData(page,'/orders/9001/care-tasks/initial/intake')).body;expect(retained.answers).toEqual(initial.answers);expect(retained.status).toBe('submitted');expect((await patientData(page,'/orders/9001/care-plan','site-b')).status).toBe(401);const requests=(await patientData(page,'/refills')).body.requests;expect(requests).toHaveLength(3);expect(new Set(requests.map(request=>request.task_id))).toEqual(new Set(['checkin-90','checkin-180','checkin-270']));
    for(const width of [1440,390]){await page.setViewportSize({width,height:1000});expect(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)).toBe(false);await page.screenshot({path:testInfo.outputPath(`care-journey-${width}.png`),fullPage:true});}
    const stats=await proof(page,member);expect(stats.calls['POST /api/v1/subscription_order_update']||0).toBe(0);expect(stats.calls['POST /api/v1/order_update']||0).toBe(0);await admin.close();
  });
});
