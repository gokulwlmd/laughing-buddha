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
  await enroll(page,member);await orders(page);await page.getByRole('button',{name:'Pause subscription',exact:true}).click();await expect(page.getByRole('dialog')).toContainText('Included prepaid shipments may also be affected');
  let stats=await proof(page,member);expect(stats.calls['POST /api/v1/subscription_order_update']||0).toBe(0);
  await page.getByRole('button',{name:'Confirm pause',exact:true}).click();await expect(page.getByRole('button',{name:'Resume subscription',exact:true})).toBeVisible();
  await page.getByRole('button',{name:'Resume subscription',exact:true}).click();await page.getByRole('button',{name:'Confirm resume',exact:true}).click();await expect(page.getByRole('button',{name:'Pause subscription',exact:true})).toBeVisible();
  stats=await proof(page,member);expect(stats.calls['POST /api/v1/subscription_order_update']).toBe(2);
});

test('MEMBER-03 early-refill review, current-order address and blocked payment method are explicit',async({page,member})=>{
  await enroll(page,member);await orders(page);await page.getByRole('button',{name:'Request early refill',exact:true}).click();await expect(page.getByRole('dialog')).toContainText('does not move a billing date');await page.locator('#action-reason').fill('Fictional travel timing for browser QA');await page.getByRole('button',{name:'Send early refill request',exact:true}).click();await expect(page.getByRole('dialog')).toHaveCount(0);
  await page.getByRole('button',{name:'Refills',exact:true}).click();await expect(page.locator('.refill-row')).toContainText(/Awaiting review/i);await page.getByRole('button',{name:'Orders',exact:true}).click();
  await page.getByRole('button',{name:'Update delivery address',exact:true}).click();await expect(page.locator('#address-region option')).toHaveCount(60);await page.locator('#address-region').selectOption('CA');await page.locator('#address-city').fill('San Francisco');await page.locator('#address-postal_code').fill('94105');await page.getByRole('button',{name:'Save this order’s address',exact:true}).click();await expect(page.getByRole('dialog')).toHaveCount(0);
  await page.getByRole('button',{name:'Future delivery address',exact:true}).click();await expect(page.getByRole('dialog')).toContainText('current order stays unchanged');await expect(page.locator('#address-first_name')).toHaveAttribute('readonly','');await page.locator('#address-region').selectOption('NY');await page.locator('#address-city').fill('New York');await page.locator('#address-postal_code').fill('10001');await page.getByRole('button',{name:'Save future delivery address',exact:true}).click();await expect(page.getByRole('dialog')).toHaveCount(0);
  await page.getByRole('button',{name:'Future delivery address',exact:true}).click();await expect(page.locator('#address-region')).toHaveValue('NY');await expect(page.locator('#address-city')).toHaveValue('New York');await page.getByRole('button',{name:'Go back',exact:true}).click();
  await page.getByRole('button',{name:'Update payment card',exact:true}).click();await expect(page.getByRole('dialog')).toContainText('Secure payment-method updates are not connected');await expect(page.locator('input[autocomplete="cc-number"]')).toHaveCount(0);const stats=await proof(page,member);expect(stats.shipping_state).toBe('CA');expect(stats.subscription_state).toBe('NY');
});

test('MEMBER-04 partial intake autosaves and resumes, provider remains explicitly disconnected',async({page,member})=>{
  await enroll(page,member);await page.getByRole('button',{name:'Medical intake',exact:true}).click();await page.getByRole('button',{name:'Start intake',exact:true}).click();await expect(page.locator('#intake-form')).toBeVisible();await expect(page.locator('main')).toContainText('medical service is not connected');await expect(page.locator('[data-action="sample-answers"]')).toHaveCount(0);
  await page.locator('[data-question="weight_goals"]').fill('Fictional browser QA goal');await expect(page.locator('#save-status')).toHaveText('Saved');await page.reload();await page.getByRole('button',{name:'Medical intake',exact:true}).click();await page.getByRole('button',{name:/Start intake|Continue form/,exact:true}).click();await expect(page.locator('[data-question="weight_goals"]')).toHaveValue('Fictional browser QA goal');
  await page.getByRole('button',{name:'Messages',exact:true}).click();await expect(page.getByRole('heading',{name:'Messaging is not available yet',exact:true})).toBeVisible();await expect(page.locator('#message-body')).toHaveCount(0);await expect(page.locator('main')).toContainText('Messages cannot be sent from here.');await proof(page,member);
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
  await page.getByRole('button',{name:/^Submit (intake|check-in)$/}).click();await expect(page.locator('.submitted-hero')).toBeVisible();
}

test.describe('Configured 12-month care journey',()=>{
  test.use({careMode:true});
  test('MEMBER-08 included refills claimed at days 80, 170 and 260 each create a zero-dollar order before a fresh check-in',async({page,member},testInfo)=>{
    test.setTimeout(120000);await enroll(page,member);await page.getByRole('button',{name:'Medical intake',exact:true}).click();
    const timeline=page.locator('[data-care-order="9001"]');await expect(timeline).toHaveCount(1);await expect(timeline.locator('.care-task')).toHaveCount(4);
    for(const day of [90,180,270]){const task=timeline.locator(`[data-care-day="${day}"]`);await expect(task).toContainText('Upcoming');await expect(task.getByRole('button',{name:'Claim included refill',exact:true})).toHaveCount(0);await expect(task.getByRole('button',{name:'Complete check-in',exact:true})).toHaveCount(0);}
    await expect(page.locator('[data-action="care-simulation"],#checkout-testing,#site-select')).toHaveCount(0);
    for(const width of [1440,390]){await page.setViewportSize({width,height:1000});await page.screenshot({path:testInfo.outputPath(`care-start-${width}.png`),fullPage:true});}await page.setViewportSize({width:1440,height:1000});
    await timeline.getByRole('button',{name:'Start intake',exact:true}).click();await finishCareForm(page,'initial');
    const initial=(await patientData(page,'/orders/9001/care-tasks/initial/intake')).body;expect(initial.answers.weight_goals).toBe('INITIAL QA ONLY');const intakeIds=new Set([initial.id]);
    await page.getByRole('button',{name:'Back to my care plan',exact:true}).click();await expect(timeline.locator('[data-care-day="0"]')).toContainText('Complete');
    const admin=await page.context().newPage();await admin.goto(member.origin+'/portal-admin/site-a');
    async function simulate(day){await admin.locator('[data-action="care-simulation"][data-order="9001"]').click();await admin.locator('#care-simulation-day').selectOption(String(day));await admin.getByRole('button',{name:'Apply timeline preview',exact:true}).click();await expect(admin.getByRole('dialog')).toHaveCount(0);
      if(day===80){let release,observed;const gate=new Promise(resolve=>release=resolve),requested=new Promise(resolve=>observed=resolve),url='**/api/v1/sites/site-a/portal/orders';await page.route(url,async route=>{observed();await gate;await route.continue();});await page.reload();await requested;try{await expect(page.getByRole('button',{name:'Medical intake',exact:true})).toBeDisabled();}finally{release();}await expect(page.locator('.welcome-card')).toBeVisible();await page.unroute(url);}else await page.reload();await expect(page.locator('.welcome-card')).toBeVisible();await page.getByRole('button',{name:'Medical intake',exact:true}).click();await expect(timeline).toContainText(`Test timeline · day ${day}`);}
    for(const [day,claimDay,childId] of [[90,80,'9002'],[180,170,'9003'],[270,260,'9004']]){
      await simulate(claimDay);const task=timeline.locator(`[data-care-day="${day}"]`);await expect(task).toContainText('Available');await expect(task.getByRole('button',{name:'Complete check-in',exact:true})).toHaveCount(0);
      await task.getByRole('button',{name:'Claim included refill',exact:true}).click();await expect(page.getByRole('dialog')).toContainText('$0 due today');await page.getByRole('dialog').getByRole('button',{name:'Claim included refill',exact:true}).click();await expect(page.getByRole('dialog')).toHaveCount(0);await expect(page.locator('#intake-form')).toBeVisible();
      const care=(await patientData(page,'/orders/9001/care-plan')).body;const claimed=care.tasks.find(item=>item.id===`checkin-${day}`);expect(claimed.claim.status).toBe('claimed');expect(claimed.claim.order_id).toBe(childId);expect(claimed.claim.amount).toBe('0.00');
      const fresh=(await patientData(page,`/orders/9001/care-tasks/checkin-${day}/intake`)).body;expect(fresh.answers).toEqual({});expect(intakeIds.has(fresh.id)).toBe(false);intakeIds.add(fresh.id);await expect(page.locator('[data-question="weight_progress"]')).toHaveValue('');
      if(day===90){await page.locator('[data-question="weight_progress"]').fill('REFILL 1 DRAFT ONLY');await expect(page.locator('#save-status')).toHaveText('Saved');await page.reload();await expect(page.locator('.welcome-card')).toBeVisible();await page.getByRole('button',{name:'Medical intake',exact:true}).click();await task.getByRole('button',{name:'Continue form',exact:true}).click();await expect(page.locator('[data-question="weight_progress"]')).toHaveValue('REFILL 1 DRAFT ONLY');}
      await finishCareForm(page,`checkin-${day}`);await page.getByRole('button',{name:'Back to my care plan',exact:true}).click();await expect(timeline).toHaveCount(1);await expect(task).toContainText('Complete');await expect(task).toContainText(`Refill order ${childId}`);await expect(task.getByRole('button',{name:'Claim included refill',exact:true})).toHaveCount(0);
      const stats=await(await page.request.get(member.origin+'/__member_qa')).json();expect(stats.calls['POST /api/v1/order_force_bill']).toBe(day/90);expect(stats.native_orders.filter(order=>order.id!=='9001').every(order=>order.total==='0.00')).toBe(true);
    }
    expect(intakeIds.size).toBe(4);const retained=(await patientData(page,'/orders/9001/care-tasks/initial/intake')).body;expect(retained.answers).toEqual(initial.answers);expect(retained.status).toBe('submitted');expect((await patientData(page,'/orders/9001/care-plan','site-b')).status).toBe(401);
    const actualOrders=(await patientData(page,'/orders')).body.orders;expect(actualOrders).toHaveLength(4);expect(actualOrders.filter(order=>order.id!=='9001').map(order=>order.total)).toEqual(['0.00','0.00','0.00']);expect((await patientData(page,'/refills')).body.requests).toHaveLength(0);
    for(const width of [1440,390]){await page.setViewportSize({width,height:1000});expect(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)).toBe(false);await page.screenshot({path:testInfo.outputPath(`care-journey-${width}.png`),fullPage:true});}
    await page.getByRole('button',{name:'Orders & plans',exact:true}).click();await page.getByRole('button',{name:'Refills',exact:true}).click();await expect(page.locator('.refill-row')).toHaveCount(3);await page.getByRole('button',{name:'Orders',exact:true}).click();await expect(page.locator('.full-order')).toHaveCount(4);await expect(page.locator('[data-care-order="9001"]')).toHaveCount(1);await expect(page.getByRole('button',{name:'Pause subscription',exact:true})).toHaveCount(1);await expect(page.getByRole('button',{name:'Pause subscription',exact:true})).toHaveAttribute('data-order','9004');await page.getByRole('button',{name:'Subscriptions',exact:true}).click();await expect(page.locator('.subscription-card')).toHaveCount(1);await expect(page.getByRole('button',{name:'Pause subscription',exact:true})).toHaveAttribute('data-order','9004');await expect(page.locator('[data-action="care-simulation"],#checkout-testing,#site-select')).toHaveCount(0);
    const stats=await(await page.request.get(member.origin+'/__member_qa')).json();expect(stats.calls['POST /api/v1/order_force_bill']).toBe(3);expect(stats.calls['POST /api/v1/subscription_order_update']).toBe(3);for(const path of ['new_order','authorize_payment','order_update'])expect(stats.calls[`POST /api/v1/${path}`]||0).toBe(0);expect(stats.native_orders.filter(order=>order.id!=='9001')).toEqual([{id:'9002',total:'0.00',next_cycle_date:'2027-04-20'},{id:'9003',total:'0.00',next_cycle_date:'2027-07-19'},{id:'9004',total:'0.00',next_cycle_date:'2027-10-17'}]);await admin.close();
  });
});

test('MEMBER-09 customer next step and same-site plan choices use simple copy and actual checkout destinations',async({page,member})=>{
  await page.route('**/api/v1/sites/site-a/portal/store',route=>route.fulfill({json:{plans:[
    {plan_id:'sema-month',therapy_id:'weight-loss',therapy_name:'Weight Loss',product_name:'Semaglutide',plan_name:'1 month',total:'249.00',currency:'USD',checkout_url:member.origin+'/c/published-month'},
    {plan_id:'sema-year',therapy_id:'weight-loss',therapy_name:'Weight Loss',product_name:'Semaglutide',plan_name:'12 months',total:'1999.00',currency:'USD',checkout_url:member.origin+'/c/published-year'},
    {plan_id:'metformin-month',therapy_id:'metformin',therapy_name:'Metformin',product_name:'Metformin',plan_name:'1 month',total:'49.00',currency:'USD',checkout_url:member.origin+'/c/published-metformin'}
  ]}}));
  await enroll(page,member);await expect(page.getByRole('heading',{name:'Complete your health intake',exact:true})).toBeVisible();await expect(page.locator('.store-plan')).toHaveCount(2);await expect(page.locator('body')).not.toContainText('preview');await expect(page.locator('body')).not.toContainText('Test order');
  const sema=page.locator('.store-plan').filter({has:page.getByRole('heading',{name:'Semaglutide',exact:true})});await sema.locator('select').selectOption('sema-year');await expect(sema.locator('.store-price')).toHaveText('$1,999.00');await expect(sema.getByRole('link',{name:'View plan',exact:true})).toHaveAttribute('href',member.origin+'/c/published-year');
  await page.locator('.welcome-card').getByRole('button',{name:'Start intake',exact:true}).click();await expect(page.locator('#intake-form')).toBeVisible();await expect(page.locator('main')).toContainText('The medical service is not connected yet');await expect(page.locator('main')).not.toContainText('fictional answers');await proof(page,member);
});
