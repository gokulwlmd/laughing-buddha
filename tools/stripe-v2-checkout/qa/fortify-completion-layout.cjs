// Actual hosted Fortify shell; synthetic, fully intercepted checkout transport.
const {chromium}=require('playwright');const fs=require('node:fs');const path=require('node:path');
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome'});
 const out=process.env.QA_SCREENSHOT_DIR||'/tmp/fortify-refined-screenshots';fs.mkdirSync(out,{recursive:true});
 for(const width of [390,1440]){
 const context=await browser.newContext({viewport:{width,height:900}});const page=await context.newPage();
 const template=JSON.parse(fs.readFileSync(path.join(__dirname,'../member_portal/weight_loss_questions.json'),'utf8'));
 const answers={ca_196:'California (CA)',ca_199:'Sample Patient',ca_571:'1 Example Street, Sample City, CA 90001',ca_200:'sample@example.test',ca_202:'2025550100'};
 template.questions.forEach(q=>{if(answers[q.id])Object.assign(q,{reuse_status:'stable',prefill_source:'checkout',saved_value:answers[q.id]});});
 let draft={id:'qa',status:'draft',revision:0,current_step:0,template,answers};let saved=false;
 await context.addInitScript(()=>sessionStorage.setItem('fhp.planCheckout.session',JSON.stringify({session_id:'qa-design-only',session_token:'synthetic-design-receipt',plan_id:'qa-plan',expires_at:4102444800})));
 await page.route('**/*',async route=>{
 const req=route.request(),url=new URL(req.url());
 if(url.hostname==='wlmd-stripe-test-0f89b1bb.fly.dev'){
  const headers={'access-control-allow-origin':'https://fortifyhp-care.lovable.app','access-control-allow-methods':'GET,POST,PATCH,OPTIONS','access-control-allow-headers':'authorization,content-type'};
  if(req.method()==='OPTIONS')return route.fulfill({status:204,headers});
  if(url.pathname==='/portal-assets/post-checkout.js')return route.fulfill({headers,contentType:'text/javascript',body:fs.readFileSync(path.join(__dirname,'../member_portal/web/post-checkout.js'),'utf8')});
  const send=json=>route.fulfill({headers,json});
  if(url.pathname.endsWith('/account')){if(req.method()==='POST')saved=true;return send({state:saved?'ready':'set_password',provider:'sticky'});}
  if(url.pathname.endsWith('/journey'))return send({id:url.pathname.includes('qa-design-second')?'DEMO-5678':'DEMO-1234',product_name:url.pathname.includes('qa-design-second')?'PT-141 · 1-month subscription':'Semaglutide · 12-month subscription',intake_status:draft.status,journey:{title:'Order received',stages:[]}});
  if(url.pathname.endsWith('/offers'))return send({offers:[]});
  if(url.pathname.endsWith('/intake')){if(req.method()==='PATCH')draft={...draft,...req.postDataJSON(),revision:draft.revision+1};return send(draft);}
  if(url.pathname.endsWith('/sessions/qa-design-only'))return send({status:'captured',session_id:'qa-design-only',plan_id:'qa-plan',order_id:'DEMO-1234'});
  return route.abort();
 }
 if(!['GET','HEAD'].includes(req.method()))return route.abort();return route.continue();
 });
 await page.goto('https://fortifyhp-care.lovable.app/checkout-complete?source=single',{waitUntil:'domcontentloaded'});
 await page.getByRole('button',{name:'Set password & continue',exact:true}).waitFor({timeout:30000});
 if(process.env.QA_CART==='1')await page.evaluate(async()=>{const old=document.querySelector('wlmd-purchase-intake'),element=document.createElement('wlmd-purchase-intake');old.replaceWith(element);await element.configure({siteId:'fortifyhp',sessions:[{session_id:'qa-design-only',session_token:'synthetic-design-receipt'},{session_id:'qa-design-second',session_token:'synthetic-second-receipt'}]});});
 const reject=page.getByRole('button',{name:'Reject all',exact:true});await reject.waitFor({state:'visible',timeout:10000});await reject.click();await reject.waitFor({state:'hidden'});
 const primary=await page.getByRole('button',{name:'Set password & continue',exact:true}).boundingBox();if(width===1440&&primary.y+primary.height>900)throw Error('Password CTA below fold');await page.screenshot({path:out+'/confirmation-'+width+'.png',fullPage:true});
 await page.getByLabel('Choose a password').fill('Synthetic-password-123!');await page.getByLabel('Confirm password',{exact:true}).fill('Synthetic-password-123!');await page.getByRole('button',{name:'Set password & continue',exact:true}).click();
 await page.getByRole('heading',{name:'Confirm your details',exact:true}).waitFor();await page.screenshot({path:out+'/saved-details-'+width+'.png',fullPage:true});await page.getByRole('button',{name:'Continue',exact:true}).click();await page.getByRole('heading',{name:'About you',exact:true}).waitFor();
 if(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth))throw Error('Horizontal overflow at '+width);
 const box=await page.locator('wlmd-purchase-intake').boundingBox();if(width===390&&Math.abs(box.width-width)>1)throw Error('Not full width');
 await page.screenshot({path:out+'/intake-'+width+'.png',fullPage:true});
 console.log(JSON.stringify({width,componentWidth:box.width,passed:true}));await context.close();
 }
 await browser.close();
})().catch(e=>{console.error(e);process.exit(1)});
