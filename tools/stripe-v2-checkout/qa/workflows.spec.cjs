const {test,expect,PASSWORD,setupOwner,nav,approve,brand,sku,offer,link,checkout,authorize,stats,control}=require('./fixtures.cjs');
const SKU='WLMD-CORE-2USD-0f89b1bb';
async function prepare(page){await brand(page);await sku(page);await link(page);}
async function login(page,app){await page.goto(app.origin+'/admin');await page.locator('#auth-form [name=email]').fill('qa-owner@example.com');await page.locator('#auth-password').fill(PASSWORD);await page.getByRole('button',{name:'Sign in',exact:true}).click();await expect(page.locator('#workspace')).toBeVisible();await expect(page.locator('#owner-email')).toHaveText('qa-owner@example.com');}
async function pay(page){await page.locator('#pay').click();await expect(page.locator('#success')).toBeVisible();}

test('AUTH-01 first setup needs its invitation and matching passwords',async({page,app})=>{
 await page.goto(app.origin+'/admin');await expect(page.locator('#auth-submit')).toBeDisabled();
 await page.goto(app.origin+app.setupPath);await page.locator('#auth-form [name=email]').fill('qa-owner@example.com');await page.locator('#auth-password').fill(PASSWORD);await page.locator('#password-confirm').fill('different-password-123');await page.locator('#auth-submit').click();await expect(page.locator('#auth-message')).toHaveText('The passwords do not match.');expect((await stats(page,app)).ownerCount).toBe(0);
 await page.locator('#password-confirm').fill(PASSWORD);await page.locator('#show-password').check();await expect(page.locator('#auth-password')).toHaveAttribute('type','text');await page.locator('#auth-submit').click();await expect(page.locator('#workspace')).toBeVisible();
 await page.locator('#logout').click();await expect(page.locator('#auth')).toBeVisible();await login(page,app);expect((await stats(page,app)).ownerCount).toBe(1);
});

test('AUTH-02 wrong password is recoverable and sign-out clears workspace',async({ownerPage:page,app})=>{
 await brand(page);await page.locator('#logout').click();await page.locator('#auth-form [name=email]').fill('qa-owner@example.com');await page.locator('#auth-password').fill('incorrect-password');await page.locator('#auth-submit').click();await expect(page.locator('#auth-message')).toContainText('Email or password is incorrect');await page.locator('#auth-password').fill(PASSWORD);await page.locator('#auth-submit').click();await expect(page.locator('#workspace')).toBeVisible();await page.locator('#logout').click();await expect(page.locator('#owner-email')).toBeEmpty();await expect(page.locator('#workspace')).toBeHidden();
});

test('AUTH-03 expired session returns to login and preserves the unapplied draft',async({ownerPage:page,app})=>{
 await nav(page,'brands');await page.locator('#brand-form [name=id]').fill('session-brand');await page.locator('#brand-form [name=name]').fill('Session brand');await page.locator('#brand-form button').last().click();await expect(page.locator('#current-review')).toBeVisible();await control(page,app,{expire_session:true});await page.locator('#refresh-workspace').click();await expect(page.locator('#auth')).toBeVisible();await expect(page.locator('#auth-message')).toContainText('session expired');await login(page,app);await expect(page.locator('#review-list')).toContainText('Session brand');expect((await stats(page,app)).brands).toBe(0);
});

test('CAT-01 campaign search, immutable identifiers and clean new forms',async({ownerPage:page})=>{
 await nav(page,'brands');await page.locator('#campaign-search').fill('Second');await expect(page.locator('#brand-campaign option')).toHaveCount(2);await page.locator('#campaign-search').fill('');await brand(page);await nav(page,'brands');await expect(page.locator('#brand-form [name=name]')).toBeEmpty();await page.locator('#brand-list').getByRole('button',{name:'Edit brand'}).click();await expect(page.locator('#brand-form [name=id]')).toHaveJSProperty('readOnly',true);await page.locator('[data-new=brand]').click();await expect(page.locator('#brand-form [name=id]')).toHaveJSProperty('readOnly',false);await expect(page.locator('#brand-form [name=name]')).toBeEmpty();
});

test('CAT-02 find duplicate SKU products and explicitly select a mapping',async({ownerPage:page,app})=>{
 await brand(page);await control(page,app,{duplicate_sku:true});await nav(page,'skus');await page.locator('#lookup-brand').selectOption('qa-brand');await page.locator('#lookup-sku').fill(SKU);await page.locator('#lookup-products').click();await expect(page.getByRole('button',{name:'Use this product'})).toHaveCount(2);await page.getByRole('button',{name:'Use this product'}).nth(1).click();await expect(page.locator('#sku-form [name=product_id]')).toHaveValue('54538');await page.locator('#sku-form button').click();await approve(page);expect((await stats(page,app)).skus).toBe(1);
});

test('CAT-03 lookup failure preserves entered values and can be retried',async({ownerPage:page,app})=>{
 await brand(page);await nav(page,'skus');await page.locator('#lookup-brand').selectOption('qa-brand');await page.locator('#lookup-sku').fill(SKU);await control(page,app,{read_failure:true});await page.locator('#lookup-products').click();await expect(page.locator('#message')).toContainText('temporarily unavailable');await expect(page.locator('#lookup-sku')).toHaveValue(SKU);await control(page,app,{read_failure:false});await page.locator('#lookup-products').click();await expect(page.getByRole('button',{name:'Use this product'})).toBeVisible();
});

test('REV-01 no change without consent; discard removes only the draft',async({ownerPage:page,app})=>{
 await nav(page,'brands');await page.locator('#brand-form [name=id]').fill('draft-brand');await page.locator('#brand-form [name=name]').fill('Draft brand');await page.locator('#brand-form button').last().click();await expect(page.locator('#review-summary')).toContainText('No Sticky records');await expect(page.locator('.change-table')).toContainText('Draft brand');await page.locator('#apply-review').click();await expect(page.locator('#message')).toContainText('Confirm that you approve');expect((await stats(page,app)).brands).toBe(0);await page.locator('#discard-review').click();await expect(page.locator('#current-review')).toBeHidden();await expect(page.locator('#review-list')).toContainText('discarded');expect((await stats(page,app)).counts.products).toBe(0);
});

test('REV-02 stale preview can be refreshed and approved once',async({ownerPage:page,app})=>{
 await nav(page,'brands');await page.locator('#brand-form [name=id]').fill('first-brand');await page.locator('#brand-form [name=name]').fill('First draft');await page.locator('#brand-form button').last().click();await expect(page.locator('#current-review')).toBeVisible();await brand(page,'Second brand','second-brand');await nav(page,'reviews');await page.locator('#review-list .record').filter({hasText:'First draft'}).getByRole('button',{name:'Open review'}).click();await page.locator('#review-consent').check();await page.locator('#apply-review').click();await expect(page.locator('#message')).toContainText('Configuration changed');await page.route('**/api/admin/reviews/*/refresh',async route=>{await new Promise(resolve=>setTimeout(resolve,300));await route.continue();});await page.locator('#refresh-review').click();await expect(page.locator('#review-consent')).toBeDisabled();await expect(page.locator('#apply-review')).toBeDisabled();await expect(page.locator('#review-consent')).not.toBeChecked();await approve(page);expect((await stats(page,app)).brands).toBe(2);
});

test('OFF-01 billing checkboxes and invalid advanced JSON preserve the form',async({ownerPage:page,app})=>{
 await brand(page);await sku(page);await nav(page,'offers');await page.locator('#offer-form [name=brand_id]').selectOption('qa-brand');await page.locator('#offer-form [name=sku]').selectOption(SKU);await page.locator('#offer-form [name=name]').fill('My plan');await page.locator('#offer-form [name=price]').fill('3.00');await page.locator('#offer-form button').last().click();await expect(page.locator('#message')).toContainText('Choose at least one billing');await page.locator('#billing-models input[value="2"]').check();await page.locator('#offer-form details').evaluate(e=>e.open=true);await page.locator('#offer-form [name=configuration]').fill('{ broken JSON');await page.locator('#offer-form button').last().click();await expect(page.locator('#message')).toContainText('valid JSON');await expect(page.locator('#offer-form [name=name]')).toHaveValue('My plan');expect((await stats(page,app)).counts.products).toBe(0);
});

test('OFF-02 dollar-prefixed names create offers without reference substitution',async({ownerPage:page,app})=>{
 await brand(page);await sku(page);await offer(page,{name:'$3 introductory plan'});await nav(page,'offers');await expect(page.locator('#managed-offers')).toContainText('$3 introductory plan');expect((await stats(page,app)).counts.products).toBe(1);expect((await stats(page,app)).counts.offers).toBe(1);
});

test('OFF-03 brand price edits update only selected checkout choices',async({ownerPage:page,app})=>{
 await brand(page);await sku(page);await offer(page,{price:'3.00'});await link(page,{created:true});await nav(page,'offers');await page.locator('#managed-offers').getByRole('button',{name:'Edit price and terms'}).click();await page.locator('#offer-form [name=price]').fill('4.00');await page.locator('#offer-form button').last().click();await expect(page.locator('#review-summary')).toContainText('qa-link');await approve(page);await checkout(page,app);await expect(page.locator('#review-total')).toContainText('4.00');expect((await stats(page,app)).counts.products).toBe(2);
});

test('OFF-04 partial Sticky write is held and cannot be blindly retried',async({ownerPage:page,app})=>{
 await brand(page);await sku(page);await control(page,app,{fail_offer:true});await nav(page,'offers');await page.locator('#offer-form [name=brand_id]').selectOption('qa-brand');await page.locator('#offer-form [name=sku]').selectOption(SKU);await page.locator('#offer-form [name=name]').fill('Uncertain plan');await page.locator('#offer-form [name=price]').fill('3.00');await page.locator('#billing-models input[value="2"]').check();await page.locator('#offer-form button').last().click();await page.locator('#review-consent').check();await page.locator('#apply-review').click();await expect(page.locator('#review-result')).toContainText('needs reconciliation');await expect(page.locator('#apply-review')).toBeHidden();await expect(page.locator('#refresh-review')).toBeHidden();expect((await stats(page,app)).counts.products).toBe(1);
});

test('CAM-01 copy routing selections and preview a new campaign',async({ownerPage:page,app})=>{
 await brand(page);await nav(page,'brands');await page.locator('#campaign-source').selectOption('422');await page.locator('#use-campaign-template').click();await expect(page.locator('#campaign-form [name=gateway_id]')).toHaveValue('254');await page.locator('#campaign-form [name=brand_id]').selectOption('qa-brand');await page.locator('#campaign-form [name=name]').fill('New QA campaign');await page.locator('#campaign-form button').last().click();await expect(page.locator('#review-summary')).toContainText('catalog updates require your approval');expect((await stats(page,app)).counts.campaigns).toBe(0);await approve(page);expect((await stats(page,app)).counts.campaigns).toBe(1);
});

test('PAY-01 public branded checkout and reusable link capture once per attempt',async({ownerPage:page,app})=>{
 await prepare(page);await page.locator('#logout').click();await checkout(page,app);await expect(page.locator('#brand-name')).toHaveText('QA Brand');expect((await page.request.get(app.origin+'/api/admin/state')).status()).toBe(401);await authorize(page);await page.locator('#pay').evaluate(b=>{b.click();b.click();});await expect(page.locator('#success')).toBeVisible();expect((await stats(page,app)).orderCount).toBe(1);await page.locator('#new-purchase').evaluate(b=>{b.click();b.click();});await expect(page.locator('#contact')).toBeVisible();await checkout(page,app);await authorize(page);await pay(page);const s=await stats(page,app);expect(s.counts.authorize_payment).toBe(2);expect(s.counts.new_order).toBe(2);expect(s.orderCount).toBe(2);
});

test('PAY-02 recurring consent is required before authorization',async({ownerPage:page,app})=>{
 await brand(page);await sku(page);await link(page,{model:'3'});await checkout(page,app);await expect(page.locator('#terms')).toContainText('every 30 days');await page.locator('#authorize').click();await expect(page.locator('#message')).toContainText('accept the recurring');expect((await stats(page,app)).counts.authorize_payment).toBe(0);await authorize(page);await pay(page);
});

test('PAY-03 declined card can be retried using the same authorization',async({ownerPage:page,app})=>{
 await prepare(page);await checkout(page,app);await authorize(page);await page.evaluate(()=>window.__qaStripeMode='decline');await page.locator('#pay').click();await expect(page.locator('#message')).toContainText('declined');expect((await stats(page,app)).counts.new_order).toBe(0);await page.evaluate(()=>window.__qaStripeMode='approve');await pay(page);expect((await stats(page,app)).counts.authorize_payment).toBe(1);
});

test('PAY-04 Stripe-style redirect return removes secret and captures same intent',async({ownerPage:page,app})=>{
 await prepare(page);await checkout(page,app);await authorize(page);await page.evaluate(()=>window.__qaStripeMode='redirect');await page.locator('#pay').click();await expect(page.locator('#success')).toBeVisible();await expect(page).toHaveURL(app.origin+'/c/qa-link');const s=await stats(page,app);expect(s.counts.authorize_payment).toBe(1);expect(s.counts.new_order).toBe(1);
});

test('PAY-05 page refresh resumes the existing card authorization',async({ownerPage:page,app})=>{
 await prepare(page);await checkout(page,app);await authorize(page);await page.reload();await expect(page.locator('#payment')).toBeVisible();await expect(page.locator('#message')).toContainText('Your payment is ready to continue');await pay(page);expect((await stats(page,app)).counts.authorize_payment).toBe(1);
});

test('PAY-06 unavailable session secret holds payment instead of creating another',async({ownerPage:page,app})=>{
 await prepare(page);await checkout(page,app);await authorize(page);await page.route('**/api/resume?*',r=>r.fulfill({status:409,contentType:'application/json',body:JSON.stringify({detail:'This payment needs review before continuing. Please contact support; do not start another payment.'})}));await page.reload();await expect(page.locator('#message')).toContainText('needs review');await expect(page.locator('#contact')).toBeHidden();await expect(page.locator('#new-purchase')).toBeHidden();expect((await stats(page,app)).counts.authorize_payment).toBe(1);
});

test('PAY-07 price change requires a fresh reviewed total',async({ownerPage:page,app})=>{
 await prepare(page);await checkout(page,app);await control(page,app,{price:'3.00'});await page.locator('#authorize').click();await expect(page.locator('#message')).toContainText('price changed');expect((await stats(page,app)).counts.authorize_payment).toBe(0);await page.locator('#edit').click();await page.locator('#contact button').click();await expect(page.locator('#review-total')).toContainText('3.00');await authorize(page);await pay(page);
});

test('PAY-08 uncertain capture stays held after refresh and is never repeated',async({ownerPage:page,app})=>{
 await prepare(page);await checkout(page,app);await authorize(page);await control(page,app,{capture_timeout:true});await page.locator('#pay').click();await expect(page.locator('#message')).toContainText('uncertain');await page.reload();await expect(page.locator('#message')).toContainText('status needs review');await expect(page.locator('#new-purchase')).toBeHidden();const s=await stats(page,app);expect(s.counts.new_order).toBe(1);expect(s.orderCount).toBe(1);
});

test('LINK-01 private invitation is scoped and revocation is visible',async({ownerPage:page,app})=>{
 await brand(page);await sku(page);await link(page,{visibility:'private'});await nav(page,'links');const invitation=await page.locator('#link-list a').getAttribute('href');await page.locator('#logout').click();const r=await page.goto(app.origin+'/c/qa-link');expect(r.status()).toBe(401);await page.goto(invitation);await expect(page.locator('#contact')).toBeVisible();expect((await page.request.get(app.origin+'/api/admin/state')).status()).toBe(401);
 await login(page,app);await nav(page,'links');await page.locator('#link-list').getByRole('button',{name:'Edit link'}).click();await expect(page.locator('#link-options input').first()).toBeAttached();await page.locator('#link-customize').evaluate(e=>e.open=true);await page.locator('#link-form [name=title]').fill('Updated private checkout');await page.locator('#link-form button').last().click();await approve(page);await page.locator('#logout').click();const revoked=await page.goto(invitation);expect(revoked.status()).toBe(401);
});

test('LINK-02 inactive link cannot be opened and can be reactivated with approval',async({ownerPage:page,app})=>{
 await prepare(page);await nav(page,'links');await page.locator('#link-list').getByRole('button',{name:'Edit link'}).click();await expect(page.locator('#link-options input').first()).toBeAttached();await page.locator('#link-form [name=enabled]').uncheck();await page.locator('#link-form button').last().click();await approve(page);await nav(page,'links');await expect(page.locator('#link-list a')).toHaveCount(0);const r=await page.request.get(app.origin+'/c/qa-link');expect(r.status()).toBe(404);
 await page.locator('#link-list').getByRole('button',{name:'Edit link'}).click();await expect(page.locator('#link-options input').first()).toBeAttached();await page.locator('#link-form [name=enabled]').check();await page.locator('#link-form button').last().click();await approve(page);await checkout(page,app);
});

test('UX-01 mobile setup, review and catalog fit without horizontal overflow',async({ownerPage:page,app})=>{
 await page.setViewportSize({width:390,height:844});await brand(page);await sku(page);await nav(page,'reviews');await page.locator('#review-list').getByRole('button',{name:'View details'}).first().click();expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);await page.screenshot({path:require('node:path').join(__dirname,'results','mobile-review.png'),fullPage:true});await page.locator('#logout-mobile').click();await expect(page.locator('#auth')).toBeVisible();expect((await stats(page,app)).counts.new_order).toBe(0);
});
