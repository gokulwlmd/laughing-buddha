const {test,expect}=require('playwright/test');
const fs=require('node:fs');
const source=fs.readFileSync(require('node:path').join(__dirname,'../member_portal/web/id-upload.js'),'utf8');
async function setup(page,mode='card'){
 await page.route('https://camera.example/**',r=>r.fulfill({contentType:'text/html',headers:{'Content-Security-Policy':"default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data: https:"},body:'<style>body{font-family:Arial,sans-serif}</style><wlmd-id-upload></wlmd-id-upload>'}));
 await page.goto('https://camera.example/');await page.addScriptTag({content:source});
 await page.evaluate(mode=>{
  window.uploads=0;window.streams=[];window.cameraMode=mode;
  Object.defineProperty(navigator.mediaDevices,'getUserMedia',{configurable:true,value:async constraints=>{
   window.constraints=constraints;
   if(window.cameraMode==='denied')throw new DOMException('Denied','NotAllowedError');
   const canvas=document.createElement('canvas');canvas.width=1280;canvas.height=960;const ctx=canvas.getContext('2d');
   let frame=0;const draw=()=>{frame++;ctx.fillStyle='#273a31';ctx.fillRect(0,0,1280,960);if(window.cameraMode!=='blank'){
    ctx.fillStyle=window.cameraMode==='moving'?`rgb(${60+frame*31%140} ${60+frame*31%140} ${60+frame*31%140})`:'#eee9d9';ctx.fillRect(110,160,1060,640);ctx.fillStyle='#233f34';ctx.font='32px sans-serif';ctx.fillText('SYNTHETIC CAMERA FIXTURE — NOT AN ID',140,230);
    for(let y=280;y<730;y+=45){ctx.fillText('Sample text for image detail 0123456789',150,y);}
   }};draw();window.drawTimer=setInterval(draw,50);
   const stream=canvas.captureStream(20);window.streams.push(stream);
   if(window.cameraMode==='late')await new Promise(resolve=>window.resolveCamera=resolve);
   return stream;
  }});
  document.querySelector('wlmd-id-upload').configure({load:async()=>({available:true}),upload:async()=>{window.uploads++;return {order_attached:true,uploaded_at:new Date().toISOString()};}});
 },mode);
 await expect(page.getByRole('button',{name:'Take photo of ID'})).toBeVisible();
}
for(const width of [1440,390])test(`CAMERA automatic capture, review and explicit upload at ${width}px`,async({page},info)=>{
 await page.setViewportSize({width,height:900});await setup(page);
 await page.getByRole('button',{name:'Take photo of ID'}).click();
 await expect(page.getByRole('dialog')).toBeVisible();
 await page.screenshot({path:info.outputPath('camera.png')});
 await expect(page.getByRole('heading',{name:'Check your photo'})).toBeVisible({timeout:15000});
 expect(await page.evaluate(()=>window.uploads)).toBe(0);
 expect(await page.evaluate(()=>window.streams.every(s=>s.getTracks().every(t=>t.readyState==='ended')))).toBe(true);
 expect(await page.evaluate(()=>window.constraints)).toMatchObject({audio:false,video:{facingMode:{ideal:'environment'}}});
 await page.screenshot({path:info.outputPath('review.png')});
 const dimensions=await page.getByAltText('Your captured ID photo').evaluate(i=>({w:i.naturalWidth,h:i.naturalHeight}));expect(dimensions.w/dimensions.h).toBeCloseTo(1.586,1);
 await page.getByRole('button',{name:'Retake',exact:true}).click();await expect(page.getByRole('heading',{name:'Check your photo'})).toBeVisible({timeout:15000});
 expect(await page.evaluate(()=>window.streams.length)).toBe(2);
 await page.getByRole('button',{name:'Use photo',exact:true}).click();
 await expect(page.getByText('Your ID photo is saved')).toBeVisible();expect(await page.evaluate(()=>window.uploads)).toBe(1);
});
test('CAMERA blank scene does not auto capture; manual capture and cancel stop tracks',async({page})=>{
 await setup(page,'blank');await page.getByRole('button',{name:'Take photo of ID'}).click();
 await expect(page.getByRole('button',{name:'Take photo now'})).toBeEnabled();await page.waitForTimeout(3000);
 await expect(page.getByRole('heading',{name:'Check your photo'})).toHaveCount(0);
 await page.getByRole('button',{name:'Take photo now'}).click();await expect(page.getByRole('heading',{name:'Check your photo'})).toBeVisible();
 await page.getByRole('button',{name:'Close photo review'}).click();expect(await page.evaluate(()=>window.uploads)).toBe(0);
 await page.getByRole('button',{name:'Take photo of ID'}).click();await expect(page.getByRole('button',{name:'Take photo now'})).toBeEnabled();await page.keyboard.press('Escape');
 expect(await page.evaluate(()=>window.streams.every(s=>s.getTracks().every(t=>t.readyState==='ended')))).toBe(true);
});
test('CAMERA permission denial leaves file upload available',async({page})=>{
 await setup(page,'denied');await page.getByRole('button',{name:'Take photo of ID'}).click();await expect(page.getByRole('alert')).toContainText('permission');await expect(page.getByLabel('Upload ID',{exact:true})).toBeAttached();await expect(page.getByRole('dialog')).toHaveCount(0);
});
test('CAMERA late permission after cancel and removal never leaks a stream',async({page})=>{
 await setup(page,'late');await page.getByRole('button',{name:'Take photo of ID'}).click();await expect.poll(()=>page.evaluate(()=>!!window.resolveCamera)).toBe(true);
 await page.getByRole('button',{name:'Cancel',exact:true}).click();await page.evaluate(()=>window.resolveCamera());await expect.poll(()=>page.evaluate(()=>window.streams[0].getTracks()[0].readyState)).toBe('ended');
 await page.evaluate(()=>window.cameraMode='blank');await page.getByRole('button',{name:'Take photo of ID'}).click();await expect(page.getByRole('button',{name:'Take photo now'})).toBeEnabled();await page.evaluate(()=>document.querySelector('wlmd-id-upload').remove());
 expect(await page.evaluate(()=>window.streams.every(s=>s.getTracks().every(t=>t.readyState==='ended')))).toBe(true);
});

test('CAMERA moving image resets countdown and hidden page stops camera',async({page})=>{
 await setup(page,'moving');await page.getByRole('button',{name:'Take photo of ID'}).click();await expect(page.getByRole('button',{name:'Take photo now'})).toBeEnabled();await page.waitForTimeout(3200);await expect(page.getByRole('heading',{name:'Check your photo'})).toHaveCount(0);
 await page.evaluate(()=>{Object.defineProperty(document,'hidden',{configurable:true,value:true});document.dispatchEvent(new Event('visibilitychange'));});
 await expect(page.getByRole('dialog')).toHaveCount(0);expect(await page.evaluate(()=>window.streams.every(s=>s.getTracks().every(t=>t.readyState==='ended')))).toBe(true);
});
