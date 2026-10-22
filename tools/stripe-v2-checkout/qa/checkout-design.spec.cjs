const {test,expect,brand,stats}=require('./fixtures.cjs');

async function save(page,kind,data){
 return page.evaluate(async({kind,data})=>{
  const auth=await(await fetch('/api/admin/auth')).json();
  const headers={'Content-Type':'application/json','X-CSRF-Token':auth.csrfToken};
  const review=await fetch('/api/admin/reviews',{method:'POST',headers,body:JSON.stringify({kind,data})});
  const result=await review.json();if(!review.ok)throw Error(JSON.stringify(result));
  const applied=await fetch('/api/admin/apply',{method:'POST',headers,body:JSON.stringify({review_id:result.id,approve:true})});
  if(!applied.ok)throw Error(JSON.stringify(await applied.json()));
  return applied.json();
 },{kind,data});
}

async function preparePlans(page){
 await brand(page,'Juniper Health');
 await save(page,'therapy',{id:'weight-loss',name:'Weight Loss',enabled:true,treatments:[{id:'sema',name:'Semaglutide'},{id:'tirz',name:'Tirzepatide'}]});
 const allSkus=[],purchaseIds=[];
 for(const months of[1,3,6,12]){
  const skus=[];
  for(const[prefix,treatment,name,monthly]of[['SEMA','sema','Semaglutide',249],['TIRZ','tirz','Tirzepatide',399]]){
   for(const renewal of[false,true]){
    const sku=prefix+'-'+months+'M'+(renewal?'-SUB':'');skus.push(sku);allSkus.push(sku);
    const offer={id:'upfront',name:'Full-term upfront',price:String(monthly*months),billing_models:[months>=6?4:renewal?(months===3?4:3):2]};
    if(months>=6){offer.prepaid_cycles=months/3;if(renewal)offer.prepaid_renewal=true;}
    await save(page,'master',{sku,name:'WLMD payment test / '+name+' / '+months+' months / '+(renewal?'Subscription':'One-time'),therapy_id:'weight-loss',treatment_id:treatment,product_duration_months:months,fulfillment_product_id:55098,currency:'USD',offers:[offer]});
   }
  }
  const id='plan-'+months;purchaseIds.push(id);
  await save(page,'purchase_option',{id,name:months+'-month plan',therapy_id:'weight-loss',duration_months:months,skus,payment_types:months>=6?['prepaid']:['once','subscription']});
 }
 await save(page,'provision',{brand_id:'qa-brand',campaign_id:422,skus:allSkus});
 await save(page,'plan_checkout',{id:'design-checkout',brand_id:'qa-brand',campaign_id:422,therapy_id:'weight-loss',title:'Choose your weight loss plan',purchase_option_ids:purchaseIds,visibility:'public',enabled:true});
}

async function noOverflow(page){expect(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth)).toBe(false);}
async function screenshot(page,name){
 await page.evaluate(async()=>{await document.fonts.ready;window.scrollTo({top:0,behavior:'instant'});await new Promise(resolve=>requestAnimationFrame(()=>requestAnimationFrame(resolve)));});
 await page.screenshot({path:test.info().outputPath(name),fullPage:true,animations:'disabled'});
}

test('DESIGN-01 compact responsive selection preserves exact upfront prices, renewal terms and checkout mapping',async({ownerPage:page,app})=>{
 test.setTimeout(90000);
 await preparePlans(page);
 await page.goto(app.origin+'/plans/design-checkout');
 await expect(page.locator('#treatments button[aria-pressed=true]')).toHaveText('Semaglutide');
 await expect(page.locator('#duration-step')).toBeVisible();
 expect(await page.locator('#durations [data-duration]').evaluateAll(es=>es.map(e=>Number(e.dataset.duration)))).toEqual([12,6,3,1]);
 await expect(page.locator('#payment-step')).toBeHidden();
 await page.locator('#durations [data-duration="12"]').click();
 await page.locator('#payments').getByRole('button',{name:/One-time purchase/}).click();
 await expect(page.locator('#selection-details')).toContainText('2,988.00');
 await expect(page.locator('#selection-details')).toContainText('No automatic renewal');
 await expect(page.locator('#selection-details')).toContainText('90 days');
 const body=await page.locator('body').innerText();
 expect(body).not.toMatch(/SEMA-12M|Full-term upfront|synthetic test product|guaranteed results|FDA.approved|\b(?:4\.9|5\.0)\s*\/\s*5/i);
 await noOverflow(page);
 await screenshot(page,'plan-desktop.png');
 await page.setViewportSize({width:390,height:844});
 await noOverflow(page);
 await screenshot(page,'plan-mobile.png');
 await page.locator('#plan-continue').click();
 await expect(page.locator('#contact')).toBeVisible();
 await expect(page.locator('#product')).toHaveText('Semaglutide');
 await expect(page.locator('#total')).toContainText('2,988.00');
 const onceKey=new URL(page.url()).pathname.split('/').pop();
 const once=await(await page.request.get(app.origin+'/api/config?link_id='+onceKey)).json();
 expect(once.sku).toBe('SEMA-12M');expect(once.options[0].renewal).toBe(false);expect(once.options[0].prepaidCycles).toBe(4);
 await noOverflow(page);
 await screenshot(page,'contact-mobile.png');
 await page.setViewportSize({width:1440,height:1000});
 await noOverflow(page);
 await screenshot(page,'contact-desktop.png');

 await page.goto(app.origin+'/plans/design-checkout');
 await page.locator('#durations [data-duration="12"]').click();
 await page.locator('#payments').getByRole('button',{name:/Subscription/}).click();
 await expect(page.locator('#selection-details')).toContainText('360 days');
 await page.locator('#treatments').getByRole('button',{name:'Tirzepatide',exact:true}).click();
 await expect(page.locator('#payment-step')).toBeHidden();
 await expect(page.locator('#plan-continue')).toBeHidden();
 await expect(page.locator('#durations [data-duration="12"]')).toContainText('4,788.00');
 await page.locator('#durations [data-duration="6"]').click();
 await page.locator('#payments').getByRole('button',{name:/Subscription/}).click();
 await expect(page.locator('#selection-details')).toContainText('180 days');
 await expect(page.locator('#selection-details')).toContainText('2,394.00');
 await page.locator('#plan-continue').click();
 await expect(page.locator('#contact')).toBeVisible();
 const subKey=new URL(page.url()).pathname.split('/').pop();
 const sub=await(await page.request.get(app.origin+'/api/config?link_id='+subKey)).json();
 expect(sub.sku).toBe('TIRZ-6M-SUB');expect(sub.options[0].renewalDays).toBe(180);expect(sub.options[0].prepaidCycles).toBe(2);
 await expect(page.locator('#total')).toContainText('2,394.00');
 const state=await stats(page,app);expect(state.counts.authorize_payment).toBe(0);expect(state.counts.new_order).toBe(0);
});
