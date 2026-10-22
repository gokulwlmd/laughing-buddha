/* Card data stays in Stripe Elements; amounts and routing are server-owned. */
let config, stripe, elements, contact, quote, attemptId, busy = false, captureStarted = false;
const $ = id => document.getElementById(id);
const match = location.pathname.match(/^\/checkout\/(\d+)\/(.+)$/);
const managedMatch = location.pathname.match(/^\/c\/([a-z0-9-]+)$/);
const context = managedMatch ? new URLSearchParams({link_id: managedMatch[1]}) : match ? new URLSearchParams({campaign_id: match[1], sku: decodeURIComponent(match[2])}) : null;
const message = (text, error = false) => { $('message').textContent = text; $('message').className = error ? 'error' : ''; };
const money = (amount, currency) => new Intl.NumberFormat(undefined, {style: 'currency', currency}).format(amount / 100);
async function api(path, data) {
  if (!context) throw new Error('Please open your checkout link.');
  const response = await fetch(path + '?' + context, {method: data === undefined ? 'GET' : 'POST',
    headers: {...(attemptId ? {'X-Checkout-Attempt': attemptId} : {}),
      ...(data === undefined ? {} : {'Content-Type': 'application/json', 'X-CSRF-Token': config.csrfToken})},
    body: data === undefined ? undefined : JSON.stringify(data)});
  let result;
  try { result = await response.json(); } catch { throw new Error('The connection was interrupted. Check your payment status before submitting again.'); }
  if (!response.ok) { const error = new Error(typeof result.detail === 'string' ? result.detail : 'Please check your billing details.'); error.status = response.status; throw error; }
  return result;
}
function applyBrand(brand) {
  if (!brand) return;
  BrandDesign.apply(document.documentElement,brand);document.title=brand.name+' · Secure checkout';
  $('brand-name').textContent = brand.name;
  document.querySelector('.wordmark').href=location.pathname;
  $('campaign').textContent = brand.name;
  if (/^#[0-9a-f]{6}$/i.test(brand.color)) document.documentElement.style.setProperty('--brand-color',brand.color);
  $('brand-logo').hidden=!brand.logo_url;if(brand.logo_url)$('brand-logo').src=brand.logo_url;
  $('brand-support').textContent = [brand.support_email,brand.support_phone].filter(Boolean).join(' · ');
}
function setStep(step){
  const current=step==='payment'?2:step==='success'?3:1;
  document.querySelectorAll('.checkout-progress li').forEach((item,index)=>{item.classList.toggle('complete',index<current);if(index===current)item.setAttribute('aria-current','step');else item.removeAttribute('aria-current');});
  $('checkout-heading').textContent=step==='payment'?'Complete your payment':step==='success'?'Thank you for your order':step==='review'?'Review your order':'Complete your order';
  $('checkout-intro').textContent=step==='payment'?'Your plan is ready. Add your payment details to finish.':step==='success'?'Your payment has been recorded.':step==='review'?'Check your plan and total before moving to payment.':'Your plan is selected. Review your details and pay securely.';
}
function customerProduct(option){
  // These are display labels supplied by the catalog, never SKU-derived billing rules.
  const raw=String(option?.name||''),marker='WLMD payment test / ',start=raw.indexOf(marker);
  const parts=(start>=0?raw.slice(start+marker.length):'').split(/\s+\/\s+/);
  if(start>=0&&parts.length>=3)return {name:parts[0],description:parts[1].replace(/^(\d+) months?$/,'$1-month plan')};
  const title=String(config?.checkoutTitle||option?.name||'Your selected plan'),labels=title.split(' · ');
  if(labels.length>=3&&/^choose /i.test(labels[0]))return {name:labels[1],description:labels[2].replace(/^(\d+) months?$/,'$1-month plan')};
  return {name:/^[A-Z0-9]+(?:-[A-Z0-9]+)+$/.test(title)?'Your selected plan':title,description:'Selected for you'};
}
function paymentLabel(option){return (option.prepaidCycles?option.renewal:option.recurring)?'Subscription':'One-time purchase';}
function updateSummary(option,reviewed=false){
  if(!option)return;const product=customerProduct(option),amount=money(Number(option.upfrontPrice||option.basePrice)*100,config.currency);
  $('product').textContent=product.name;$('plan-description').textContent=product.description;
  $('summary-payment').hidden=false;$('summary-payment').textContent=paymentLabel(option);$('plan-price').textContent=amount;
  if(!reviewed){$('total').textContent=amount;$('total-label').textContent='Plan total';$('delivery-price').textContent='Confirmed at review';}
  if(reviewed&&quote){$('total').textContent=money(quote.amount,quote.currency);$('total-label').textContent='Total due today';$('delivery-price').textContent='Included in the total';}
  $('summary-terms').textContent=option.prepaidCycles?option.prepaidCycles+' scheduled deliveries, '+option.days+' days apart. '+(option.renewal?'Full plan renews every '+option.renewalDays+' days.':'No automatic renewal.'):option.recurring?'Renews every '+option.days+' days.':'One payment. No automatic renewal.';
  $('address-heading').textContent=option.shippable?'Delivery & billing address':'Billing address';$('address-help').textContent=option.shippable?'Use the same address for your delivery and payment method.':'Use the address linked to your payment method.';
}
function receipt(result) {
  $('contact').hidden = $('review').hidden = $('payment').hidden = true;
  $('success').hidden = false; $('order-id').textContent = result.orderId; message('');setStep('success');
  if(result.amount!==undefined){$('total').textContent=money(result.amount,result.currency||'usd');$('total-label').textContent='Total paid';}
}
async function complete(intent) {
  const status = await api('/api/status');
  if (status.status === 'captured') { receipt(status); return; }
  if (intent.id !== status.intentId || intent.amount !== status.amount || intent.currency !== status.currency) {
    throw new Error('The payment details do not match this checkout. Contact support before trying again.');
  }
  if (intent.status !== 'requires_capture') throw new Error('Payment authorization is not complete. Check its status before retrying.');
  captureStarted = true;
  const result = await api('/api/capture', {});
  if (result.status !== 'captured' || result.amount !== status.amount) throw new Error('The payment result needs review. Please do not submit again.');
  receipt(result);
}
async function confirm() {
  if (busy) return;
  busy = true; $('pay').disabled = true; message('Authorizing payment…');
  try {
    const submitted = await elements.submit();
    if (submitted.error) throw new Error(submitted.error.message);
    const result = await stripe.confirmPayment({elements, confirmParams: {
      return_url: location.origin + location.pathname, payment_method_data: {billing_details: {
        name: contact.name, email: contact.email, phone: contact.phone,
        address: {line1: contact.address, city: contact.city, state: contact.region, postal_code: contact.postal_code, country: contact.country}
      }}}, redirect: 'if_required'});
    if (result.error) throw new Error(result.error.message);
    await complete(result.paymentIntent);
  } catch (error) { message(error.message, true); }
  finally { busy = false; $('pay').disabled = captureStarted; }
}
function termsFor(q) {
  const total = money(q.amount, q.currency),option=q.option;
  if(option.prepaidCycles)return `Pay ${total} today. Your plan includes ${option.prepaidCycles} scheduled deliveries, ${option.days} days apart, starting with your first delivery. ${option.renewal?`Your full plan renews automatically every ${option.renewalDays} days for ${total}.`:'No automatic renewal.'} There are no additional product charges for the included deliveries.`;
  return option.recurring
    ? `Pay ${total} today. Your subscription renews every ${option.days} days at ${money(Number(option.basePrice)*100,q.currency)} before any applicable tax or delivery charges.`
    : `Pay ${total} today. This is a one-time purchase with no automatic renewal.`;
}
function mountPayment(result) {
  elements = stripe.elements({clientSecret: result.clientSecret, appearance: {theme: 'stripe', variables: {colorPrimary:config.branding?.color||'#1f5646',colorText:config.branding?.text_color||'#173c36',fontFamily:BrandDesign.fonts[config.branding?.font]||BrandDesign.fonts.system,borderRadius:'7px'}}});
  const payment = elements.create('payment', {layout: 'tabs', fields: {billingDetails: {name: 'never', email: 'never', phone: 'never', address: 'never'}}});
  payment.mount('#payment-element');
  const express = elements.create('expressCheckout'); express.on('confirm', confirm); express.mount('#express-checkout');
  payment.on('ready', () => { $('pay').disabled = false; });
  $('pay').textContent = 'Pay ' + money(quote.amount, quote.currency);
  $('payment-terms').textContent = termsFor(quote);
  $('contact').hidden = $('review').hidden = true; $('payment').hidden = false;setStep('payment');updateSummary(quote.option,true);
}
let stripeReady;
async function ensureStripe(){
 if(stripe)return;
 if(!stripeReady)stripeReady=new Promise((resolve,reject)=>{if(typeof Stripe==='function'){resolve();return;}const script=document.createElement('script');script.src='https://js.stripe.com/v3/';script.async=true;script.onload=resolve;script.onerror=()=>{script.remove();stripeReady=null;reject(new Error('The secure card form could not load. Check your connection and try again.'));};document.head.append(script);});
 await stripeReady;stripe=Stripe(config.publishableKey);
}
function showPaymentHold(status){
 $('contact').hidden=$('review').hidden=$('payment').hidden=true;$('payment-hold').hidden=false;
 $('checkout-heading').textContent='Let’s check your payment';$('checkout-intro').textContent='We need to confirm the earlier attempt before you pay again.';
 const authorizing=status.status==='authorization_pending';
 $('hold-title').textContent=authorizing?'Your payment setup needs a check':'Your payment needs a check';
 $('hold-description').textContent=authorizing?'We couldn’t confirm that the payment form was ready. Please contact the store before trying another payment.':'We haven’t confirmed the result of your earlier payment. Please contact the store before paying again.';
 $('hold-help').textContent='Checking your status won’t submit another payment.';
 $('product').textContent='Your selected plan';$('plan-description').textContent='Payment status under review';
 if(Number.isInteger(status.amount)){$('total').textContent=money(status.amount,status.currency);$('total-label').textContent='Amount under review';}
 $('summary-breakdown').hidden=true;
 const email=status.branding?.support_email,phone=status.branding?.support_phone,link=$('hold-contact');
 if(email){link.href='mailto:'+email+'?subject=Checkout%20payment%20help';link.textContent='Contact support';link.hidden=false;}else if(phone){link.href='tel:'+phone;link.textContent='Call support';link.hidden=false;}
 message('');
}
$('check-payment-status').addEventListener('click',async()=>{
 const button=$('check-payment-status');button.disabled=true;button.textContent='Checking…';
 try{const status=await api('/api/status');if(status.status==='captured'){$('payment-hold').hidden=true;receipt(status);}else if(status.status==='awaiting_card'){location.reload();}else{$('hold-help').textContent='The result is still unconfirmed. Please contact the store before trying another payment.';}}
 catch(error){$('hold-help').textContent='We couldn’t check the status. Please contact the store before trying another payment.';}
 finally{button.disabled=false;button.textContent='Check payment status';}
});
async function initialize() {
  try {
    // Remove Stripe return secrets from the address bar immediately, including on error.
    const query = new URLSearchParams(location.search);
    const returnedSecret = query.get('payment_intent_client_secret');
    if (location.search) history.replaceState({}, '', location.pathname);
    const status = await api('/api/status');
    attemptId = status.attemptId;
    applyBrand(status.branding);
    if (status.status === 'captured') { receipt(status); return; }
    if (!['new','awaiting_card'].includes(status.status)&&!returnedSecret){showPaymentHold(status);return;}
    message(status.status==='awaiting_card'?'Resuming your secure payment…':'Loading your plan details…');
    config = await api('/api/config');
    $('campaign').textContent = config.branding?.name || config.campaignName;
    applyBrand(config.branding);
    $('sku').textContent = config.sku;
    $('product').textContent = config.checkoutTitle || config.options[0]?.name || config.sku;
    $('payment-test-notice').hidden=!config.paymentTestOnly;
    if (!config.ready) throw new Error(managedMatch ? 'This checkout is not available yet. Please contact the brand for help.' : config.blockedReason);
    if (returnedSecret) {
      message('Checking payment authorization…');
      await ensureStripe();
      const result = await stripe.retrievePaymentIntent(returnedSecret);
      if (result.error) throw new Error(result.error.message);
      await complete(result.paymentIntent); return;
    }
    $('pay').addEventListener('click', confirm);
    if (status.status === 'awaiting_card') {
      await ensureStripe();
      const resumed = await api('/api/resume', {});
      contact = resumed.contact; quote = resumed; mountPayment(resumed);
      $('total').textContent = money(quote.amount, quote.currency);
      message('Your payment is ready to continue.');
      return;
    }
    if (status.status !== 'new'){showPaymentHold(status);return;}
    $('payment-test-notice').hidden=!config.paymentTestOnly;
    const select = $('selection');
    for (const option of config.options) {
      const el = document.createElement('option'); el.value = option.key;
      el.textContent = paymentLabel(option)+' · '+money(Number(option.upfrontPrice||option.basePrice)*100,config.currency)+(option.prepaidCycles?' · '+option.prepaidCycles+' deliveries every '+option.days+' days':option.recurring?' · Every '+option.days+' days':'')+(option.blockedReason?' (unavailable)':'');
      el.disabled = !!option.blockedReason;
      select.append(el);
    }
    const available = config.options.filter(o => !o.blockedReason);
    if (!available.length) throw new Error('No plans are currently available for online payment. Please contact the brand.');
    const requestedSelection = query.get('selection');
    select.value = available.some(o => o.key === requestedSelection) ? requestedSelection : available.length === 1 ? available[0].key : '';
    if (requestedSelection) history.replaceState({}, '', location.pathname);
    $('payment-choice').hidden=available.length===1;
    updateSummary(config.options.find(o=>o.key===select.value)||available[0]);
    try{const previous=new URL(document.referrer);if(previous.origin===location.origin&&/^\/plans\/[a-z0-9-]+(?:\/choose)?$/.test(previous.pathname)){$('change-plan').href=previous.pathname.replace(/\/choose$/,'');$('change-plan').hidden=false;}}catch{}
    select.addEventListener('change', () => {
      const option = config.options.find(o => o.key === select.value);
      $('option-note').textContent = option?.blockedReason ? 'This plan is not currently available online.' : '';
      updateSummary(option);
    });
    for (const shipping of config.shipping) {
      const el = document.createElement('option'); el.value = shipping.id; el.textContent = shipping.name; $('shipping').append(el);
    }
    $('shipping').value = config.shipping.length === 1 ? config.shipping[0].id : '';
    $('shipping-choice').hidden=config.shipping.length<=1;
    for (const country of config.countries) {
      const el = document.createElement('option'); el.value = country.code; el.textContent = country.name; $('country').append(el);
    }
    $('contact').hidden = false; message('');
    $('contact').addEventListener('submit', async event => {
      event.preventDefault(); const button = event.target.querySelector('button'); button.disabled = true;
      try {
        const form = Object.fromEntries(new FormData(event.target));
        const selection = form.selection, shipping_id = form.shipping ? Number(form.shipping) : null;
        delete form.selection; delete form.shipping; contact = form;
        message('Calculating your total…');
        quote = await api('/api/quote', {contact, selection, shipping_id});
        const total = money(quote.amount, quote.currency);
        $('total').textContent = total; $('review-total').textContent = total;
        $('terms').textContent = termsFor(quote);
        $('recurring-label').hidden = !quote.option.recurring; $('consent').checked = false;
        $('contact').hidden = true; $('review').hidden = false;setStep('review');updateSummary(quote.option,true); message('');
        ensureStripe().catch(()=>{});
      } catch (error) { message(error.message, true); }
      finally { button.disabled = false; }
    });
    $('edit').addEventListener('click', () => { $('review').hidden = true; $('contact').hidden = false;setStep('details'); });
    $('authorize').addEventListener('click', async () => {
      if (busy) return;
      busy = true; $('authorize').disabled = true;
      try {
        if (quote.option.recurring && !$('consent').checked) throw new Error('Please accept the recurring billing terms.');
        message('Preparing secure payment…');$('authorize').textContent='Opening secure payment…';
        await ensureStripe();
        const result = await api('/api/authorize', {quote_id: quote.id, recurring_consent: $('consent').checked});
        mountPayment(result); message('');
      } catch (error) { message(error.message, true); }
      finally { busy = false; $('authorize').disabled = false;$('authorize').textContent='Continue to payment →'; }
    });
  } catch (error) { message(error.message, true); }
}
$('new-purchase').addEventListener('click', async () => {
  if (busy) return;
  busy = true; $('new-purchase').disabled = true;
  try {
    if (!config) config = await api('/api/config');
    await api('/api/new-purchase', {previous_attempt_id: attemptId});
    location.replace(location.pathname);
  } catch (error) {
    message(error.message, true); busy = false; $('new-purchase').disabled = false;
  }
});
$('summary-toggle').addEventListener('click',()=>{const button=$('summary-toggle'),expanded=button.getAttribute('aria-expanded')!=='true';button.setAttribute('aria-expanded',String(expanded));button.textContent=expanded?'Hide plan details':'View plan details';document.querySelector('aside').toggleAttribute('data-expanded',expanded);});
initialize();
