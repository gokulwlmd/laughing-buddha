const {test:base,expect}=require('playwright/test');
const {spawn}=require('node:child_process');
const net=require('node:net');
const path=require('node:path');

async function freePort(){const server=net.createServer();await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));const port=server.address().port;await new Promise(resolve=>server.close(resolve));return port;}
const test=base.extend({demo:[async({},use)=>{
 const apiPort=await freePort(),frontPort=await freePort();
 const child=spawn(process.env.QA_PYTHON||'python3',[path.join(__dirname,'../demo/run.py'),'--api-port',String(apiPort),'--frontend-port',String(frontPort)],{stdio:['ignore','pipe','pipe']});
 let errors='';child.stderr.on('data',d=>errors+=d);let info;
 try{
  info=await new Promise((resolve,reject)=>{let output='';const timer=setTimeout(()=>reject(Error('Demo startup timed out: '+errors)),15000);child.stdout.on('data',d=>{output+=d;const line=output.split('\n')[0];try{const value=JSON.parse(line);clearTimeout(timer);resolve(value);}catch{}});child.on('exit',code=>{clearTimeout(timer);reject(Error('Demo exited '+code+': '+errors));});});
  await use(info);
 }finally{child.kill('SIGTERM');}
},{scope:'worker'}]});

test('API-DEMO-01 a separate frontend uses two calls and completes a non-payment checkout',async({page,demo})=>{
 const calls=[];page.on('request',r=>{if(r.url().startsWith(demo.api+'/api/v1/'))calls.push({method:r.method(),url:r.url(),body:r.postData()});});
 await page.goto(demo.frontend);await expect(page.locator('#price')).toHaveText('$1,494.00');await expect(page.locator('#plan-name')).toHaveText('Semaglutide');
 await page.locator('#checkout').click();await expect(page).toHaveURL(new RegExp(demo.api+'/demo/checkout/'));
 await expect(page.locator('#brand-name')).toHaveText('Willow Health +');await expect(page.locator('#terms')).toContainText('180 days');await expect(page.locator('#terms')).toContainText('2 shipments');await expect(page.locator('input')).toHaveCount(0);
 expect(calls.map(c=>c.method)).toEqual(['GET','POST']);expect(JSON.parse(calls[1].body)).toEqual({plan_id:'sema-6m-sub',return_url:demo.frontend+'/complete'});
 await page.locator('#finish button').click();await expect(page).toHaveURL(demo.frontend+'/complete');await expect(page.locator('#completed')).toContainText('No payment was taken and no order was created.');
});

test('API-DEMO-02 site switch updates independent prices and keeps the exact selected plan',async({page,demo})=>{
 await page.goto(demo.frontend);await expect(page.locator('#price')).toHaveText('$1,494.00');await page.locator('#site').selectOption('harbor-wellness');await expect(page.locator('#price')).toHaveText('$1,643.40');await expect(page.locator('#api-docs')).toHaveAttribute('href',demo.api+'/sites/harbor-wellness/docs');
 await page.locator('#medications').getByRole('button',{name:'Tirzepatide'}).click();await page.locator('#durations').getByRole('button',{name:/12 months/}).click();await page.locator('#purchases').getByRole('button',{name:'One-time purchase'}).click();await expect(page.locator('#price')).toHaveText('$5,926.80');await expect(page.locator('#terms')).toContainText('No automatic renewal');
 await page.locator('#checkout').click();await expect(page.locator('#brand-name')).toHaveText('Harbor Wellness +');await expect(page.locator('#plan-name')).toHaveText('Tirzepatide');await expect(page.locator('#terms')).toContainText('4 shipments');await expect(page.locator('#terms')).not.toContainText('Renews every');
});

test('API-DEMO-03 mobile layout and developer view show real requests without secrets',async({page,demo})=>{
 await page.setViewportSize({width:390,height:844});await page.goto(demo.frontend);await expect(page.locator('#price')).toHaveText('$1,494.00');expect(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)).toBe(false);
 await page.locator('#developer summary').click();await expect(page.locator('#get-call')).toContainText('/api/v1/sites/willow-health/plans');await expect(page.locator('#post-call')).toContainText('sema-6m-sub');await expect(page.locator('#catalog-response')).toContainText('1494.00');
 expect(await page.locator('body').innerText()).not.toMatch(/sk_live_|pk_live_|STICKY_API_PASSWORD/);
});
