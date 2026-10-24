const {test,expect,brand,sku,offer,approve,nav,stats}=require('./fixtures.cjs');
const path=require('node:path');

test('COM-01 create a brand coupon, approve it and list verified terms',async({ownerPage:page,app})=>{
 await brand(page);await nav(page,'commerce');
 await expect(page.locator('#commerce-brand')).toHaveValue('qa-brand');
 const f=page.locator('#commerce-coupon-form');
 await f.locator('[name=code]').fill('WELCOME20');await f.locator('[name=percent]').fill('20');
 await f.locator('[name=applies_to_renewals]').selectOption('true');
 await f.locator('[name=expires_on]').fill('2030-12-01');await f.locator('button[type=submit]').click();
 await expect(page.locator('#review-summary')).toContainText('WELCOME20');
 await expect(page.locator('#review-summary')).toContainText('Each separate cart order counts as a use');
 await approve(page);await nav(page,'commerce');await page.locator('#commerce-load-coupons').click();
 await expect(page.locator('#commerce-coupons')).toContainText('WELCOME20');
 await expect(page.locator('#commerce-coupons')).toContainText('First payment and renewals');
 await page.screenshot({path:path.join(__dirname,'results/brand-commerce-desktop.png'),fullPage:true});
 expect((await stats(page,app)).counts.authorize_payment).toBe(0);
});

test('COM-02 price-only editor preserves current price until approved',async({ownerPage:page})=>{
 await brand(page);await sku(page);await offer(page);await nav(page,'commerce');
 const input=page.locator('#commerce-prices input[name=price]').first();await expect(input).toHaveValue('3.00');
 await input.fill('9.00');await page.locator('#commerce-prices button').first().click();
 await expect(page.locator('#review-summary')).toContainText('Existing purchases and subscriptions retain their original offer');
 await approve(page);await nav(page,'commerce');await expect(input).toHaveValue('9.00');
});

test('COM-03 mobile layout and brand switching keep coupons separate',async({ownerPage:page})=>{
 await brand(page);await brand(page,'Other brand','other-brand','167');
 await page.setViewportSize({width:390,height:844});await nav(page,'commerce');
 await page.locator('#commerce-brand').selectOption('other-brand');
 await expect(page.locator('#commerce-campaign')).toHaveValue('167');
 await page.locator('#commerce-load-coupons').click();
 await expect(page.locator('#commerce-coupons')).toContainText('No coupons assigned');
 await expect(page.locator('#commerce-scope')).toContainText('Other brand');
 expect(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)).toBe(false);
 await page.screenshot({path:path.join(__dirname,'results/brand-commerce-mobile.png'),fullPage:true});
});
