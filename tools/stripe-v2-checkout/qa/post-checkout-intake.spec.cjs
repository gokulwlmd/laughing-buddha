const {test,expect}=require('playwright/test');
const fs=require('node:fs');
const path=require('node:path');
const idScript=fs.readFileSync(path.join(__dirname,'../member_portal/web/id-upload.js'),'utf8');
const script=fs.readFileSync(path.join(__dirname,'../member_portal/web/post-checkout.js'),'utf8');
const template={title:'Semaglutide health intake',version:'mock-care-1',sections:[{id:'health',title:'Your health',description:'Tell us about yourself.'},{id:'review',title:'Anything else?',description:'Review and finish.'}],questions:[{id:'allergies',section_id:'health',label:'Do you have any allergies?',type:'single_choice',required:true,options:[{value:'no',label:'No'},{value:'yes',label:'Yes'}]},{id:'details',section_id:'health',label:'Which allergies?',type:'textarea',required:true,show_if:{question_id:'allergies',equals:'yes'}},{id:'notes',section_id:'review',label:'Anything else to share?',type:'textarea',required:false}]};
async function setup(page,accountOptions={}){let photoWrites=0;let identityWrites=0,identityVerified=!accountOptions.identity;let accountWrites=0;let draft={id:'i-1',revision:0,status:'draft',current_step:0,answers:accountOptions.answers||{},template:accountOptions.template||template};let patches=0;await page.route('https://shop.example/**',r=>r.fulfill({contentType:'text/html',body:'<html><head><meta charset="UTF-8"></head><body style="font:18px Arial;background:#f4f1ec;margin:40px"><wlmd-purchase-intake></wlmd-purchase-intake><script src="https://backend.example/portal-assets/post-checkout.js"></script></body></html>'}));await page.route('https://backend.example/portal-assets/post-checkout.js',r=>r.fulfill({contentType:'text/javascript',body:script}));await page.route('https://backend.example/portal-assets/id-upload.js',r=>r.fulfill({contentType:'text/javascript',headers:{'access-control-allow-origin':'https://shop.example'},body:idScript}));await page.route('https://backend.example/api/**',async r=>{if(r.request().method()==='OPTIONS')return r.fulfill({headers:{'access-control-allow-origin':'https://shop.example','access-control-allow-methods':'GET,POST,PATCH','access-control-allow-headers':'authorization,content-type'}});expect(r.request().headers().authorization).toBe('Bearer receipt-only-token');if(r.request().url().includes('/journey'))return r.fulfill({headers:{'access-control-allow-origin':'https://shop.example'},json:{id:'QA-1',product_name:'Semaglutide',intake_status:draft.status,journey:{title:draft.status==='submitted'?'Your intake is saved':'Your health intake is next',stages:[]}}});if(r.request().url().endsWith('/account')){if(r.request().method()==='POST'){accountWrites++;expect(r.request().postDataJSON()).toEqual({password:'Synthetic-password-123!'});if(accountOptions.fail)return r.fulfill({status:502,headers:{'access-control-allow-origin':'https://shop.example'},json:{detail:'Your purchase is saved. Please try account setup again.'}});}return r.fulfill({headers:{'access-control-allow-origin':'https://shop.example'},json:{state:accountWrites?'ready':accountOptions.state||'sign_in',provider:'sticky'}});}if(r.request().url().endsWith('/id-photo/reuse')){photoWrites++;identityVerified=true;return r.fulfill({headers:{'access-control-allow-origin':'https://shop.example'},json:{status:'uploaded',order_attached:true,saved:true,uploaded_at:'2026-10-24T00:00:00Z'}});}if(r.request().url().endsWith('/id-photo')){if(r.request().method()==='POST'){photoWrites++;if(accountOptions.photoFail)return r.fulfill({status:409,headers:{'access-control-allow-origin':'https://shop.example'},json:{detail:'We couldn’t confirm your upload. Retry your saved photo.'}});expect(typeof r.request().postDataJSON().file_contents).toBe('string');identityVerified=true;}return r.fulfill({headers:{'access-control-allow-origin':'https://shop.example'},json:{status:accountOptions.photoFail&&photoWrites&&!identityVerified?'needs_review':photoWrites?'uploaded':'needed',available:true,order_attached:!!photoWrites&&identityVerified,saved:!!photoWrites||!!accountOptions.savedPhoto,uploaded_at:'2026-10-24T00:00:00Z'}});}if(r.request().url().endsWith('/identity')){identityWrites++;expect(r.request().postDataJSON()).toEqual({last4:'1234'});identityVerified=!accountOptions.identityFail;return r.fulfill({status:identityVerified?200:409,headers:{'access-control-allow-origin':'https://shop.example'},json:identityVerified?{status:'verified'}:{detail:'We couldn’t confirm your identity. Please try again shortly.'}});}if(!identityVerified)return r.fulfill({status:409,headers:{'access-control-allow-origin':'https://shop.example'},json:{detail:{code:'identity_verification_required',message:'Verify your identity to continue your intake.'}}});if(r.request().method()==='PATCH'){patches++;const body=r.request().postDataJSON();expect(body.revision).toBe(draft.revision);draft={...draft,...body,revision:draft.revision+1};}if(r.request().url().endsWith('/submit'))draft={...draft,status:'submitted',revision:draft.revision+1};await r.fulfill({headers:{'access-control-allow-origin':'https://shop.example'},json:draft});});await page.goto('https://shop.example/complete');await page.evaluate(async()=>{await customElements.whenDefined('wlmd-purchase-intake');await document.querySelector('wlmd-purchase-intake').configure({siteId:'fortifyhp',sessions:[{session_id:'owned-order',session_token:'receipt-only-token'}]});});return {draft:()=>draft,patches:()=>patches,accountWrites:()=>accountWrites,identityWrites:()=>identityWrites,photoWrites:()=>photoWrites};}
test('shared intake saves draft, conditional questions and submits without login',async({page},info)=>{const state=await setup(page);await expect(page.getByRole('heading',{name:'Semaglutide health intake'})).toBeVisible();await expect(page.locator('input[type=password]')).toHaveCount(0);await page.getByRole('radio',{name:'Yes',exact:true}).check();await expect(page.getByRole('textbox',{name:'Which allergies?'})).toBeVisible();await page.getByRole('textbox',{name:'Which allergies?'}).fill('Synthetic QA only');await expect.poll(()=>state.draft().answers.details).toBe('Synthetic QA only');await page.getByRole('button',{name:'Continue',exact:true}).click();await expect(page.getByRole('textbox',{name:'Anything else to share?'})).toBeVisible();await page.screenshot({path:info.outputPath('shared-intake-desktop.png'),fullPage:true});await page.getByRole('button',{name:'Submit intake'}).click();await expect(page.getByText('Your intake has been submitted.',{exact:false})).toBeVisible();expect(state.draft().status).toBe('submitted');});
test('required answers and mobile reflow',async({page},info)=>{await page.setViewportSize({width:390,height:844});await setup(page);await page.getByRole('button',{name:'Continue',exact:true}).click();await expect(page.getByText('Please answer this question.')).toBeVisible();await page.getByRole('radio',{name:'No',exact:true}).check();await page.getByRole('button',{name:'Continue',exact:true}).click();await expect(page.getByRole('button',{name:'Submit intake'})).toBeVisible();expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);await page.screenshot({path:info.outputPath('shared-intake-mobile.png'),fullPage:true});});

test('set Sticky password without email while intake stays usable',async({page},info)=>{
 const state=await setup(page,{state:'set_password'});
 await page.getByLabel('Choose a password').fill('Synthetic-password-123!');
 await page.getByLabel('Confirm password',{exact:true}).fill('Synthetic-password-123!');
 await page.getByRole('button',{name:'Save portal password'}).click();
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
 await page.getByRole('button',{name:'Save portal password'}).click();
 await expect(page.getByText('The passwords do not match.',{exact:false})).toBeVisible();expect(state.accountWrites()).toBe(0);
 await page.getByLabel('Choose a password').fill('Synthetic-password-123!');await page.getByLabel('Confirm password',{exact:true}).fill('Synthetic-password-123!');
 await page.getByRole('button',{name:'Save portal password'}).click();
 await expect(page.getByText('Your purchase is saved. Please try account setup again.')).toBeVisible();
 await expect(page.getByRole('heading',{name:'Semaglutide health intake'})).toBeVisible();
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
 await page.setViewportSize({width,height:900});const state=await setup(page,{identity:true});
 await expect(page.getByRole('heading',{name:'Verify your identity',exact:true})).toBeVisible();
 await expect(page.getByRole('radio',{name:'No',exact:true})).toHaveCount(0);
 expect(state.identityWrites()).toBe(0);
 await page.screenshot({path:info.outputPath('identity-checkout-'+width+'.png'),fullPage:true});
 await page.getByLabel('Last 4 digits of your SSN').fill('1234');
 await page.getByRole('button',{name:'Verify & continue to intake'}).click();
 await expect(page.getByRole('heading',{name:'Semaglutide health intake'})).toBeVisible();
 expect(state.identityWrites()).toBe(1);
 await expect(page.locator('#identity-last4')).toHaveCount(0);
 expect(await page.evaluate(()=>JSON.stringify({...localStorage,...sessionStorage}))).not.toContain('1234');
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
});
test('IDENTITY shared verification error stays before intake and clears digits',async({page})=>{
 const state=await setup(page,{identity:true,identityFail:true});
 await page.getByLabel('Last 4 digits of your SSN').fill('1234');
 await page.getByRole('button',{name:'Verify & continue to intake'}).click();
 await expect(page.getByRole('alert')).toContainText('couldn’t confirm');
 await expect(page.getByLabel('Last 4 digits of your SSN')).toHaveValue('');
 await expect(page.getByRole('radio')).toHaveCount(0);
 expect(state.identityWrites()).toBe(1);
});

test('IDPHOTO shared checkout accepts photo without SSN and preserves intake flow',async({page})=>{
 const state=await setup(page,{identity:true});await expect(page.getByLabel('Upload ID',{exact:true})).toBeVisible();
 const data=await page.evaluate(()=>{const c=document.createElement('canvas');c.width=600;c.height=400;const ctx=c.getContext('2d');ctx.fillStyle='#aaa';ctx.fillRect(0,0,600,400);return c.toDataURL('image/png').split(',')[1];});
 await page.getByLabel('Upload ID',{exact:true}).setInputFiles({name:'synthetic.png',mimeType:'image/png',buffer:Buffer.from(data,'base64')});
 await page.getByRole('button',{name:'Upload this photo',exact:true}).click();
 await expect(page.getByRole('heading',{name:'Semaglutide health intake'})).toBeVisible();expect(state.identityWrites()).toBe(0);expect(state.photoWrites()).toBe(1);
});

test('IDPHOTO saved photo attaches automatically for the next intake without asking again',async({page})=>{
 const state=await setup(page,{identity:true,savedPhoto:true});
 await expect(page.getByRole('heading',{name:'Semaglutide health intake'})).toBeVisible();
 expect(state.identityWrites()).toBe(0);expect(state.photoWrites()).toBe(1);
 await expect(page.getByLabel('Upload ID',{exact:true})).toHaveCount(0);
});

test('IDPHOTO uncertain upload offers an explicit retry with the saved photo',async({page})=>{
 const state=await setup(page,{identity:true,photoFail:true});
 await expect(page.getByLabel('Upload ID',{exact:true})).toBeVisible();
 const data=await page.evaluate(()=>{const c=document.createElement('canvas');c.width=600;c.height=400;return c.toDataURL('image/png').split(',')[1];});
 await page.getByLabel('Upload ID',{exact:true}).setInputFiles({name:'synthetic.png',mimeType:'image/png',buffer:Buffer.from(data,'base64')});
 await page.getByRole('button',{name:'Upload this photo',exact:true}).click();
 await expect(page.getByRole('button',{name:'Retry saved photo',exact:true})).toBeVisible();
 expect(state.photoWrites()).toBe(1);
 await page.getByRole('button',{name:'Retry saved photo',exact:true}).click();
 await expect(page.getByRole('heading',{name:'Semaglutide health intake'})).toBeVisible();expect(state.photoWrites()).toBe(2);
});
