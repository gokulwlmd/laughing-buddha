// Hosted visual smoke: a fresh visitor may select a plan and open its blank contact form.
// No customer data, quotes, payment preparation, payment actions, or admin writes.
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const path=require('node:path');
const origin='https://wlmd-stripe-test-0f89b1bb.fly.dev';
const output='/private/tmp/wlmd-reference-live';
const assets=new Set();
let stage='launch',blockedWrites=0,financialRequests=0,visits=0;
async function cleanScreenshot(page,name){
 await page.evaluate(async()=>{
  await document.fonts.ready;
  window.scrollTo({top:0,behavior:'instant'});
  await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));
 });
 assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,'Page must not overflow horizontally');
 assert.equal(await page.evaluate(()=>document.fonts.check('400 16px "Red Hat Display"')),true,'Self-hosted display font must be loaded');
 await page.screenshot({path:path.join(output,name),fullPage:true,animations:'disabled'});
}
(async()=>{
 fs.mkdirSync(output,{recursive:true});
 const browser=await chromium.launch({channel:'chrome',headless:true});
 try{
  const context=await browser.newContext({viewport:{width:1440,height:1000}});
  await context.route('**/*',async route=>{
   const request=route.request(),url=new URL(request.url()),method=request.method();
   const financial=/\/(?:api\/(?:authorize|capture|resume|quote)|payment_intents)(?:\/|$)/.test(url.pathname);
   if(financial){financialRequests++;return route.abort('blockedbyclient');}
   if(url.origin===origin&&!['GET','HEAD','OPTIONS'].includes(method)){
    if(url.pathname==='/api/start-checkout'&&method==='POST'){visits++;return route.continue();}
    blockedWrites++;return route.abort('blockedbyclient');
   }
   return route.continue();
  });
  const page=await context.newPage();
  page.on('response',response=>{
   const url=new URL(response.url());
   if(url.origin===origin&&url.pathname.startsWith('/assets/')&&response.ok())assets.add(url.pathname);
  });
  stage='plan';
  await page.goto(origin+'/plans/site-api-public-weight-loss',{waitUntil:'domcontentloaded'});
  await page.locator('#treatments').getByRole('button',{name:'Semaglutide',exact:true}).click({timeout:60000});
  await page.locator('#durations [data-duration="12"]').click();
  await page.locator('#payments').getByRole('button',{name:/One-time purchase/}).click();
  assert.match(await page.locator('#selection-details').innerText(),/No automatic renewal/);
  assert.match(await page.locator('#selection-details').innerText(),/90 days/);
  for(const asset of ['/assets/plan-selector-v4.css','/assets/plan-selector-v4.js','/assets/checkout-font-v1.css','/assets/brand-design-v2.js']){
   assert(assets.has(asset),'Missing successful response for '+asset);
  }
  await cleanScreenshot(page,'plan-desktop.png');
  await page.setViewportSize({width:390,height:844});
  await cleanScreenshot(page,'plan-mobile.png');
  stage='contact';
  await page.locator('#plan-continue').click();
  await page.locator('#contact button:not(:disabled)').waitFor({state:'visible',timeout:60000});
  assert.equal(await page.locator('#product').innerText(),'Semaglutide');
  assert.equal(await page.locator('#summary-payment').innerText(),'One-time purchase');
  assert.match(await page.locator('#plan-description').innerText(),/12.month/);
  assert.equal(await page.locator('#contact input').evaluateAll(inputs=>inputs.every(input=>input.value==='')),true,'Contact inputs must remain blank');
  assert.equal(await page.locator('#review').isVisible(),false);
  assert.equal(await page.locator('#payment').isVisible(),false);
  assert.equal(await page.locator('#payment-hold').isVisible(),false);
  assert(assets.has('/assets/checkout-v4.css'),'New checkout CSS must load');
  assert(assets.has('/assets/checkout-v9.js'),'Existing payment behavior must remain');
  await cleanScreenshot(page,'contact-mobile.png');
  await page.setViewportSize({width:1440,height:1000});
  await cleanScreenshot(page,'contact-desktop.png');
  assert(assets.has('/assets/red-hat-display-latin-v1.woff2'),'Self-hosted font asset must load');
  assert.equal(financialRequests,0,'No quote/financial/resume request may be attempted');
  assert.equal(blockedWrites,0,'No unexpected server write may be attempted');
  assert.equal(visits,1,'Only one fresh blank checkout visit is expected');
  console.log(JSON.stringify({ok:true,viewports:[1440,390],screenshots:4,output,new_design_assets:true,self_hosted_font:true,horizontal_overflow:false,blank_checkout_visits:visits,financial_requests:financialRequests,unexpected_writes:blockedWrites}));
  await context.close();
 }finally{await browser.close();}
})().catch(error=>{
 const message=String(error.message).replace(/\/c\/choice-[a-f0-9]+/g,'/c/[redacted]').replace(/([?&]access=)[^&\s]+/g,'$1[redacted]');
 console.error(JSON.stringify({ok:false,stage,message,financial_requests:financialRequests,unexpected_writes:blockedWrites}));process.exitCode=1;
});
