// Port of the reference-design plan page (web/plans.html + plan-selector-v4.js),
// driven by the Site API's GET /plans instead of the internal /api/plans.
import { useMemo, useRef, useState } from 'react';
import { brandFlags, brandStyle, layoutOf } from '../config/siteConfig.js';
import { deliverySummary, lowestPrice, money, monthlyEquivalent, paymentTerms, paymentTitle, planLengthName } from '../lib/format.js';
import { Footer, Header, TEST_NOTICE } from '../components/Shell.jsx';

const LOCK = (
  <svg viewBox="0 0 24 24" aria-hidden="true">
    <rect x="5" y="10" width="14" height="11" rx="3" />
    <path d="M8 10V7a4 4 0 0 1 8 0v3" />
  </svg>
);

const PACKAGE_ART = (
  <svg viewBox="0 0 130 130" fill="none">
    <ellipse cx="66" cy="111" rx="42" ry="7" fill="currentColor" opacity=".08" />
    <path d="M33 31 78 24 100 36 55 45Z" fill="white" stroke="currentColor" strokeOpacity=".22" />
    <path d="M33 31 55 45V109L33 94Z" fill="currentColor" fillOpacity=".08" stroke="currentColor" strokeOpacity=".22" />
    <path d="m55 45 45-9v65l-45 8Z" fill="white" stroke="currentColor" strokeOpacity=".22" />
    <path d="m65 62 25-5M65 68l18-4" stroke="currentColor" strokeWidth="2" strokeLinecap="round" opacity=".45" />
    <path d="m65 91 25-5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" opacity=".2" />
    <circle cx="78" cy="78" r="5" fill="currentColor" opacity=".12" />
  </svg>
);

function Tile({ title, selected, disabled, onClick, children, titleClass, ...rest }) {
  return (
    <button type="button" aria-pressed={String(!!selected)} disabled={disabled} onClick={onClick} {...rest}>
      {title !== undefined && <strong className={titleClass}>{title}</strong>}
      {children}
    </button>
  );
}

function SummaryRow({ label, value }) {
  return (
    <div className="summary-row">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

const slug = (s) => String(s).toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');

// ?product=<medication> preselects it (matched by name or slug), as in plan-selector-v4.
function requestedMedication(medications) {
  let wanted = '';
  try {
    wanted = (new URLSearchParams(window.location.search).get('product') || '').toLowerCase();
  } catch {
    /* no URL */
  }
  return (wanted && medications.find((m) => m.toLowerCase() === wanted || slug(m) === slug(wanted))) || medications[0] || null;
}

export default function PlansView({ site, brand, plans, initialPlanId, busy, error, onContinue }) {
  const cfg = site.plans || {};
  const order = cfg.medicationOrder || [];
  const rank = (name) => (order.indexOf(name) < 0 ? 999 : order.indexOf(name));

  const medications = useMemo(() => {
    const names = [...new Set(plans.map((p) => p.medication))];
    return names.sort((a, b) => rank(a) - rank(b) || a.localeCompare(b));
  }, [plans]); // eslint-disable-line react-hooks/exhaustive-deps
  // Longest plan first, as in the reference design.
  const durations = useMemo(() => [...new Set(plans.map((p) => p.duration_months))].sort((a, b) => b - a), [plans]);

  const initial = plans.find((p) => p.plan_id === initialPlanId);
  const [medication, setMedication] = useState(() => initial?.medication || requestedMedication(medications));
  const [months, setMonths] = useState(initial?.duration_months || null);
  const [planId, setPlanId] = useState(initial?.plan_id || null);
  const [opening, setOpening] = useState(false);
  const durationRef = useRef(null);
  const paymentRef = useRef(null);

  const choicesFor = (med, m) => plans.filter((p) => p.medication === med && p.duration_months === m);
  const choices = medication && months ? choicesFor(medication, months) : [];
  const selected = plans.find((p) => p.plan_id === planId);

  const moveTo = (ref) =>
    requestAnimationFrame(() => {
      const el = ref.current;
      if (!el) return;
      el.querySelector('h2')?.focus({ preventScroll: true });
      el.scrollIntoView({ block: 'nearest', behavior: 'instant' });
    });

  const continueNow = (ev) => {
    ev.preventDefault();
    if (!selected || opening || busy) return;
    setOpening(true);
    onContinue(selected);
  };

  return (
    <div className="lb-plans" data-layout={layoutOf(brand)} style={brandStyle(brand)} {...brandFlags(brand)}>
      <main>
        <Header brand={brand} />
        <nav className="checkout-progress" aria-label="Checkout progress">
          <span className="current" aria-current="step">
            <i>1</i>Your plan
          </span>
          <span>
            <i>2</i>Your details
          </span>
          <span>
            <i>3</i>Payment
          </span>
        </nav>
        <div className="page-heading">
          <p className="eyebrow" id="therapy-name">{cfg.therapy || 'Your plan'}</p>
          <h1 id="plan-title">{cfg.title || 'Choose your plan'}</h1>
          <p className="intro">{cfg.intro || 'A plan that fits you. Choose your medication, plan length and payment option.'}</p>
        </div>

        {error && <p id="plan-error" role="status">{error}</p>}

        <div id="plan-content">
          {cfg.testNotice && (
            <p className="test-notice" role="note">
              {TEST_NOTICE}
            </p>
          )}
          <div className="plan-layout">
            <div className="plan-options">
              <section id="treatment-step">
                <div className="step-heading">
                  <span>1</span>
                  <h2 tabIndex={-1}>Choose your medication</h2>
                </div>
                <div id="treatments" className="tiles" role="group" aria-label="Medication">
                  {medications.map((m) => (
                    <Tile
                      key={m}
                      title={m}
                      selected={medication === m}
                      onClick={() => {
                        if (medication === m) return;
                        setMedication(m);
                        setMonths(null);
                        setPlanId(null);
                        moveTo(durationRef);
                      }}
                    />
                  ))}
                </div>
                <p className="hint eligibility-note">Treatment and dose depend on clinical eligibility and approval.</p>
              </section>

              <section id="duration-step" ref={durationRef} hidden={!medication}>
                <div className="step-heading">
                  <span>2</span>
                  <h2 tabIndex={-1}>Choose your plan length</h2>
                </div>
                <p className="section-copy">One upfront price for your full plan.</p>
                <div id="durations" className="duration-cards" role="group" aria-label="Duration plans">
                  {medication &&
                    durations.map((d) => {
                      const c = choicesFor(medication, d);
                      if (!c.length) return null;
                      return (
                        <Tile
                          key={d}
                          data-duration={d}
                          selected={months === d}
                          onClick={() => {
                            setMonths(d);
                            setPlanId(null);
                            moveTo(paymentRef);
                          }}
                        >
                          <span className="duration-description">
                            <strong className="duration-name">{planLengthName(d)}</strong>
                            <span>{deliverySummary(c)}</span>
                          </span>
                          <span className="duration-price">
                            <strong>{lowestPrice(c)}</strong>
                            <span>paid upfront</span>
                          </span>
                        </Tile>
                      );
                    })}
                </div>
              </section>

              <section id="payment-step" ref={paymentRef} hidden={!months}>
                <div className="step-heading">
                  <span>3</span>
                  <h2 tabIndex={-1}>One-time or subscription?</h2>
                </div>
                <div id="payments" className="payment-tiles" role="group" aria-label="Purchase options">
                  {[...choices]
                    .sort((a, b) => Number(a.purchase_type === 'subscription') - Number(b.purchase_type === 'subscription'))
                    .map((p) => (
                      <Tile key={p.plan_id} title={paymentTitle(p)} selected={planId === p.plan_id} onClick={() => setPlanId(p.plan_id)}>
                        <span className="payment-price">{money(p.price, p.currency)}</span>
                        <span className="payment-copy">{paymentTerms(p)}</span>
                      </Tile>
                    ))}
                </div>
              </section>
            </div>

            <aside aria-label="Your selection">
              <p className="eyebrow">Your order summary</p>
              <div className="summary-product">
                <div className="package-art" aria-hidden="true">
                  {PACKAGE_ART}
                </div>
                <div>
                  <span className="summary-caption">Your selected medication</span>
                  <h2 id="selection-title">{medication || 'Your plan'}</h2>
                </div>
              </div>
              <div id="selection-details">
                <SummaryRow label="Medication" value={medication || 'Choose medication'} />
                <SummaryRow label="Plan length" value={months ? planLengthName(months) : 'Choose a plan'} />
                <SummaryRow label="Payment" value={selected ? paymentTitle(selected) : 'Choose an option'} />
                {selected ? (
                  <>
                    <p className="summary-terms">{paymentTerms(selected)}</p>
                    <div className="selection-total">
                      <span>Total upfront</span>
                      <strong>{money(selected.price, selected.currency)}</strong>
                    </div>
                    {monthlyEquivalent(selected) && <p className="monthly-equivalent">{monthlyEquivalent(selected)}</p>}
                  </>
                ) : (
                  <p className="summary-prompt">{months ? 'Choose one-time or subscription to see your total.' : 'Choose a plan length to see your price.'}</p>
                )}
              </div>
              {selected && (
                <a id="plan-continue" className="continue" href="#details" aria-disabled={opening || busy ? 'true' : undefined} onClick={continueNow}>
                  {opening || busy ? 'Opening your secure checkout…' : 'Continue to your details →'}
                </a>
              )}
              <p className="hint summary-note">Review your details and final total before you pay.</p>
              <div className="secure-note">
                {LOCK}
                Secure, encrypted card payments
              </div>
            </aside>
          </div>
        </div>
        <Footer brand={brand} />
      </main>
    </div>
  );
}
