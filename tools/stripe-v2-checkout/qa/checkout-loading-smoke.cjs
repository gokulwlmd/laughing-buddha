// Read-only hosted comparison. No contact/card input or financial API calls.
const {chromium}=require('playwright');
(async()=>{
 const browser=await chromium.launch({channel:'chrome',headless:true});
 const results=[];
 try{
  for(const previous of [true,false]){
   const context=await browser.newContext();const page=await context.newPage();let financial=0;
   page.on('request',r=>{if(/\/api\/(authorize|capture|resume)(?:\?|$)/.test(r.url()))financial++;});
   if(previous)await page.route('**/assets/checkout-v9.js',route=>route.continue({url:route.request().url().replace('checkout-v9.js','checkout-v8.js')}));
   await page.goto('https://wlmd-site-api-demo-0f89b1bb.fly.dev/');
   await page.locator('#price').filter({hasText:'$1,494.00'}).waitFor({timeout:60000});
   await page.locator('#durations button').filter({hasText:/^1 month ·/}).click();
   await page.locator('#purchases button').filter({hasText:'One-time purchase'}).click();
   const start=Date.now();await page.locator('#checkout').click();
   await page.locator('#contact [name=name]').waitFor({state:'visible',timeout:60000});
   const typingMs=Date.now()-start;
   await page.locator('#contact button:not(:disabled)').waitFor({state:'visible',timeout:60000});
   if(financial)throw Error('A financial API was invoked');
   results.push({version:previous?'v8':'v9',click_to_typing_ms:typingMs,click_to_validated_config_ms:Date.now()-start,financial_calls:financial});
   if(!previous)await page.screenshot({path:'/private/tmp/checkout-v9-hosted.png',fullPage:true});
   await context.close();
  }
  console.log(JSON.stringify(results));
 }finally{await browser.close();}
})().catch(e=>{console.error(e.message);process.exit(1);});
