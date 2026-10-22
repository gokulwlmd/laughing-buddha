// Explicit read-only public smoke test. Never fills contact/card details or calls Pay.
const {chromium}=require('playwright');
(async()=>{
 const browser=await chromium.launch({channel:'chrome',headless:true});
 const page=await browser.newPage({viewport:{width:1365,height:1000}});
 const writes=[];
 page.on('request',r=>{if(/\/api\/(authorize|capture|resume)(?:\?|$)/.test(r.url()))writes.push(r.url());});
 try{
  const origin='https://wlmd-site-api-demo-0f89b1bb.fly.dev';
  await page.goto(origin);
  await page.locator('#price').filter({hasText:'$1,494.00'}).waitFor({timeout:60000});
  if(!await page.locator('body').innerText().then(t=>t.includes('REAL CHARGES')))throw Error('Missing real-charge notice');
  await page.locator('#developer summary').click();
  if((await page.locator('#post-call').innerText()).includes('return_url'))throw Error('Unsupported return URL advertised');
  await page.screenshot({path:'/private/tmp/site-api-public-demo.png',fullPage:true});
  await page.locator('#developer summary').click();
  await page.locator('#durations button').filter({hasText:/^1 month ·/}).click();
  await page.locator('#purchases button').filter({hasText:'One-time purchase'}).click();
  await page.locator('#checkout').click();
  await page.waitForURL('https://wlmd-stripe-test-0f89b1bb.fly.dev/c/**',{timeout:60000});
  await page.locator('#contact').waitFor({timeout:60000});
  const selected=await page.locator('body').innerText();
  if(/Let’s check your payment|payment setup needs a check/.test(selected))throw Error('Fresh visitor hit a held payment');
  if(writes.length)throw Error('Smoke check attempted a financial API call');
  // Reproduce a frontend server resolving checkout_url without a cookie jar.
  const response=await fetch(origin+'/api/v1/sites/payment-test/checkout',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({plan_id:'sema-6m-sub'})});
  if(response.status!==201)throw Error('Checkout API did not return 201');
  const {checkout_url}=await response.json();
  const resolved=await fetch(checkout_url);
  const html=await resolved.text();
  if(resolved.status!==200||!html.includes('id="contact"'))throw Error('Cookie-free server redirect reached an invitation gate');
  for(let visitor=0;visitor<2;visitor++){
   const context=await browser.newContext();const fresh=await context.newPage();
   fresh.on('request',r=>{if(/\/api\/(authorize|capture|resume)(?:\?|$)/.test(r.url()))writes.push(r.url());});
   await fresh.goto(resolved.url);
   await fresh.locator('#contact button:not(:disabled)').waitFor({timeout:60000});
   if((await context.cookies()).some(c=>c.name.startsWith('link_access_')))throw Error('Public checkout still needed invitation cookies');
   if(visitor===0)await fresh.screenshot({path:'/private/tmp/public-api-cookie-free.png',fullPage:true});
   await context.close();
  }
  if(writes.length)throw Error('Smoke check invoked a financial API');
  console.log(JSON.stringify({frontend:true,real_handoff:true,fresh_details_form:true,cookie_free_server_redirect:true,independent_browsers:2,financial_calls:writes.length,screenshot:'/private/tmp/public-api-cookie-free.png'}));
 }finally{await browser.close();}
})().catch(e=>{console.error(e.message);process.exit(1);});
