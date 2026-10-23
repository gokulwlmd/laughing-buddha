'use strict';
let templateSkeletonId=null;
let creatingSiteBrand=true,newSiteBrandId='',templateRows=[],templateDraftTherapyId='',siteStep=1;
const paymentNames={once:'One-time purchase',subscription:'Subscription',prepaid:'Pay upfront'};
function templateTherapies(value){
 const select=$('template-therapy');value??=select.value;select.replaceChildren();option(select,'','Choose a therapy');
 for(const t of state.therapies||[])option(select,t.id,t.name);option(select,'__new','Create a new therapy…');select.value=value;
}
function newTemplate(t={}){
 templateSkeletonId=t.skeleton_id||null;
 const f=$('template-form');f.reset();f.elements.id.value=t.id||'template-'+crypto.randomUUID().slice(0,12);
 for(const k of ['name','title'])f.elements[k].value=t[k]||'';
 templateDraftTherapyId=t.new_therapy?.id||'therapy-'+crypto.randomUUID().slice(0,12);
 templateTherapies(t.new_therapy?'__new':t.therapy_id||'');f.elements.therapy_id.disabled=!!t.id&&(state.checkoutTemplates||[]).some(x=>x.id===t.id);
 f.elements.therapy_name.value=t.new_therapy?.name||'';f.elements.treatment_names.value=(t.new_therapy?.treatments||[]).map(x=>x.name).join(', ');
 f.elements.enabled.checked=t.enabled!==false;
 templateRows=structuredClone(t.plans||(t.purchase_option_ids||[]).map(id=>(state.purchaseOptions||[]).find(p=>p.id===id)).filter(Boolean));
 if(templateSkeletonId){const skeleton=(state.therapySkeletons||[]).find(s=>s.id===templateSkeletonId);for(const p of templateRows)if(!p.skus.length){const wanted=(skeleton?.products||[]).filter(x=>x.duration_months===p.duration_months).map(x=>x.sku);p.skus=(state.masters||[]).filter(m=>wanted.includes(m.sku)&&m.therapy_id===t.therapy_id).map(m=>m.sku);p.payment_types=['once','subscription',...(p.duration_months>=6?['prepaid']:[])];}}
 $('template-mode').textContent=t.id?'Edit checkout template':'New checkout template';$('template-editor').hidden=false;renderTemplateRows();$('template-editor').scrollIntoView({block:'start'});
}
function templateProducts(p){return (state.masters||[]).filter(m=>m.enabled&&!m.exclude_from_campaign_setup&&m.therapy_id===($('template-therapy').value==='__new'?templateDraftTherapyId:$('template-therapy').value)&&m.product_duration_months===Number(p.duration_months));}
function catalogPrice(m){if(m.planning_contract)return m.offers.map(o=>new Intl.NumberFormat('en',{style:'currency',currency:m.currency||'USD'}).format(Number(o.price))+' upfront').join(' / ');return (m.offers||[]).map(o=>new Intl.NumberFormat('en',{style:'currency',currency:m.currency||'USD'}).format(Number(o.price))+(o.prepaid_cycles?' upfront':o.billing_models.includes(2)&&o.billing_models.length===1?' one-time':' per payment')).join(' / ');}
function templateProblems(){
 const problems=[];if(templateSkeletonId)problems.push((state.therapySkeletons||[]).find(s=>s.id===templateSkeletonId)?.reason||'Master therapy draft needs billing verification.');if(!templateRows.length)problems.push('Add at least one plan.');
 for(const p of templateRows){if(!p.skus.length)problems.push(p.name+': choose a product.');if(!p.payment_types.length)problems.push(p.name+': choose how customers can pay.');
 const eligible=templateProducts(p);if(p.skus.some(sku=>!eligible.some(m=>m.sku===sku)))problems.push(p.name+': replace unavailable or mismatched products.');}
 return problems;
}
function updateTemplatePreview(){
 $('template-preview-title').textContent=$('template-form').elements.title.value||'Choose your plan';const target=$('template-preview-plans');target.replaceChildren();
 for(const p of templateRows){const box=card(p.name,p.duration_months+'-month plan');for(const sku of p.skus){const m=(state.masters||[]).find(m=>m.sku===sku);box.append(element('p',m?m.name+' · '+catalogPrice(m):sku+' · Product unavailable'));}if(!p.skus.length)box.append(element('p','Choose a product to show its price.','hint'));box.append(element('small',p.payment_types.map(t=>paymentNames[t]).join(' · ')));target.append(box);}
 const problems=templateProblems();$('template-readiness').textContent=problems.length?'Draft · '+problems.join(' '):'Ready to save · all plans have products selected. Final availability is checked during site setup.';
 $('template-form').querySelector('button[type=submit]').disabled=problems.length>0;
}
function renderTemplateRows(){
 renderSkeletonContract();
 $('template-new-therapy').hidden=$('template-therapy').value!=='__new';const target=$('template-plans');target.replaceChildren();
 templateRows.forEach((p,index)=>{
 const box=element('fieldset',undefined,'template-plan');box.dataset.planIndex=index;box.append(element('legend','Plan '+(index+1)));
 const row=element('div',undefined,'row'),name=element('label','Plan name'),input=element('input');input.value=p.name;input.required=true;input.maxLength=100;input.addEventListener('input',()=>{p.name=input.value;updateTemplatePreview();});name.append(input);
 const duration=element('label','Duration'),select=element('select');for(let n=1;n<=36;n++)option(select,n,n+' month'+(n===1?'':'s'));select.value=p.duration_months;select.addEventListener('change',()=>{p.duration_months=Number(select.value);p.skus=[];if(/^\d+-month plan$/.test(p.name))p.name=select.value+'-month plan';renderTemplateRows();});duration.append(select);row.append(name,duration);box.append(row);
 const products=element('div',undefined,'choices');box.append(element('h3','Products customers can choose'));
 const eligible=templateProducts(p);
 for(const m of eligible){const label=element('label',undefined,'checkbox'),choice=element('input');choice.type='checkbox';choice.value=m.sku;choice.checked=p.skus.includes(m.sku);choice.addEventListener('change',()=>{p.skus=choice.checked?[...p.skus,m.sku]:p.skus.filter(s=>s!==m.sku);updateTemplatePreview();});const text=element('span',m.name);text.append(element('small',m.sku+' · '+catalogPrice(m)));label.append(choice,text);products.append(label);}
 for(const sku of p.skus.filter(sku=>!eligible.some(m=>m.sku===sku))){const warning=element('div',undefined,'readiness-warning');warning.append(element('span',sku+' is unavailable for this duration. '));action(warning,'Remove product',()=>{p.skus=p.skus.filter(s=>s!==sku);renderTemplateRows();});products.append(warning);}
 if(!eligible.length)products.append(element('p','No matching products for this therapy and duration. Save a draft while these products are added in Advanced → Master SKUs.','hint'));box.append(products);
 const choices=element('fieldset');choices.append(element('legend','How customers can pay'));for(const [type,label]of Object.entries(paymentNames)){const l=element('label',undefined,'checkbox'),i=element('input');i.type='checkbox';i.value=type;i.checked=p.payment_types.includes(type);i.addEventListener('change',()=>{p.payment_types=i.checked?[...p.payment_types,type]:p.payment_types.filter(t=>t!==type);updateTemplatePreview();});l.append(i,element('span',label));choices.append(l);}box.append(choices);action(box,'Remove plan',()=>{templateRows.splice(index,1);renderTemplateRows();});target.append(box);
 });updateTemplatePreview();
}
function templatePayload(draft=false){
 const f=$('template-form'),therapy_id=f.elements.therapy_id.value==='__new'?templateDraftTherapyId:f.elements.therapy_id.value;
 const payload={skeleton_id:templateSkeletonId,id:f.elements.id.value,name:f.elements.name.value,title:f.elements.title.value,therapy_id,enabled:f.elements.enabled.checked,draft,
 plans:templateRows.map((p,i)=>({id:p.id||'plan-'+i,name:p.name,therapy_id,duration_months:Number(p.duration_months),skus:p.skus,payment_types:p.payment_types,enabled:true}))};
 if(f.elements.therapy_id.value==='__new')payload.new_therapy={id:therapy_id,name:f.elements.therapy_name.value,enabled:true,treatments:f.elements.treatment_names.value.split(',').map(n=>n.trim()).filter(Boolean).map(name=>({id:slug(name),name}))};return payload;
}
function newSite(s={}){
 const f=$('site-form');f.reset();creatingSiteBrand=!s.id;newSiteBrandId='brand-'+crypto.randomUUID().slice(0,12);f.elements.id.value=s.id||'site-'+crypto.randomUUID().slice(0,12);f.elements.name.value=s.name||'';
 f.elements.brand_id.value=s.brand_id||'';f.elements.campaign_id.value=s.campaign_id||'';f.elements.connection.value=s.id?'existing':'new';f.elements.brand_id.disabled=!!s.id;f.elements.connection.disabled=!!s.id;f.elements.campaign_id.disabled=!!s.id;
 $('site-brand-options').hidden=!!s.id;$('site-mode').textContent=s.id?'Update site checkouts':'Add a site';$('site-editor').hidden=false;$('site-customizer').hidden=true;
 $('site-form').querySelector('button[type=submit]').textContent=s.id?'Review checkout updates →':'Review and create site →';siteConnection();siteDefaults();renderSiteBrand();setSiteStep(s.id?2:1);$('site-editor').scrollIntoView({block:'start'});
}
function siteDefaults(){
 const f=$('site-form'),saved=state.siteDefaults?.routing_template_id||(state.synthetic?422:null);
 if(!f.elements.routing_template_id.value&&saved)f.elements.routing_template_id.value=String(saved);
 const source=f.elements.routing_template_id.selectedOptions[0];$('site-payment-default').textContent=source?.value?'Payment setup: '+source.textContent+'. Each new site gets its own connection and prices.':'First site: choose a payment setup below. It can be reused for future sites.';
 $('site-connection-options').open=!f.elements.routing_template_id.value&&f.elements.connection.value==='new';
}
function siteConnection(){const f=$('site-form'),creating=f.elements.connection.value==='new';$('site-existing').hidden=creating;$('site-create-campaign').hidden=!creating;f.elements.campaign_id.required=!creating;f.elements.routing_template_id.required=creating;}
function renderSiteBrand(){
 const b=state.brands.find(b=>b.id===$('site-brand').value);$('site-brand-fields').hidden=!creatingSiteBrand;
 $('site-brand-note').textContent=creatingSiteBrand?'Your name, logo and color will appear on every checkout.':b?'Uses '+b.name+'’s logo, colors and support details.':'';
}
function setSiteStep(step){siteStep=step;$('site-step-identity').hidden=step!==1;$('site-step-checkouts').hidden=step!==2;$('site-step-label').textContent=step===1?'1 · YOUR SITE':'2 · INCLUDED CHECKOUTS';$('site-identity-summary').textContent=$('site-form').elements.name.value+' · '+(creatingSiteBrand?'New branding':state.brands.find(b=>b.id===$('site-brand').value)?.name||'');}
function sitePayload(){const f=$('site-form'),data={id:f.elements.id.value,name:f.elements.name.value,brand_id:creatingSiteBrand?newSiteBrandId:f.elements.brand_id.value,remember_connection:f.elements.remember_connection.checked};
 if(f.elements.connection.value==='existing')data.campaign_id=Number(f.elements.campaign_id.value);else {data.campaign_name=f.elements.name.value;data.routing_template_id=Number(f.elements.routing_template_id.value);}
 if(creatingSiteBrand)data.new_brand={id:newSiteBrandId,name:f.elements.brand_name.value||f.elements.name.value,logo_url:f.elements.logo_url.value,color:f.elements.color.value,support_email:f.elements.support_email.value};return data;
}
function openSiteCustomizer(site,row){
 const plan=state.planCheckouts.find(p=>p.id===row.checkout_id),f=$('site-checkout-form'),o=plan.site_override||{};
 f.reset();f.elements.site_id.value=site.id;f.elements.template_id.value=row.template_id;f.elements.title.value=plan.title;f.elements.visibility.value=plan.visibility;f.elements.enabled.checked=plan.enabled;
 const selected=o.purchase_option_ids||plan.purchase_option_ids,target=$('site-checkout-plans');target.replaceChildren();
 for(const p of plan.template_snapshot.plans){const label=element('label',undefined,'checkbox'),i=element('input');i.type='checkbox';i.name='purchase_option_ids';i.value=p.id;i.checked=selected.includes(p.id);label.append(i,element('span',p.name));target.append(label);}
 for(const i of f.querySelectorAll('[name=payment_types]'))i.checked=(o.payment_types||['once','subscription','prepaid']).includes(i.value);
 const pricing=$('offer-form');pricing.elements.brand_id.value=site.brand_id;renderOfferCampaigns(site.campaign_id);
 $('site-editor').hidden=true;$('site-customizer').hidden=false;$('site-customizer').scrollIntoView({block:'start'});
}
function renderSites(){
 renderTherapySkeletons();
 $('staging-notice').hidden=!state.synthetic;templateTherapies();siteDefaults();
 const templates=state.checkoutTemplates||[],drafts=state.templateDrafts||[];
 list('template-list',[...templates,...drafts.filter(d=>!templates.some(t=>t.id===d.id))],t=>{
 const draft=drafts.find(d=>d.id===t.id),published=templates.some(x=>x.id===t.id);const e=card(t.name,published?(t.ready===false?'Needs attention':t.enabled?'Included in new sites':'Not included in new sites'):'Draft · not included in sites');
 e.append(element('p',(published?t.purchase_option_ids.length:t.plans.length)+' plans'+(draft&&published?' · Unpublished draft saved':'')));
 if(t.reason)e.append(element('p',t.reason,'readiness-warning'));action(e,draft?'Continue draft':'Edit template',()=>newTemplate(draft||t));return e;
 },'Create your first checkout template. Add its plans and products together.');
 const enabled=templates.filter(t=>t.enabled);$('site-templates-summary').replaceChildren();
 for(const t of enabled){const box=card(t.name,t.ready===false?t.reason:t.purchase_option_ids.length+' plans · branding added automatically');if(t.ready===false)action(box,'Fix template',()=>{page('templates');newTemplate(t);});$('site-templates-summary').append(box);}
 if(!enabled.length){$('site-templates-summary').append(element('p','No ready templates yet. Finish a template before adding a site.'));action($('site-templates-summary'),'Open checkout templates',()=>page('templates'));}
 $('site-form').querySelector('button[type=submit]').disabled=!enabled.length||enabled.some(t=>t.ready===false);
 list('site-list',state.sites||[],site=>{
 const b=state.brands.find(b=>b.id===site.brand_id),e=card(site.name,b?.name||'');if(b?.color)e.style.borderLeft='4px solid '+b.color;
 const portalActions=element('div',undefined,'actions');
 for(const [label,path] of [['Orders & members','/portal-admin/'],['Member login','/portal/']]){const a=element('a',label+' ↗');a.href=path+encodeURIComponent(site.id);a.target='_blank';a.rel='noopener noreferrer';portalActions.append(a);}e.append(portalActions);
 for(const row of site.checkouts){const checkout=element('div',undefined,'site-checkout'),p=(state.planCheckouts||[]).find(p=>p.id===row.checkout_id);checkout.append(element('h3',row.name));
 let status=row.status==='paused'?'Paused':row.status==='incomplete'?'Needs attention':row.status==='live'?'Published':p?.visibility==='public'?'Published in test mode · payments blocked':'Ready to preview';
 checkout.append(element('p',status+(row.update_available?' · Template update available':'')));if(row.reason)checkout.append(element('p',row.reason,'hint'));
 const actions=element('div',undefined,'actions');if(p&&['ready','live'].includes(row.status)){
 const a=element('a','Preview ↗');a.href=p.url;a.target='_blank';a.rel='noopener noreferrer';actions.append(a);
 action(actions,p.visibility==='public'?'Copy public link':'Copy private preview',async()=>{try{await navigator.clipboard.writeText(p.url);message(p.visibility==='public'?'Public link copied.':'Private preview copied. Share only with reviewers.');}catch{const input=element('input');input.readOnly=true;input.value=p.url;input.setAttribute('aria-label','Checkout URL');checkout.append(input);input.focus();input.select();}});
 if(p.visibility==='private')action(actions,'Publish',()=>{openSiteCustomizer(site,row);$('site-checkout-form').elements.visibility.value='public';message('Review the included plans below, then approve publication.');});}
 if(p)action(actions,'Edit checkout',()=>openSiteCustomizer(site,row));else action(actions,'Fix template',()=>{page('templates');newTemplate(templates.find(t=>t.id===row.template_id));});
 checkout.append(actions);e.append(checkout);}
 action(e,site.checkouts.some(c=>c.update_available)?'Review template updates':site.checkouts.some(c=>c.status==='incomplete')?'Check setup':'Update checkouts',()=>newSite(site));
 action(e,'Edit branding',()=>{page('brands');fill('brand-form',b);});return e;
 },'Your sites will appear here. Add a site to prepare its branded checkouts.');
}
function renderSiteReview(r){
 const sources=r.preview.templates||(r.preview.plans?[{template:r.preview.after,plans:r.preview.plans}]:[]);
 if(r.preview.brand)$('review-summary').append(element('p','Brand: '+r.preview.brand.name+' · '+r.preview.brand.color));
 for(const source of sources){const group=element('div',undefined,'record');group.append(element('h3',source.template.name));for(const p of source.plans){group.append(element('p',p.name+' · '+p.duration_months+' months · '+p.payment_types.map(t=>paymentNames[t]).join(' / ')));for(const sku of p.skus){const m=(state.masters||[]).find(m=>m.sku===sku);group.append(element('p',m?m.name+' · '+sku+' · '+catalogPrice(m):sku));}if(!p.skus.length)group.append(element('p','Draft: product selection needed.'));}$('review-summary').append(group);}
 if(r.result?.checkouts)for(const row of r.result.checkouts)$('review-result').append(element('p',row.status==='ready'?'Checkout ready to preview':row.reason||'Setup needs attention'));
}
$('template-new').addEventListener('click',()=>newTemplate());$('template-close').addEventListener('click',()=>$('template-editor').hidden=true);
$('template-therapy').addEventListener('change',()=>{templateRows=structuredClone((state.purchaseOptions||[]).filter(p=>p.therapy_id===$('template-therapy').value&&!p.id.startsWith('tpl-')).map(p=>({...p,enabled:true})));renderTemplateRows();});
$('template-form').addEventListener('input',updateTemplatePreview);
$('template-add-plan').addEventListener('click',()=>{templateRows.push({id:'plan-'+crypto.randomUUID().slice(0,12),name:'1-month plan',duration_months:1,skus:[],payment_types:['once','subscription']});renderTemplateRows();});
$('template-save-draft').addEventListener('click',async()=>{if(!$('template-form').reportValidity())return;const b=$('template-save-draft');b.disabled=true;try{await propose('template_editor',templatePayload(true));}catch(e){message(e.message,true,true);}finally{b.disabled=false;}});
submit('template-form',()=>templatePayload(),'template_editor');
$('site-new').addEventListener('click',()=>newSite());$('site-close').addEventListener('click',()=>$('site-editor').hidden=true);
$('site-connection').addEventListener('change',siteConnection);$('site-brand').addEventListener('change',()=>{creatingSiteBrand=!$('site-brand').value;renderSiteBrand();});
$('site-new-brand').addEventListener('click',()=>{creatingSiteBrand=true;$('site-brand').value='';renderSiteBrand();});
$('site-form').elements.routing_template_id.addEventListener('change',siteDefaults);
$('site-continue').addEventListener('click',()=>{if($('site-form').reportValidity())setSiteStep(2);});$('site-back').addEventListener('click',()=>setSiteStep(1));
$('site-form').addEventListener('submit',event=>{if(siteStep===1){event.preventDefault();event.stopImmediatePropagation();setSiteStep(2);}});
submit('site-form',()=>sitePayload(),'site');
submit('site-checkout-form',f=>({site_id:f.get('site_id'),template_id:f.get('template_id'),title:f.get('title'),purchase_option_ids:f.getAll('purchase_option_ids'),payment_types:f.getAll('payment_types'),visibility:f.get('visibility'),enabled:f.get('enabled')==='on'}),'site_checkout');

function skeletonMatrix(skeleton){
 const group=element('div');group.append(element('p','Every plan is paid in full upfront. Subscriptions renew for the full term; one-time plans end after that term.'));
 for(const months of [1,3,6,12]){
  const products=skeleton.products.filter(p=>p.duration_months===months);
  const box=card(months+'-month plan','Pay upfront · Shipment settings are saved per SKU');
  for(const p of products)box.append(element('p',p.sku+' · '+p.treatment+' · '+(p.renewal_months?'Renews every '+(months*30)+' days':'No renewal')+' · '+skeletonPrice(p)+' · '+skeletonShipments(p)));
  group.append(box);
 }
 group.append(element('p','The first shipment is at purchase. Later shipments are prepaid. Edit each SKU’s shipment count and interval in Master SKUs; renewal stays separate.','hint'));
 return group;
}
function renderTherapySkeletons(){
 list('therapy-skeleton-list',state.therapySkeletons||[],s=>{
  const box=card(s.name,'Reusable skeleton · '+s.therapy.treatments.length+' treatments · 4 durations · '+s.products.length+' SKUs');
  box.append(element('p',s.reason,'hint'));
  const details=element('details');details.append(element('summary','View all SKUs and payment rules'),skeletonMatrix(s));box.append(details);
  action(box,'Open skeleton draft',()=>{
   const saved=(state.templateDrafts||[]).find(d=>d.skeleton_id===s.id);
   const draft=structuredClone(saved||(state.skeletonDrafts||[]).find(d=>d.skeleton_id===s.id));
   if((state.therapies||[]).some(t=>t.id===draft.therapy_id))draft.new_therapy=null;
   newTemplate(draft);
  });return box;
 },'');
}
function renderSkeletonContract(){
 const target=$('template-skeleton-contract'),s=(state.therapySkeletons||[]).find(s=>s.id===templateSkeletonId);target.hidden=!s;target.replaceChildren();
 if(s){target.append(element('h3',s.name),skeletonMatrix(s));$('template-therapy').disabled=true;}
}

function skeletonPrice(product){const m=(state.masters||[]).find(m=>m.sku===product.sku);return m?catalogPrice(m):new Intl.NumberFormat('en',{style:'currency',currency:product.currency}).format(Number(product.price))+' starter upfront price';}

function skeletonShipments(p){const c=(state.masters||[]).find(m=>m.sku===p.sku)?.planning_contract||p;return c.shipments_per_term?c.shipments_per_term+' shipments per term'+(c.shipment_interval?' · Every '+c.shipment_interval+' days':' · Set interval'):'Shipment count to be set';}
