'use strict';
const $=id=>document.getElementById(id);
const titles={sites:'Sites',templates:'Checkout Templates','purchase-options':'Plans',therapies:'Therapies',overview:'Overview',master:'Master SKUs',campaigns:'Campaigns',brands:'Brands',skus:'SKU catalog',offers:'Prices & billing',links:'Checkout links',reviews:'Review queue'};
let auth={},state={brands:[],skus:[],offers:[],links:[],reviews:[]},currentReview=null;
let checkoutBrand='',activeBrand='',campaigns=[],models=[],campaignLoading=null,modelLoading=null,linkEpoch=0,lookupEpoch=0,applying=false,reviewRefreshing=false;
const pendingForms=new Set();
function message(text,error=false,focus=false){
  const box=$('message');box.textContent=text;box.hidden=!text;box.className='message'+(error?' error':'');
  if(focus&&text){box.focus({preventScroll:true});box.scrollIntoView({block:'nearest',behavior:'smooth'});}
}
function element(tag,text,className){const e=document.createElement(tag);if(text!==undefined)e.textContent=text;if(className)e.className=className;return e;}
function option(select,value,label){const o=element('option',label);o.value=value;select.append(o);}
async function api(path,body){
  const controller=new AbortController(),timer=setTimeout(()=>controller.abort(),90000);
  try{
    const r=await fetch('/api/admin/'+path,{method:body===undefined?'GET':'POST',signal:controller.signal,
      headers:body===undefined?{}:{'Content-Type':'application/json','X-CSRF-Token':auth.csrfToken||''},body:body===undefined?undefined:JSON.stringify(body)});
    let d;try{d=await r.json();}catch{throw Error('The server could not complete this request. Check the review history before retrying an approval.');}
    if(!r.ok){
      if(r.status===401&&path!=='login'){await showAuth('Your session expired. Sign in again to continue.');}
      const error=Error(typeof d.detail==='string'?d.detail:'Please check the highlighted form fields.');error.status=r.status;throw error;
    }
    return d;
  }catch(e){if(e.name==='AbortError')throw Error('This request timed out. Check the review history before retrying; a change may still be processing.');if(e instanceof TypeError)throw Error('Connection lost. Your form is preserved. Check the review history before retrying an approval.');throw e;}
  finally{clearTimeout(timer);}
}
function page(name){
  history.replaceState({},'',location.pathname+'#'+name);
  document.querySelectorAll('[data-view]').forEach(e=>e.hidden=e.dataset.view!==name);
  document.querySelectorAll('[data-page]').forEach(e=>e.classList.toggle('active',e.dataset.page===name));$('page-title').textContent=titles[name];
  $('advanced-navigation').open=!['sites','templates'].includes(name);
  if(auth.authenticated&&['sites','brands','skus','offers','links','campaigns'].includes(name))loadCampaigns().catch(e=>message(e.message,true));
  if(auth.authenticated&&name==='master'&&typeof masterPage==='function')masterPage().catch(e=>message(e.message,true));
  if(name==='links')renderCheckoutBrowser();
  if(auth.authenticated&&name==='offers')loadModels().catch(e=>message(e.message,true));
}
function list(id,records,render,empty){const e=$(id);e.replaceChildren();if(!records.length)e.append(element('div',empty,'empty'));records.forEach(r=>e.append(render(r)));}
function card(title,description){const e=element('div',undefined,'record');e.append(element('strong',title),element('p',description));return e;}
function action(parent,label,handler){const b=element('button',label,'secondary');b.type='button';b.addEventListener('click',async()=>{b.disabled=true;try{await handler();}catch(e){message(e.message,true,true);}finally{b.disabled=false;}});parent.append(b);return b;}
function selectedModels(){return Array.from($('billing-models').querySelectorAll('input:checked'),e=>Number(e.value));}
function fill(id,data){
  const form=$(id);
  Object.entries(data).forEach(([key,value])=>{
    if(['options','billing_models','configuration'].includes(key))return;
    const field=form.elements.namedItem(key);if(!field||!('value'in field))return;
    if(field.type==='checkbox')field.checked=value;else field.value=value??'';
  });
  if(id==='brand-form'){const d={...BrandDesign.defaults,...data};for(const k of Object.keys(BrandDesign.defaults))form.elements[k].value=d[k];renderBrandPreview();}
  if(id==='link-form'){renderLinkCampaigns();form.elements.campaign_id.value=data.campaign_id||state.brands.find(b=>b.id===data.brand_id)?.campaign_id||'';}
  if(id==='offer-form'){
    renderOfferCampaigns(data.campaign_id);
    form.elements.configuration.value=JSON.stringify(data.configuration||{},null,2);
    form.elements.id.value=state.offers.some(o=>o.id===data.id)?data.id:'';
    $('billing-models').querySelectorAll('input').forEach(e=>e.checked=(data.billing_models||[]).includes(Number(e.value)));
  }
  const kind=id.split('-')[0],key=kind==='sku'?'sku':'id';
  const exists=kind==='offer'?state.offers.some(o=>o.id===data.id):(state[{brand:'brands',sku:'skus',link:'links'}[kind]]||[]).some(o=>o[key]===data[key]);
  if(form.elements[key]&&kind!=='offer')form.elements[key].readOnly=exists;
  if($(kind+'-mode'))$(kind+'-mode').textContent=exists?'Edit '+({brand:'brand',sku:'SKU mapping',offer:'payment choice price and terms',link:'checkout link'}[kind]):'New '+({brand:'brand',sku:'SKU',offer:'payment choice',link:'checkout link'}[kind]);
}
function resetForm(kind){
  if(kind==='master'){resetMaster();return;}
  const form=$(kind+'-form');if(!form)return;form.reset();
  for(const key of ['id','sku'])if(form.elements[key])form.elements[key].readOnly=false;
  if(kind==='brand')renderBrandPreview();
  if(kind==='link'){form.elements.brand_id.value=activeBrand;renderLinkCampaigns();}
  if(kind==='offer'){form.elements.id.value='';renderOfferCampaigns();$('billing-models').querySelectorAll('input').forEach(e=>e.checked=false);}
  if(kind==='link'){linkEpoch++;$('link-options').replaceChildren(element('p','Choose a campaign and SKU. Billing choices load automatically.','hint'));form.elements.title.value='';form.elements.id.value='';}
  if($(kind+'-mode'))$(kind+'-mode').textContent='New '+({brand:'brand',sku:'SKU',offer:'payment choice',link:'checkout link'}[kind]);
}
function renderCampaigns(){
  document.querySelectorAll('[data-campaigns]').forEach(select=>{
    const old=select.value,query=select.id==='brand-campaign'?$('campaign-search').value.trim().toLowerCase():select.id==='setup-campaign'?$('setup-search').value.trim().toLowerCase():'';
    select.replaceChildren();option(select,'',select.id==='brand-campaign'?'Map later':'Select a campaign');
    [...new Map([...campaigns,...state.brands.flatMap(b=>brandCampaigns(b).map(id=>({id,name:b.name})))].map(c=>[c.id,c])).values()].filter(c=>!query||c.name.toLowerCase().includes(query)||String(c.id).includes(query)||String(c.id)===old).forEach(c=>option(select,c.id,c.name+' · '+c.id));
    if(old&&!Array.from(select.options).some(o=>o.value===old))option(select,old,'Campaign '+old);
    select.value=old;if(select.id==='setup-template'&&!old)select.value='422';
  });
  renderLinkCampaigns();
}
async function loadCampaigns(force=false){
  if(campaigns.length&&!force){renderCampaigns();return;}
  if(campaignLoading)return campaignLoading;
  $('load-campaigns').disabled=true;
  campaignLoading=(async()=>{const d=await api('campaigns');campaigns=d.campaigns.sort((a,b)=>a.name.localeCompare(b.name));renderCampaigns();$('load-campaigns').textContent='Refresh campaigns ('+campaigns.length+')';})();
  try{await campaignLoading;}finally{campaignLoading=null;$('load-campaigns').disabled=false;}
}
async function loadModels(force=false){
  if(models.length&&!force)return;
  if(modelLoading)return modelLoading;
  $('load-models').disabled=true;
  modelLoading=(async()=>{const checked=selectedModels(),d=await api('models');models=d.models;$('billing-models').replaceChildren();
    for(const m of models){const label=element('label',undefined,'checkbox');const input=element('input');input.type='checkbox';input.name='billing_models';input.value=m.id;input.checked=checked.includes(m.id);const text=element('span',m.id===2?'One-time purchase':m.days>0&&m.type?.id===1?'Subscription · Every '+m.days+' days':'Advanced schedule · '+m.name,'choice-label');if(m.days)text.append(element('small','Charges every '+m.days+' days'));label.append(input,text);$('billing-models').append(label);}
    $('load-models').textContent='Refresh billing options';})();
  try{await modelLoading;}finally{modelLoading=null;$('load-models').disabled=false;}
}
function render(){
  if(typeof renderSites==='function')renderSites();
  if(typeof renderTherapies==='function')renderTherapies();
  if(typeof renderMaster==='function')renderMaster();
  if(!activeBrand&&state.brands.length===1)activeBrand=state.brands[0].id;
  renderSetup();
  $('owner-email').textContent=state.owner||'';$('review-count').textContent=state.reviews.filter(r=>r.status==='draft').length||'';
  $('metrics').replaceChildren();
  [['Brands',state.brands.length],['Stable SKUs',state.skus.length],['Checkout links',state.links.length],['Pending reviews',state.reviews.filter(r=>r.status==='draft').length]].forEach(([name,count])=>{const e=element('div',undefined,'metric');e.append(element('span',name),element('strong',String(count)));$('metrics').append(e);});
  document.querySelectorAll('[data-brands]').forEach(select=>{const old=select.value;select.replaceChildren();option(select,'','Select a brand');state.brands.forEach(b=>option(select,b.id,b.name));select.value=old||(['setup-brand','link-brand'].includes(select.id)?activeBrand:'');});
  renderLinkCampaigns();renderOfferCampaigns();
  document.querySelectorAll('[data-skus]').forEach(select=>{const old=select.value;select.replaceChildren();option(select,'','Select a SKU');state.skus.forEach(s=>option(select,s.sku,s.name+' · '+s.sku));select.value=old;});
  renderBrands();
  if(typeof renderSiteBrand==='function')renderSiteBrand();
  list('sku-list',state.skus,s=>{const e=card(s.name,s.sku+' · Source product '+s.product_id);action(e,'Edit mapping',()=>fill('sku-form',s));return e;},'Find a product by brand and SKU, then approve its catalog mapping.');
  renderCheckoutBrowser();
  list('managed-offers',state.offers,o=>{const brand=state.brands.find(b=>b.id===o.brand_id),e=card(o.name,(brand?.name||o.brand_id)+' · Campaign '+(o.campaign_id||brand?.campaign_id)+' · '+o.sku+' · '+o.price);action(e,'Edit price and terms',async()=>{await loadModels();fill('offer-form',o);});return e;},'New brand offers appear here after approval. Existing Sticky offers can be inspected and used on checkout links.');
  list('review-list',state.reviews,r=>{const e=card(r.kind.charAt(0).toUpperCase()+r.kind.slice(1)+' change · '+(r.preview.after?.name||r.preview.after?.title||r.preview.after?.sku||''),r.status+' · '+new Date(r.created*1000).toLocaleString());if(r.result&&Object.keys(r.result.created||{}).length)e.append(element('p','Recorded Sticky objects: '+JSON.stringify(r.result.created)));action(e,r.status==='draft'?'Open review':'View details',()=>showReview(r));return e;},'Changes appear here once you prepare a preview.');
}
async function refresh(){state=await api('state');state.offers||=[];render();}
const fieldNames={id:'Identifier',name:'Name',category:'Checkout category',product_duration_months:'Product duration',campaign_id:'Sticky campaign',brand_id:'Brand',sku:'SKU',product_id:'Source product',price:'Price',billing_models:'Billing options',configuration:'Offer settings',logo_url:'Logo',color:'Brand color',support_email:'Support email',support_phone:'Support phone',custom_domain:'Custom domain',title:'Checkout title',visibility:'Access',options:'Customer choices',enabled:'Active',offers:'Payment choices',skus:'Master SKUs',currency:'Price currency',assigned_skus:'Assigned SKUs',billing_terms:'Verified billing intervals'};
function display(key,value){
  if(value===null||value===undefined||value==='')return '—';
  if(key==='therapy_id')return (state.therapies||[]).find(t=>t.id===value)?.name||String(value);
  if(key==='treatment_id')return (state.therapies||[]).flatMap(t=>t.treatments).find(t=>t.id===value)?.name||String(value);
  if(key==='purchase_option_ids')return value.map(id=>(state.purchaseOptions||[]).find(p=>p.id===id)?.name||id).join('\n');
  if(key==='payment_types')return value.map(t=>({once:'One-time purchase',subscription:'Subscription',prepaid:'Pay upfront'}[t])).join(', ');
  if(key==='purchase_options')return value.map(p=>p.name+' · '+p.duration_months+' months · '+p.skus.join(', ')).join('\n');
  if(key==='duration_months')return value+' months';
  if(key==='treatments')return value.map(t=>t.name).join(', ');
  if(key==='entries')return value.map(e=>e.sku+' · '+e.options.length+' enabled purchase options').join('\n');
  if(key==='product_duration_months')return value+'-month product';
  if(key==='brand_id')return state.brands.find(b=>b.id===value)?.name||String(value);
  if(key==='billing_terms')return Object.entries(value).map(([id,t])=>'Model '+id+': '+(t.days?'every '+t.days+' days':'one-time')).join('\n');
  if(key==='offers'&&Array.isArray(value)&&value.every(o=>o&&typeof o==='object'&&Array.isArray(o.billing_models)))return value.map(o=>masterPlanLabel(o)+' · '+o.price+(o.prepaid_cycles?' upfront':' per payment')).join('\n');
  if(key==='billing_models')return value.map(id=>purchaseSchedule(id)).join('\n');
  if(typeof value==='boolean')return value?'Yes':'No';
  if(typeof value==='object')return JSON.stringify(value,null,2);
  return String(value);
}
function showReview(r){
  currentReview=r;$('current-review').hidden=false;const draft=r.status==='draft';
  $('review-preview').textContent=JSON.stringify(r.preview,null,2);$('review-consent').checked=false;$('review-consent').disabled=applying||reviewRefreshing;$('review-consent-label').hidden=!draft;
  for(const id of ['apply-review','refresh-review','discard-review']){$(id).hidden=!draft;$(id).disabled=applying||reviewRefreshing;}
  $('review-summary').replaceChildren();$('review-result').replaceChildren();
  const writes=r.preview.stickyWrites||[];
  $('review-summary').append(element('p',writes.length?writes.length+' catalog updates require your approval.':'This change updates checkout configuration only. No Sticky records will be changed.','status-note'));
  if(r.preview.impact)$('review-summary').append(element('p',r.preview.impact));
  if(r.preview.readinessNote)$('review-summary').append(element('p',r.preview.readinessNote,'readiness-warning'));
  const before=r.preview.before||{},after=r.preview.after||{},table=element('table',undefined,'change-table');
  const head=element('tr');['Setting','Current','Proposed'].forEach(t=>head.append(element('th',t)));table.append(head);
  Object.keys(after).filter(k=>!['revision','billing_terms','product_template'].includes(k)).forEach(k=>{if(JSON.stringify(before[k])===JSON.stringify(after[k]))return;const row=element('tr');row.append(element('td',fieldNames[k]||k.replaceAll('_',' ')),element('td',display(k,before[k])),element('td',display(k,after[k])));table.append(row);});
  $('review-summary').append(table);
  if(after.product_template){const p=after.product_template;$('review-summary').append(element('p','Fulfillment defaults: '+(p.is_shippable?'Requires shipping':'No shipping')+' · '+(p.is_taxable?'Taxable':'Not taxable')+' · Category '+p.category_id+' · Maximum quantity '+p.max_quantity,'status-note'));}
  if(typeof renderSiteReview==='function')renderSiteReview(r);
  if(r.preview.entries&&typeof renderMasterEntries==='function')renderMasterEntries(r.preview.entries,$('review-summary'));
  if(r.preview.affectedCheckoutLinks?.length)$('review-summary').append(element('p','Checkout links that will change: '+r.preview.affectedCheckoutLinks.join(', ')));
  if(r.status==='reconcile')$('review-result').append(element('p','This change needs reconciliation. The recorded object IDs are shown below; do not submit it again.','readiness-warning'));
  if(r.result&&Object.keys(r.result.created||{}).length){const ids=Object.entries(r.result.created).map(([kind,id])=>kind.charAt(0).toUpperCase()+kind.slice(1)+' '+id);$('review-result').append(element('p','Recorded Sticky objects: '+ids.join(' · '),'status-note'));}
  if(r.status==='applied'){
    const next={site:['sites','Open site checkouts'],site_checkout:['sites','Open site checkouts'],checkout_template:['sites','Add a site'],therapy:['purchase-options','Create purchase options'],purchase_option:['links','Build a checkout'],plan_checkout:['links','Open plan checkouts'],brand:['campaigns','Manage brand campaigns'],sku:['offers','Continue to offers'],offer:['links','Configure checkout link'],link:['links','Open checkout links'],campaign:['master','Apply master to this campaign'],master:['campaigns','Assign SKUs to a campaign'],provision:['links','Copy checkout links'],campaign_setup:['links','Copy checkout links']}[r.kind];
    if(next)action($('review-result'),next[1],()=>page(next[0]));
    if(r.result?.validation&&typeof renderMasterValidation==='function')renderMasterValidation(r.result.validation,$('review-result'));
  }
  page('reviews');window.scrollTo({top:0,behavior:'smooth'});
}
async function propose(kind,data){message('Preparing your change preview…');const r=await api('reviews',{kind,data});await refresh();showReview({...r,kind,status:'draft'});message('Preview ready. Review the changes and approve when you are satisfied.');}
function submit(id,build,kind){$(id).addEventListener('submit',async event=>{event.preventDefault();if(pendingForms.has(id))return;pendingForms.add(id);const button=event.target.querySelector('button[type=submit],button:last-child'),label=button.textContent;button.disabled=true;button.textContent='Preparing preview…';try{await propose(kind,await build(new FormData(event.target)));}catch(e){message(e.message,true,true);}finally{pendingForms.delete(id);button.disabled=false;button.textContent=label;}});}
async function apiAuth(){const r=await fetch('/api/admin/auth');if(!r.ok)throw Error('Unable to reach admin authentication. Refresh and try again.');return r.json();}
async function showAuth(note=''){
  auth=await apiAuth();$('auth-password').type=$('password-confirm').type='password';$('show-password').checked=false;$('workspace').hidden=true;$('auth').hidden=false;const setup=!auth.configured;
  $('auth-title').textContent=setup?'Set up your owner account.':'Welcome back.';$('auth-description').textContent=setup?(auth.canSetup?'Choose your owner email and password.':'Open your private owner setup link to create this account. If it expired, request a fresh setup link.'):'Sign in to manage your brands, catalog and checkouts.';
  $('auth-password').minLength=setup?12:1;$('auth-password').autocomplete=setup?'new-password':'current-password';$('password-confirm-label').hidden=!setup;$('password-confirm').required=setup;$('password-hint').hidden=!setup;
  $('auth-submit').textContent=setup?'Create owner account':'Sign in';$('auth-submit').disabled=setup&&!auth.canSetup;$('auth-message').textContent=note;
}
async function enter(){auth=await apiAuth();if(!auth.authenticated){await showAuth();return;}await refresh();const requested=location.hash.slice(1);page(Object.hasOwn(titles,requested)?requested:'sites');$('auth').hidden=true;$('workspace').hidden=false;}
$('auth-form').addEventListener('submit',async event=>{event.preventDefault();if(pendingForms.has('auth'))return;const setup=!auth.configured;if(setup&&$('auth-password').value!==$('password-confirm').value){$('auth-message').textContent='The passwords do not match.';$('password-confirm').focus();return;}pendingForms.add('auth');$('auth-submit').disabled=true;$('auth-message').textContent='';try{await api(setup?'setup':'login',Object.fromEntries(new FormData(event.target)));event.target.reset();await enter();}catch(e){$('auth-message').textContent=e.message;}finally{pendingForms.delete('auth');$('auth-submit').disabled=!auth.configured&&!auth.canSetup;}});
$('show-password').addEventListener('change',event=>{for(const id of ['auth-password','password-confirm'])$(id).type=event.target.checked?'text':'password';});
$('logout').addEventListener('click',async()=>{try{await api('logout',{});for(const kind of ['brand','sku','offer','link','master','provision'])resetForm(kind);activeBrand='';checkoutBrand='';state={brands:[],skus:[],offers:[],links:[],reviews:[],masters:[],assignments:[]};$('master-validation').replaceChildren();render();$('current-review').hidden=true;currentReview=null;message('');$('auth-form').reset();await showAuth();}catch(e){message(e.message,true,true);}});
$('logout-mobile').addEventListener('click',()=>$('logout').click());
$('refresh-workspace').addEventListener('click',async event=>{event.target.disabled=true;try{await refresh();message('Workspace refreshed.');}catch(e){message(e.message,true,true);}finally{event.target.disabled=false;}});
document.querySelectorAll('[data-page]').forEach(b=>b.addEventListener('click',()=>page(b.dataset.page)));document.querySelectorAll('[data-go]').forEach(b=>b.addEventListener('click',()=>page(b.dataset.go)));document.querySelectorAll('[data-new]').forEach(b=>b.addEventListener('click',()=>resetForm(b.dataset.new)));
document.querySelectorAll('form').forEach(f=>f.addEventListener('invalid',e=>{const details=e.target.closest('details');if(details)details.open=true;},true));
submit('brand-form',f=>{const d=Object.fromEntries(f);if(!d.id)d.id=brandSlug(d.name);return {...d,campaign_id:d.campaign_id?Number(d.campaign_id):null};},'brand');
submit('sku-form',f=>({...Object.fromEntries(f),product_id:Number(f.get('product_id'))}),'sku');
submit('offer-form',f=>{const ids=f.getAll('billing_models').map(Number);if(!ids.length)throw Error('Choose at least one billing option.');let config;try{config=JSON.parse(f.get('configuration')||'{}');}catch{throw Error('Advanced offer settings must be valid JSON. Your form has been preserved.');}return {...Object.fromEntries(f),name:f.get('name').trim()||ids.map(id=>purchaseSchedule(id)).join(' / ').slice(0,150),id:f.get('id')||null,campaign_id:f.get('campaign_id')?Number(f.get('campaign_id')):null,billing_models:ids,configuration:config};},'offer');
const numericIds=value=>{const values=value.split(',').map(v=>v.trim());if(values.some(v=>!/^\d+$/.test(v)||Number(v)<1))throw Error('Use comma-separated positive IDs in the payment and routing settings.');return values.map(Number);};
submit('campaign-form',f=>{const d=Object.fromEntries(f);return {...d,gateway_id:Number(d.gateway_id),channel_id:Number(d.channel_id),offers:numericIds(d.offers),countries:numericIds(d.countries),shipping_profiles:numericIds(d.shipping_profiles)};},'campaign');
submit('link-form',f=>{const d=Object.fromEntries(f);delete d.option;const selected=f.getAll('option');if(!selected.length)throw Error('Load offers and choose at least one customer billing option.');d.campaign_id=Number(d.campaign_id);return {...d,options:selected,enabled:f.get('enabled')==='on'};},'link');
$('campaign-search').addEventListener('input',renderCampaigns);$('load-campaigns').addEventListener('click',()=>loadCampaigns(true).catch(e=>message(e.message,true,true)));$('load-models').addEventListener('click',()=>loadModels(true).catch(e=>message(e.message,true,true)));
$('use-campaign-template').addEventListener('click',async event=>{const id=$('campaign-source').value;if(!id){message('Select a campaign to copy settings from.',true,true);return;}event.target.disabled=true;try{const d=await api('campaign-template?campaign_id='+encodeURIComponent(id)),form=$('campaign-form');for(const key of ['gateway_id','channel_id','offers','countries','shipping_profiles'])form.elements[key].value=Array.isArray(d[key])?d[key].join(', '):d[key]??'';$('campaign-template-note').textContent=d.description;if(!d.gateway_id)message('This campaign has no Stripe Connect v2 mapping. Select a valid v2 profile in payment settings.',true,true);else message('Campaign settings loaded. Review the values before creating the new campaign.');}catch(e){message(e.message,true,true);}finally{event.target.disabled=false;}});
$('lookup-products').addEventListener('click',async event=>{const brand=state.brands.find(b=>b.id===$('lookup-brand').value),sku=$('lookup-sku').value.trim();if(!brand?.campaign_id||!sku){message('Choose a mapped brand and enter the exact SKU.',true,true);return;}const epoch=++lookupEpoch;event.target.disabled=true;$('lookup-results').replaceChildren(element('p','Looking up matching products…','hint'));try{const c=await api('inspect?'+new URLSearchParams({campaign_id:brand.campaign_id,sku}));if(epoch!==lookupEpoch)return;$('lookup-results').replaceChildren();for(const o of new Map(c.options.map(o=>[o.productId,o])).values()){const e=card(o.name,'Product '+o.productId+' · Base price '+(o.upfrontPrice||o.basePrice)+' '+(c.currency||''));action(e,'Use this product',()=>{resetForm('sku');fill('sku-form',{sku,name:o.name,product_id:o.productId});message('Product selected. Review the SKU mapping to add it to your catalog.');});$('lookup-results').append(e);}}catch(e){if(epoch===lookupEpoch){$('lookup-results').replaceChildren(element('p',e.message,'hint'));message(e.message,true,true);}}finally{event.target.disabled=false;}});
for(const id of ['lookup-brand','lookup-sku'])$(id).addEventListener('input',()=>{lookupEpoch++;$('lookup-results').replaceChildren();});
function optionChoices(c,selected=[]){
  const target=$('link-options');target.replaceChildren();if(c.blockedReason)target.append(element('p',c.blockedReason,'readiness-warning'));
  for(const o of c.options){const label=element('label',undefined,'checkbox'),input=element('input');input.type='checkbox';input.name='option';input.value=o.key;input.checked=selected.includes(o.key);input.dataset.blocked=o.blockedReason||c.blockedReason||'';const text=element('span',(o.blockedReason?'Additional setup needed · '+o.offerName:o.prepaidCycles?'Pay upfront · '+o.prepaidCycles+' shipments every '+o.days+' days · No renewal':o.recurring?'Subscription · Every '+o.days+' days':'One-time purchase')+' · '+(o.upfrontPrice||o.basePrice)+' '+(c.currency||''),'choice-label');text.append(element('small',o.name));if(input.dataset.blocked)text.append(element('small','Not ready for online payment: '+input.dataset.blocked));label.append(input,text);target.append(label);}
  updateOptionAvailability();
}
function updateOptionAvailability(){const active=$('link-form').elements.enabled.checked;$('link-options').querySelectorAll('input').forEach(e=>e.disabled=active&&!!e.dataset.blocked);}
async function loadLinkOptions(selected=null){const form=$('link-form'),brand=selectedLinkCampaign(),sku=form.elements.sku.value;if(!brand?.campaign_id||!sku)throw Error('Select a campaign and SKU first.');const epoch=++linkEpoch;if(!brand.id||!brand.campaign_ids.includes(brand.campaign_id)){$('link-options').replaceChildren(element('p','Attach this campaign to your brand before creating its checkout link.','hint'));$('link-assign-master').hidden=!brand.id;return;}$('link-options').replaceChildren(element('p','Loading customer offer choices…','hint'));$('link-assign-master').hidden=true;try{const c=await api('inspect?'+new URLSearchParams({campaign_id:brand.campaign_id,sku}));if(epoch!==linkEpoch)return;optionChoices(c,selected===null?defaultLinkChoices(brand,sku,c):selected);}catch(e){if(epoch!==linkEpoch)return;$('link-options').replaceChildren(element('p',e.message,'hint'));$('link-assign-master').hidden=!(state.masters||[]).some(m=>m.sku===sku&&m.enabled);throw e;}}
$('load-link-options').addEventListener('click',async event=>{event.target.disabled=true;try{await loadLinkOptions();}catch(e){message(e.message,true,true);}finally{event.target.disabled=false;}});
for(const field of ['brand_id','campaign_id','sku'])$('link-form').elements[field].addEventListener('change',()=>{linkEpoch++;if(field==='brand_id'){activeBrand=$('link-brand').value;renderLinkCampaigns(true);}$('link-assign-master').hidden=true;$('link-options').replaceChildren();autoLink().catch(e=>message(e.message,true,true));});$('link-form').elements.enabled.addEventListener('change',updateOptionAvailability);
$('inspect-form').addEventListener('submit',async event=>{event.preventDefault();const button=event.target.querySelector('button');button.disabled=true;try{const c=await api('inspect?'+new URLSearchParams(Object.fromEntries(new FormData(event.target))));$('inspected-offers').replaceChildren();for(const o of c.options){const e=card(o.offerName,o.modelName+' · Product '+o.productId+' · Base price '+(o.upfrontPrice||o.basePrice)+' '+(c.currency||''));if(o.blockedReason)e.append(element('p',o.blockedReason,'readiness-warning'));$('inspected-offers').append(e);}message(c.blockedReason||'Configured offers loaded.',!!c.blockedReason);}catch(e){message(e.message,true,true);}finally{button.disabled=false;}});
$('refresh-review').addEventListener('click',async()=>{if(!currentReview||applying||reviewRefreshing)return;reviewRefreshing=true;for(const id of ['apply-review','refresh-review','discard-review','review-consent'])$(id).disabled=true;try{const r=await api('reviews/'+encodeURIComponent(currentReview.id)+'/refresh',{});await refresh();showReview(r);message('Preview refreshed using current configuration.');}catch(e){message(e.message,true,true);}finally{reviewRefreshing=false;$('review-consent').disabled=false;for(const id of ['apply-review','refresh-review','discard-review'])$(id).disabled=currentReview?.status!=='draft';}});
$('discard-review').addEventListener('click',async()=>{if(!currentReview||applying||reviewRefreshing)return;try{await api('reviews/'+encodeURIComponent(currentReview.id)+'/discard',{});$('current-review').hidden=true;currentReview=null;await refresh();message('Draft discarded. No changes were applied.');}catch(e){message(e.message,true,true);}});
$('apply-review').addEventListener('click',async()=>{
  if(!currentReview||applying||reviewRefreshing||currentReview.status!=='draft')return;if(!$('review-consent').checked){message('Confirm that you approve the displayed change.',true,true);return;}
  applying=true;const review=currentReview;for(const id of ['apply-review','refresh-review','discard-review'])$(id).disabled=true;$('apply-review').textContent='Applying changes…';
  try{const result=await api('apply',{review_id:review.id,approve:true});if(review.kind==='brand')activeBrand=review.preview.after.id;await refresh();resetForm(review.kind);if(review.kind==='campaign_setup'){const selectedBrand=$('setup-brand').value;$('setup-form').reset();$('setup-brand').value=selectedBrand||activeBrand;$('setup-mode').dispatchEvent(new Event('change'));renderCampaigns();$('setup-campaign').value=String(result.validation?.campaign_id||'');}showReview({...review,status:'applied',result});message(result.validation&&!result.validation.ready?'Configuration applied. Some checkout checks need attention; see the results below.':'Change applied and verified.',false,true);}
  catch(e){try{await refresh();const latest=state.reviews.find(r=>r.id===review.id);if(latest&&location.hash==='#reviews')showReview(latest);}catch{}message(e.message,true,true);}
  finally{applying=false;$('review-consent').disabled=false;$('apply-review').textContent='Approve and apply changes';for(const id of ['apply-review','refresh-review','discard-review'])$(id).disabled=currentReview?.status!=='draft';}
});
function brandCampaigns(brand){return [...new Set([brand?.campaign_id,...(brand?.campaign_ids||[])].filter(Boolean))];}
function renderLinkCampaigns(reset=false){
 const select=$('link-campaign'),brand=state.brands.find(b=>b.id===$('link-brand').value),old=reset?'':select.value;select.replaceChildren();option(select,'','Select a campaign');
 const rows=[...new Map([...campaigns,...state.brands.flatMap(b=>brandCampaigns(b).map(id=>({id,name:b.name})))].map(c=>[c.id,c])).values()];
 for(const c of rows)option(select,c.id,c.name+' · '+c.id+(brand&&!brandCampaigns(brand).includes(c.id)?' (attach to brand)':''));
 select.value=old;if(!select.value&&brandCampaigns(brand).length===1)select.value=String(brandCampaigns(brand)[0]);
 $('link-campaign-status').textContent=rows.length?rows.length+' accessible campaigns. Attached campaigns inherit your brand design.':'No campaigns loaded yet. Use Refresh campaigns to try again.';
 $('link-brand-design').textContent=brand?'Uses '+brand.name+'’s saved logo, colors, font and layout.':'Choose the brand whose design this checkout should use.';
}
function selectedLinkCampaign(){const cid=Number($('link-campaign').value),brand=state.brands.find(b=>b.id===$('link-brand').value);return cid?{...brand,campaign_ids:brandCampaigns(brand),campaign_id:cid}:null;}
$('refresh-link-campaigns').addEventListener('click',async event=>{event.target.disabled=true;$('link-campaign-status').textContent='Loading campaigns…';try{await loadCampaigns(true);}catch(e){$('link-campaign-status').textContent=e.message;message(e.message,true,true);}finally{event.target.disabled=false;}});
$('link-assign-master').addEventListener('click',async()=>{try{const brand=selectedLinkCampaign();if(!brand)return;await loadCampaigns();page('campaigns');$('setup-mode').value='existing';$('setup-mode').dispatchEvent(new Event('change'));$('setup-brand').value=brand.id||activeBrand;$('setup-campaign').value=String(brand.campaign_id);}catch(e){message(e.message,true,true);}});
function linkPayload(link,changes={}){return Object.fromEntries(['id','brand_id','campaign_id','sku','title','visibility','options','enabled'].map(k=>[k,link[k]]).concat(Object.entries(changes)));}
function defaultLinkChoices(brand,sku,catalog){
 const a=(state.assignments||[]).find(a=>a.brand_id===brand.id&&a.campaign_id===brand.campaign_id&&a.sku===sku);
 const managed=a?.offers.flatMap(slot=>{const o=state.offers.find(o=>o.id===slot.id)||slot;return o.billing_models.map(mid=>o.offer_id+':'+o.product_id+':'+mid);});
 return catalog.options.filter(o=>!o.blockedReason&&!catalog.blockedReason&&(!managed||managed.includes(o.key))).map(o=>o.key);
}
async function autoLink(){
 const f=$('link-form'),brand=selectedLinkCampaign(),sku=f.elements.sku.value;
 if(!brand||!sku)return;
 if(!f.elements.id.readOnly){f.elements.title.value=(state.skus.find(s=>s.sku===sku)?.name||sku);f.elements.id.value=('checkout-'+brand.campaign_id+'-'+sku.toLowerCase().replace(/[^a-z0-9]+/g,'-')).slice(0,65)+'-'+crypto.randomUUID().slice(0,8);}
 await loadLinkOptions();
}
function renderSetup(){
 const masters=(state.masters||[]).filter(m=>m.enabled),summary=$('setup-catalog');summary.replaceChildren(element('strong',masters.length+' master SKU'+(masters.length===1?'':'s')+' included'));
 for(const m of masters)summary.append(element('p',m.sku+' · '+m.offers.map(o=>o.price+' '+m.currency+' / '+o.billing_models.length+' purchase options').join(' · ')));
 if(!masters.length)action(summary,'Add your first master SKU',()=>page('master'));
 $('setup-form').querySelector('button[type=submit]').disabled=!masters.length;
 list('setup-list',state.brands.flatMap(b=>brandCampaigns(b).map(cid=>({...b,campaign_id:cid}))),b=>{
  const assigned=(state.assignments||[]).filter(a=>a.brand_id===b.id&&a.campaign_id===b.campaign_id),e=card(b.name,'Campaign '+b.campaign_id+' · '+assigned.length+' master SKUs assigned');
  action(e,'Assign all master SKUs',()=>propose('campaign_setup',{brand_id:b.id,campaign_id:b.campaign_id}));
  action(e,'Checkout links',()=>{openBrandCheckouts(b.id);$('link-form').elements.campaign_id.value=String(b.campaign_id);$('link-list').scrollIntoView({block:'start'});});
  return e;
 },'Select an existing campaign or create a new one to assign your catalog.');
}
$('setup-mode').addEventListener('change',()=>{const creating=$('setup-mode').value==='new',f=$('setup-form');$('setup-existing').hidden=creating;$('setup-new').hidden=!creating;f.elements.campaign_id.required=!creating;f.elements.name.required=creating;f.elements.template_id.required=creating;});
$('setup-search').addEventListener('input',renderCampaigns);
submit('setup-form',f=>f.get('mode')==='new'?{brand_id:f.get('brand_id'),name:f.get('name'),template_id:Number(f.get('template_id'))}:{brand_id:f.get('brand_id'),campaign_id:Number(f.get('campaign_id'))},'campaign_setup');
function brandSlug(name){return (name.toLowerCase().replace(/[^a-z0-9]+/g,'-').replace(/^-|-$/g,'').slice(0,45)||'brand')+'-'+crypto.randomUUID().slice(0,6);}
function chooseBrand(id){activeBrand=id;$('setup-brand').value=id;$('link-brand').value=id;renderLinkCampaigns(true);}
function renderBrandPreview(){const f=$('brand-form'),b=Object.fromEntries(new FormData(f));BrandDesign.apply($('brand-preview'),b);$('preview-name').textContent=b.name||'Your brand';$('preview-support').textContent=[b.support_email,b.support_phone].filter(Boolean).join(' · ');const logo=$('preview-logo');logo.hidden=!b.logo_url;if(/^https:\/\//.test(b.logo_url))logo.src=b.logo_url;else logo.removeAttribute('src');}
function renderBrands(){list('brand-list',state.brands,b=>{const ids=brandCampaigns(b),e=card(b.name,ids.length+' campaign'+(ids.length===1?'':'s')+' · '+(state.links.filter(l=>l.brand_id===b.id).length+(state.planCheckouts||[]).filter(p=>p.brand_id===b.id).length)+' checkout links');const swatch=element('span',b.color||'#245844','brand-swatch');swatch.style.borderColor=b.color||'#245844';e.append(swatch);if(ids.length)e.append(element('p','Campaigns: '+ids.join(', ')));if(b.custom_domain)e.append(element('p',b.custom_domain+' · DNS/HTTPS pending'));action(e,'Edit brand',async()=>{fill('brand-form',b);$('brand-form').scrollIntoView({block:'start'});await loadCampaigns();});action(e,'Manage campaigns',()=>{chooseBrand(b.id);page('campaigns');});action(e,'Checkout links',()=>{openBrandCheckouts(b.id);});return e;},'Create your first brand. Its design will be shared by every campaign and checkout link.');}
$('brand-form').addEventListener('input',()=>{const f=$('brand-form');if(!f.elements.id.readOnly&&!f.elements.id.value&&f.elements.name.value)f.elements.id.value=brandSlug(f.elements.name.value);renderBrandPreview();});
$('brand-form').addEventListener('change',renderBrandPreview);
$('setup-brand').addEventListener('change',()=>{activeBrand=$('setup-brand').value;});
renderBrandPreview();
enter().catch(e=>{$('auth').hidden=false;$('auth-message').textContent=e.message;});

function renderOfferCampaigns(selected){const f=$('offer-form'),b=state.brands.find(b=>b.id===f.elements.brand_id.value),old=selected??f.elements.campaign_id.value;f.elements.campaign_id.replaceChildren();option(f.elements.campaign_id,'','Select a campaign');for(const cid of brandCampaigns(b))option(f.elements.campaign_id,cid,(campaigns.find(c=>c.id===cid)?.name||'Campaign')+' · '+cid);f.elements.campaign_id.value=String(old||b?.campaign_id||'');}
$('offer-form').elements.brand_id.addEventListener('change',()=>renderOfferCampaigns(null));

function checkoutCard(l){const e=card(l.title,(state.brands.find(b=>b.id===l.brand_id)?.name||l.brand_id)+' · Campaign '+(l.campaign_id||state.brands.find(b=>b.id===l.brand_id)?.campaign_id)+' · '+l.sku+' · '+l.visibility+' · '+(l.enabled?'Active':'Inactive'));const actions=element('div',undefined,'actions');
    if(l.enabled){const a=element('a','Open checkout ↗');a.href=l.url;a.target='_blank';a.rel='noopener noreferrer';actions.append(a);}
    action(actions,'Copy link',async()=>{try{await navigator.clipboard.writeText(l.url);message('Link copied.'+(l.visibility==='private'?' Keep this invitation private.':''));}catch{const input=element('input');input.readOnly=true;input.value=l.url;input.setAttribute('aria-label','Checkout URL');e.append(input);input.focus();input.select();message('Select and copy the URL shown under this link.');}});
    action(actions,'Edit link',async()=>{fill('link-form',l);await loadLinkOptions(l.options);});action(actions,l.visibility==='private'?'Make public':'Make private',()=>propose('link',linkPayload(l,{visibility:l.visibility==='private'?'public':'private'})));e.append(actions);return e;}

function categoryForLink(link){return (state.masters||[]).find(m=>m.sku===link.sku)?.category?.trim()||'Uncategorized';}
function openBrandCheckouts(id){checkoutBrand=id;chooseBrand(id);resetForm('link');page('links');}
function renderCheckoutBrowser(){
 const brand=state.brands.find(b=>b.id===checkoutBrand);
 if(typeof renderPlans==='function')renderPlans();
 $('checkout-brand-directory').hidden=!!brand;$('brand-checkout-workspace').hidden=!brand;
 list('checkout-brand-list',state.brands,b=>{const links=state.links.filter(l=>l.brand_id===b.id),cats=new Set(links.map(categoryForLink)),e=card(b.name,(links.length+(state.planCheckouts||[]).filter(p=>p.brand_id===b.id).length)+' checkout links · '+cats.size+' categories');const swatch=element('p','Saved brand color: '+(b.color||'#245844'),'brand-swatch');swatch.style.borderColor=b.color||'#245844';e.append(swatch);const button=action(e,'View checkouts →',()=>openBrandCheckouts(b.id));button.dataset.brandOpen=b.id;button.setAttribute('aria-label','View '+b.name+' checkouts');return e;},'Create a brand to organize its checkout links.');
 if(!brand){$('link-list').replaceChildren();return;}
 $('checkout-brand-name').textContent=brand.name;
 $('checkout-brand-theme').textContent='All links here use '+brand.name+'’s saved design · '+(brand.color||'#245844');
 const links=state.links.filter(l=>l.brand_id===brand.id),groups=new Map();
 for(const link of links){const category=categoryForLink(link);if(!groups.has(category))groups.set(category,[]);groups.get(category).push(link);}
 const target=$('link-list');target.replaceChildren();
 for(const category of [...groups.keys()].sort((a,b)=>a==='Uncategorized'?1:b==='Uncategorized'?-1:a.localeCompare(b))){const group=element('section',undefined,'checkout-category');group.dataset.category=category;group.append(element('h3',category+' · '+groups.get(category).length));for(const link of groups.get(category))group.append(checkoutCard(link));target.append(group);}
 if(!links.length)target.append(element('p','No checkout links for this brand yet. Assign its master catalog to a campaign, or create a link here.','empty'));
}
$('checkout-all-brands').addEventListener('click',()=>{checkoutBrand='';renderCheckoutBrowser();});
$('checkout-edit-design').addEventListener('click',()=>{const b=state.brands.find(b=>b.id===checkoutBrand);if(b){page('brands');fill('brand-form',b);$('brand-form').scrollIntoView({block:'start'});}});
$('link-brand').addEventListener('change',()=>{if($('link-brand').value){checkoutBrand=$('link-brand').value;renderCheckoutBrowser();}});
