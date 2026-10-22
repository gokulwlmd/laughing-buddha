'use strict';
let creatingSiteBrand=false,newSiteBrandId='';
function newTemplate(t={}){
 const f=$('template-form');f.reset();f.elements.id.value=t.id||'template-'+crypto.randomUUID().slice(0,12);f.elements.id.readOnly=!!t.id;
 for(const k of ['name','title','therapy_id'])f.elements[k].value=t[k]||'';
 f.elements.therapy_id.disabled=!!t.id;f.elements.enabled.checked=t.enabled!==false;
 templatePlans(t.purchase_option_ids||[]);$('template-mode').textContent=t.id?'Edit checkout template':'New checkout template';
}
function templatePlans(selected){
 const target=$('template-plans'),f=$('template-form');selected||=Array.from(target.querySelectorAll('input:checked'),e=>e.value);target.replaceChildren();
 for(const p of state.purchaseOptions||[]){if(p.therapy_id!==f.elements.therapy_id.value)continue;
  const label=element('label',undefined,'checkbox'),input=element('input');input.type='checkbox';input.name='purchase_option_ids';input.value=p.id;input.checked=selected.includes(p.id);
  label.append(input,element('span',p.name+' · '+p.skus.join(', ')+(p.enabled?'':' · Inactive')));target.append(label);
 }
 if(!target.children.length)target.append(element('p','Add duration plans and assign matching master SKUs under Advanced.','hint'));
}
function newSite(s={}){
 const f=$('site-form');f.reset();creatingSiteBrand=false;newSiteBrandId='';$('site-brand-fields').hidden=true;$('site-brand').disabled=false;
 f.elements.id.value=s.id||'site-'+crypto.randomUUID().slice(0,12);f.elements.id.readOnly=!!s.id;f.elements.name.value=s.name||'';f.elements.brand_id.value=s.brand_id||'';f.elements.campaign_id.value=s.campaign_id||'';
 f.elements.connection.disabled=!!s.id;f.elements.brand_id.disabled=!!s.id;f.elements.campaign_id.disabled=!!s.id;$('site-new-brand').hidden=!!s.id;
 $('site-mode').textContent=s.id?'Review site updates':'Add a site';siteConnection();renderSiteBrand();
}
function siteConnection(){const f=$('site-form'),creating=f.elements.connection.value==='new';$('site-existing').hidden=creating;$('site-create-campaign').hidden=!creating;f.elements.campaign_id.required=!creating;f.elements.campaign_name.required=creating;f.elements.routing_template_id.required=creating;}
function renderSiteBrand(){const b=state.brands.find(b=>b.id===$('site-brand').value);$('site-brand-note').textContent=creatingSiteBrand?'New brand design will be included in the same review.':b?'Uses '+b.name+'’s logo, colors and support details.'+(b.custom_domain?' Custom domain: DNS/HTTPS pending.':''):'Select an existing brand or create one here.';}
function openSiteCustomizer(site,row){
 const plan=state.planCheckouts.find(p=>p.id===row.checkout_id),f=$('site-checkout-form'),o=plan.site_override||{};
 f.reset();f.elements.site_id.value=site.id;f.elements.template_id.value=row.template_id;f.elements.title.value=plan.title;f.elements.visibility.value=plan.visibility;f.elements.enabled.checked=plan.enabled;
 const selected=o.purchase_option_ids||plan.purchase_option_ids,target=$('site-checkout-plans');target.replaceChildren();
 for(const p of plan.template_snapshot.plans){const label=element('label',undefined,'checkbox'),i=element('input');i.type='checkbox';i.name='purchase_option_ids';i.value=p.id;i.checked=selected.includes(p.id);label.append(i,element('span',p.name));target.append(label);}
 for(const i of f.querySelectorAll('[name=payment_types]'))i.checked=(o.payment_types||['once','subscription','prepaid']).includes(i.value);
 const pricing=$('offer-form');pricing.elements.brand_id.value=site.brand_id;renderOfferCampaigns(site.campaign_id);
 $('site-customizer').hidden=false;$('site-customizer').scrollIntoView({block:'start'});
}
function renderSites(){
 $('staging-notice').hidden=!state.synthetic;
 const f=$('template-form'),selected=f.elements.therapy_id.value;f.elements.therapy_id.replaceChildren();option(f.elements.therapy_id,'','Choose a therapy');for(const t of state.therapies||[])option(f.elements.therapy_id,t.id,t.name);f.elements.therapy_id.value=selected;templatePlans();
 list('template-list',state.checkoutTemplates||[],t=>{const e=card(t.name,t.purchase_option_ids.length+' plans · '+(t.enabled?'Included in new sites':'Disabled for new sites'));action(e,'Edit template',()=>newTemplate(t));return e;},'Create a checkout template from your saved therapy plans.');
 const templates=(state.checkoutTemplates||[]).filter(t=>t.enabled);$('site-templates-summary').textContent=templates.length?'Automatically prepares: '+templates.map(t=>t.name).join(', '):'Create an enabled checkout template first.';
 list('site-list',state.sites||[],site=>{
  const b=state.brands.find(b=>b.id===site.brand_id),e=card(site.name,(b?.name||site.brand_id)+' · Campaign '+site.campaign_id);
  if(b?.color)e.style.borderLeft='4px solid '+b.color;
  for(const row of site.checkouts){const checkout=element('div',undefined,'site-checkout'),p=(state.planCheckouts||[]).find(p=>p.id===row.checkout_id);checkout.append(element('h3',row.name),element('p',({ready:'Ready · private invitation',live:'Live · public checkout',incomplete:'Incomplete · configuration needs attention'}[row.status])+(row.customized?' · Customized':'')+(row.update_available?' · Update available':'')));
   const actions=element('div',undefined,'actions');
   if(p&&row.status!=='incomplete'){const a=element('a','Preview ↗');a.href=p.url;a.target='_blank';a.rel='noopener noreferrer';actions.append(a);action(actions,'Copy link',async()=>{try{await navigator.clipboard.writeText(p.url);message('Link copied.'+(p.visibility==='private'?' Keep this invitation private.':''));}catch{const input=element('input');input.readOnly=true;input.value=p.url;input.setAttribute('aria-label','Checkout URL');checkout.append(input);input.focus();input.select();}});}
   if(p)action(actions,'Customize',()=>openSiteCustomizer(site,row));checkout.append(actions);e.append(checkout);
  }
  action(e,site.checkouts.some(c=>c.update_available)?'Review template updates':'Review / retry setup',()=>{page('sites');newSite(site);});
  action(e,'Edit brand design',()=>{page('brands');fill('brand-form',b);});return e;
 },'Add a site to prepare all enabled checkout templates.');
}
function renderSiteReview(r){
 const sources=r.preview.templates||(r.preview.plans?[{template:r.preview.after,plans:r.preview.plans}]:[]);
 if(r.preview.brand)$('review-summary').append(element('p','Brand: '+r.preview.brand.name+' · '+r.preview.brand.color+' · '+(r.preview.brand.support_email||'No support email')));
 for(const source of sources){const group=element('div',undefined,'record');group.append(element('h3',source.template.name));for(const p of source.plans)group.append(element('p',p.name+' · '+p.duration_months+' months · '+p.skus.join(', ')+' · '+p.payment_types.map(t=>({once:'One-time',subscription:'Subscription',prepaid:'Pay upfront'}[t])).join(' / ')));$('review-summary').append(group);}
 if(r.result?.checkouts)for(const row of r.result.checkouts)$('review-result').append(element('p',row.template_id+' · '+row.status+(row.reason?' · '+row.reason:'')));
}
$('template-new').addEventListener('click',()=>newTemplate());$('template-therapy').addEventListener('change',()=>templatePlans([]));
$('site-new').addEventListener('click',()=>newSite());$('site-connection').addEventListener('change',siteConnection);$('site-brand').addEventListener('change',renderSiteBrand);
$('site-new-brand').addEventListener('click',()=>{creatingSiteBrand=true;newSiteBrandId='brand-'+crypto.randomUUID().slice(0,12);$('site-brand').disabled=true;$('site-brand-fields').hidden=false;renderSiteBrand();});
submit('template-form',f=>({id:f.get('id'),name:f.get('name'),title:f.get('title'),therapy_id:$('template-therapy').value,purchase_option_ids:f.getAll('purchase_option_ids'),enabled:f.get('enabled')==='on'}),'checkout_template');
submit('site-form',f=>{const form=$('site-form'),data={id:f.get('id'),name:f.get('name'),brand_id:creatingSiteBrand?newSiteBrandId:form.elements.brand_id.value};
 if(form.elements.connection.value==='existing')data.campaign_id=Number(form.elements.campaign_id.value);else {data.campaign_name=f.get('campaign_name');data.routing_template_id=Number(f.get('routing_template_id'));}
 if(creatingSiteBrand)data.new_brand={id:newSiteBrandId,name:f.get('brand_name'),logo_url:f.get('logo_url'),color:f.get('color'),support_email:f.get('support_email')};return data;
},'site');
submit('site-checkout-form',f=>({site_id:f.get('site_id'),template_id:f.get('template_id'),title:f.get('title'),purchase_option_ids:f.getAll('purchase_option_ids'),payment_types:f.getAll('payment_types'),visibility:f.get('visibility'),enabled:f.get('enabled')==='on'}),'site_checkout');
newTemplate();newSite();
