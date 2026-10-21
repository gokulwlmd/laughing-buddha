/* Card data stays in Stripe Elements; amounts and routing are server-owned. */
let config, stripe, elements, contact, quote, attemptId, busy = false, captureStarted = false;
const $ = id => document.getElementById(id);
const match = location.pathname.match(/^\/checkout\/(\d+)\/(.+)$/);
const managedMatch = location.pathname.match(/^\/c\/([a-z0-9-]+)$/);
const context = managedMatch ? new URLSearchParams({link_id: managedMatch[1]}) : match ? new URLSearchParams({campaign_id: match[1], sku: decodeURIComponent(match[2])}) : null;
const message = (text, error = false) => { $('message').textContent = text; $('message').className = error ? 'error' : ''; };
const money = (amount, currency) => new Intl.NumberFormat(undefined, {style: 'currency', currency}).format(amount / 100);
async function api(path, data) {
  if (!context) throw new Error('Open a campaign/SKU checkout link.');
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
function receipt(result) {
  $('contact').hidden = $('review').hidden = $('payment').hidden = true;
  $('success').hidden = false; $('order-id').textContent = result.orderId; message('');
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
  const total = money(q.amount, q.currency);
  if(q.option.prepaidCycles)return `One payment of ${total} covers ${q.option.prepaidCycles} shipment orders, every ${q.option.days} days (${q.option.prepaidCycles*q.option.days}-day plan). The first shipment is included. No automatic renewal or additional product payments. This is a synthetic test product; no medication is shipped.`;
  return q.option.recurring
    ? `Today: ${total}. This subscription bills automatically every ${q.option.days} days under the selected offer. Future charges follow its configured pricing and applicable taxes and shipping.`
    : `You authorize one payment of ${total}.`;
}
function mountPayment(result) {
  elements = stripe.elements({clientSecret: result.clientSecret, appearance: {theme: 'stripe', variables: {colorPrimary:config.branding?.color||'#1f5646',colorText:config.branding?.text_color||'#173c36',fontFamily:BrandDesign.fonts[config.branding?.font]||BrandDesign.fonts.system,borderRadius:'7px'}}});
  const payment = elements.create('payment', {layout: 'tabs', fields: {billingDetails: {name: 'never', email: 'never', phone: 'never', address: 'never'}}});
  payment.mount('#payment-element');
  const express = elements.create('expressCheckout'); express.on('confirm', confirm); express.mount('#express-checkout');
  payment.on('ready', () => { $('pay').disabled = false; });
  $('pay').textContent = 'Pay ' + money(quote.amount, quote.currency);
  $('payment-terms').textContent = termsFor(quote);
  $('contact').hidden = $('review').hidden = true; $('payment').hidden = false;
}
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
    config = await api('/api/config');
    $('campaign').textContent = config.branding?.name || config.campaignName;
    applyBrand(config.branding);
    $('sku').textContent = config.sku;
    $('product').textContent = config.checkoutTitle || config.options[0]?.name || config.sku;
    if (!config.ready) throw new Error(managedMatch ? 'This checkout is not available yet. Please contact the brand for help.' : config.blockedReason);
    stripe = Stripe(config.publishableKey);
    if (returnedSecret) {
      message('Checking payment authorization…');
      const result = await stripe.retrievePaymentIntent(returnedSecret);
      if (result.error) throw new Error(result.error.message);
      await complete(result.paymentIntent); return;
    }
    $('pay').addEventListener('click', confirm);
    if (status.status === 'awaiting_card') {
      const resumed = await api('/api/resume', {});
      contact = resumed.contact; quote = resumed; mountPayment(resumed);
      $('total').textContent = money(quote.amount, quote.currency);
      message('Your existing payment is ready to continue. No new payment was created.');
      return;
    }
    if (status.status !== 'new') throw new Error('A payment attempt is already open. Its status needs review before another payment.');
    const select = $('selection');
    for (const option of config.options) {
      const el = document.createElement('option'); el.value = option.key;
      el.textContent = `${option.prepaidCycles?'Pay upfront · '+option.prepaidCycles+' shipments every '+option.days+' days · No renewal:':option.offerName} ${option.prepaidCycles?money(Number(option.upfrontPrice)*100,config.currency):'· '+option.modelName}${option.blockedReason ? ' (unavailable)' : ''}`;
      el.disabled = !!option.blockedReason;
      select.append(el);
    }
    const available = config.options.filter(o => !o.blockedReason);
    if (!available.length) throw new Error('No plans are currently available for online payment. Please contact the brand.');
    const requestedSelection = query.get('selection');
    select.value = available.some(o => o.key === requestedSelection) ? requestedSelection : available.length === 1 ? available[0].key : '';
    if (requestedSelection) history.replaceState({}, '', location.pathname);
    select.addEventListener('change', () => {
      const option = config.options.find(o => o.key === select.value);
      $('option-note').textContent = option?.blockedReason ? 'This plan is not currently available online.' : '';
    });
    for (const shipping of config.shipping) {
      const el = document.createElement('option'); el.value = shipping.id; el.textContent = shipping.name; $('shipping').append(el);
    }
    $('shipping').value = config.shipping.length === 1 ? config.shipping[0].id : '';
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
        $('contact').hidden = true; $('review').hidden = false; message('');
      } catch (error) { message(error.message, true); }
      finally { button.disabled = false; }
    });
    $('edit').addEventListener('click', () => { $('review').hidden = true; $('contact').hidden = false; });
    $('authorize').addEventListener('click', async () => {
      if (busy) return;
      busy = true; $('authorize').disabled = true;
      try {
        if (quote.option.recurring && !$('consent').checked) throw new Error('Please accept the recurring billing terms.');
        message('Preparing secure payment…');
        const result = await api('/api/authorize', {quote_id: quote.id, recurring_consent: $('consent').checked});
        mountPayment(result); message('');
      } catch (error) { message(error.message, true); }
      finally { busy = false; $('authorize').disabled = false; }
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
initialize();
