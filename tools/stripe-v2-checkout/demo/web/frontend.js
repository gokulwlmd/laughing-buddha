'use strict';
const $=id=>document.getElementById(id),apiOrigin=document.querySelector('meta[name=api-origin]').content;
const realPayments=document.querySelector('meta[name=payment-mode]')?.content==='real';
const checkoutBody=plan=>realPayments?{plan_id:plan.plan_id}:{plan_id:plan.plan_id,return_url:location.origin+'/complete'};
let catalog,medication='Semaglutide',months=6,purchase='subscription',loading=false,sequence=0;
const money=(price,currency='USD')=>new Intl.NumberFormat('en-US',{style:'currency',currency}).format(Number(price));
function selected(){return catalog?.plans.find(p=>p.medication===medication&&p.duration_months===months&&p.purchase_type===purchase);}
function buttons(id,items,value,onChange){
 $(id).replaceChildren();
 for(const item of items){const button=document.createElement('button');button.type='button';button.setAttribute('aria-pressed',String(item.value===value));button.textContent=item.label;button.addEventListener('click',()=>{onChange(item.value);render();});$(id).append(button);}
}
function render(){
 const plan=selected();
 buttons('medications',[...new Set(catalog.plans.map(p=>p.medication))].map(value=>({value,label:value})),medication,value=>medication=value);
 buttons('durations',[1,3,6,12].map(value=>({value,label:value+' month'+(value===1?'':'s')+' · '+money(catalog.plans.find(p=>p.medication===medication&&p.duration_months===value&&p.purchase_type===purchase).price)})),months,value=>months=value);
 buttons('purchases',[{value:'once',label:'One-time purchase'},{value:'subscription',label:'Subscription'}],purchase,value=>purchase=value);
 $('plan-name').textContent=plan.medication;$('plan-description').textContent=plan.duration_months+'-month '+(plan.purchase_type==='subscription'?'subscription':'one-time plan');$('price').textContent=money(plan.price);$('terms').textContent=plan.terms;$('checkout').disabled=loading;
 const base='/api/v1/sites/'+catalog.site_id;
 $('get-call').textContent='GET '+apiOrigin+base+'/plans';
 $('post-call').textContent='POST '+apiOrigin+base+'/checkout\nContent-Type: application/json\n\n'+JSON.stringify(checkoutBody(plan),null,2)+'\n\n// Then open result.checkout_url';
}
async function load(){
 const request=++sequence;loading=true;$('checkout').disabled=true;$('message').textContent='Loading plans…';
 const site=$('site').value;
 $('api-docs').href=apiOrigin+'/sites/'+site+'/docs';$('download-spec').href=apiOrigin+'/sites/'+site+'/openapi.json';
 try{const response=await fetch(apiOrigin+'/api/v1/sites/'+site+'/plans');if(!response.ok)throw Error('Could not load these plans. Please try again.');const data=await response.json();if(request!==sequence)return;catalog=data;loading=false;document.documentElement.style.setProperty('--brand',catalog.color);$('brand-name').textContent=catalog.site_name+' +';document.title=catalog.site_name+' · Site API demo';$('catalog-response').textContent=JSON.stringify(catalog,null,2);$('checkout-response').textContent='Choose “Continue to checkout” to run this call.';$('message').textContent='';render();}
 catch(error){if(request===sequence){loading=false;$('message').textContent=error.message;}}
}
$('site').addEventListener('change',load);
$('checkout').addEventListener('click',async()=>{
 if(loading||!selected())return;
 loading=true;$('checkout').disabled=true;$('checkout').textContent='Opening your checkout…';
 try{
  const response=await fetch(apiOrigin+'/api/v1/sites/'+catalog.site_id+'/checkout',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(checkoutBody(selected()))});
  const result=await response.json();if(!response.ok)throw Error(typeof result.detail==='string'?result.detail:'Could not open checkout. Please try again.');
  $('checkout-response').textContent=JSON.stringify(result,null,2);
  location.assign(result.checkout_url);
 }catch(error){$('message').textContent=error.message;loading=false;$('checkout').disabled=false;$('checkout').textContent='Continue to checkout →';}
});
if(location.pathname==='/complete'){$('shopping').hidden=true;$('completed').hidden=false;$('brand-name').textContent='Site API demo +';$('api-docs').href=apiOrigin+'/sites/willow-health/docs';}
else load();
