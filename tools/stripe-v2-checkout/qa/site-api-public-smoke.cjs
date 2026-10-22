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
  console.log(JSON.stringify({frontend:true,real_handoff:true,fresh_details_form:true,financial_calls:writes.length,screenshot:'/private/tmp/site-api-public-demo.png'}));
 }finally{await browser.close();}
})().catch(e=>{console.error(e.message);process.exit(1);});
