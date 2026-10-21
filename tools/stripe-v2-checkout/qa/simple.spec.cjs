const {test,expect,approve,stats,control,brand}=require('./fixtures.cjs');
async function go(page,name){await page.locator('#navigation>[data-page='+name+']').click();if(name==='links'&&await page.locator('#checkout-brand-directory').isVisible()&&await page.locator('[data-brand-open]').count())await page.locator('[data-brand-open]').first().click();}
async function master(page,sku='NEW-THERAPY'){
 await expect(page.locator('#link-brand option').first()).toBeAttached();
 if(await page.locator('#link-brand option').count()===1)await brand(page);
 await go(page,'master');await page.locator('#master-new').click();await page.locator('#master-form [name=sku]').fill(sku);await page.locator('#master-form [name=name]').fill('New therapy');await page.locator('#master-offer-editor [data-field=price]').fill('99.00');await page.locator('#master-form button[type=submit]').click();await expect(page.locator('#review-summary')).toContainText('Requires shipping');await approve(page);
}
async function assign(page){await go(page,'campaigns');await page.locator('#setup-campaign').selectOption('422');await page.locator('#setup-form button[type=submit]').click();await approve(page);}
test('SIM-01 six primary screens, local master and one-review existing campaign assignment',async({ownerPage:page,app})=>{
 await expect(page.locator('#page-title')).toHaveText('Brands');await expect(page.locator('#navigation>button')).toHaveCount(6);await expect(page.locator('#master-advanced')).not.toHaveAttribute('open','');
 await master(page);expect((await stats(page,app)).counts.products).toBe(0);await assign(page);await go(page,'links');await expect(page.locator('#link-list')).toContainText('NEW-THERAPY');await expect(page.locator('#link-list a')).toHaveCount(1);const counts=(await stats(page,app)).counts;expect(counts.products).toBe(1);expect(counts.offers).toBe(1);expect(counts.authorize_payment).toBe(0);
 await assign(page);expect((await stats(page,app)).counts.products).toBe(1);
});
test('SIM-02 new campaign name and template include every master SKU and ready links',async({ownerPage:page,app})=>{
 await master(page,'FIRST-MED');await master(page,'SECOND-MED');await go(page,'campaigns');await page.locator('#setup-mode').selectOption('new');await page.locator('#setup-form [name=name]').fill('Fresh brand');await expect(page.locator('#setup-template')).toHaveValue('422');await expect(page.locator('#setup-catalog')).toContainText('2 master SKUs included');await page.locator('#setup-form button[type=submit]').click();await expect(page.locator('#review-summary')).toContainText('FIRST-MED');await expect(page.locator('#review-summary')).toContainText('SECOND-MED');await approve(page);await go(page,'links');await expect(page.locator('#link-list a')).toHaveCount(2);const counts=(await stats(page,app)).counts;expect(counts.campaigns).toBe(1);expect(counts.products).toBe(2);
});
test('SIM-03 automatically selected choices and generated link address with public/private control',async({ownerPage:page,app})=>{
 await master(page);await assign(page);await go(page,'links');await page.locator('#link-list').getByRole('button',{name:'Make public'}).click();await approve(page);await go(page,'links');let url=await page.locator('#link-list a').getAttribute('href');expect(url).not.toContain('?');expect((await page.request.get(url)).status()).toBe(200);
 await page.locator('[data-new=link]').click();await page.locator('#link-form [name=brand_id]').selectOption('qa-brand');await page.locator('#link-form [name=sku]').selectOption('NEW-THERAPY');await expect(page.locator('#link-options input:checked')).toHaveCount(1);await expect(page.locator('#link-form [name=id]')).not.toHaveValue('');await page.locator('#link-form button').last().click();await approve(page);await go(page,'links');await expect(page.locator('#link-list .record')).toHaveCount(2);expect((await stats(page,app)).counts.authorize_payment).toBe(0);
});
test('SIM-04 uncertain campaign creation cannot duplicate through a fresh setup',async({ownerPage:page,app})=>{
 await master(page);await go(page,'campaigns');await page.locator('#setup-mode').selectOption('new');await page.locator('#setup-form [name=name]').fill('Held campaign');await page.locator('#setup-form button[type=submit]').click();await control(page,app,{campaign_timeout:true});await page.locator('#review-consent').check();await page.locator('#apply-review').click();await expect(page.locator('#message')).toContainText('held for reconciliation');await go(page,'campaigns');await page.locator('#setup-form button[type=submit]').click();await expect(page.locator('#message')).toContainText('needs reconciliation');expect((await stats(page,app)).counts.campaigns).toBe(1);
});
test('SIM-05 mobile master campaign and links need no advanced settings',async({ownerPage:page})=>{
 await page.setViewportSize({width:390,height:844});await master(page);await assign(page);await go(page,'campaigns');expect(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)).toBe(false);await page.screenshot({path:require('node:path').join(__dirname,'results/mobile-simple-campaigns.png'),fullPage:true});await go(page,'links');expect(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)).toBe(false);await page.screenshot({path:require('node:path').join(__dirname,'results/mobile-simple-links.png'),fullPage:true});
});

test('SIM-06 choose a brand before checkout creation and retain all accessible campaign choices',async({ownerPage:page,app})=>{
 await go(page,'links');await expect(page.locator('#checkout-brand-directory')).toContainText('Create a brand');await expect(page.locator('#link-form')).toBeHidden();await expect(page.locator('#link-campaign option[value="422"]')).toBeAttached();await expect(page.locator('#link-campaign option[value="167"]')).toBeAttached();expect((await stats(page,app)).brands).toBe(0);
 await master(page,'UNASSIGNED-MED');await go(page,'links');await page.locator('#link-campaign').selectOption('422');await page.locator('#link-form [name=sku]').selectOption('UNASSIGNED-MED');await expect(page.locator('#link-assign-master')).toBeVisible();await page.locator('#link-assign-master').click();await expect(page.locator('#setup-campaign')).toHaveValue('422');await page.locator('#setup-form button[type=submit]').click();await approve(page);await go(page,'links');await expect(page.locator('#link-list a')).toHaveCount(1);expect((await stats(page,app)).counts.authorize_payment).toBe(0);
});
test('SIM-07 existing Sticky SKU creates a checkout under the selected brand',async({ownerPage:page,app})=>{
 await brand(page);
 const token=(await (await page.request.get(app.origin+'/api/admin/auth')).json()).csrfToken;
 const headers={'Origin':app.origin,'X-CSRF-Token':token};
 const review=await (await page.request.post(app.origin+'/api/admin/reviews',{headers,data:{kind:'sku',data:{sku:'WLMD-CORE-2USD-0f89b1bb',name:'Existing test SKU',product_id:54537}}})).json();
 expect((await page.request.post(app.origin+'/api/admin/apply',{headers,data:{review_id:review.id,approve:true}})).status()).toBe(200);
 await page.locator('#refresh-workspace').click();await go(page,'links');await page.locator('#link-campaign').selectOption('422');await page.locator('#link-form [name=sku]').selectOption('WLMD-CORE-2USD-0f89b1bb');await expect(page.locator('#link-options input:checked').first()).toBeAttached();await page.locator('#link-form button').last().click();await expect(page.locator('#review-summary')).toContainText('QA Brand');expect((await stats(page,app)).brands).toBe(1);await approve(page);await go(page,'links');await expect(page.locator('#link-list a')).toHaveCount(1);expect((await stats(page,app)).brands).toBe(1);expect((await stats(page,app)).counts.products).toBe(0);
});
