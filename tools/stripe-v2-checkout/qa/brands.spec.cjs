const {test,expect,approve,nav,checkout,authorize,stats}=require('./fixtures.cjs');
const path=require('node:path');
async function createBrand(page,name='Violet Care'){
 await page.locator('#advanced-navigation').evaluate(e=>e.open=true);await page.locator('#navigation [data-page=brands]').click();await page.locator('[data-new=brand]').click();
 await page.locator('#brand-form [name=name]').fill(name);await page.locator('#brand-form [name=color]').fill('#663399');
 await page.locator('#brand-form [name=background_color]').fill('#faf0ff');await page.locator('#brand-form [name=font]').selectOption('serif');await page.locator('#brand-form [name=layout]').selectOption('stacked');
 await expect(page.locator('#preview-name')).toHaveText(name);await expect(page.locator('#brand-preview')).toHaveAttribute('data-layout','stacked');
 const id=await page.locator('#brand-form [name=id]').inputValue();expect(id).toMatch(/^[a-z0-9-]+$/);
 await page.locator('#brand-form button').last().click();await approve(page);return id;
}
async function addMaster(page){await page.locator('#advanced-navigation').evaluate(e=>e.open=true);await page.locator('#navigation [data-page=master]').click();await page.locator('#master-new').click();await page.locator('#master-form [name=sku]').fill('VIOLET-MED');await page.locator('#master-form [name=name]').fill('Violet medication');await page.locator('#master-offer-editor [data-field=price]').fill('29.00');await page.locator('#master-form button[type=submit]').click();await approve(page);}
async function attach(page,cid){await page.locator('#advanced-navigation').evaluate(e=>e.open=true);await page.locator('#navigation [data-page=campaigns]').click();await page.locator('#setup-campaign').selectOption(cid);await page.locator('#setup-form button[type=submit]').click();await approve(page);}
async function links(page){await nav(page,'links');return page.locator('#link-list a').evaluateAll(es=>es.map(e=>e.href));}

test('BRD-01 one brand, two campaigns, matching checkout and payment design, reusable links after design edit',async({ownerPage:page,app})=>{
 const id=await createBrand(page);await addMaster(page);await attach(page,'422');const original=(await links(page))[0];await attach(page,'167');const urls=await links(page);expect(urls).toContain(original);expect(urls).toHaveLength(2);
 await expect(page.locator('#link-brand')).toHaveValue(id);await expect(page.locator('#link-brand-design')).toContainText('Violet Care');
 for(const url of urls){await page.goto(url);await expect(page.locator('#brand-name')).toHaveText('Violet Care');await expect(page.locator('html')).toHaveAttribute('data-layout','stacked');expect(await page.locator('html').evaluate(e=>getComputedStyle(e).getPropertyValue('--brand-color'))).toBe('#663399');}
 const linkId=new URL(urls[0]).pathname.split('/').pop();await checkout(page,app,linkId);await authorize(page);expect(await page.evaluate(()=>getComputedStyle(document.documentElement).getPropertyValue('--brand-color').trim())).toBe('#663399');expect((await page.evaluate(()=>window.__qaAppearance)).variables.colorPrimary).toBe('#663399');
 await page.locator('#pay').click();await expect(page.locator('#success')).toBeVisible();await expect(page.locator('#brand-name')).toHaveText('Violet Care');
 await page.goto(app.origin+'/admin#brands');await page.getByRole('button',{name:'Edit brand',exact:true}).click();await page.locator('#brand-form [name=color]').fill('#194f64');await page.locator('#brand-form [name=layout]').selectOption('split');await page.locator('#brand-form button').last().click();await expect(page.locator('#review-summary')).toContainText('Checkout links that will change');await approve(page);
 expect((await links(page)).sort()).toEqual(urls.sort());
 for(const url of urls){await page.goto(url);await expect(page.locator('html')).toHaveAttribute('data-layout','split');expect(await page.locator('html').evaluate(e=>getComputedStyle(e).getPropertyValue('--brand-color'))).toBe('#194f64');}
 expect((await stats(page,app)).counts.new_order).toBe(1);
});

test('BRD-02 unattached campaign guides the selected brand to campaign setup',async({ownerPage:page,app})=>{
 const id=await createBrand(page);await addMaster(page);await nav(page,'links');await page.locator('#link-campaign').selectOption('167');await page.locator('#link-form [name=sku]').selectOption('VIOLET-MED');await expect(page.locator('#link-options')).toContainText('Attach this campaign');await expect(page.locator('#link-options input')).toHaveCount(0);await page.locator('#link-assign-master').click();await expect(page.locator('#setup-brand')).toHaveValue(id);await expect(page.locator('#setup-campaign')).toHaveValue('167');await page.locator('#setup-form button[type=submit]').click();await approve(page);await links(page);await expect(page.locator('#link-list')).toContainText('Violet Care · Campaign 167');expect((await stats(page,app)).counts.authorize_payment).toBe(0);
});

test('BRD-03 mobile brand preview and inherited checkout fit the viewport',async({ownerPage:page})=>{
 await page.setViewportSize({width:390,height:844});await createBrand(page,'Violet Care');await page.locator('#advanced-navigation').evaluate(e=>e.open=true);await page.locator('#navigation [data-page=brands]').click();await page.getByRole('button',{name:'Edit brand',exact:true}).click();await expect(page.locator('#brand-preview')).toBeVisible();expect(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)).toBe(false);await page.screenshot({path:path.join(__dirname,'results/mobile-brand-editor.png'),fullPage:true});
 await addMaster(page);await attach(page,'422');const url=(await links(page))[0];await page.goto(url);await expect(page.locator('#contact')).toBeVisible();expect(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)).toBe(false);await page.screenshot({path:path.join(__dirname,'results/mobile-branded-checkout.png'),fullPage:true});
});
