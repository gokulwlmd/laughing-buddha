import { useEffect, useMemo, useState } from 'react';
import { applyDocument, brandOf, brandStyle, loadSiteConfig } from './config/siteConfig.js';
import { createApi } from './api/client.js';
import { useCheckout } from './checkout/useCheckout.js';
import PlansView from './views/PlansView.jsx';
import CheckoutView from './views/CheckoutView.jsx';

export default function App() {
  const [site, setSite] = useState(null);
  const [catalog, setCatalog] = useState(null);
  const [fatal, setFatal] = useState(null);

  useEffect(() => {
    const ctrl = new AbortController();
    (async () => {
      let s;
      try {
        s = await loadSiteConfig();
        applyDocument(s, brandOf(s));
        setSite(s);
      } catch (e) {
        setFatal(e.message || 'Checkout could not be loaded.');
        return;
      }
      try {
        const c = await createApi(s).getPlans(ctrl.signal);
        setCatalog(c);
      } catch (e) {
        if (e.name !== 'AbortError') setFatal('These plans are temporarily unavailable. Please contact us for help.');
      }
    })();
    return () => ctrl.abort();
  }, []);

  if (!site) return fatal ? <Fatal message={fatal} /> : <Loading label="Loading checkout…" />;
  const brand = brandOf(site, catalog);
  if (fatal) return <Fatal message={fatal} brand={brand} retry />;
  if (!catalog) return <Loading label="Loading your plan options…" brand={brand} />;
  return <Checkout site={site} brand={brand} catalog={catalog} />;
}

function Checkout({ site, brand, catalog }) {
  const api = useMemo(() => createApi(site), [site]);
  const c = useCheckout(site, api);
  const plan = catalog.plans.find((p) => p.plan_id === c.data.planId);

  if (c.step === 'init') return <Loading label="Loading your checkout…" brand={brand} />;
  if (c.step === 'plans') {
    return (
      <PlansView
        site={site}
        brand={brand}
        plans={catalog.plans}
        initialPlanId={c.data.planId}
        busy={c.busy}
        error={c.error || (catalog.plans.length ? null : 'No plans are available right now. Please contact us for help.')}
        onContinue={c.selectPlan}
      />
    );
  }
  return <CheckoutView site={site} brand={brand} plan={plan} c={c} />;
}

function Loading({ label, brand }) {
  return (
    <div className="lb-plans app-loading" style={brand ? brandStyle(brand) : undefined}>
      <main>
        <p className="loading" role="status">
          {label}
        </p>
      </main>
    </div>
  );
}

function Fatal({ message, brand, retry }) {
  return (
    <div className="lb-plans" style={brand ? brandStyle(brand) : undefined}>
      <main>
        <div className="page-heading">
          <h1>Checkout unavailable</h1>
        </div>
        <p id="plan-error" role="status">
          {message}
        </p>
        {retry && (
          <button id="retry-plans" type="button" onClick={() => window.location.reload()}>
            Try loading plans again
          </button>
        )}
      </main>
    </div>
  );
}
