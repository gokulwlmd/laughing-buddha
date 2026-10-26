const {test,expect,brand,sku,link,checkout,stats}=require('./fixtures.cjs');

test('discount entry sends only the code and displays authoritative upfront and renewal totals',async({ownerPage:page,app})=>{
 await brand(page);await sku(page);await link(page);await checkout(page,app);
 await page.locator('#edit').click();await page.getByLabel('Discount code (optional)').fill('FORTIFYTEST99');
 let posted;
 await page.route('**/api/quote?**',async route=>{
  posted=route.request().postDataJSON();
  await route.fulfill({json:{id:'quote-fixture',amount:1668,currency:'usd',total:'16.68',renewalPrice:'16.68',coupon:{code:'FORTIFYTEST99',lifetime:true},option:{prepaidCycles:4,days:90,renewal:true,renewalDays:360,recurring:true,basePrice:'417.00',upfrontPrice:'1668.00'}}});
 });
 await page.locator('#contact button').click();
 await expect(page.locator('#review')).toBeVisible();
 expect(posted.coupon_code).toBe('FORTIFYTEST99');expect(posted.contact.coupon_code).toBeUndefined();
 await expect(page.locator('#review-total')).toContainText('16.68');
 await expect(page.locator('#terms')).toContainText('FORTIFYTEST99 applied.');
 await expect(page.locator('#terms')).toContainText('every 360 days for $16.68');
 await page.locator('#edit').click();await expect(page.locator('#coupon-code')).toHaveValue('FORTIFYTEST99');
 await page.route('**/api/quote?**',route=>route.fulfill({status:422,json:{detail:'This discount code is invalid or expired.'}}));
 await page.locator('#contact button').click();await expect(page.locator('#message')).toContainText('invalid or expired');
 await expect(page.locator('#review')).toBeHidden();expect((await stats(page,app)).counts.authorize_payment).toBe(0);
});
