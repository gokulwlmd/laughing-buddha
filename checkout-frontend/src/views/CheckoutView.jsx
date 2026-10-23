// Port of the reference-design checkout page (web/index.html + checkout-v4.css + checkout-v9.js), driven by
// the Site API session endpoints instead of the internal /api/* endpoints.
import { useMemo, useRef, useState } from 'react';
import { Elements, ExpressCheckoutElement, PaymentElement, useElements, useStripe } from '@stripe/react-stripe-js';
import { brandFlags, brandStyle, FONTS, layoutOf } from '../config/siteConfig.js';
import { getStripe } from '../checkout/useCheckout.js';
import { money, moneyMinor, paymentTitle, planLengthName, summaryTerms } from '../lib/format.js';
import { US_STATES } from '../lib/usStates.js';
import { Footer, Header, TEST_NOTICE } from '../components/Shell.jsx';

const HEADINGS = {
  details: ['Complete your order', 'Your plan is selected. Review your details and pay securely.'],
  review: ['Review your order', 'Check your plan and total before moving to payment.'],
  payment: ['Complete your payment', 'Your plan is ready. Add your payment details to finish.'],
  done: ['Thank you for your order', 'Your payment has been recorded.'],
  held: ['Let’s check your payment', 'We need to confirm the earlier attempt before you pay again.'],
};

function Progress({ step }) {
  const current = step === 'payment' ? 2 : step === 'done' ? 3 : 1;
  // As in the original: "Your plan" shows as complete once the details are submitted.
  const firstDone = !['details', 'held'].includes(step);
  const items = ['Your plan', 'Your details', 'Payment'];
  return (
    <nav className="checkout-progress" aria-label="Checkout progress">
      <ol>
        {items.map((label, i) => (
          <li key={label} className={i < current && (i > 0 || firstDone) ? 'complete' : undefined} aria-current={i === current ? 'step' : undefined}>
            <span>{i + 1}</span>
            {label}
          </li>
        ))}
      </ol>
    </nav>
  );
}

export default function CheckoutView({ site, brand, plan, c }) {
  const [heading, intro] = HEADINGS[c.step] || HEADINGS.details;
  const reviewed = !!c.data.quote && ['review', 'payment', 'done'].includes(c.step);
  const statusMessage =
    c.error ||
    c.notice ||
    (c.step === 'details' && !c.config ? 'Checking your plan. You can enter your details now.' : '') ||
    (c.step === 'details' && c.busy ? 'Calculating your total…' : '') ||
    (c.step === 'review' && c.busy ? 'Preparing secure payment…' : '');

  return (
    <div className="lb-checkout" data-layout={layoutOf(brand)} style={brandStyle(brand)} {...brandFlags(brand)}>
      <main>
        <Header brand={brand} />
        <Progress step={c.step} />
        {(c.config?.payment_test_only || site.plans?.testNotice) && (
          <p id="payment-test-notice" className="test-notice" role="note">
            {TEST_NOTICE}
          </p>
        )}
        <div className="page-heading">
          <h1 id="checkout-heading">{heading}</h1>
          <p id="checkout-intro">{intro}</p>
        </div>

        <section className="layout">
          <article>
            <div id="message" role="status" aria-live="polite" className={c.error ? 'error' : ''}>
              {statusMessage}
            </div>

            {c.step === 'held' && <Hold c={c} brand={brand} />}
            {c.step === 'details' && <DetailsForm c={c} />}
            {c.step === 'review' && <Review c={c} />}
            {c.step === 'payment' && c.payment && <Payment site={site} brand={brand} c={c} />}
            {c.step === 'done' && c.receipt && <Success c={c} site={site} />}
          </article>

          <Summary plan={plan} c={c} reviewed={reviewed} />
        </section>
        <Footer brand={brand} />
      </main>
    </div>
  );
}

function DetailsForm({ c }) {
  const cfg = c.config;
  const saved = c.data.contact || {};
  const countries = cfg?.countries || [];
  const shipping = cfg?.shipping || [];
  const shippable = !!cfg?.plan?.shippable;
  const ready = !!cfg;
  const [country, setCountry] = useState(saved.country || 'US');
  const [state, setState] = useState(saved.country === 'US' || !saved.country ? saved.region || '' : '');
  const [shippingId, setShippingId] = useState(c.data.shippingId ?? '');
  const effectiveCountry = countries.some((x) => x.code === country) ? country : countries[0]?.code || country;
  const usa = effectiveCountry === 'US';
  const effectiveShipping = shipping.length === 1 ? String(shipping[0].id) : String(shippingId ?? '');

  const submit = (ev) => {
    ev.preventDefault();
    if (!ready || c.busy) return;
    const f = Object.fromEntries(new FormData(ev.currentTarget));
    const contact = {
      name: f.name.trim(),
      email: f.email.trim(),
      phone: f.phone.trim(),
      address: f.address.trim(),
      city: f.city.trim(),
      region: (usa ? state : f.region_other || '').trim(),
      postal_code: f.postal_code.trim(),
      country: effectiveCountry,
    };
    c.submitDetails(contact, shipping.length ? Number(effectiveShipping) || null : null);
  };

  return (
    <form id="contact" onSubmit={submit}>
      <div className="section-heading">
        <h2>Contact information</h2>
        <p>We'll send your order confirmation here.</p>
      </div>
      <label>
        Full name
        <input name="name" autoComplete="name" required minLength={2} maxLength={100} placeholder="First and last name" defaultValue={saved.name} />
      </label>
      <div className="row">
        <label>
          Email address
          <input name="email" type="email" autoComplete="email" required maxLength={254} placeholder="you@example.com" defaultValue={saved.email} />
        </label>
        <label>
          Phone number
          <input name="phone" type="tel" autoComplete="tel" required minLength={7} maxLength={30} placeholder="(555) 123-4567" defaultValue={saved.phone} />
        </label>
      </div>

      <div className="section-heading address-heading">
        <h2 id="address-heading">{shippable ? 'Delivery & billing address' : 'Billing address'}</h2>
        <p id="address-help">{shippable ? 'Use the same address for your delivery and payment method.' : 'Use the address linked to your payment method.'}</p>
      </div>
      <label>
        Street address
        <input name="address" autoComplete="address-line1" required minLength={2} maxLength={150} placeholder="Street address" defaultValue={saved.address} />
      </label>
      <div className="row">
        <label>
          City
          <input name="city" autoComplete="address-level2" required maxLength={80} defaultValue={saved.city} />
        </label>
        <label>
          State / region
          {usa ? (
            <select id="state" name="region" autoComplete="address-level1" required disabled={!ready} value={state} onChange={(e) => setState(e.target.value)}>
              <option value="" disabled>
                Choose your state
              </option>
              {US_STATES.map(([code, name]) => (
                <option key={code} value={code}>
                  {name}
                </option>
              ))}
            </select>
          ) : (
            <input id="other-region" name="region_other" autoComplete="address-level1" required maxLength={80} defaultValue={saved.country !== 'US' ? saved.region : ''} />
          )}
        </label>
      </div>
      <div className="row">
        <label>
          ZIP / postal code
          <input name="postal_code" autoComplete="postal-code" required minLength={2} maxLength={20} defaultValue={saved.postal_code} />
        </label>
        <label>
          Country
          <select id="country" name="country" autoComplete="country" required disabled={!ready} value={effectiveCountry} onChange={(e) => setCountry(e.target.value)}>
            {(countries.length ? countries : [{ code: 'US', name: 'United States' }]).map((x) => (
              <option key={x.code} value={x.code}>
                {x.name}
              </option>
            ))}
          </select>
        </label>
      </div>
      {shipping.length > 1 && (
        <label id="shipping-choice">
          Delivery method
          <select id="shipping" name="shipping" required={shippable} value={effectiveShipping} onChange={(e) => setShippingId(e.target.value)}>
            <option value="">Choose a delivery method</option>
            {shipping.map((s) => (
              <option key={s.id} value={s.id}>
                {s.name}
              </option>
            ))}
          </select>
        </label>
      )}
      <button type="submit" disabled={!ready || c.busy}>
        Review my order <span aria-hidden="true">→</span>
      </button>
      <p className="button-note">Review your final total before entering payment details.</p>
    </form>
  );
}

function Review({ c }) {
  const q = c.data.quote;
  const [consent, setConsent] = useState(false);
  if (!q) return null;
  const needsConsent = q.terms_consent_required;
  return (
    <section id="review">
      <p className="eyebrow">Before you pay</p>
      <h2>Review your order</h2>
      <p className="review-caption">Total due today</p>
      <h3 id="review-total">{moneyMinor(q.amount, q.currency)}</h3>
      <p id="terms" className="terms">
        {q.payment_terms}
      </p>
      {needsConsent && (
        <label id="recurring-label" className="consent">
          <input id="consent" type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} />{' '}
          <span>I agree to the plan and payment terms above.</span>
        </label>
      )}
      <button
        id="authorize"
        type="button"
        disabled={c.busy}
        onClick={() => {
          if (needsConsent && !consent) {
            c.setError('Please accept the recurring billing terms.');
            return;
          }
          c.preparePayment(needsConsent ? consent : false);
        }}
      >
        {c.busy ? 'Opening secure payment…' : 'Continue to payment'} <span aria-hidden="true">→</span>
      </button>
      <button id="edit" className="secondary" type="button" disabled={c.busy} onClick={c.back}>
        Edit my details
      </button>
    </section>
  );
}

function Payment({ site, brand, c }) {
  const stripePromise = useMemo(() => getStripe(c.payment.publishable_key), [c.payment.publishable_key]);
  const options = useMemo(
    () => ({
      clientSecret: c.payment.client_secret,
      appearance: {
        theme: 'stripe',
        variables: {
          colorPrimary: brand.color || '#1f5646',
          colorText: brand.text_color || '#173c36',
          fontFamily: FONTS[brand.font] || FONTS.system,
          borderRadius: '7px',
        },
      },
    }),
    [c.payment.client_secret], // eslint-disable-line react-hooks/exhaustive-deps
  );
  return (
    <section id="payment">
      <p className="eyebrow">Final step</p>
      <h2>Payment details</h2>
      <p className="small">Your card details are encrypted and securely processed.</p>
      <Elements stripe={stripePromise} options={options} key={c.payment.client_secret}>
        <PaymentInner site={site} c={c} />
      </Elements>
    </section>
  );
}

function PaymentInner({ site, c }) {
  const stripe = useStripe();
  const elements = useElements();
  const [ready, setReady] = useState(false);
  const [paying, setPaying] = useState(false);
  const lock = useRef(false); // synchronous guard: a double click must never confirm twice
  const setError = c.setError; // shown in the page's #message area, like the original
  const enabled = site.checkout?.paymentsEnabled === true;
  const contact = c.data.contact || {};
  const quote = c.data.quote;
  const amount = moneyMinor(c.payment.amount, c.payment.currency);

  // Same confirmation as the original: Payment Element + confirmPayment on the
  // Sticky-created intent, then the API completes the order.
  const confirm = async () => {
    if (!stripe || !elements || !enabled || lock.current) return;
    lock.current = true;
    setPaying(true);
    setError(null);
    try {
      const submitted = await elements.submit();
      if (submitted.error) throw new Error(submitted.error.message);
      const result = await stripe.confirmPayment({
        elements,
        redirect: 'if_required',
        confirmParams: {
          return_url: window.location.origin + window.location.pathname,
          payment_method_data: {
            billing_details: {
              name: contact.name,
              email: contact.email,
              phone: contact.phone,
              address: {
                line1: contact.address,
                city: contact.city,
                state: contact.region,
                postal_code: contact.postal_code,
                country: contact.country,
              },
            },
          },
        },
      });
      if (result.error) throw new Error(result.error.message);
      await c.onAuthorized(result.paymentIntent);
    } catch (e) {
      setError(e.message || 'Your payment could not be completed.');
    } finally {
      lock.current = false;
      setPaying(false);
    }
  };

  return (
    <>
      {!enabled && (
        <p className="test-notice" role="note">
          Payments aren’t open on this checkout yet. You can review your order, but no card can be charged.
        </p>
      )}
      {enabled && (
        <div id="express-checkout">
          <ExpressCheckoutElement onConfirm={confirm} />
        </div>
      )}
      <div id="payment-element" data-ready={ready ? 'true' : undefined}>
        <PaymentElement
          onReady={() => setReady(true)}
          onLoadError={() => setError('The secure payment form could not load. Please reload this checkout to resume the same payment.')}
          options={{ layout: 'tabs', fields: { billingDetails: { name: 'never', email: 'never', phone: 'never', address: 'never' } } }}
        />
      </div>
      <button id="pay" type="button" disabled={!ready || !enabled || paying || c.busy} onClick={confirm}>
        {paying || c.busy ? 'Processing…' : `Pay ${amount}`}
      </button>
      <p id="payment-terms" className="small payment-terms">
        {quote?.payment_terms}
      </p>
    </>
  );
}

function Success({ c, site }) {
  return (
    <section id="success">
      <div className="check" aria-hidden="true">
        ✓
      </div>
      <p className="eyebrow">Thank you</p>
      <h2>Your payment is complete</h2>
      <p>Keep your order number for your records.</p>
      <p className="receipt">
        Order number <strong id="order-id">{c.receipt.order_id}</strong>
      </p>
      {site.checkout?.memberPortal && (
        <>
          <button id="create-account" type="button" disabled={c.portalBusy} onClick={c.openPortal}>
            {c.portalBusy ? 'Opening account setup…' : 'Create your patient account'} <span aria-hidden="true">→</span>
          </button>
          <p className="small">Track your order, complete your intake and manage refills.</p>
        </>
      )}
      <button id="new-purchase" className="secondary" type="button" onClick={c.startOver}>
        Place another order
      </button>
      <p className="small">Each new order is reviewed and paid for separately.</p>
    </section>
  );
}

function Hold({ c, brand }) {
  const r = c.receipt;
  const authorizing = r?.status === 'authorization_pending';
  const known = !!r;
  const title = !known ? 'We couldn’t load your checkout' : authorizing ? 'Your payment setup needs a check' : 'Your payment needs a check';
  const description = !known
    ? 'We couldn’t confirm where this checkout stands. If you already entered card details, please contact the store before paying again.'
    : authorizing
      ? 'We couldn’t confirm that the payment form was ready. Please contact the store before trying another payment.'
      : 'We haven’t confirmed the result of your earlier payment. Please contact the store before paying again.';
  const email = brand.support_email;
  const phone = brand.support_phone;
  return (
    <section id="payment-hold" className="payment-hold">
      <p className="eyebrow">Payment status</p>
      <h2 id="hold-title">{title}</h2>
      <p id="hold-description">{description}</p>
      <button id="check-payment-status" type="button" disabled={c.busy} onClick={c.refreshStatus}>
        {c.busy ? 'Checking…' : 'Check payment status'}
      </button>
      {!c.paymentInFlight && (
        <button className="secondary" type="button" disabled={c.busy} onClick={c.startOver}>
          Start over
        </button>
      )}
      {email ? (
        <a id="hold-contact" className="support-link" href={`mailto:${email}?subject=Checkout%20payment%20help`}>
          Contact support
        </a>
      ) : (
        phone && (
          <a id="hold-contact" className="support-link" href={`tel:${phone}`}>
            Call support
          </a>
        )
      )}
      <p id="hold-help" className="small" role="status">
        {c.holdNote || 'Checking your status won’t submit another payment.'}
      </p>
    </section>
  );
}

function Summary({ plan, c, reviewed }) {
  const [expanded, setExpanded] = useState(false);
  const held = c.step === 'held';
  const q = c.data.quote;
  let total = plan ? money(plan.price, plan.currency) : '—';
  let totalLabel = 'Plan total';
  if (c.step === 'done' && c.receipt?.amount != null) {
    total = moneyMinor(c.receipt.amount, c.receipt.currency || 'usd');
    totalLabel = 'Total paid';
  } else if (reviewed && q) {
    total = moneyMinor(q.amount, q.currency);
    totalLabel = 'Total due today';
  } else if (held && Number.isInteger(c.receipt?.amount)) {
    total = moneyMinor(c.receipt.amount, c.receipt.currency || 'usd');
    totalLabel = 'Amount under review';
  }
  const canChange = ['details', 'review'].includes(c.step);

  return (
    <aside aria-label="Your order summary" data-expanded={expanded ? '' : undefined}>
      <div className="summary-heading">
        <h2>Order summary</h2>
        {canChange && (
          <a
            id="change-plan"
            href="#plans"
            onClick={(e) => {
              e.preventDefault();
              c.changePlan();
            }}
          >
            Change plan
          </a>
        )}
      </div>
      <div className="summary-product">
        <div className="product-icon" aria-hidden="true">
          <svg viewBox="0 0 48 48">
            <path d="m10 14 14-7 14 7v21l-14 7-14-7Z" />
            <path d="m10 14 14 7 14-7M24 21v21M17 10.5l14 7v9l-7 3.5" />
            <path d="m15 30 4 2" />
          </svg>
        </div>
        <div className="summary-product-copy">
          <h2 id="product">{held || !plan ? 'Your selected plan' : plan.medication}</h2>
          <p id="plan-description" className="plan-description">
            {held ? 'Payment status under review' : plan ? planLengthName(plan.duration_months) : 'Your plan details will appear here.'}
          </p>
          {plan && !held && (
            <p id="summary-payment" className="plan-pill">
              {paymentTitle(plan)}
            </p>
          )}
        </div>
      </div>
      {!held && (
        <dl id="summary-breakdown" className="summary-breakdown">
          <div>
            <dt>Plan price</dt>
            <dd id="plan-price">{plan ? money(plan.price, plan.currency) : '—'}</dd>
          </div>
          <div>
            <dt id="delivery-label">Delivery &amp; tax</dt>
            <dd id="delivery-price">{reviewed ? 'Included in the total' : 'Confirmed at review'}</dd>
          </div>
        </dl>
      )}
      <div className="summary-total">
        <span id="total-label">{totalLabel}</span>
        <strong id="total">{total}</strong>
      </div>
      {plan && !held && (
        <p id="summary-terms" className="summary-terms">
          {summaryTerms(plan)}
        </p>
      )}
      <div className="summary-reassurance">
        <div>
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <rect x="5" y="10" width="14" height="11" rx="3" />
            <path d="M8 10V7a4 4 0 0 1 8 0v3M12 14v3" />
          </svg>
          <p>
            <strong>Secure payment</strong>Your payment details stay protected.
          </p>
        </div>
        <div>
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M6 3h12v18l-3-2-3 2-3-2-3 2Z" />
            <path d="M9 8h6M9 12h6" />
          </svg>
          <p>
            <strong>Clear pricing</strong>Review your full total before you pay.
          </p>
        </div>
      </div>
      <button id="summary-toggle" type="button" aria-expanded={expanded} onClick={() => setExpanded(!expanded)}>
        {expanded ? 'Hide plan details' : 'View plan details'}
      </button>
    </aside>
  );
}
