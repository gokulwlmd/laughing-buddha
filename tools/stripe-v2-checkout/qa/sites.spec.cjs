const {test,expect,nav,approve,stats,setupOwner}=require('./fixtures.cjs');
async function save(page,kind,data){return page.evaluate(async({kind,data})=>{const auth=await (await fetch('/api/admin/auth')).json(),headers={'Content-Type':'application/json','X-CSRF-Token':auth.csrfToken};const r=await fetch('/api/admin/reviews',{method:'POST',headers,body:JSON.stringify({kind,data})});const review=await r.json();if(!r.ok)throw Error(JSON.stringify(review));const a=await fetch('/api/admin/apply',{method:'POST',headers,body:JSON.stringify({review_id:review.id,approve:true})});if(!a.ok)throw Error(JSON.stringify(await a.json()));return a.json();},{kind,data});}
async function seed(page){
 await save(page,'brand',{id:'demo-brand',name:'Demo brand',color:'#6260c3'});
 await save(page,'therapy',{id:'weight-loss',name:'Weight Loss',enabled:true,treatments:[{id:'sema',name:'Semaglutide'},{id:'tirz',name:'Tirzepatide'}]});
 for(const [sku,treatment,months,price]of [['DEMO-SEMA-1M','sema',1,'299.00'],['DEMO-TIRZ-1M','tirz',1,'449.00'],['DEMO-SEMA-3M','sema',3,'799.00']])await save(page,'master',{sku,name:sku,therapy_id:'weight-loss',treatment_id:treatment,product_duration_months:months,currency:'USD',offers:[{id:'standard',name:'Standard',price,billing_models:[2,3]}]});
 for(const [id,months,skus]of [['monthly',1,['DEMO-SEMA-1M','DEMO-TIRZ-1M']],['quarterly',3,['DEMO-SEMA-3M']]])await save(page,'purchase_option',{id,name:months+'-month plan',therapy_id:'weight-loss',duration_months:months,skus,payment_types:['once','subscription']});
 await page.locator('#refresh-workspace').click();await nav(page,'templates');
 await page.locator('#template-new').click();const f=page.locator('#template-form');await f.locator('[name=name]').fill('Weight Loss');await f.locator('[name=title]').fill('Choose your plan');await f.locator('[name=therapy_id]').selectOption('weight-loss');await expect(page.locator('#template-preview-plans')).toContainText('$299.00');await f.locator('button[type=submit]').click();await expect(page.locator('#review-summary')).toContainText('DEMO-SEMA-1M');await approve(page);
}
async function site(page,{newBrand=false,wlmdSiteId=""}={}){
 await nav(page,'sites');await page.locator('#site-new').click();const f=page.locator('#site-form');await f.locator('[name=name]').fill('Demo site');await f.locator('[name=wlmd_site_id]').fill(wlmdSiteId);
 if(newBrand){await f.locator('[name=brand_name]').fill('New site brand');await f.locator('[name=color]').fill('#123456');await f.locator('[name=routing_template_id]').selectOption('422');}
 else {await page.locator('#site-brand-options summary').click();await f.locator('[name=brand_id]').selectOption('demo-brand');await f.locator('[name=connection]').selectOption('existing');await f.locator('[name=campaign_id]').selectOption('422');}
 await page.locator('#site-continue').click();await expect(page.locator('#site-templates-summary')).toContainText('Weight Loss');await f.locator('button[type=submit]').click();
 await expect(page.locator('#review-summary')).toContainText('Weight Loss');await expect(page.locator('#review-summary')).toContainText('299.00');await approve(page);await expect(page.locator('[data-view=sites]')).toBeVisible();
}
test('SITE-01 template and site UI prepare all branded checkouts, repeat setup and preserve private URL',async({ownerPage:page,app})=>{
 await expect(page.locator('[data-view=sites]')).toBeVisible();await expect(page.locator('#advanced-navigation')).not.toHaveAttribute('open','');await seed(page);await site(page,{wlmdSiteId:'wlmd-browser-101'});
 const list=page.locator('#site-list');await expect(list).toContainText('Ready to preview');const url=await list.getByRole('link',{name:'Preview ↗'}).getAttribute('href');const before=(await stats(page,app)).counts;
 await list.getByRole('button',{name:'Update checkouts'}).click();await expect(page.locator('#site-form [name=wlmd_site_id]')).toHaveValue('wlmd-browser-101');await expect(page.locator('#site-form [name=wlmd_site_id]')).toHaveAttribute('readonly','');await page.locator('#site-form button[type=submit]').click();await approve(page);await nav(page,'sites');expect(await list.getByRole('link',{name:'Preview ↗'}).getAttribute('href')).toBe(url);expect((await stats(page,app)).counts).toEqual(before);
 await page.goto(url);await page.locator('#treatments').getByRole('button',{name:'Semaglutide',exact:true}).click();await expect(page.locator('#durations [data-duration="1"]')).toContainText('$299.00');await expect(page.locator('#durations')).not.toContainText('$449.00');await page.locator('#treatments').getByRole('button',{name:'Tirzepatide',exact:true}).click();await expect(page.locator('#durations [data-duration="1"]')).toContainText('$449.00');
});
test('SITE-02 mobile site creation with new brand, customization and reviewed template update',async({ownerPage:page,app})=>{
 await seed(page);await page.setViewportSize({width:390,height:844});await site(page,{newBrand:true});await expect(page.locator('#site-list')).toContainText('New site brand');await page.locator('#site-list').getByRole('button',{name:'Edit checkout'}).click();
 const f=page.locator('#site-checkout-form');await f.locator('[name=title]').fill('My site plans');await f.locator('[name=visibility]').selectOption('public');await page.locator('#site-checkout-plans input').nth(1).uncheck();await f.locator('[value=subscription]').uncheck();await f.locator('[value=prepaid]').uncheck();await f.locator('button[type=submit]').click();await approve(page);await nav(page,'sites');await expect(page.locator('#site-list')).toContainText('Published');
 await nav(page,'templates');await page.locator('#template-list').getByRole('button',{name:'Edit template'}).click();await page.locator('#template-form [name=title]').fill('A new default');await page.locator('#template-form button[type=submit]').click();await approve(page);await nav(page,'sites');await expect(page.locator('#site-list')).toContainText('Template update available');
 await page.locator('#site-list').getByRole('button',{name:'Review template updates'}).click();await page.locator('#site-form button[type=submit]').click();await approve(page);await nav(page,'sites');await expect(page.locator('#site-list')).not.toContainText('Template update available');const url=await page.locator('#site-list').getByRole('link',{name:'Preview ↗',exact:true}).getAttribute('href');expect(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)).toBe(false);
 await page.screenshot({path:require('node:path').join(__dirname,'results/mobile-sites.png'),fullPage:true});await page.goto(url);await expect(page.locator('#plan-title')).toHaveText('My site plans');await page.locator('#treatments button').first().click();await expect(page.locator('#durations>button')).toHaveCount(1);await page.locator('#durations [data-duration="1"]').click();await expect(page.locator('#payments button')).toHaveCount(1);expect((await stats(page,app)).counts.new_order).toBe(0);
});
test('SITE-03 missing gateway is incomplete and does not offer a ready link',async({ownerPage:page,app})=>{
 await seed(page);await site(page);await page.request.post(app.origin+'/__qa/control',{data:{missing_gateway:true}});await page.locator('#refresh-workspace').click();await expect(page.locator('#site-list')).toContainText('Needs attention');await expect(page.locator('#site-list').getByRole('link',{name:'Preview ↗',exact:true})).toHaveCount(0);
});
test('SITE-04 slow initial state loads before navigation becomes available',async({page,app})=>{
 let release,entered;const held=new Promise(resolve=>release=resolve),requested=new Promise(resolve=>entered=resolve);
 await page.route(app.origin+'/api/admin/state',async route=>{entered();await held;await route.continue();});
 const setup=setupOwner(page,app);await requested;await expect(page.locator('#workspace')).toBeHidden();release();await setup;
 await expect(page.locator('#page-title')).toHaveText('Sites');await nav(page,'brands');await expect(page.locator('#brand-form')).toBeVisible();await expect(page.locator('#page-title')).toHaveText('Brands');
});

test('SITE-05 draft template can be resumed and completed without losing a published template',async({ownerPage:page})=>{
 await seed(page);await nav(page,'templates');await page.locator('#template-list').getByRole('button',{name:'Edit template'}).click();
 const first=page.locator('.template-plan').first();for(const i of await first.locator('.choices input').all())await i.uncheck();
 await expect(page.locator('#template-readiness')).toContainText('choose a product');await expect(page.locator('#template-form button[type=submit]')).toBeDisabled();
 await page.locator('#template-save-draft').click();await approve(page);await expect(page.locator('#template-list')).toContainText('Unpublished draft saved');
 await page.locator('#template-list').getByRole('button',{name:'Continue draft'}).click();await expect(first.locator('.choices input:checked')).toHaveCount(0);
 await first.locator('.choices input').first().check();await page.locator('#template-form button[type=submit]').click();await approve(page);await expect(page.locator('#template-list')).not.toContainText('Unpublished draft saved');
});
test('SITE-06 next site uses saved setup with no Advanced navigation and publication is explicit',async({ownerPage:page,app})=>{
 await seed(page);await site(page,{newBrand:true});await page.locator('#site-new').click();await page.locator('#site-form [name=name]').fill('Second site');
 await expect(page.locator('#site-connection-options')).not.toHaveAttribute('open','');await expect(page.locator('#site-form [name=routing_template_id]')).toHaveValue('422');
 await page.locator('#site-continue').click();await page.locator('#site-form button[type=submit]').click();await approve(page);
 const card=page.locator('#site-list>.record').filter({has:page.getByText('Second site',{exact:true}).first()});await expect(card).toContainText('Ready to preview');await expect(card.getByRole('button',{name:'Copy public link'})).toHaveCount(0);
 await card.getByRole('button',{name:'Publish',exact:true}).click();await expect(page.locator('#site-checkout-form [name=visibility]')).toHaveValue('public');await page.locator('#site-checkout-form button[type=submit]').click();await approve(page);await expect(card.getByRole('button',{name:'Copy public link'})).toBeVisible();
 expect((await stats(page,app)).counts.new_order).toBe(0);await expect(page.locator('#site-mode')).not.toHaveText('New undefined');
});

test('SITE-07 new therapy and incomplete plans save together as a recoverable draft',async({ownerPage:page})=>{
 await nav(page,'templates');await page.locator('#template-new').click();const f=page.locator('#template-form');await f.locator('[name=name]').fill('Example therapy');await f.locator('[name=title]').fill('Choose your example plan');await f.locator('[name=therapy_id]').selectOption('__new');await f.locator('[name=therapy_name]').fill('Example therapy');await f.locator('[name=treatment_names]').fill('Treatment A, Treatment B');await page.locator('#template-add-plan').click();await expect(page.locator('#template-plans')).toContainText('No matching products');await expect(f.locator('button[type=submit]')).toBeDisabled();await page.locator('#template-save-draft').click();await approve(page);await expect(page.locator('#template-list')).toContainText('Draft · not included in sites');await page.locator('#template-list').getByRole('button',{name:'Continue draft'}).click();await expect(f.locator('[name=treatment_names]')).toHaveValue('Treatment A, Treatment B');await expect(page.locator('.template-plan')).toHaveCount(1);await page.screenshot({path:require('node:path').join(__dirname,'results/template-editor.png'),fullPage:true});
});

test('SITE-08 master therapy skeleton shows all terms and preserves a nonpayable draft',async({ownerPage:page,app})=>{
 await nav(page,'templates');const skeleton=page.locator('#therapy-skeleton-list');
 await expect(skeleton).toContainText('Master Therapy 1');await skeleton.getByText('View all SKUs and payment rules').first().click();
 for(const prefix of ['SEMA','TIRZ'])for(const months of [1,3,6,12])for(const suffix of ['','-SUB'])await expect(skeleton).toContainText(prefix+'-'+months+'M'+suffix);
 await expect(skeleton).toContainText('Renews every 180 days');await expect(skeleton).toContainText('4 shipments per term');
 await skeleton.getByRole('button',{name:'Open skeleton draft'}).first().click();
 await expect(page.locator('#template-plans .template-plan')).toHaveCount(4);
 await expect(page.locator('#template-form button[type=submit]')).toBeDisabled();
 await page.locator('#template-save-draft').click();await approve(page);await nav(page,'templates');
 await page.locator('#template-list').getByRole('button',{name:'Continue draft'}).click();
 await expect(page.locator('#template-skeleton-contract')).toContainText('TIRZ-12M-SUB');
 await expect(page.locator('#template-form button[type=submit]')).toBeDisabled();
 await page.setViewportSize({width:390,height:844});expect(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)).toBe(false);
 expect((await stats(page,app)).counts.new_order).toBe(0);
});

test('SITE-09 starter therapies and editable master upfront prices preserve the billing contract',async({ownerPage:page,app})=>{
 await nav(page,'templates');await expect(page.locator('#therapy-skeleton-list')).toContainText('Master Therapy 2 · Sermorelin');await expect(page.locator('#therapy-skeleton-list')).toContainText('Master Therapy 3 · Metformin');
 await save(page,'therapy',{id:'metformin',name:'Metformin',enabled:true,treatments:[{id:'metformin',name:'Metformin'}]});
 await save(page,'master',{sku:'METFORM-12M-SUB',name:'Metformin 12 months subscription',therapy_id:'metformin',treatment_id:'metformin',product_duration_months:12,category:'Metformin',currency:'USD',enabled:true,offers:[{id:'upfront',name:'Full-term upfront price',price:'588.00',billing_models:[]}],planning_contract:{charge:'full_term_upfront',term_months:12,renewal_months:12,shipments_per_term:null,shipment_interval:null,later_shipment_charge:'0.00'}});
 await page.locator('#refresh-workspace').click();await nav(page,'master');const card=page.locator('#master-list .record').filter({hasText:'METFORM-12M-SUB'});await expect(card).toContainText('$588.00 upfront');await expect(card).toContainText('Renews every 360 days');
 await card.getByRole('button',{name:'Edit upfront plan'}).click();await page.locator('#master-planning-price').fill('600.00');await page.locator('#master-form button[type=submit]').click();await approve(page);await nav(page,'master');await expect(card).toContainText('$600.00 upfront');await expect(card).toContainText('Renews every 360 days');
 await nav(page,'templates');const met=page.locator('#therapy-skeleton-list .record').filter({hasText:'Master Therapy 3 · Metformin'}).first();await met.getByText('View all SKUs and payment rules').click();await expect(met).toContainText('$600.00 upfront');
 expect((await stats(page,app)).counts.new_order).toBe(0);
});

test('SITE-10 upfront shipment editor persists the rebuilt product setup and updates template terms',async({ownerPage:page,app})=>{
 await save(page,'therapy',{id:'metformin',name:'Metformin',enabled:true,treatments:[{id:'metformin',name:'Metformin'}]});
 for(const [months,count]of [[6,2],[12,4]])await save(page,'master',{sku:'METFORM-'+months+'M',name:'Metformin '+months+' months',therapy_id:'metformin',treatment_id:'metformin',product_duration_months:months,category:'Metformin',currency:'USD',enabled:true,offers:[{id:'upfront',name:'Full-term upfront price',price:String(months*49)+'.00',billing_models:[]}],planning_contract:{charge:'full_term_upfront',term_months:months,renewal_months:null,shipments_per_term:count,shipment_interval:90,later_shipment_charge:'0.00'}});
 await page.locator('#refresh-workspace').click();await nav(page,'master');const row=page.locator('#master-list>.record').filter({hasText:'METFORM-12M'});
 await expect(row).toContainText('Pay upfront');await expect(row).toContainText('4 shipments included · Every 90 days');await row.getByRole('button',{name:'Edit upfront plan'}).click();
 await expect(page.locator('#master-planning-preview')).toContainText('Day 270');await expect(page.locator('#master-planning-shipments')).toHaveValue('4');await expect(page.locator('#master-planning-interval')).toHaveValue('90');
 await page.locator('#master-planning-shipments').fill('3');await page.locator('#master-planning-interval').fill('120');await expect(page.locator('#master-planning-preview')).toContainText('Day 240');await page.locator('#master-form button[type=submit]').click();await expect(page.locator('#review-summary')).toContainText('Shipment days: 0, 120, 240');await approve(page);
 await nav(page,'master');await expect(row).toContainText('3 shipments included · Every 120 days');await row.getByRole('button',{name:'Edit upfront plan'}).click();await expect(page.locator('#master-planning-shipments')).toHaveValue('3');await expect(page.locator('#master-planning-interval')).toHaveValue('120');
 const state=await page.evaluate(async()=>await(await fetch('/api/admin/state')).json());const m=state.masters.find(m=>m.sku==='METFORM-12M');expect(m.product_setup.prepaid_cycles).toBe(3);expect(m.product_setup.shipment_days).toEqual([0,120,240]);expect(m.product_setup.upfront_price).toBe('588.00');expect(m.product_setup.renewal_months).toBeNull();
 const six=page.locator('#master-list>.record').filter({hasText:'METFORM-6M'});await expect(six).toContainText('2 shipments included · Every 90 days');
 await nav(page,'templates');const met=page.locator('#therapy-skeleton-list>.record').filter({hasText:'Master Therapy 3 · Metformin'});await met.getByText('View all SKUs and payment rules').click();await expect(met).toContainText('3 shipments per term · Every 120 days');
 await expect(page.locator('#therapy-skeleton-list')).toContainText('Master Therapy 4 · PT-141');expect((await stats(page,app)).counts.new_order).toBe(0);
});
