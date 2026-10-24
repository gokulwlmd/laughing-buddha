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
  await page.getByRole('button',{name:'Create invitation',exact:true}).click();const invitation=await page.locator('#enrollment-url').inputValue();await page.goto(invitation);await expect(page.getByRole('heading',{name:'Create your patient account'})).toBeVisible();await page.locator('#auth-password').fill('patient-only-test-password');await page.locator('#auth-confirm').fill('patient-only-test-password');await page.getByRole('button',{name:'Create account',exact:true}).click();await expect(page.getByRole('heading',{name:'Your next step',level:1,exact:true})).toBeVisible();await expect(page.locator('.care-home')).toContainText('Welcome, Sample.');
}
async function patientCopy(page){await expect(page.locator('main')).not.toContainText(/medical (?:service|team|intake provider) is not connected|\btest order\b|\btest timeline\b|dry run|use test answers|payment-test product|fictional answers|not been sent to a (?:medical team|clinician)/i);}
async function readable(page){
  const details=await page.locator('.page-head p,.welcome-card p,.small-note,.section-description,.field>label,.field legend,.choice,.modal p,.care-task-date,.care-refill-state,.order-progress-note,.order-progress-copy p,.order-progress-copy h4').evaluateAll(nodes=>nodes.filter(node=>node.getClientRects().length&&node.textContent.trim()).map(node=>({text:node.textContent.trim().slice(0,70),size:parseFloat(getComputedStyle(node).fontSize)})));
  for(const item of details)expect(item.size,JSON.stringify(item)).toBeGreaterThanOrEqual(16);
  const buttons=await page.locator('.btn-primary:visible').evaluateAll(nodes=>nodes.map(node=>{
    const {width,height}=node.getBoundingClientRect();return {width,height};
  }));
  for(const box of buttons){expect(box.height).toBeGreaterThanOrEqual(48);expect(box.width).toBeGreaterThanOrEqual(48);}
}
async function reflow(page,width){
  // Read one DOM snapshot: background responses can replace the entire shell
  // between separate boundingBox calls. Still require all seven patient routes.
  await expect.poll(()=>page.evaluate(width=>{
    const links=[...document.querySelectorAll('.nav-link')];
    return document.documentElement.scrollWidth<=innerWidth+1&&links.length===7&&links.every(link=>{
      const box=link.getBoundingClientRect();
      return box.width>0&&box.height>0&&box.x>=0&&box.right<=width+1;
    });
  },width)).toBe(true);
}
async function orders(page){await page.getByRole('button',{name:'Orders & plans',exact:true}).click();await expect(page.locator('.full-order')).toContainText('9001');}
async function proof(page,member){const result=await(await page.request.get(member.origin+'/__member_qa')).json();expect(result.calls['POST /api/v1/new_order']||0).toBe(0);expect(result.calls['POST /api/v1/authorize_payment']||0).toBe(0);expect(result.calls['POST /api/v1/order_force_bill']||0).toBe(0);return result;}

test('MEMBER-18 FortifyHP theme retains all patient routes and resets for another site',async({page,member},testInfo)=>{
  await page.route('**/api/v1/sites/site-a/portal/**',async route=>{
    const response=await route.fetch(),data=await response.json();if(data.site)data.site={...data.site,name:'FortifyHP',theme:'fortifyhp',color:'#A2563F'};
    await route.fulfill({response,json:data});
  });
  await page.goto(member.origin+'/portal/site-a');
  await expect(page.locator('body')).toHaveAttribute('data-portal-theme','fortifyhp');
  await expect(page.getByRole('img',{name:'FortifyHP',exact:true})).toBeVisible();
  expect(await page.locator('body').evaluate(node=>getComputedStyle(node).backgroundColor)).toBe('rgb(244, 241, 236)');
  await readable(page);await page.screenshot({path:testInfo.outputPath('fortifyhp-sign-in.png'),fullPage:true});
  await enroll(page,member);
  await expect(page.locator('body')).toHaveAttribute('data-portal-theme','fortifyhp');
  await expect(page.getByRole('img',{name:'FortifyHP',exact:true})).toBeVisible();
  for(const width of [1440,720,390]){
    await page.setViewportSize({width,height:1000});
    for(const name of ['Overview','Orders & plans','Refills','Medical intake','Messages','Notifications']){
      await page.getByRole('button',{name,exact:true}).click();
      await expect(page.getByRole('button',{name,exact:true})).toHaveAttribute('aria-current','page');
      await expect(page.locator('body')).toHaveAttribute('data-portal-theme','fortifyhp');
      await expect(page.locator('.loading-card')).toHaveCount(0);await reflow(page,width);await readable(page);
    }
    await page.getByRole('button',{name:'Overview',exact:true}).click();
    await page.screenshot({path:testInfo.outputPath(`fortifyhp-home-${width}.png`),fullPage:true});
  }
  await page.getByRole('button',{name:'Orders & plans',exact:true}).click();
  for(const name of ['Pause subscription','Update delivery address','Future delivery address','Update payment card'])await expect(page.getByRole('button',{name,exact:true})).toBeVisible();
  await page.goto(member.origin+'/portal/site-b');
  await expect(page.locator('body')).toHaveAttribute('data-portal-theme','default');
  await expect(page.getByRole('heading',{name:'Welcome back.',exact:true})).toBeVisible();
  await expect(page.locator('body')).not.toContainText('9001');await proof(page,member);
});

test('MEMBER-19 staff can edit site-only refill rules without exposing settings to patients',async({page,member})=>{
  await ownerLogin(page,member);await page.getByRole('button',{name:'Refill settings',exact:true}).click();
  await expect(page.getByRole('heading',{name:'Refill settings',exact:true})).toBeVisible();
  await expect(page.locator('#site-rule-sku')).toHaveValue('SEMA-1M-SUB');
  await page.getByLabel('Minimum days before refill access',{exact:true}).fill('30');
  await page.getByRole('button',{name:'Save site refill settings',exact:true}).click();
  await expect(page.locator('.notice.success')).toContainText('saved for this site');
  await page.reload();await page.getByRole('button',{name:'Refill settings',exact:true}).click();
  await expect(page.getByLabel('Minimum days before refill access',{exact:true})).toHaveValue('30');
  await page.locator('#site-select').selectOption('site-b');
  await expect(page.getByRole('heading',{name:'No products assigned yet',exact:true})).toBeVisible();
  await page.goto(member.origin+'/portal/site-a');
  await expect(page.getByRole('button',{name:'Refill settings',exact:true})).toHaveCount(0);
  await proof(page,member);
});

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
  await page.getByRole('button',{name:'Refill history',exact:true}).click();await expect(page.locator('.refill-row')).toContainText(/Awaiting review/i);await page.getByRole('button',{name:'Orders',exact:true}).click();
  await page.getByRole('button',{name:'Update delivery address',exact:true}).click();await expect(page.locator('#address-region option')).toHaveCount(60);await page.locator('#address-region').selectOption('CA');await page.locator('#address-city').fill('San Francisco');await page.locator('#address-postal_code').fill('94105');await page.getByRole('button',{name:'Save this order’s address',exact:true}).click();await expect(page.getByRole('dialog')).toHaveCount(0);
  await page.getByRole('button',{name:'Future delivery address',exact:true}).click();await expect(page.getByRole('dialog')).toContainText('current order stays unchanged');await expect(page.locator('#address-first_name')).toHaveAttribute('readonly','');await page.locator('#address-region').selectOption('NY');await page.locator('#address-city').fill('New York');await page.locator('#address-postal_code').fill('10001');await page.getByRole('button',{name:'Save future delivery address',exact:true}).click();await expect(page.getByRole('dialog')).toHaveCount(0);
  await page.getByRole('button',{name:'Future delivery address',exact:true}).click();await expect(page.locator('#address-region')).toHaveValue('NY');await expect(page.locator('#address-city')).toHaveValue('New York');await page.getByRole('button',{name:'Go back',exact:true}).click();
  await page.getByRole('button',{name:'Update payment card',exact:true}).click();await expect(page.getByRole('dialog')).toContainText('Contact support for help updating your payment card.');await expect(page.getByRole('dialog')).not.toContainText('not connected');await expect(page.locator('input[autocomplete="cc-number"]')).toHaveCount(0);const stats=await proof(page,member);expect(stats.shipping_state).toBe('CA');expect(stats.subscription_state).toBe('NY');
});

test('MEMBER-04 partial intake autosaves and resumes without technical patient notices',async({page,member})=>{
  await enroll(page,member);await page.getByRole('button',{name:'Medical intake',exact:true}).click();await page.getByRole('button',{name:'Start intake',exact:true}).click();await expect(page.locator('#intake-form')).toBeVisible();await patientCopy(page);await readable(page);await expect(page.locator('[data-action="sample-answers"]')).toHaveCount(0);
  await page.locator('[data-question="weight_goals"]').fill('Fictional browser QA goal');await expect(page.locator('#save-status')).toHaveText('Saved');await page.reload();await page.getByRole('button',{name:'Medical intake',exact:true}).click();await page.getByRole('button',{name:/Start intake|Continue form/,exact:true}).click();await expect(page.locator('[data-question="weight_goals"]')).toHaveValue('Fictional browser QA goal');
  await page.getByRole('button',{name:'Messages',exact:true}).click();await expect(page.getByRole('heading',{name:'Chat with your doctor',exact:true})).toBeVisible();await expect(page.locator('#message-body')).toBeVisible();await page.locator('#message-body').fill('Question saved for a later care conversation.');await page.getByRole('button',{name:'Save draft',exact:true}).click();await expect(page.locator('#message-draft-status')).toContainText('Draft saved');await page.reload();await page.getByRole('button',{name:'Messages',exact:true}).click();await expect(page.locator('#message-body')).toHaveValue('Question saved for a later care conversation.');expect((await patientData(page,'/messages/draft')).body.body).toBe('Question saved for a later care conversation.');expect((await patientData(page,'/messages')).body.messages).toEqual([]);await patientCopy(page);await proof(page,member);
});

test('MEMBER-05 desktop, mobile and 200-percent-equivalent reflow remain readable and usable',async({page,member},testInfo)=>{
  await page.setViewportSize({width:1440,height:1000});await page.goto(member.origin+'/portal/site-a');await readable(page);await page.screenshot({path:testInfo.outputPath('login-desktop.png'),fullPage:true});await enroll(page,member);
  // A 720 CSS-pixel viewport exercises the reflow of a 1440px display at 200% zoom.
  for(const width of [1440,720,390]){
    await page.setViewportSize({width,height:1000});await page.getByRole('button',{name:'Overview',exact:true}).click();await reflow(page,width);await readable(page);await patientCopy(page);await expect(page.locator('main')).not.toContainText('Included refills have no extra payment');await page.screenshot({path:testInfo.outputPath(`overview-${width}.png`),fullPage:true});
    await orders(page);await reflow(page,width);await readable(page);await patientCopy(page);await expect(page.locator('.full-order')).not.toContainText('Your included refills are already paid for');await expect(page.locator('.full-order')).toContainText('Next eligible date:');await page.screenshot({path:testInfo.outputPath(`orders-${width}.png`),fullPage:true});
    await page.getByRole('button',{name:'Medical intake',exact:true}).click();await page.getByRole('button',{name:/Start intake|Continue form/,exact:true}).click();await expect(page.locator('#intake-form')).toBeVisible();await reflow(page,width);await readable(page);await patientCopy(page);await page.screenshot({path:testInfo.outputPath(`intake-${width}.png`),fullPage:true});
  }
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
    await page.getByRole('button',{name:'Back to my care plan',exact:true}).click();await expect(timeline.locator('[data-care-day="0"]')).toContainText('Complete');await orders(page);await expect(page.locator('#order-9001')).not.toContainText('Next eligible date:');await expect(page.locator('#order-9001')).toContainText('View your intake and refill schedule.');await expect(page.locator('#order-9001 [data-stage="payment"]')).toHaveAttribute('data-state','complete');await expect(page.locator('#order-9001 [data-stage="intake"]')).toHaveAttribute('data-state','complete');await expect(page.locator('#order-9001 [data-stage="review"]')).toHaveAttribute('data-state','current');await expect(page.locator('#order-9001 [data-stage="prescription"],#order-9001 [data-stage="shipping"]')).toHaveCount(2);await page.getByRole('button',{name:'Medical intake',exact:true}).click();
    const admin=await page.context().newPage();await admin.goto(member.origin+'/portal-admin/site-a');
    async function simulate(day){await admin.locator('[data-action="care-simulation"][data-order="9001"]').click();await admin.locator('#care-simulation-day').selectOption(String(day));await admin.getByRole('button',{name:'Apply timeline preview',exact:true}).click();await expect(admin.getByRole('dialog')).toHaveCount(0);
      if(day===80){let release,observed;const gate=new Promise(resolve=>release=resolve),requested=new Promise(resolve=>observed=resolve),url='**/api/v1/sites/site-a/portal/orders';await page.route(url,async route=>{observed();await gate;await route.continue();});await page.reload();await requested;try{await expect(page.getByRole('button',{name:'Medical intake',exact:true})).toBeDisabled();}finally{release();}await expect(page.locator('.welcome-card')).toBeVisible();await page.unroute(url);}else await page.reload();await expect(page.locator('.welcome-card')).toBeVisible();await page.getByRole('button',{name:'Medical intake',exact:true}).click();await patientCopy(page);}
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
    await page.getByRole('button',{name:'Orders & plans',exact:true}).click();await page.getByRole('button',{name:'Refill history',exact:true}).click();await expect(page.locator('.refill-row')).toHaveCount(3);await page.getByRole('button',{name:'Orders',exact:true}).click();await expect(page.locator('.full-order')).toHaveCount(4);await expect(page.locator('.full-order').filter({hasText:'Next eligible date:'})).toHaveCount(0);await expect(page.locator('[data-care-order="9001"]')).toHaveCount(1);await expect(page.getByRole('button',{name:'Pause subscription',exact:true})).toHaveCount(1);await expect(page.getByRole('button',{name:'Pause subscription',exact:true})).toHaveAttribute('data-order','9004');await page.getByRole('button',{name:'Subscriptions',exact:true}).click();await expect(page.locator('.subscription-card')).toHaveCount(1);await expect(page.getByRole('button',{name:'Pause subscription',exact:true})).toHaveAttribute('data-order','9004');await expect(page.locator('[data-action="care-simulation"],#checkout-testing,#site-select')).toHaveCount(0);
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
  await page.locator('.welcome-card').getByRole('button',{name:'Start intake',exact:true}).click();await expect(page.locator('#intake-form')).toBeVisible();await patientCopy(page);await proof(page,member);
});

test('MEMBER-10 order timeline uses only recorded payment, intake, clinical and shipment evidence',async({page,member})=>{
  let evidence={payment_status:'paid',intake_status:'not_started',medical_status:'not_connected',fulfillment_status:'unknown',dry_run:true,test_only:true};
  await page.route('**/api/v1/sites/site-a/portal/orders',async route=>{const response=await route.fetch(),body=await response.json();body.orders=body.orders.map(order=>({...order,...evidence}));await route.fulfill({response,json:body});});
  await enroll(page,member);await orders(page);
  const timeline=page.locator('#order-9001 ol[aria-label="Order status timeline"]');
  async function stages(expected){
    await expect(timeline).toBeVisible();await expect(timeline.locator('li')).toHaveCount(5);
    expect(await timeline.locator('li').evaluateAll(nodes=>nodes.map(node=>[node.dataset.stage,node.dataset.state]))).toEqual(expected);
    await expect(timeline.locator('[aria-current="step"]')).toHaveCount(expected.filter(([,state])=>state==='current').length);await patientCopy(page);
  }
  await stages([['payment','complete'],['intake','current'],['review','upcoming'],['prescription','upcoming'],['shipping','upcoming']]);
  evidence.intake_status='draft';await page.reload();await orders(page);
  await stages([['payment','complete'],['intake','current'],['review','upcoming'],['prescription','upcoming'],['shipping','upcoming']]);
  evidence.intake_status='submitted';await page.reload();await orders(page);
  await stages([['payment','complete'],['intake','complete'],['review','current'],['prescription','upcoming'],['shipping','upcoming']]);
  await expect(timeline.locator('[data-stage="review"]')).toContainText('Awaiting review');
  evidence.medical_status='approved';await page.reload();await orders(page);
  await stages([['payment','complete'],['intake','complete'],['review','complete'],['prescription','current'],['shipping','upcoming']]);
  evidence.medical_status='prescribed';await page.reload();await orders(page);
  await stages([['payment','complete'],['intake','complete'],['review','complete'],['prescription','complete'],['shipping','current']]);
  // A shipment record does not establish an unrecorded prescription or approval.
  evidence.medical_status='not_connected';evidence.fulfillment_status='shipped';await page.reload();await orders(page);
  await stages([['payment','complete'],['intake','complete'],['review','current'],['prescription','upcoming'],['shipping','complete']]);
  evidence.payment_status='unknown';evidence.intake_status='not_started';evidence.fulfillment_status='unknown';await page.reload();await orders(page);
  await stages([['payment','current'],['intake','upcoming'],['review','upcoming'],['prescription','upcoming'],['shipping','upcoming']]);
  await proof(page,member);
});

test('MEMBER-11 address dialog supports keyboard fields, focus containment and return to the opener',async({page,member},testInfo)=>{
  await page.setViewportSize({width:390,height:900});await enroll(page,member);await orders(page);
  const opener=page.getByRole('button',{name:'Update delivery address',exact:true});await opener.focus();await page.keyboard.press('Enter');
  const dialog=page.getByRole('dialog',{name:'Update delivery address',exact:true});await expect(dialog).toBeVisible();await expect(dialog).toHaveAttribute('aria-modal','true');await readable(page);await reflow(page,390);
  const focusable=await dialog.locator('button:not(:disabled),input:not(:disabled):not([type="hidden"]),select:not(:disabled),textarea:not(:disabled),a[href]').count(),visited=new Set();
  for(let index=0;index<focusable+2;index++){await page.keyboard.press('Tab');const focused=await page.evaluate(()=>({within:Boolean(document.activeElement.closest('[role="dialog"]')),id:document.activeElement.id,outline:getComputedStyle(document.activeElement).outlineStyle,shadow:getComputedStyle(document.activeElement).boxShadow}));expect(focused.within).toBe(true);visited.add(focused.id);expect(focused.outline!=='none'||focused.shadow!=='none').toBe(true);}
  expect(visited.has('address-city')).toBe(true);expect(visited.has('address-region')).toBe(true);expect(visited.has('address-postal_code')).toBe(true);
  for(let index=0;index<focusable+2;index++){await page.keyboard.press('Shift+Tab');expect(await page.evaluate(()=>Boolean(document.activeElement.closest('[role="dialog"]')))).toBe(true);}
  await page.screenshot({path:testInfo.outputPath('address-keyboard-mobile.png'),fullPage:true});await page.keyboard.press('Escape');await expect(dialog).toHaveCount(0);await expect(opener).toBeFocused();
  await proof(page,member);
});

test('MEMBER-12 pale site branding keeps primary actions and their labels readable',async({page,member},testInfo)=>{
  await enroll(page,member);let tint='#bfe8ff';
  for(const endpoint of ['configuration','me'])await page.route(`**/api/v1/sites/site-a/portal/${endpoint}`,async route=>{const response=await route.fetch(),body=await response.json();body.site.color=tint;await route.fulfill({response,json:body});});
  for(const color of ['#bfe8ff','#ffffff','#ffff00','#66e099']){
    tint=color;await page.reload();await orders(page);
    const contrast=await page.getByRole('button',{name:'Request refill',exact:true}).evaluate(button=>{
      const style=getComputedStyle(button),channels=value=>value.match(/[\d.]+/g).slice(0,3).map(Number),luminance=rgb=>rgb.map(value=>{value/=255;return value<=0.04045?value/12.92:((value+0.055)/1.055)**2.4;}).reduce((total,value,index)=>total+value*[0.2126,0.7152,0.0722][index],0),a=luminance(channels(style.color)),b=luminance(channels(style.backgroundColor));return(Math.max(a,b)+0.05)/(Math.min(a,b)+0.05);
    });
    expect(contrast,`Primary button contrast for ${color}`).toBeGreaterThanOrEqual(4.5);await readable(page);
  }
  tint='#bfe8ff';await page.reload();await expect(page.locator('.welcome-card')).toBeVisible();
  for(const width of [1440,390]){await page.setViewportSize({width,height:1000});await reflow(page,width);await page.screenshot({path:testInfo.outputPath(`pale-brand-${width}.png`),fullPage:true});}
  await proof(page,member);
});

test('MEMBER-13 shipment details appear only from recorded tracking and shipment dates',async({page,member},testInfo)=>{
  let evidence={fulfillment_status:'unknown',tracking_number:null,shipping_date:null};
  await page.route('**/api/v1/sites/site-a/portal/orders',async route=>{const response=await route.fetch(),body=await response.json();body.orders=body.orders.map(order=>({...order,...evidence}));await route.fulfill({response,json:body});});
  await enroll(page,member);await orders(page);await expect(page.locator('.tracking-number')).toHaveCount(0);
  evidence={fulfillment_status:'shipped',tracking_number:'1Z-QA-RECORDED-9001',shipping_date:'2027-01-21'};await page.reload();await orders(page);
  const shipment=page.locator('[data-shipment-order="9001"]');await expect(shipment.locator('.tracking-number')).toHaveText('1Z-QA-RECORDED-9001');await expect(shipment).toContainText('Jan 21');
  await expect(page.locator('#order-9001 [data-stage="shipping"]')).toHaveAttribute('data-state','complete');await expect(page.locator('#order-9001 [data-stage="prescription"]')).not.toHaveAttribute('data-state','complete');
  for(const width of [1440,390]){await page.setViewportSize({width,height:1000});await reflow(page,width);await readable(page);await page.screenshot({path:testInfo.outputPath(`tracking-${width}.png`),fullPage:true});}
  evidence={fulfillment_status:'shipped',tracking_number:null,shipping_date:null};await page.reload();await orders(page);await expect(page.locator('.tracking-number')).toHaveCount(0);await expect(page.locator('#order-9001')).not.toContainText('Jan 21');await proof(page,member);
});

test.describe('Configured care notifications',()=>{
  test.use({careMode:true});
  test('MEMBER-14 notifications persist read state and open the correct patient care step',async({page,member},testInfo)=>{
  await enroll(page,member);const initial=(await patientData(page,'/notifications')).body,notice=initial.notifications.find(item=>item.order_id==='9001'&&item.action==='open-care-task');expect(notice).toBeTruthy();expect(notice.read_at).toBeNull();
  await page.locator('.nav-link[data-action="navigate"][data-view="notifications"]').click();const item=page.locator(`.notification-item[data-notification="${notice.id}"]`);await expect(item).toContainText(notice.title);await item.locator('[data-action="read-notification"]').click();
  await expect.poll(async()=>{const current=(await patientData(page,'/notifications')).body;return current.notifications.find(entry=>entry.id===notice.id)?.read_at;}).toBeTruthy();
  const marked=(await patientData(page,'/notifications')).body;expect(marked.unread_count).toBe(initial.unread_count-1);await page.reload();await page.locator('.nav-link[data-action="navigate"][data-view="notifications"]').click();await expect(item).toBeVisible();await expect(item.locator('[data-action="read-notification"]')).toHaveCount(0);
  for(const width of [1440,390]){await page.setViewportSize({width,height:1000});await reflow(page,width);await readable(page);await page.screenshot({path:testInfo.outputPath(`notifications-${width}.png`),fullPage:true});}
  await item.locator('[data-action="open-notification"]').click();await expect(page.locator('#intake-form')).toBeVisible();expect((await patientData(page,'/notifications','site-b')).status).toBe(401);expect((await patientData(page,'/messages/draft','site-b')).status).toBe(401);await proof(page,member);
  });
});

test('MEMBER-15 doctor drafts preserve text across save failures and stale revisions without sending',async({page,member},testInfo)=>{
  let sends=0;page.on('request',request=>{if(request.method()==='POST'&&request.url().endsWith('/portal/messages'))sends++;});await enroll(page,member);await page.getByRole('button',{name:'Messages',exact:true}).click();
  await expect(page.getByRole('heading',{name:'Chat with your doctor',exact:true})).toBeVisible();const field=page.locator('#message-body'),save=page.getByRole('button',{name:'Save draft',exact:true}),status=page.locator('#message-draft-status');
  await field.fill('First private draft.');await save.click();await expect(status).toContainText('Draft saved');const first=(await patientData(page,'/messages/draft')).body;expect(first.body).toBe('First private draft.');
  await page.route('**/api/v1/sites/site-a/portal/messages/draft',route=>route.request().method()==='PUT'?route.fulfill({status:503,json:{detail:'Draft saving is temporarily unavailable.'}}):route.continue());
  await field.fill('Keep this unsaved question.');await save.click();await expect(status).not.toContainText('Draft saved');await expect(field).toHaveValue('Keep this unsaved question.');expect((await patientData(page,'/messages/draft')).body.body).toBe(first.body);
  await page.unroute('**/api/v1/sites/site-a/portal/messages/draft');await save.click();await expect(status).toContainText('Draft saved');const current=(await patientData(page,'/messages/draft')).body;expect(current.body).toBe('Keep this unsaved question.');
  const edited=await page.evaluate(async draft=>{const auth=JSON.parse(sessionStorage.getItem('member-portal-session:site-a'));const response=await fetch('/api/v1/sites/site-a/portal/messages/draft',{method:'PUT',headers:{Authorization:`Bearer ${auth.access_token}`,'Content-Type':'application/json'},body:JSON.stringify({body:'Saved in another browser tab.',revision:draft.revision})});return response.status;},current);expect(edited).toBe(200);
  await field.fill('Local text must survive the revision conflict.');await save.click();await expect(status).not.toContainText('Draft saved');await expect(field).toHaveValue('Local text must survive the revision conflict.');expect((await patientData(page,'/messages/draft')).body.body).toBe('Saved in another browser tab.');
  expect((await patientData(page,'/messages')).body.messages).toEqual([]);expect(sends).toBe(0);await expect(page.locator('main')).toContainText('Draft · not sent');await expect(page.getByRole('button',{name:'Send message',exact:true})).toHaveCount(0);await expect(page.locator('main')).not.toContainText('Message sent');
  for(const width of [1440,390]){await page.setViewportSize({width,height:1000});await reflow(page,width);await readable(page);await page.screenshot({path:testInfo.outputPath(`doctor-draft-${width}.png`),fullPage:true});}
  const reload=page.locator('[data-action="reload-message-draft"]');await reload.click();await page.getByRole('dialog').getByRole('button',{name:'Go back',exact:true}).click();await expect(field).toHaveValue('Local text must survive the revision conflict.');await reload.click();await page.getByRole('dialog').getByRole('button',{name:'Load saved draft',exact:true}).click();await expect(field).toHaveValue('Saved in another browser tab.');await expect(status).toContainText('Draft saved');await field.fill('My recovered question for the next care conversation.');await save.click();await expect(status).toContainText('Draft saved');expect((await patientData(page,'/messages/draft')).body.body).toBe('My recovered question for the next care conversation.');expect(sends).toBe(0);
  for(const width of [1440,390]){await page.setViewportSize({width,height:1000});await reflow(page,width);await page.screenshot({path:testInfo.outputPath(`doctor-chat-${width}.png`),fullPage:true});}await proof(page,member);
});

test.describe('Independent treatment refill cards',()=>{
  test.use({careMode:true});
  test('MEMBER-16 refills group by paid term and a notification opens one treatment confirmation',async({page,member},testInfo)=>{
    const claims=[];let readAt=null;
    await page.route('**/api/v1/sites/site-a/portal/orders',async route=>{
      const response=await route.fetch(),body=await response.json();if(!body.orders.length)return route.fulfill({response,json:body});
      const first=structuredClone(body.orders[0]);first.intake_status='submitted';first.care_plan.initial_intake_complete=true;
      Object.assign(first.care_plan.tasks[0],{status:'submitted',intake_status:'submitted',can_submit:false});
      Object.assign(first.care_plan.tasks[1],{status:'draft',intake_status:'draft',can_open:true,can_submit:true,claim:{status:'claimed',available:false,order_id:'9002',amount:'0.00',created_at:'2026-10-23T12:00:00Z'}});
      const child=structuredClone(first);Object.assign(child,{id:'9002',number:'9002',total:'0.00',created_at:'2026-10-24T12:00:00Z'});
      const second=structuredClone(first);Object.assign(second,{id:'9100',number:'9100',therapy_id:'metformin',therapy_name:'Metformin',product_name:'Metformin',sku:'METFORM-6M-SUB',plan_name:'6-month subscription'});
      Object.assign(second.care_plan,{id:'care-9100',order_id:'9100',term_order_id:'9100',sku:'METFORM-6M-SUB',coverage_days:180});second.care_plan.tasks=second.care_plan.tasks.slice(0,2);
      Object.assign(second.care_plan.tasks[1],{status:'not_started',intake_status:'not_started',can_open:false,can_submit:false,claim:{status:'available',available:true,order_id:null,amount:'0.00',opens_at:'2026-10-23T12:00:00Z'}});
      body.orders=[child,second,first];await route.fulfill({response,json:body});
    });
    await page.route('**/api/v1/sites/site-a/portal/notifications**',async route=>{if(route.request().method()==='POST')readAt='2026-10-23T12:00:00Z';await route.fulfill({json:{notifications:[{id:'qa-refill-9100',kind:'refill-ready',title:'Your Metformin refill is ready',body:'Review your included refill.',created_at:'2026-10-23T12:00:00Z',read_at:readAt,order_id:'9100',task_id:'checkin-90',action:'claim-refill'}],unread_count:readAt?0:1}});});
    await page.route('**/api/v1/sites/site-a/portal/orders/*/care-tasks/*/claim',async route=>{claims.push({url:route.request().url(),body:route.request().postDataJSON()});await route.fulfill({status:503,json:{detail:'Offline QA stopped before creating a refill.'}});});
    await enroll(page,member);await page.getByRole('navigation',{name:'Patient navigation',exact:true}).getByRole('button',{name:'Refills',exact:true}).click();await expect(page.locator('.refill-plan')).toHaveCount(2);await expect(page.locator('[data-refill-order="9002"]')).toHaveCount(0);
    const first=page.locator('.refill-plan[data-refill-order="9001"]'),second=page.locator('.refill-plan[data-refill-order="9100"]');await expect(first).toContainText('Semaglutide');await expect(second).toContainText('Metformin');
    await expect(first.locator('.refill-next-step [data-action="open-care-task"]')).toHaveAttribute('data-task','checkin-90');await expect(first.locator('.refill-next-step [data-action="open-care-task"]')).toHaveAttribute('data-order','9001');await expect(first.locator('[data-action="claim-refill"]')).toHaveCount(0);await expect(second.locator('.refill-next-step [data-action="claim-refill"]')).toHaveAttribute('data-order','9100');await expect(page.getByRole('button',{name:/claim all|refill all/i})).toHaveCount(0);expect(claims).toEqual([]);
    for(const width of [1440,390]){await page.setViewportSize({width,height:1000});await reflow(page,width);await readable(page);await page.screenshot({path:testInfo.outputPath(`independent-refills-${width}.png`),fullPage:true});}
    await page.locator('.nav-link[data-action="navigate"][data-view="notifications"]').click();await page.locator('[data-notification="qa-refill-9100"] [data-action="open-notification"]').click();await expect(second).toBeVisible();await expect(page.getByRole('dialog')).toHaveCount(0);expect(claims).toEqual([]);await second.locator('.refill-next-step [data-action="claim-refill"]').click();const dialog=page.getByRole('dialog');await expect(dialog).toContainText('$0 due today');expect(claims).toEqual([]);
    await dialog.getByRole('button',{name:'Claim included refill',exact:true}).click();await expect.poll(()=>claims.length).toBe(1);expect(claims[0].url).toContain('/orders/9100/care-tasks/checkin-90/claim');expect(claims[0].body.client_request_id).toBeTruthy();await expect(page.locator('body')).toContainText('Offline QA stopped before creating a refill.');await proof(page,member);
  });
});

test.describe('Treatment overview',()=>{
  test.use({careMode:true});
  test('MEMBER-17 home keeps separate purchased terms, groups included orders and preserves patient navigation',async({page,member})=>{
    await page.route('**/api/v1/sites/site-a/portal/configuration',async route=>{
      const response=await route.fetch(),body=await response.json();body.therapies.push({id:'metformin',name:'Metformin'});await route.fulfill({response,json:body});
    });
    await page.route('**/api/v1/sites/site-a/portal/orders',async route=>{
      const response=await route.fetch(),body=await response.json();if(!body.orders.length)return route.fulfill({response,json:body});
      const first=structuredClone(body.orders[0]);
      const second=structuredClone(first);Object.assign(second,{id:'9100',number:'9100',created_at:'2026-10-23T12:00:00Z',plan_name:'6-month subscription'});
      Object.assign(second.care_plan,{id:'care-9100',order_id:'9100',term_order_id:'9100',coverage_days:180});second.care_plan.tasks=second.care_plan.tasks.slice(0,2);
      Object.assign(first.care_plan.tasks[1],{status:'draft',intake_status:'draft',can_open:true,can_submit:true,claim:{status:'claimed',available:false,order_id:'9002',amount:'0.00',created_at:'2026-10-24T12:00:00Z'}});
      const child=structuredClone(first);Object.assign(child,{id:'9002',number:'9002',total:'0.00',created_at:'2026-10-24T12:00:00Z'});
      // A newer included order must not replace its purchased term, and the
      // same medication bought again must keep its own treatment entry.
      body.orders=[child,second,first];await route.fulfill({response,json:body});
    });
    await enroll(page,member);
    const navigation=page.getByRole('navigation',{name:'Patient navigation',exact:true});
    const routes=[['Overview','Your next step'],['Orders & plans','Orders & plans'],['Refills','Manage your refills'],['Medical intake','Intake & check-ins'],['Messages','Chat with your doctor'],['Notifications','Notifications']];
    for(const [label] of routes)await expect(navigation.getByRole('button',{name:label,exact:true})).toBeVisible();
    for(const width of [1440,390]){
      await page.setViewportSize({width,height:1000});await navigation.getByRole('button',{name:'Overview',exact:true}).click();
      const treatments=page.locator('.home-treatments'),rows=treatments.locator('.treatment-summary-row');
      await expect(rows).toHaveCount(2);await expect(rows.filter({hasText:'Semaglutide'})).toHaveCount(2);
      const original=rows.filter({has:page.locator('[data-action="order-detail"][data-order="9001"]')}),repeat=rows.filter({has:page.locator('[data-action="order-detail"][data-order="9100"]')});
      await expect(original).toHaveCount(1);await expect(original).toContainText('12-month plan');await expect(repeat).toHaveCount(1);await expect(repeat).toContainText('6-month plan');
      await expect(treatments.locator('[data-action="order-detail"][data-order="9002"]')).toHaveCount(0);await reflow(page,width);await readable(page);await patientCopy(page);
      for(const orderId of ['9001','9100']){
        await treatments.locator(`[data-action="order-detail"][data-order="${orderId}"]`).click();
        await expect(navigation.getByRole('button',{name:'Orders & plans',exact:true})).toHaveAttribute('aria-current','page');
        await expect(page.locator(`#order-${orderId} .order-head .order-id`)).toBeInViewport();
        await navigation.getByRole('button',{name:'Overview',exact:true}).click();
      }
      for(const [label,heading] of routes){
        const link=navigation.getByRole('button',{name:label,exact:true});await link.click();
        await expect(link).toHaveAttribute('aria-current','page');await expect(page.getByRole('heading',{name:heading,level:1,exact:true})).toBeVisible();
      }
    }
    await navigation.getByRole('button',{name:'Overview',exact:true}).click();
    const planFacts=page.locator('.home-plan-facts');await expect(planFacts).toContainText('Next scheduled date');const unfilteredFacts=await planFacts.innerText();
    await navigation.getByRole('button',{name:'Orders & plans',exact:true}).click();await page.locator('#therapy-filter').selectOption('metformin');await expect(page.locator('.full-order')).toHaveCount(0);
    await navigation.getByRole('button',{name:'Overview',exact:true}).click();await expect(planFacts).toHaveText(unfilteredFacts,{useInnerText:true});await expect(page.locator('.home-plan-summary [data-action="order-detail"]')).toHaveAttribute('data-order','9001');
    await proof(page,member);
  });
});

test('MEMBER-20 navigation scrolls to content and modal keeps page stationary',async({page,member})=>{
  await enroll(page,member);await orders(page);
  await page.evaluate(()=>window.scrollTo(0,document.body.scrollHeight));
  await page.getByRole('button',{name:'Medical intake',exact:true}).click();
  await expect(page.getByRole('heading',{level:1})).toBeInViewport();
  await orders(page);
  const address=page.getByRole('button',{name:'Update delivery address',exact:true});await address.click();
  await expect(page.locator('body')).toHaveClass(/modal-open/);
  await expect(page.getByRole('dialog')).toBeInViewport();
  await page.keyboard.press('Escape');await expect(page.locator('body')).not.toHaveClass(/modal-open/);
  await expect(page.getByRole('button',{name:'Update delivery address',exact:true})).toBeFocused();
  await proof(page,member);
});


test('MEMBER-21 saved intake details and explicit confirmation remain readable on mobile',async({page,member},info)=>{
 await page.setViewportSize({width:390,height:900});await enroll(page,member);
 await page.route('**/api/v1/sites/site-a/portal/intakes/9001',async route=>{
   const response=await route.fetch(),data=await response.json();
   if(data.template){
     const height=data.template.questions.find(q=>q.id==='height_inches');Object.assign(height,{reuse_policy:'stable',reuse_status:'stable',saved_value:68});
     if(data.answers.height_inches===undefined)data.answers.height_inches=68;
     const goal=data.template.questions.find(q=>q.id==='weight_goals');Object.assign(goal,{reuse_policy:'confirm',reuse_status:'confirm',saved_value:'Synthetic prior goal'});
   }
   await route.fulfill({response,json:data});
 });
 await page.getByRole('button',{name:'Medical intake',exact:true}).click();await page.getByRole('button',{name:'Start intake',exact:true}).click();
 await expect(page.getByText('Saved from your previous intake',{exact:false})).toBeVisible();
 await expect(page.locator('[data-question="height_inches"]')).not.toBeVisible();
 await page.getByRole('button',{name:'Still correct',exact:true}).click();
 await expect(page.locator('[data-question="weight_goals"]')).toHaveValue('Synthetic prior goal');
 await expect(page.locator('#save-status')).toHaveText('Saved');
 await page.getByText('Change saved answer',{exact:true}).click();await page.locator('[data-question="height_inches"]').fill('69');
 await expect(page.locator('#save-status')).toHaveText('Saved');await readable(page);await reflow(page,390);
 await page.screenshot({path:info.outputPath('member-reused-answers-mobile.png'),fullPage:true});
 await proof(page,member);
});

test('MEMBER-22 monthly refill confirms native charge and schedule without a second checkout',async({page,member},info)=>{
 const writes=[];
 await page.route('**/api/v1/sites/site-a/portal/orders',async route=>{
  const response=await route.fetch(),body=await response.json();for(const order of body.orders){order.product_name='Semaglutide / 1 months / Subscription';order.care_plan={coverage_days:30,tasks:[]};order.subscriptions=[{id:'monthly-9001',status:'active',next_billing_date:'2026-11-22',billing_interval_days:30,actions:['pause']}];}
  await route.fulfill({response,json:body});
 });
 await page.route('**/api/v1/sites/site-a/portal/orders/9001/subscriptions/monthly-9001/renewal',async route=>{
  if(route.request().method()==='POST'){writes.push(route.request().postDataJSON());return route.fulfill({status:409,json:{detail:'We are confirming your payment and next renewal date. Do not pay again.'}});}
  return route.fulfill({json:{available:true,quote_id:'renew_offline_quote_1234',amount:'2.99',currency:'USD',scheduled_date:'2026-11-22',next_billing_date:'2026-12-01',interval_days:30}});
 });
 await enroll(page,member);await orders(page);await page.getByRole('button',{name:'Refill options',exact:true}).click();
 const card=page.locator('[data-refill-order="9001"]');
 await expect(card.getByRole('heading',{name:'Semaglutide',exact:true})).toBeVisible();
 await expect(card).toContainText('Monthly subscription · 30-day supply');
 await expect(card).toContainText('Payment: $2.99');
 await expect(card).not.toContainText('Not included in this plan');await expect(card).not.toContainText('amount is not available');
 await expect(card.getByRole('button',{name:'Claim included refill',exact:true})).toHaveCount(0);
 await expect(card.locator('.refill-plan-options')).toHaveCount(0);expect(writes).toEqual([]);
 for(const width of [1440,390]){await page.setViewportSize({width,height:1000});await reflow(page,width);await readable(page);await page.screenshot({path:info.outputPath('monthly-native-renewal-'+width+'.png'),fullPage:true});}
 await card.getByRole('button',{name:'Request refill sooner',exact:true}).click();
 const dialog=page.getByRole('dialog');await expect(dialog).toContainText('existing subscription');await expect(dialog).toContainText('Dec 1');expect(writes).toEqual([]);
 await dialog.getByRole('button',{name:'Go back',exact:true}).click();expect(writes).toEqual([]);
 await card.getByRole('button',{name:'Request refill sooner',exact:true}).click();
 await dialog.getByRole('button',{name:'Pay $2.99 & renew',exact:true}).click();
 await expect(dialog).toContainText('Do not pay again');expect(writes).toEqual([{quote_id:'renew_offline_quote_1234',confirmed:true}]);
 await expect(dialog.getByRole('button',{name:'Pay $2.99 & renew',exact:true})).toHaveCount(0);
 await dialog.getByRole('button',{name:'Close',exact:true}).click();
 await card.getByRole('button',{name:'Manage subscription',exact:true}).click();
 await expect(page.locator('.line-subscriptions').getByRole('button',{name:'Pause subscription',exact:true})).toBeInViewport();
 await proof(page,member);
});
test('MEMBER-24 paused subscription does not offer a separate early purchase',async({page,member})=>{
 await page.route('**/api/v1/sites/site-a/portal/orders',async route=>{
  const response=await route.fetch(),body=await response.json();for(const order of body.orders)order.subscriptions=[{id:'paused',status:'held',next_billing_date:null,actions:['resume']}];
  await route.fulfill({response,json:body});
 });
 await enroll(page,member);await page.getByRole('button',{name:'Refills',exact:true}).click();
 const card=page.locator('[data-refill-order="9001"]');await expect(card).toContainText('Your subscription is paused');
 await expect(card.getByRole('button',{name:'Request refill sooner',exact:true})).toHaveCount(0);
 await expect(card.locator('.refill-plan-options')).toHaveCount(0);await proof(page,member);
});
test('MEMBER-26 required intake blocks renewal but displays verified price',async({page,member})=>{
 await page.route('**/api/v1/sites/site-a/portal/orders/*/subscriptions/*/renewal',async route=>route.fulfill({json:{available:false,amount:'2.99',currency:'USD',scheduled_date:'2026-11-22',reason:'Complete your health intake for this order before requesting an early refill.'}}));
 await enroll(page,member);await page.getByRole('button',{name:'Refills',exact:true}).click();
 const card=page.locator('[data-refill-order="9001"]');await expect(card).toContainText('Payment: $2.99');
 await expect(card.getByRole('button',{name:'Request refill sooner',exact:true})).toBeDisabled();await expect(card).toContainText('Complete your health intake');await proof(page,member);
});
test.describe('Visible included-refill instructions',()=>{
 test.use({careMode:true,timezoneId:'America/Los_Angeles'});
 test('MEMBER-25 six-month nonrenewing prepaid plan never promises a paid renewal',async({page,member})=>{
  await page.route('**/api/v1/sites/site-a/portal/orders',async route=>{
   const response=await route.fetch(),body=await response.json();for(const order of body.orders){order.care_plan.coverage_days=180;order.care_plan.tasks=order.care_plan.tasks.slice(0,2);for(const sub of order.subscriptions)sub.prepaid_renews=false;}
   await route.fulfill({response,json:body});
  });
  await enroll(page,member);await page.getByRole('button',{name:'Refills',exact:true}).click();
  const card=page.locator('[data-refill-order="9001"]');
  await expect(card).toContainText('6-month plan');await expect(card).toContainText('1included refill remaining');
  await expect(card.getByRole('button',{name:'Claim included refill',exact:true})).toBeDisabled();
  await expect(card.getByRole('heading',{name:'Your next paid renewal',exact:true})).toHaveCount(0);
  await proof(page,member);
 });
 test('MEMBER-23 upcoming refill remains visible and disabled with opening date and steps',async({page,member},info)=>{
  await enroll(page,member);await page.getByRole('button',{name:'Refills',exact:true}).click();
  const card=page.locator('[data-refill-order="9001"]');
  await expect(card.getByRole('button',{name:'Claim included refill',exact:true})).toBeDisabled();
  const schedule=(await patientData(page,'/orders/9001/care-plan')).body;
  const expectedDate=new Date(schedule.tasks[1].claim.opens_at+'T12:00:00').toLocaleDateString('en-US',{month:'short',day:'numeric',year:'numeric'});
  await expect(card).toContainText('Claim window opens: '+expectedDate);
  await expect(card).toContainText('3');
  await expect(card.locator('.refill-locked ol li')).toHaveCount(3);
  await expect(card).toContainText('Complete your initial health intake');
  for(const width of [1440,390]){await page.setViewportSize({width,height:1000});await reflow(page,width);await readable(page);await page.screenshot({path:info.outputPath('locked-refill-'+width+'.png'),fullPage:true});}
  await proof(page,member);
 });
});

for(const width of [1440,390])test(`IDENTITY account settings and intake at ${width}px`,async({page,member},info)=>{
  await page.setViewportSize({width,height:1000});
  await page.route('**/api/v1/sites/site-a/portal/**',async route=>{const response=await route.fetch(),data=await response.json();if(data.site)data.site={...data.site,name:'FortifyHP',theme:'fortifyhp',color:'#A2563F'};await route.fulfill({response,json:data});});
  await enroll(page,member);await page.request.post(member.origin+'/__member_identity');
  await page.getByRole('button',{name:'Account settings',exact:true}).click();
  await expect(page.getByRole('heading',{name:'Identity verification',exact:true})).toBeVisible();
  await expect(page.getByLabel('Last 4 digits of your SSN')).toBeVisible();
  await reflow(page,width);await page.screenshot({path:info.outputPath(`identity-account-needed-${width}.png`),fullPage:true});
  await page.getByRole('button',{name:'Medical intake',exact:true}).click();
  await page.getByRole('button',{name:'Start intake',exact:true}).click();
  await expect(page.getByRole('heading',{name:'Verify your identity',exact:true})).toBeVisible();
  await expect(page.locator('#intake-form')).toHaveCount(0);
  await page.getByLabel('Last 4 digits of your SSN').fill('1234');
  await page.getByRole('button',{name:'Verify & continue to intake',exact:true}).click();
  await expect(page.locator('#intake-form')).toBeVisible();
  await page.getByRole('button',{name:'Account settings',exact:true}).click();
  await expect(page.getByText("You're verified. You're all set.",{exact:true})).toBeVisible();
  await expect(page.locator('#identity-last4')).toHaveCount(0);
  expect(await page.evaluate(()=>JSON.stringify({...localStorage,...sessionStorage}))).not.toContain('1234');
  await reflow(page,width);await page.screenshot({path:info.outputPath(`identity-account-verified-${width}.png`),fullPage:true});
  await proof(page,member);
});

for(const width of [1440,390])test(`IDPHOTO upload alternative resumes intake at ${width}px`,async({page,member},info)=>{
 await page.setViewportSize({width,height:1000});await enroll(page,member);await page.request.post(member.origin+'/__member_identity');
 await page.getByRole('button',{name:'Medical intake',exact:true}).click();await page.getByRole('button',{name:'Start intake',exact:true}).click();
 await expect(page.getByLabel('Upload ID',{exact:true})).toBeVisible();
 await expect(page.getByRole('button',{name:'Take photo of ID',exact:true})).toBeVisible();
 const data=await page.evaluate(()=>{const c=document.createElement('canvas');c.width=800;c.height=500;const x=c.getContext('2d');x.fillStyle='#e4e7e4';x.fillRect(0,0,800,500);x.fillStyle='#333';x.font='24px sans-serif';x.fillText('SYNTHETIC UI TEST - NOT AN ID',100,250);return c.toDataURL('image/png').split(',')[1];});
 await page.getByLabel('Upload ID',{exact:true}).setInputFiles({name:'synthetic.png',mimeType:'image/png',buffer:Buffer.from(data,'base64')});
 await expect(page.getByRole('img',{name:/Your selected ID photo/})).toBeVisible();
 await page.screenshot({path:info.outputPath('id-photo-preview-'+width+'.png'),fullPage:true});
 await page.getByRole('button',{name:'Upload this photo',exact:true}).click();
 await expect(page.locator('#intake-form')).toBeVisible();
 await page.getByRole('button',{name:'Account settings',exact:true}).click();
 await expect(page.getByRole('heading',{name:'Your ID photo is saved'})).toBeVisible();
 await expect(page.getByText('Your ID photo is on file.',{exact:true})).toBeVisible();
 await expect(page.locator('#identity-last4')).toHaveCount(0);
 expect(await page.evaluate(()=>JSON.stringify({...localStorage,...sessionStorage}))).not.toContain('data:image');
 await reflow(page,width);await page.screenshot({path:info.outputPath('id-photo-saved-'+width+'.png'),fullPage:true});await proof(page,member);
});
