const {test,expect,nav,approve,stats}=require('./fixtures.cjs');
async function save(page,kind,data){return page.evaluate(async({kind,data})=>{const auth=await (await fetch('/api/admin/auth')).json(),headers={'Content-Type':'application/json','X-CSRF-Token':auth.csrfToken};const r=await fetch('/api/admin/reviews',{method:'POST',headers,body:JSON.stringify({kind,data})});const review=await r.json();if(!r.ok)throw Error(JSON.stringify(review));const a=await fetch('/api/admin/apply',{method:'POST',headers,body:JSON.stringify({review_id:review.id,approve:true})});if(!a.ok)throw Error(JSON.stringify(await a.json()));return a.json();},{kind,data});}
async function seed(page){
 await save(page,'brand',{id:'demo-brand',name:'Demo brand',color:'#6260c3'});
 await save(page,'therapy',{id:'weight-loss',name:'Weight Loss',enabled:true,treatments:[{id:'sema',name:'Semaglutide'},{id:'tirz',name:'Tirzepatide'}]});
 for(const [sku,treatment,months,price]of [['DEMO-SEMA-1M','sema',1,'299.00'],['DEMO-TIRZ-1M','tirz',1,'449.00'],['DEMO-SEMA-3M','sema',3,'799.00']])await save(page,'master',{sku,name:sku,therapy_id:'weight-loss',treatment_id:treatment,product_duration_months:months,currency:'USD',offers:[{id:'standard',name:'Standard',price,billing_models:[2,3]}]});
 for(const [id,months,skus]of [['monthly',1,['DEMO-SEMA-1M','DEMO-TIRZ-1M']],['quarterly',3,['DEMO-SEMA-3M']]])await save(page,'purchase_option',{id,name:months+'-month plan',therapy_id:'weight-loss',duration_months:months,skus,payment_types:['once','subscription']});
 await page.locator('#refresh-workspace').click();await nav(page,'templates');
 const f=page.locator('#template-form');await f.locator('[name=name]').fill('Weight Loss');await f.locator('[name=title]').fill('Choose your plan');await f.locator('[name=therapy_id]').selectOption('weight-loss');for(const input of await page.locator('#template-plans input').all())await input.check();await f.locator('button[type=submit]').click();await expect(page.locator('#review-summary')).toContainText('DEMO-SEMA-1M');await approve(page);
}
async function site(page,{newBrand=false}={}){
 await nav(page,'sites');const f=page.locator('#site-form');await f.locator('[name=name]').fill('Demo site');
 if(newBrand){await page.locator('#site-new-brand').click();await f.locator('[name=brand_name]').fill('New site brand');await f.locator('[name=color]').fill('#123456');}
 else await f.locator('[name=brand_id]').selectOption('demo-brand');
 await expect(f.locator('[name=campaign_id] option[value="422"]')).toBeAttached();await f.locator('[name=campaign_id]').selectOption('422');await f.locator('button[type=submit]').click();
 await expect(page.locator('#review-summary')).toContainText('Weight Loss');await expect(page.locator('#review-summary')).toContainText('299.00');await approve(page);await nav(page,'sites');
}
test('SITE-01 template and site UI prepare all branded checkouts, repeat setup and preserve private URL',async({ownerPage:page,app})=>{
 await expect(page.locator('[data-view=sites]')).toBeVisible();await expect(page.locator('#advanced-navigation')).not.toHaveAttribute('open','');await seed(page);await site(page);
 const list=page.locator('#site-list');await expect(list).toContainText('Ready · private invitation');const url=await list.getByRole('link',{name:'Preview ↗'}).getAttribute('href');const before=(await stats(page,app)).counts;
 await list.getByRole('button',{name:'Review / retry setup'}).click();await page.locator('#site-form button[type=submit]').click();await approve(page);await nav(page,'sites');expect(await list.getByRole('link',{name:'Preview ↗'}).getAttribute('href')).toBe(url);expect((await stats(page,app)).counts).toEqual(before);
 await page.goto(url);await expect(page.locator('#durations [data-duration="1"]')).toContainText('$299.00');await expect(page.locator('#durations [data-duration="1"]')).toContainText('$449.00');
});
test('SITE-02 mobile site creation with new brand, customization and reviewed template update',async({ownerPage:page,app})=>{
 await seed(page);await page.setViewportSize({width:390,height:844});await site(page,{newBrand:true});await expect(page.locator('#site-list')).toContainText('New site brand');await page.locator('#site-list').getByRole('button',{name:'Customize'}).click();
 const f=page.locator('#site-checkout-form');await f.locator('[name=title]').fill('My site plans');await f.locator('[name=visibility]').selectOption('public');await page.locator('#site-checkout-plans [value=quarterly]').uncheck();await f.locator('[value=subscription]').uncheck();await f.locator('[value=prepaid]').uncheck();await f.locator('button[type=submit]').click();await approve(page);await nav(page,'sites');await expect(page.locator('#site-list')).toContainText('Live · public checkout');
 await nav(page,'templates');await page.locator('#template-list').getByRole('button',{name:'Edit template'}).click();await page.locator('#template-form [name=title]').fill('A new default');await page.locator('#template-form button[type=submit]').click();await approve(page);await nav(page,'sites');await expect(page.locator('#site-list')).toContainText('Update available');
 await page.locator('#site-list').getByRole('button',{name:'Review template updates'}).click();await page.locator('#site-form button[type=submit]').click();await approve(page);await nav(page,'sites');await expect(page.locator('#site-list')).not.toContainText('Update available');const url=await page.locator('#site-list a').getAttribute('href');expect(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)).toBe(false);
 await page.screenshot({path:require('node:path').join(__dirname,'results/mobile-sites.png'),fullPage:true});await page.goto(url);await expect(page.locator('#plan-title')).toHaveText('My site plans');await expect(page.locator('#durations>button')).toHaveCount(1);await page.locator('#durations [data-duration="1"]').click();await page.locator('#treatments button').first().click();await expect(page.locator('#payments button')).toHaveCount(1);expect((await stats(page,app)).counts.new_order).toBe(0);
});
test('SITE-03 missing gateway is incomplete and does not offer a ready link',async({ownerPage:page,app})=>{
 await seed(page);await site(page);await page.request.post(app.origin+'/__qa/control',{data:{missing_gateway:true}});await page.locator('#refresh-workspace').click();await expect(page.locator('#site-list')).toContainText('Incomplete');await expect(page.locator('#site-list a')).toHaveCount(0);
});
