'use strict';
let commerceEpoch=0;
function renderCommerceSelectors(brandId,campaignId){
 const brands=$('commerce-brand'),campaign=$('commerce-campaign');
 const chosen=brandId??brands.value,oldCampaign=campaignId??campaign.value;
 brands.replaceChildren();option(brands,'','Choose a brand');
 for(const b of state.brands)option(brands,b.id,b.name);
 brands.value=chosen|| (state.brands.length===1?state.brands[0].id:'');
 const brand=state.brands.find(b=>b.id===brands.value);campaign.replaceChildren();
 option(campaign,'','Choose a campaign');
 for(const cid of brandCampaigns(brand))option(campaign,cid,(campaigns.find(c=>Number(c.id)===Number(cid))?.name||'Campaign')+' · '+cid);
 campaign.value=brandCampaigns(brand).includes(Number(oldCampaign))?oldCampaign:brand?.campaign_id||'';
 $('commerce-scope').textContent=brand?'Changes apply only to '+brand.name+' and the selected campaign. Review each change before saving.':'Select a brand to begin.';
 $('commerce-api-docs').hidden=!brand;if(brand)$('commerce-api-docs').href='/api/admin/brands/'+encodeURIComponent(brand.id)+'/commerce/openapi.json';
 $('commerce-coupon-form').querySelector('button').disabled=!campaign.value;
 $('commerce-load-coupons').disabled=!campaign.value;
}
function openCommerce(brand,campaign){renderCommerceSelectors(brand,campaign);page('commerce');}
async function commerceReview(path,body,kind){
 const result=await api(path,body);await refresh();showReview({...result,kind,status:'draft'});
 message('Review the changes, then approve to save.');
}
async function loadCommerce(){
 const epoch=++commerceEpoch,brand=$('commerce-brand').value,campaign=Number($('commerce-campaign').value);
 const target=$('commerce-prices');target.replaceChildren();$('commerce-coupons').replaceChildren();
 if(!brand||!campaign){target.append(element('p','Select a brand and campaign to see prices.'));return;}
 target.append(element('p','Loading prices…'));
 try{
 const data=await api('brands/'+encodeURIComponent(brand)+'/prices');if(epoch!==commerceEpoch)return;target.replaceChildren();
 const rows=data.prices.filter(p=>p.campaign_id===campaign);
 for(const p of rows){
  const box=card((state.masters||[]).find(m=>m.sku===p.sku)?.name||p.name,p.sku+' · '+p.name);
  const form=element('form'),label=element('label','Selling price ('+((state.masters||[]).find(m=>m.sku===p.sku)?.currency||'USD')+')'),input=element('input');
  input.type='number';input.min='0.01';input.max='99999999.99';input.step='0.01';input.required=true;input.value=p.price;input.name='price';label.append(input);
  const button=element('button','Review price change →');button.type='submit';form.append(label,button);box.append(form);target.append(box);
  form.addEventListener('submit',async event=>{event.preventDefault();button.disabled=true;try{
   await commerceReview('brands/'+encodeURIComponent(brand)+'/prices/'+encodeURIComponent(p.id)+'/reviews',{price:input.value,expected_price:p.price},'offer');
  }catch(e){message(e.message,true,true);}finally{button.disabled=false;}});
 }
 if(!rows.length)target.append(element('p','No managed products in this campaign yet. Prepare its site checkouts first.','empty'));
 }catch(e){if(epoch===commerceEpoch)target.replaceChildren(element('p','Prices could not be loaded. Reselect the campaign to retry.'));throw e;}
}
$('commerce-brand').addEventListener('change',()=>{renderCommerceSelectors($('commerce-brand').value,'');loadCommerce().catch(e=>message(e.message,true));});
$('commerce-campaign').addEventListener('change',()=>{renderCommerceSelectors();loadCommerce().catch(e=>message(e.message,true));});
$('commerce-coupon-form').addEventListener('submit',async event=>{
 event.preventDefault();const form=event.target,button=form.querySelector('button'),f=new FormData(form);
 const brand=$('commerce-brand').value,campaign=Number($('commerce-campaign').value);
 if(!brand||!campaign){message('Choose a brand and campaign first.',true,true);return;}
 button.disabled=true;try{
 await commerceReview('brands/'+encodeURIComponent(brand)+'/coupons/reviews',{
  campaign_id:campaign,code:f.get('code'),percent:Number(f.get('percent')),
  applies_to_renewals:f.get('applies_to_renewals')==='true',expires_on:f.get('expires_on'),timezone:f.get('timezone'),
  max_uses:Number(f.get('max_uses')),max_uses_per_customer:Number(f.get('max_uses_per_customer'))},'coupon');
 }catch(e){message(e.message,true,true);}finally{button.disabled=false;}
});
$('commerce-load-coupons').addEventListener('click',async event=>{
 const button=event.target,epoch=commerceEpoch,brand=$('commerce-brand').value,campaign=$('commerce-campaign').value;
 if(!brand||!campaign)return;button.disabled=true;
 try{
 const data=await api('brands/'+encodeURIComponent(brand)+'/coupons?campaign_id='+encodeURIComponent(campaign));if(epoch!==commerceEpoch)return;
 list('commerce-coupons',data.coupons,c=>{
  const box=card(c.codes.join(', ')||c.name,c.percent+'% off · '+(c.applies_to_renewals?'First payment and renewals':'First payment only'));
  box.append(element('p',(c.active?'Enabled':'Disabled')+' · Expires '+(c.expires_at||'not specified')+' '+c.timezone));
  box.append(element('p',c.use_count+' uses'+(c.max_uses?' of '+c.max_uses:'')));return box;
 },'No coupons assigned to this campaign.');
 }catch(e){message(e.message,true,true);}finally{button.disabled=false;}
});
