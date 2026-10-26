const {test,expect}=require('playwright/test');
const fs=require('node:fs');
const path=require('node:path');
const idScript=fs.readFileSync(path.join(__dirname,'../member_portal/web/id-upload.js'),'utf8');
const script=fs.readFileSync(path.join(__dirname,'../member_portal/web/post-checkout.js'),'utf8');
const template={title:'Semaglutide health intake',version:'mock-care-1',sections:[{id:'health',title:'Your health',description:'Tell us about yourself.'},{id:'review',title:'Anything else?',description:'Review and finish.'}],questions:[{id:'allergies',section_id:'health',label:'Do you have any allergies?',type:'single_choice',required:true,options:[{value:'no',label:'No'},{value:'yes',label:'Yes'}]},{id:'details',section_id:'health',label:'Which allergies?',type:'textarea',required:true,show_if:{question_id:'allergies',equals:'yes'}},{id:'notes',section_id:'review',label:'Anything else to share?',type:'textarea',required:false}]};
async function setup(page,accountOptions={}){let photoWrites=0;let identityWrites=0,identityVerified=!accountOptions.identity;let accountWrites=0;let draft={id:'i-1',revision:0,status:'draft',current_step:0,answers:accountOptions.answers||{},template:accountOptions.template||template};let patches=0;await page.route('https://shop.example/**',r=>r.fulfill({contentType:'text/html',body:'<html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1"></head><body style="font:18px Arial;background:#f4f1ec;margin:40px"><wlmd-purchase-intake></wlmd-purchase-intake><script src="https://backend.example/portal-assets/post-checkout.js"></script></body></html>'}));await page.route('https://backend.example/portal-assets/post-checkout.js',r=>r.fulfill({contentType:'text/javascript',body:script}));await page.route('https://backend.example/portal-assets/id-upload.js',r=>r.fulfill({contentType:'text/javascript',headers:{'access-control-allow-origin':'https://shop.example'},body:idScript}));await page.route('https://backend.example/api/**',async r=>{if(r.request().method()==='OPTIONS')return r.fulfill({headers:{'access-control-allow-origin':'https://shop.example','access-control-allow-methods':'GET,POST,PATCH','access-control-allow-headers':'authorization,content-type'}});expect(r.request().headers().authorization).toBe('Bearer receipt-only-token');if(r.request().url().includes('/journey'))return r.fulfill({headers:{'access-control-allow-origin':'https://shop.example'},json:{id:'QA-1',product_name:'Semaglutide',intake_status:draft.status,journey:{title:draft.status==='submitted'?'Your intake is saved':'Your health intake is next',stages:[]}}});if(r.request().url().endsWith('/account')){if(accountOptions.accountReadFail&&r.request().method()==='GET')return r.fulfill({status:502,headers:{'access-control-allow-origin':'https://shop.example'},json:{detail:'Account unavailable'}});if(r.request().method()==='POST'){accountWrites++;expect(r.request().postDataJSON()).toEqual({password:'Synthetic-password-123!'});if(accountOptions.fail)return r.fulfill({status:502,headers:{'access-control-allow-origin':'https://shop.example'},json:{detail:'Your purchase is saved. Please try account setup again.'}});}return r.fulfill({headers:{'access-control-allow-origin':'https://shop.example'},json:{state:accountWrites?'ready':accountOptions.state||'sign_in',provider:'sticky'}});}if(r.request().url().endsWith('/id-photo/reuse')){photoWrites++;identityVerified=true;return r.fulfill({headers:{'access-control-allow-origin':'https://shop.example'},json:{status:'uploaded',order_attached:true,saved:true,uploaded_at:'2026-10-24T00:00:00Z'}});}if(r.request().url().endsWith('/id-photo')){if(r.request().method()==='POST'){photoWrites++;if(accountOptions.photoFail)return r.fulfill({status:409,headers:{'access-control-allow-origin':'https://shop.example'},json:{detail:'We couldn’t confirm your upload. Retry your saved photo.'}});expect(typeof r.request().postDataJSON().file_contents).toBe('string');identityVerified=true;}return r.fulfill({headers:{'access-control-allow-origin':'https://shop.example'},json:{status:accountOptions.photoFail&&photoWrites&&!identityVerified?'needs_review':photoWrites?'uploaded':'needed',available:true,order_attached:!!photoWrites&&identityVerified,saved:!!photoWrites||!!accountOptions.savedPhoto,uploaded_at:'2026-10-24T00:00:00Z'}});}if(r.request().url().endsWith('/identity')){identityWrites++;expect(r.request().postDataJSON()).toEqual({last4:'1234'});identityVerified=!accountOptions.identityFail;return r.fulfill({status:identityVerified?200:409,headers:{'access-control-allow-origin':'https://shop.example'},json:identityVerified?{status:'verified'}:{detail:'We couldn’t confirm your identity. Please try again shortly.'}});}if(!identityVerified&&r.request().url().endsWith('/submit'))return r.fulfill({status:409,headers:{'access-control-allow-origin':'https://shop.example'},json:{detail:{code:'identity_verification_required',message:'Verify your identity to continue your intake.'}}});if(r.request().method()==='PATCH'){patches++;const body=r.request().postDataJSON();expect(body.revision).toBe(draft.revision);draft={...draft,...body,revision:draft.revision+1};}if(r.request().url().endsWith('/submit'))draft={...draft,status:'submitted',revision:draft.revision+1};await r.fulfill({headers:{'access-control-allow-origin':'https://shop.example'},json:draft});});await page.goto('https://shop.example/complete');await page.evaluate(async()=>{await customElements.whenDefined('wlmd-purchase-intake');await document.querySelector('wlmd-purchase-intake').configure({siteId:'fortifyhp',sessions:[{session_id:'owned-order',session_token:'receipt-only-token'}]});});if(accountOptions.state!=='set_password'&&!accountOptions.welcome)await page.getByRole('button',{name:'Start health intake',exact:true}).click();return {draft:()=>draft,patches:()=>patches,accountWrites:()=>accountWrites,identityWrites:()=>identityWrites,photoWrites:()=>photoWrites};}
test('shared intake saves draft, conditional questions and submits without login',async({page},info)=>{const state=await setup(page);await expect(page.getByRole('heading',{name:'Your health'})).toBeVisible();await expect(page.locator('input[type=password]')).toHaveCount(0);await page.getByRole('radio',{name:'Yes',exact:true}).check();await expect(page.getByRole('textbox',{name:'Which allergies?'})).toBeVisible();await page.getByRole('textbox',{name:'Which allergies?'}).fill('Synthetic QA only');await expect.poll(()=>state.draft().answers.details).toBe('Synthetic QA only');await page.getByRole('button',{name:'Continue',exact:true}).click();await expect(page.getByRole('textbox',{name:'Anything else to share?'})).toBeVisible();await page.screenshot({path:info.outputPath('shared-intake-desktop.png'),fullPage:true});await page.getByRole('button',{name:'Submit intake'}).click();await expect(page.getByText('Your intake has been submitted.',{exact:false})).toBeVisible();expect(state.draft().status).toBe('submitted');});
test('required answers and mobile reflow',async({page},info)=>{await page.setViewportSize({width:390,height:844});await setup(page);await page.getByRole('button',{name:'Continue',exact:true}).click();await expect(page.getByText('Please answer this question.')).toBeVisible();await page.getByRole('radio',{name:'No',exact:true}).check();await page.getByRole('button',{name:'Continue',exact:true}).click();await expect(page.getByRole('button',{name:'Submit intake'})).toBeVisible();expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);await page.screenshot({path:info.outputPath('shared-intake-mobile.png'),fullPage:true});});

test('set Sticky password without email while intake stays usable',async({page},info)=>{
 const state=await setup(page,{state:'set_password'});
 await page.getByLabel('Choose a password').fill('Synthetic-password-123!');
 await page.getByLabel('Confirm password',{exact:true}).fill('Synthetic-password-123!');
 await page.getByRole('button',{name:'Set password & continue'}).click();
 await expect(page.getByRole('heading',{name:'Your portal password is saved'})).toBeVisible();
 expect(state.accountWrites()).toBe(1);
 await expect(page.locator('input[type=password]')).toHaveCount(0);
 expect(await page.evaluate(()=>JSON.stringify({...localStorage,...sessionStorage}))).not.toContain('Synthetic-password');
 await page.getByRole('radio',{name:'No',exact:true}).check();
 await expect.poll(()=>state.draft().answers.allergies).toBe('no');
 await page.screenshot({path:info.outputPath('sticky-password-desktop.png'),fullPage:true});
});
test('password mismatch and provider error preserve purchase and intake',async({page},info)=>{
 await page.setViewportSize({width:390,height:844});const state=await setup(page,{state:'set_password',fail:true});
 await page.getByLabel('Choose a password').fill('Synthetic-password-123!');
 await page.getByLabel('Confirm password',{exact:true}).fill('Mismatch-password-123!');
 await page.getByRole('button',{name:'Set password & continue'}).click();
 await expect(page.getByText('The passwords do not match.',{exact:false})).toBeVisible();expect(state.accountWrites()).toBe(0);
 await page.getByLabel('Choose a password').fill('Synthetic-password-123!');await page.getByLabel('Confirm password',{exact:true}).fill('Synthetic-password-123!');
 await page.getByRole('button',{name:'Set password & continue'}).click();
 await expect(page.getByText('Your purchase is saved. Please try account setup again.')).toBeVisible();
 await page.getByRole('button',{name:'Set up later · continue to intake',exact:true}).click();
 await expect(page.getByRole('heading',{name:'Your health'})).toBeVisible();
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 await page.screenshot({path:info.outputPath('sticky-password-mobile.png'),fullPage:true});
});

for(const width of [1440,390])test(`saved details skip re-entry and health answers require confirmation at ${width}px`,async({page},info)=>{
 await page.setViewportSize({width,height:900});
 const reused=structuredClone(template);
 reused.questions.unshift({id:'height',section_id:'health',label:'Height in inches',type:'number',required:true,reuse_status:'stable',reuse_policy:'stable',saved_value:68});
 reused.questions[1].reuse_status='confirm';reused.questions[1].reuse_policy='confirm';reused.questions[1].saved_value='no';
 const state=await setup(page,{template:reused,answers:{height:68}});
 await expect(page.getByText('Saved from your previous intake',{exact:false})).toBeVisible();
 await expect(page.getByRole('spinbutton')).not.toBeVisible();
 await page.getByRole('button',{name:'Continue',exact:true}).click();
 await expect(page.getByText('Please answer this question.')).toBeVisible();
 await page.getByRole('button',{name:'Still correct'}).click();
 await expect.poll(()=>state.draft().answers.allergies).toBe('no');
 await page.getByText('Change saved answer',{exact:true}).click();
 await page.getByRole('spinbutton').fill('69');
 await expect.poll(()=>state.draft().answers.height).toBe(69);
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 await page.screenshot({path:info.outputPath('reused-intake-'+width+'.png'),fullPage:true});
 await page.getByRole('button',{name:'Continue',exact:true}).click();
 await page.getByRole('button',{name:'Submit intake'}).click();
 await expect(page.getByText('Your intake has been submitted.',{exact:false})).toBeVisible();
});

for(const width of [1440,390])test(`IDENTITY shared purchase intake verification at ${width}px`,async({page},info)=>{
 await page.setViewportSize({width,height:900});const state=await setup(page,{identity:true});await reachIdentity(page);
 await expect(page.getByRole('heading',{name:'One last step: verify your identity',exact:true})).toBeVisible();
 await expect(page.getByRole('radio',{name:'No',exact:true})).toHaveCount(0);
 expect(state.identityWrites()).toBe(0);
 await page.screenshot({path:info.outputPath('identity-checkout-'+width+'.png'),fullPage:true});
 await page.getByLabel('Last 4 digits of your SSN').fill('1234');
 await page.getByRole('button',{name:'Verify & finish intake'}).click();
 await expect(page.getByRole('heading',{name:'Your intake is saved'})).toBeVisible();
 expect(state.identityWrites()).toBe(1);
 await expect(page.locator('#identity-last4')).toHaveCount(0);
 expect(await page.evaluate(()=>JSON.stringify({...localStorage,...sessionStorage}))).not.toContain('1234');
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
});
test('IDENTITY shared verification error stays before intake and clears digits',async({page})=>{
 const state=await setup(page,{identity:true,identityFail:true});await reachIdentity(page);
 await page.getByLabel('Last 4 digits of your SSN').fill('1234');
 await page.getByRole('button',{name:'Verify & finish intake'}).click();
 await expect(page.getByRole('alert')).toContainText('couldn’t confirm');
 await expect(page.getByLabel('Last 4 digits of your SSN')).toHaveValue('');
 await expect(page.getByRole('radio')).toHaveCount(0);
 expect(state.identityWrites()).toBe(1);
});

test('IDPHOTO shared checkout accepts photo without SSN and preserves intake flow',async({page})=>{
 const state=await setup(page,{identity:true});await reachIdentity(page);await expect(page.getByLabel('Upload ID',{exact:true})).toBeVisible();
 const data=await page.evaluate(()=>{const c=document.createElement('canvas');c.width=600;c.height=400;const ctx=c.getContext('2d');ctx.fillStyle='#aaa';ctx.fillRect(0,0,600,400);return c.toDataURL('image/png').split(',')[1];});
 await page.getByLabel('Upload ID',{exact:true}).setInputFiles({name:'synthetic.png',mimeType:'image/png',buffer:Buffer.from(data,'base64')});
 await page.getByRole('button',{name:'Upload this photo',exact:true}).click();
 await expect(page.getByRole('heading',{name:'Your intake is saved'})).toBeVisible();expect(state.identityWrites()).toBe(0);await expect.poll(()=>state.photoWrites()).toBe(1);
});

test('IDPHOTO saved photo attaches automatically for the next intake without asking again',async({page})=>{
 const state=await setup(page,{identity:true,savedPhoto:true});await reachIdentity(page);
 await expect(page.getByRole('heading',{name:'Your intake is saved'})).toBeVisible();
 expect(state.identityWrites()).toBe(0);await expect.poll(()=>state.photoWrites()).toBe(1);
 await expect(page.getByLabel('Upload ID',{exact:true})).toHaveCount(0);
});

test('IDPHOTO uncertain upload offers an explicit retry with the saved photo',async({page})=>{
 const state=await setup(page,{identity:true,photoFail:true});await reachIdentity(page);
 await expect(page.getByLabel('Upload ID',{exact:true})).toBeVisible();
 const data=await page.evaluate(()=>{const c=document.createElement('canvas');c.width=600;c.height=400;return c.toDataURL('image/png').split(',')[1];});
 await page.getByLabel('Upload ID',{exact:true}).setInputFiles({name:'synthetic.png',mimeType:'image/png',buffer:Buffer.from(data,'base64')});
 await page.getByRole('button',{name:'Upload this photo',exact:true}).click();
 await expect(page.getByRole('button',{name:'Retry saved photo',exact:true})).toBeVisible();
 expect(state.photoWrites()).toBe(1);
 await page.getByRole('button',{name:'Retry saved photo',exact:true}).click();
 await expect(page.getByRole('heading',{name:'Your intake is saved'})).toBeVisible();expect(state.photoWrites()).toBe(2);
});

async function reachIdentity(page){
 await expect(page.getByLabel('Last 4 digits of your SSN')).toHaveCount(0);
 await page.getByRole('radio',{name:'No',exact:true}).check();
 await page.getByRole('button',{name:'Continue',exact:true}).click();
 await page.getByRole('button',{name:'Submit intake',exact:true}).click();
}

test('expanded weight-loss form saves through visible steps then verifies identity last',async({page},info)=>{
 await page.setViewportSize({width:390,height:844});
 const expanded=JSON.parse(fs.readFileSync(path.join(__dirname,'../member_portal/weight_loss_questions.json'),'utf8'));
 const answers=Object.fromEntries(expanded.questions.map(q=>[q.id,q.type==='number'?68:q.options?(q.type==='multi_choice'?[q.options.find(o=>/none/i.test(o.value))?.value||q.options[0].value]:q.options.find(o=>/^no\b/i.test(o.value))?.value||q.options[0].value):'Synthetic QA only']));
 const state=await setup(page,{template:expanded,answers,identity:true});
 await expect(page.getByLabel('Last 4 digits of your SSN')).toHaveCount(0);
 for(let i=0;i<expanded.sections.length;i++){if(state.draft().current_step===expanded.sections.length-1)break;const before=state.draft().current_step;await page.getByRole('button',{name:'Continue',exact:true}).click();await expect.poll(()=>state.draft().current_step).toBeGreaterThan(before);}
 await page.getByRole('button',{name:'Submit intake',exact:true}).click();
 await expect(page.getByRole('heading',{name:'One last step: verify your identity'})).toBeVisible();
 await page.getByLabel('Last 4 digits of your SSN').fill('1234');await page.getByRole('button',{name:'Verify & finish intake'}).click();
 await expect(page.getByRole('button',{name:'Go to my care plan →'})).toBeVisible();
 expect(state.draft().status).toBe('submitted');expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 await page.screenshot({path:info.outputPath('completed-intake-mobile.png'),fullPage:true});
});

test('optional offer shows explicit price and does not submit another purchase after uncertainty',async({page})=>{
 let purchases=0;
 await setup(page,{welcome:true});
 await page.route('https://backend.example/api/**/offers**',async r=>{
  if(r.request().method()==='OPTIONS')return r.fulfill({headers:{'access-control-allow-origin':'https://shop.example','access-control-allow-methods':'GET,POST','access-control-allow-headers':'authorization,content-type'}});
  const headers={'access-control-allow-origin':'https://shop.example'};
  if(r.request().method()==='POST'){purchases++;expect(r.request().postDataJSON()).toEqual({quote_id:'synthetic-offer-quote',confirmed:true});return r.fulfill({headers,json:{status:'needs_review',message:'We’re confirming this payment. Please contact support before trying again.'}});}
  return r.fulfill({headers,json:{offers:r.request().url().includes('thank_you')?[{quote_id:'synthetic-offer-quote',name:'Example optional product',plan_name:'One-time plan',amount:100,currency:'USD',terms:'One-time purchase using your saved payment method.'}]:[]}});
 });
 await page.evaluate(()=>document.querySelector('wlmd-purchase-intake').loadOffers(true));
 expect(purchases).toBe(0);await page.getByRole('button',{name:'Buy for $1.00'}).click();
 await expect(page.getByText('We’re confirming this payment.',{exact:false})).toBeVisible();
 await expect(page.getByRole('button',{name:'Buy for $1.00'})).toHaveCount(0);expect(purchases).toBe(1);
 await page.getByRole('button',{name:'Start health intake',exact:true}).click();
 await expect(page.getByRole('heading',{name:'Your health'})).toBeVisible();
});

// Real component, isolated transport: every cart item keeps its own receipt and
// intake even when an ancillary read or another item's account setup fails.
async function setupCart(page,{failJourney=false,failSecondAccount=false,expiredHandoff=false}={}){
 const drafts=['first','second'].map(id=>({id,revision:0,status:'draft',current_step:0,answers:{allergies:'no'},template}));
 const accountCalls=[],portalCalls=[];
 let failed=false;
 await page.route('https://shop.example/**',r=>r.fulfill({contentType:'text/html',body:'<html><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1"></head><body style="font:18px Arial;margin:16px"><wlmd-purchase-intake></wlmd-purchase-intake><script src="https://backend.example/portal-assets/post-checkout.js"></script></body></html>'}));
 await page.route('https://backend.example/portal-assets/post-checkout.js',r=>r.fulfill({contentType:'text/javascript',body:script}));
 await page.route('https://backend.example/portal/**',r=>r.fulfill({contentType:'text/html',body:'<h1>Member portal destination</h1>'}));
 await page.route('https://backend.example/api/**',async r=>{
  const headers={'access-control-allow-origin':'https://shop.example','access-control-allow-methods':'GET,POST,PATCH','access-control-allow-headers':'authorization,content-type'};
  if(r.request().method()==='OPTIONS')return r.fulfill({headers});
  const url=new URL(r.request().url()),i=url.pathname.includes('/first/')?0:1;
  expect(r.request().headers().authorization).toBe('Bearer '+['first-receipt','second-receipt'][i]);
  const send=(json,status=200)=>r.fulfill({headers,json,status});
  if(url.pathname.endsWith('/account')){
   if(r.request().method()==='GET')return send({state:'set_password'});
   accountCalls.push(i);expect(r.request().postDataJSON()).toEqual({password:'Synthetic-password-123!'});
   if(failSecondAccount&&i===1&&!failed){failed=true;return send({detail:'Connecting this product failed. Please try again.'},503);}
   return send({state:'ready',portal_handoff:'synthetic-handoff-'+i,handoff_expires_at:new Date(Date.now()+(expiredHandoff?-60000:1800000)).toISOString()});
  }
  if(url.pathname.endsWith('/portal')){portalCalls.push(i);return send({site_id:'fortifyhp',enrollment_url:`https://backend.example/portal/fortifyhp#invite=synthetic-invitation-${i}`});}
  if(url.pathname.endsWith('/journey'))return failJourney?send({detail:'Status unavailable'},503):send({id:i+1,product_name:['Semaglutide','Metformin'][i],intake_status:drafts[i].status,journey:{title:'Order received',stages:[]}});
  if(url.pathname.endsWith('/offers'))return send({offers:[]});
  if(r.request().method()==='PATCH'){expect(r.request().postDataJSON().revision).toBe(drafts[i].revision);Object.assign(drafts[i],r.request().postDataJSON(),{revision:drafts[i].revision+1});}
  if(url.pathname.endsWith('/submit')){drafts[i].status='submitted';drafts[i].revision++;}
  return send(drafts[i]);
 });
 await page.goto('https://shop.example/complete');
 await page.evaluate(async()=>{await customElements.whenDefined('wlmd-purchase-intake');await document.querySelector('wlmd-purchase-intake').configure({siteId:'fortifyhp',sessions:[{session_id:'first',session_token:'first-receipt'},{session_id:'second',session_token:'second-receipt'}]});});
 return {drafts,accountCalls,portalCalls};
}
async function saveCartPassword(page){
 await page.getByLabel('Choose a password').fill('Synthetic-password-123!');
 await page.getByLabel('Confirm password',{exact:true}).fill('Synthetic-password-123!');
 await page.getByRole('button',{name:'Set password & continue',exact:true}).click();
}
test('multi-product completion survives failed status reads and offers the remaining intake only',async({page},info)=>{
 await page.setViewportSize({width:390,height:844});
 const state=await setupCart(page,{failJourney:true});
 await page.getByRole('button',{name:'Set up later · continue to intake',exact:true}).click();
 for(let i=0;i<2;i++){
  await page.getByRole('button',{name:'Continue',exact:true}).click();
  await page.getByRole('button',{name:'Submit intake',exact:true}).click();
  await expect(page.getByText(`${i+1} of 2 complete`,{exact:true})).toBeVisible();
  if(i===0)await page.getByRole('button',{name:'Finish another product’s intake'}).click();
 }
 await expect(page.getByRole('button',{name:'Finish another product’s intake'})).toHaveCount(0);
 await expect(page.getByRole('button',{name:'Go to my care plan →'})).toBeVisible();
 expect(state.drafts.map(d=>d.status)).toEqual(['submitted','submitted']);
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 await page.screenshot({path:info.outputPath('multi-product-complete-mobile.png'),fullPage:true});
});
test('partial account setup retries only the missing receipt then uses the verified handoff',async({page})=>{
 const state=await setupCart(page,{failSecondAccount:true});
 await saveCartPassword(page);
 await expect(page.getByText('Your password is saved. Enter the same password',{exact:false})).toBeVisible();
 await saveCartPassword(page);
 await expect(page.getByRole('heading',{name:'Your portal password is saved'})).toBeVisible();
 expect(state.accountCalls).toEqual([0,1,1]);
 expect(await page.evaluate(()=>JSON.stringify({...localStorage,...sessionStorage}))).not.toContain('Synthetic-password');
 await page.getByRole('button',{name:'Open member portal',exact:true}).click();
 await expect(page).toHaveURL('https://backend.example/portal/fortifyhp#handoff=synthetic-handoff-1');
 expect(state.portalCalls).toEqual([]);
});
for(const scenario of ['partial','expired'])test(`${scenario} account handoff preserves all purchased receipts for portal sign-in`,async({page})=>{
 const state=await setupCart(page,{failSecondAccount:scenario==='partial',expiredHandoff:scenario==='expired'});
 await saveCartPassword(page);
 if(scenario==='partial')await expect(page.getByRole('alert')).toContainText('Connecting this product failed');
 else await expect(page.getByText('use your password to open your member portal.',{exact:false})).toBeVisible();
 await page.getByRole('button',{name:'Open member portal',exact:true}).click();
 await expect(page.getByRole('heading',{name:'Member portal destination'})).toBeVisible();
 const hash=new URLSearchParams(new URL(page.url()).hash.slice(1));
 expect(hash.has('handoff')).toBe(false);
 expect(JSON.parse(hash.get('invites'))).toEqual(['synthetic-invitation-0','synthetic-invitation-1']);
 expect(state.portalCalls.sort()).toEqual([0,1]);
});

for(const width of [1440,390,320])test(`CoreAge short steps and checkout reuse at ${width}px`,async({page},info)=>{
 await page.setViewportSize({width,height:900});
 const form=JSON.parse(fs.readFileSync(path.join(__dirname,'../member_portal/weight_loss_questions.json'),'utf8'));
 const answers={ca_196:'California (CA)',ca_199:'Synthetic Patient',ca_571:'1 Example St, Test City, CA 90001',ca_200:'patient@example.test',ca_202:'2025550100'};
 form.questions.forEach(q=>{if(answers[q.id])Object.assign(q,{reuse_status:'stable',prefill_source:'checkout',saved_value:answers[q.id]});});
 const state=await setup(page,{template:form,answers});
 await expect(page.getByRole('button',{name:'Back to order',exact:true})).toBeVisible();
 await expect(page.getByRole('heading',{name:'Confirm your details'})).toBeVisible();
 await expect(page.getByText('From your checkout',{exact:false})).toHaveCount(5);
 await page.getByText('Change saved answer',{exact:true}).first().click();
 await expect(page.getByRole('combobox',{name:'State where you live'})).toHaveValue('California (CA)');
 await page.getByRole('combobox',{name:'State where you live'}).selectOption('New York (NY)');
 await expect.poll(()=>state.draft().answers.ca_196).toBe('New York (NY)');
 await page.screenshot({path:info.outputPath('thank-you-'+width+'.png'),fullPage:true});
 await page.getByRole('button',{name:'Continue',exact:true}).click();
 await expect(page.getByRole('heading',{name:'About you'})).toBeVisible();
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 await page.screenshot({path:info.outputPath('intake-step-'+width+'.png'),fullPage:true});
});
test('CoreAge medication branches, long dropdown and empty-step skipping',async({page})=>{
 const form=JSON.parse(fs.readFileSync(path.join(__dirname,'../member_portal/weight_loss_questions.json'),'utf8'));
 form.sections=form.sections.filter(s=>['treatment','dose','experience','review'].includes(s.id));
 form.questions=form.questions.filter(q=>form.sections.some(s=>s.id===q.section_id));
 await setup(page,{template:form});
 await page.locator('#q-ca_538-0').check();await page.locator('#q-ca_545-0').check();
 await page.getByRole('button',{name:'Continue',exact:true}).click();
 await expect(page.getByText('Current Tirzepatide Dosage',{exact:true})).toBeVisible();
 await expect(page.getByText('Current Semaglutide Dosage',{exact:true})).toHaveCount(0);
 await expect(page.getByRole('combobox',{name:'Units per week'})).toBeVisible();
 await page.getByRole('button',{name:'Back',exact:true}).click();
 await page.locator('#q-ca_538-1').check();await page.locator('#q-ca_585-0').check();
 await page.getByRole('button',{name:'Continue',exact:true}).click();
 await expect(page.getByRole('heading',{name:'Review & finish'})).toBeVisible();
});

for(const width of [1440,390,320])test(`clean confirmation and full-width intake at ${width}px`,async({page},info)=>{
 await page.setViewportSize({width,height:844});
 const form=JSON.parse(fs.readFileSync(path.join(__dirname,'../member_portal/weight_loss_questions.json'),'utf8'));
 form.sections=form.sections.filter(s=>s.id==='about'||s.id==='review');form.questions=form.questions.filter(q=>form.sections.some(s=>s.id===q.section_id));
 await setup(page,{state:'set_password',template:form});
 await expect(page.getByRole('heading',{name:'Congratulations! Your order is placed.'})).toBeVisible();
 await expect(page.getByText('Order #QA-1',{exact:true})).toBeVisible();
 await expect(page.getByRole('heading',{name:'About you'})).toBeHidden();
 await expect(page.getByRole('list',{name:'After-purchase checklist'})).toHaveCount(0);
 await page.screenshot({path:info.outputPath('clean-confirmation-'+width+'.png'),fullPage:true});
 await page.getByLabel('Choose a password').fill('Synthetic-password-123!');await page.getByLabel('Confirm password',{exact:true}).fill('Synthetic-password-123!');
 await page.getByRole('button',{name:'Set password & continue',exact:true}).click();
 await expect(page.getByRole('heading',{name:'About you'})).toBeVisible();
 await expect(page.getByRole('heading',{name:'Congratulations! Your order is placed.'})).toHaveCount(0);
 const box=await page.locator('.intake-panel').boundingBox();if(width<600){expect(Math.abs(box.x)).toBeLessThan(2);expect(box.width).toBeGreaterThanOrEqual(width-1);}
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 await page.screenshot({path:info.outputPath('focused-intake-'+width+'.png'),fullPage:true});
 await page.getByLabel('Date of birth').fill('1990-01-01');
 await page.getByRole('button',{name:'Back to order',exact:true}).click();
 await page.getByRole('button',{name:'Start health intake',exact:true}).click();
 await expect(page.getByLabel('Date of birth')).toHaveValue('1990-01-01');
});

test('account lookup failure never blocks health intake',async({page})=>{
 await setup(page,{accountReadFail:true,welcome:true});
 await expect(page.getByText('Your purchase is saved. Portal password setup is temporarily unavailable.')).toBeVisible();
 await page.getByRole('button',{name:'Start health intake',exact:true}).click();
 await expect(page.getByRole('heading',{name:'Your health'})).toBeVisible();
 await page.getByRole('radio',{name:'No',exact:true}).check();
 await page.getByRole('button',{name:'Continue',exact:true}).click();
 await expect(page.getByRole('button',{name:'Submit intake'})).toBeVisible();
});
