const {test,expect}=require('playwright/test');
const fs=require('node:fs');const path=require('node:path');
const script=fs.readFileSync(path.join(__dirname,'../member_portal/web/post-checkout.js'),'utf8');
async function setup(page,{conflict=false,account='sign_in',slowSave=false}={}){
 const drafts={first:{id:'one',revision:0,status:'draft',current_step:0,answers:{},template:{title:'Semaglutide intake',sections:[{id:'health',title:'Your health'}],questions:[{id:'notes',section_id:'health',label:'Health information',type:'textarea',required:true}]}},second:{id:'two',revision:1,status:'submitted',current_step:0,answers:{notes:'Saved second answer'},template:{title:'Metformin intake',sections:[{id:'health',title:'Your health'}],questions:[]}}};
 await page.route('https://shop.example/**',r=>r.fulfill({contentType:'text/html',body:'<html><meta charset="utf-8"><body style="font:18px Arial;margin:16px"><wlmd-purchase-intake></wlmd-purchase-intake><script src="https://backend.example/portal-assets/post-checkout.js"></script></body></html>'}));
 await page.route('https://backend.example/portal-assets/post-checkout.js',r=>r.fulfill({contentType:'text/javascript',body:script}));
 await page.route('https://backend.example/api/**',async r=>{
  const headers={'access-control-allow-origin':'https://shop.example','access-control-allow-methods':'GET,POST,PATCH','access-control-allow-headers':'authorization,content-type'};
  if(r.request().method()==='OPTIONS')return r.fulfill({headers});
  const match=r.request().url().match(/sessions\/(first|second)(\/.*)/),key=match[1],tail=match[2];
  expect(r.request().headers().authorization).toBe('Bearer token-'+key);
  if(tail==='/account')return r.fulfill({headers,json:{state:account}});
  if(tail.startsWith('/journey'))return r.fulfill({headers,json:{id:key,product_name:key==='first'?'Semaglutide':'Metformin',intake_status:drafts[key].status,journey:{title:'Your intake is saved',stages:[{label:'Medical review',detail:'Waiting for a review update',state:'unconfirmed'}]}}});
  if(r.request().method()==='PATCH'){
   if(slowSave)await new Promise(resolve=>setTimeout(resolve,150));
   if(r.request().postDataJSON().revision!==drafts[key].revision)return r.fulfill({headers,status:409,json:{detail:'Revision conflict'}});
   if(conflict)return r.fulfill({headers,status:409,json:{detail:'Revision conflict'}});
   drafts[key]={...drafts[key],...r.request().postDataJSON(),revision:drafts[key].revision+1};
  }
  if(tail==='/intake/submit')drafts[key]={...drafts[key],status:'submitted'};
  return r.fulfill({headers,json:drafts[key]});
 });
 await page.goto('https://shop.example/complete');
 await page.evaluate(async()=>{await customElements.whenDefined('wlmd-purchase-intake');await document.querySelector('wlmd-purchase-intake').configure({siteId:'fortifyhp',sessions:[{session_id:'first',session_token:'token-first'},{session_id:'second',session_token:'token-second'}]});});
 return drafts;
}
for(const width of [1440,390])test(`purchase checklist resumes each product independently at ${width}px`,async({page},testInfo)=>{
 await page.setViewportSize({width,height:900});const drafts=await setup(page);
 await expect(page.getByText('Health intake · 1 of 2 complete',{exact:false})).toBeVisible();
 await page.getByRole('textbox',{name:'Health information'}).fill('Synthetic saved answer');
 await page.getByRole('button',{name:'Metformin Intake complete'}).click();
 expect(drafts.first.answers.notes).toBe('Synthetic saved answer');
 await expect(page.getByText('Your intake has been submitted.',{exact:false})).toBeVisible();
 await expect(page.getByRole('textbox',{name:'Health information'})).toHaveCount(0);
 await page.getByRole('button',{name:/Semaglutide/}).click();
 await expect(page.getByRole('textbox',{name:'Health information'})).toHaveValue('Synthetic saved answer');
 await page.getByRole('button',{name:'Submit intake',exact:true}).click();
 await expect(page.getByText('Health intake · 2 of 2 complete',{exact:false})).toBeVisible();
 await page.getByText('Order progress',{exact:true}).click();
 await expect(page.getByText('Waiting for a review update',{exact:false})).toBeVisible();
 expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
 await page.screenshot({path:testInfo.outputPath('purchase-checklist.png'),fullPage:true});
 // Reload uses backend drafts and never requests a repeat submission.
 await page.reload();await page.evaluate(async()=>{await customElements.whenDefined('wlmd-purchase-intake');await document.querySelector('wlmd-purchase-intake').configure({siteId:'fortifyhp',sessions:[{session_id:'first',session_token:'token-first'},{session_id:'second',session_token:'token-second'}]});});
 await expect(page.getByText('Health intake · 2 of 2 complete',{exact:false})).toBeVisible();
 await expect(page.getByRole('button',{name:'Submit intake',exact:true})).toHaveCount(0);
});
test('failed autosave blocks product switching and preserves answers',async({page})=>{
 await setup(page,{conflict:true});await page.getByRole('textbox',{name:'Health information'}).fill('Keep this unsaved answer');
 await page.getByRole('button',{name:'Metformin Intake complete'}).click();
 await expect(page.getByRole('textbox',{name:'Health information'})).toHaveValue('Keep this unsaved answer');
 await expect(page.getByRole('alert')).toContainText('changed in another window');
});
test('refreshing progress does not erase a partly entered password',async({page})=>{
 await setup(page,{account:'set_password'});
 await page.getByLabel('Choose a password').fill('Synthetic-only-password');
 await page.getByRole('button',{name:'Refresh order updates'}).click();
 await expect(page.getByLabel('Choose a password')).toHaveValue('Synthetic-only-password');
 expect(await page.evaluate(()=>JSON.stringify({...localStorage,...sessionStorage}))).not.toContain('Synthetic-only-password');
});

test('overlapping autosave and navigation flushes serialize revisions',async({page})=>{
 const drafts=await setup(page,{slowSave:true});
 await page.getByRole('textbox',{name:'Health information'}).fill('First edit');
 await page.evaluate(()=>{const el=document.querySelector('wlmd-purchase-intake');window.firstFlush=el.flush();});
 await page.getByRole('textbox',{name:'Health information'}).fill('Latest edit');
 const saved=await page.evaluate(async()=>{const el=document.querySelector('wlmd-purchase-intake');return Promise.all([window.firstFlush,el.flush(),el.flush()]);});
 expect(saved).toEqual([true,true,true]);expect(drafts.first.answers.notes).toBe('Latest edit');
 await expect(page.getByRole('alert')).toHaveCount(0);
});
