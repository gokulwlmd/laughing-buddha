const {test,expect,nav,approve,brand,offer,authorize,stats,control}=require('./fixtures.cjs');
async function preset(page){await nav(page,'master');await page.locator('#master-tirz').click();await expect(page.locator('#master-form [name=sku]')).toHaveValue('TIRZ-1M');await page.locator('#master-form button[type=submit]').click();await approve(page);}
async function provision(page,brandId='qa-brand'){
 await nav(page,'master');await page.locator('#provision-form [name=brand_id]').selectOption(brandId);
 for(const c of await page.locator('#master-selection input').all())await c.check();
 await page.locator('#provision-form button[type=submit]').click();await approve(page);
}
async function prepared(page){await preset(page);await brand(page);await provision(page);}

test('MST-01 agreed preset saves five intervals without a Sticky write',async({ownerPage:page,app})=>{
 await nav(page,'master');await page.locator('#master-tirz').click();await expect(page.locator('#master-offer-editor input[data-model]:checked')).toHaveCount(5);await expect(page.locator('#master-offer-editor [data-field=price]')).toHaveValue('449.00');await page.locator('#master-form button[type=submit]').click();await expect(page.locator('#review-summary')).toContainText('No Sticky records');expect((await stats(page,app)).counts.products).toBe(0);await approve(page);await nav(page,'master');await expect(page.locator('#master-list')).toContainText('Revision 1');expect((await stats(page,app)).counts.offers).toBe(0);
});

test('MST-02 test brand, assignment preview, private link and repeated assignment',async({ownerPage:page,app})=>{
 await preset(page);await nav(page,'master');await page.locator('#master-test-brand').click();await expect(page.locator('#brand-form [name=campaign_id]')).toHaveValue('422');await page.locator('#brand-form button').last().click();await approve(page);await provision(page,'wlmd-test');await expect(page.locator('#review-result')).toContainText('Configuration checks passed');await nav(page,'master');await expect(page.locator('#master-assignment-list')).toContainText('Master revision current');const before=await stats(page,app);expect(before.counts.products).toBe(1);expect(before.counts.offers).toBe(1);
 await provision(page,'wlmd-test');const after=await stats(page,app);expect(after.counts.products).toBe(1);expect(after.counts.offers).toBe(1);await nav(page,'links');await expect(page.locator('#link-list')).toContainText('private');await expect(page.locator('#link-list a')).toHaveCount(1);
});

test('MST-03 quote validation checks each assigned billing choice without charging',async({ownerPage:page,app})=>{
 await prepared(page);await nav(page,'master');const f=page.locator('#master-validation-form');await f.locator('[name=brand_id]').selectOption('qa-brand');await f.locator('[name=quotes]').check();await f.locator('details').evaluate(e=>e.open=true);await f.locator('[name=shipping_id]').fill('2');await f.locator('button[type=submit]').click();await expect(page.locator('#master-validation')).toContainText('Configuration checks passed');await expect(page.locator('#master-validation .record p').filter({hasText:'Server quote verified'})).toHaveCount(5);const s=await stats(page,app);expect(s.counts.authorize_payment).toBe(0);expect(s.counts.new_order).toBe(0);
});

test('MST-04 every preset interval can complete a distinct simulated checkout',async({ownerPage:page,app})=>{
 await prepared(page);await nav(page,'links');const invitation=await page.locator('#link-list a').getAttribute('href');await page.goto(invitation);
 for(const [i,[mid,days]]of [[3,30],[4,90],[5,180],[7,270],[6,360]].entries()){
  if(i){await page.locator('#new-purchase').click();}
  await expect(page.locator('#contact')).toBeVisible();const values=await page.locator('#selection option').evaluateAll(es=>es.map(e=>e.value));await page.locator('#selection').selectOption(values.find(v=>v.endsWith(':'+mid)));
  for(const [k,v]of Object.entries({name:'QA Customer',email:'master-qa@example.invalid',phone:'+12025550100',address:'1 Test Way',city:'San Francisco',region:'CA',postal_code:'94105'}))await page.locator('#contact [name='+k+']').fill(v);
  await page.locator('#contact button').click();await expect(page.locator('#terms')).toContainText('every '+days+' days');await expect(page.locator('#review-total')).toContainText('449.00');await authorize(page);await page.locator('#pay').click();await expect(page.locator('#success')).toBeVisible();
 }
 const s=await stats(page,app);expect(s.counts.authorize_payment).toBe(5);expect(s.counts.new_order).toBe(5);expect(s.orderCount).toBe(5);
});

test('MST-05 new master revision shows update available without changing assigned checkout',async({ownerPage:page,app})=>{
 await prepared(page);await nav(page,'master');await page.locator('#master-list').getByRole('button',{name:'Edit master preset'}).click();await page.locator('#master-offer-editor [data-field=price]').fill('555.00');await page.locator('#master-form button[type=submit]').click();await approve(page);await nav(page,'master');await expect(page.locator('#master-assignment-list')).toContainText('Master update available');await provision(page);await expect(page.locator('#review-result')).toContainText('449.00');expect((await stats(page,app)).counts.products).toBe(1);
});

test('MST-06 partial assignment holds created IDs and blocks a fresh attempt',async({ownerPage:page,app})=>{
 await preset(page);await brand(page);await nav(page,'master');await page.locator('#provision-form [name=brand_id]').selectOption('qa-brand');await page.locator('#provision-form button[type=submit]').click();await control(page,app,{fail_offer:true});await page.locator('#review-consent').check();await page.locator('#apply-review').click();await expect(page.locator('#message')).toContainText('held for reconciliation');await expect(page.locator('#review-result')).toContainText('Product_0_0');await nav(page,'master');await page.locator('#provision-form button[type=submit]').click();await expect(page.locator('#message')).toContainText('unresolved master assignment');expect((await stats(page,app)).counts.products).toBe(1);
});

test('MST-07 mobile master setup and approval remain usable',async({ownerPage:page})=>{
 await page.setViewportSize({width:390,height:844});await preset(page);await brand(page);await provision(page);await nav(page,'master');await expect(page.locator('#master-assignment-list')).toContainText('TIRZ-1M');expect(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)).toBe(false);await page.screenshot({path:require('node:path').join(__dirname,'results/mobile-master.png'),fullPage:true});
});
