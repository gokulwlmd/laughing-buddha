'use strict';
const $=id=>document.getElementById(id),make=(tag,text)=>{const e=document.createElement(tag);if(text!==undefined)e.textContent=text;return e;};
const planId=decodeURIComponent(location.pathname.split('/')[2]);let data,groups=[],group=null,product=null,payment=null;
function treatmentName(entry){return data.treatments.find(t=>t.id===entry.treatmentId)?.name||'Your treatment';}
function money(option,entry){return new Intl.NumberFormat('en',{style:'currency',currency:entry.currency}).format(Number(option.upfrontPrice||option.basePrice));}
function recurring(o){return o.prepaidCycles?Boolean(o.renewal):Boolean(o.recurring);}
function paymentTitle(o){return recurring(o)?'Subscription':'One-time purchase';}
function paymentTerms(o,entry){const amount=money(o,entry);return o.prepaidCycles?`${amount} upfront. ${o.prepaidCycles} scheduled deliveries, ${o.days} days apart. ${o.renewal?`Renews every ${o.renewalDays} days for the full plan price.`:'No automatic renewal.'}`:o.recurring?`${amount} per payment. Renews every ${o.days} days.`:`${amount} upfront. One payment, no automatic renewal.`;}
function treatments(g){const map=new Map();for(const entry of g.entries){const key=entry.treatmentId||entry.sku;if(!map.has(key))map.set(key,{id:key,name:treatmentName(entry),entries:[],choices:[]});const treatment=map.get(key);treatment.entries.push(entry);if(entry.available)for(const option of entry.options)treatment.choices.push({option,entry});}return [...map.values()];}
function priceSummary(t){if(!t.choices.length)return 'Temporarily unavailable';const prices=[...new Set(t.choices.map(c=>money(c.option,c.entry)))];if(prices.length===1)return prices[0]+' upfront';return t.choices.map(c=>money(c.option,c.entry)+' '+(recurring(c.option)?'subscription':'one-time')).filter((v,i,a)=>a.indexOf(v)===i).join(' / ');}
function tile(title,detail,selected,handler,disabled=false){const button=make('button');button.type='button';button.setAttribute('aria-pressed',String(selected));button.disabled=disabled;button.append(make('strong',title));if(detail)button.append(make('span',detail));button.addEventListener('click',handler);return button;}
function medicationList(){const map=new Map();for(const g of groups)for(const t of treatments(g)){if(!map.has(t.id))map.set(t.id,{id:t.id,name:t.name,available:false});if(t.choices.length)map.get(t.id).available=true;}return [...map.values()];}
let medication=null;
function moveTo(id){const target=$(id);target.querySelector('h2').focus({preventScroll:true});target.scrollIntoView({block:'nearest',behavior:'instant'});}
function render(){
 const list=$('treatments');list.replaceChildren();
 for(const t of medicationList())list.append(tile(t.name,'',medication?.id===t.id,()=>{if(medication?.id===t.id)return;medication=t;group=null;product=null;payment=null;render();moveTo('duration-step');},!t.available));
 $('duration-step').hidden=!medication;const durations=$('durations');durations.replaceChildren();
 if(medication)for(const g of groups){const t=treatments(g).find(t=>t.id===medication.id);if(!t)continue;const button=tile(g.name,priceSummary(t),group?.id===g.id,()=>{group=g;product=t;payment=null;render();moveTo('payment-step');},!t.choices.length);button.dataset.duration=g.durationMonths;durations.append(button);}
 $('payment-step').hidden=!product;const payments=$('payments');payments.replaceChildren();
 for(const choice of product?.choices||[]){const o=choice.option,button=tile(paymentTitle(o),'',payment?.option.key===o.key&&payment?.entry.sku===choice.entry.sku,()=>{payment=choice;render();});const price=make('span',money(o,choice.entry));price.className='payment-price';const copy=make('span',paymentTerms(o,choice.entry));copy.className='payment-copy';button.append(price,copy);payments.append(button);}
 $('selection-title').textContent=medication?.name||'Your plan';const details=$('selection-details');details.replaceChildren();
 if(group){const name=make('p',group.name);name.className='selection-product';details.append(name);}else details.append(make('p',medication?'Choose a plan length to see your price.':'Start by choosing your medication.'));
 if(payment){details.append(make('p',paymentTitle(payment.option)),make('p',paymentTerms(payment.option,payment.entry)));const total=make('div');total.className='selection-total';total.append(make('span','Total upfront'),make('strong',money(payment.option,payment.entry)));details.append(total);}else if(product)details.append(make('p',priceSummary(product)),make('p','Choose one-time or subscription to continue.'));
 const next=$('plan-continue');next.hidden=!payment;next.removeAttribute('aria-disabled');next.textContent='Continue to your details →';if(payment)next.href='/plans/'+encodeURIComponent(planId)+'/choose?'+new URLSearchParams({sku:payment.entry.sku,option:payment.option.key,purchase_option_id:payment.entry.purchaseOptionId||''});else next.removeAttribute('href');
}
$('plan-continue').addEventListener('click',event=>{const button=event.currentTarget;if(button.getAttribute('aria-disabled')==='true'){event.preventDefault();return;}button.setAttribute('aria-disabled','true');button.textContent='Opening your secure checkout…';});
window.addEventListener('pageshow',event=>{if(event.persisted&&data)render();});
(async()=>{const loading=$('plan-loading');try{
 const response=await fetch('/api/plans/'+encodeURIComponent(planId));if(!response.ok)throw Error(response.status===401?'Open your private checkout invitation to view these plans.':'These plans are temporarily unavailable. Please contact us for help.');data=await response.json();
 if(data.paymentTestOnly){const notice=make('p','Live payment test: your card will be charged. No medication will be shipped.');notice.className='test-notice';notice.setAttribute('role','note');$('plan-content').prepend(notice);}
 BrandDesign.apply(document.body,data.branding);$('brand-name').textContent=data.branding.name||'';$('plan-title').textContent=data.title;document.title=data.title;$('therapy-name').textContent=data.therapy;
 if(data.branding.logo_url){$('brand-logo').src=data.branding.logo_url;$('brand-logo').hidden=false;}$('brand-support').textContent=[data.branding.support_email,data.branding.support_phone].filter(Boolean).join(' · ');
 groups=data.purchaseOptions?.length?data.purchaseOptions.map(p=>({...p,entries:data.entries.filter(e=>e.purchaseOptionId===p.id)})):[...new Set(data.entries.map(e=>e.durationMonths).filter(Boolean))].map(d=>({id:'legacy-'+d,name:d+'-month plan',durationMonths:d,entries:data.entries.filter(e=>e.durationMonths===d)}));groups.sort((a,b)=>a.durationMonths-b.durationMonths);
 render();$('plan-content').hidden=false;loading.hidden=true;if(!data.entries.some(e=>e.available))throw Error('No plans are available right now. Please contact us for help.');
 }catch(error){loading.hidden=true;$('plan-error').textContent=error.message;$('plan-error').hidden=false;$('retry-plans').hidden=false;}})();
$('retry-plans').addEventListener('click',()=>location.reload());
