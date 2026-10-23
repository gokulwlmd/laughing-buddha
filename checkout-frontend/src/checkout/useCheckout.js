import { useCallback, useEffect, useRef, useState } from 'react';
import { loadStripe } from '@stripe/stripe-js';
import { loadCheckout, saveCheckout } from '../lib/storage.js';

// Steps: plans → details → review → payment → done   (+ held, for uncertain payments)
const QUOTE_TTL_MS = 9.5 * 60 * 1000; // API quotes expire after 10 minutes
const PENDING = new Set(['authorization_pending', 'capture_pending', 'needs_review']);

const stripeCache = new Map();
export function getStripe(publishableKey) {
  if (!stripeCache.has(publishableKey)) stripeCache.set(publishableKey, loadStripe(publishableKey));
  return stripeCache.get(publishableKey);
}

function stripeReturnParams() {
  const q = new URLSearchParams(window.location.search);
  const secret = q.get('payment_intent_client_secret');
  return secret ? { intentId: q.get('payment_intent'), secret } : null;
}

function cleanUrl() {
  const q = new URLSearchParams(window.location.search);
  ['payment_intent', 'payment_intent_client_secret', 'redirect_status'].forEach((k) => q.delete(k));
  const rest = q.toString();
  window.history.replaceState(null, '', window.location.pathname + (rest ? `?${rest}` : ''));
}

export function useCheckout(site, api) {
  const [step, setStep] = useState('init');
  const [data, setData] = useState({}); // persisted: session, planId, contact, shippingId, quote, publishableKey
  const [config, setConfig] = useState(null);
  const [payment, setPayment] = useState(null); // {client_secret, publishable_key, amount, currency, payment_intent_id}
  const [receipt, setReceipt] = useState(null);
  const [error, setError] = useState(null);
  const [notice, setNotice] = useState(null);
  const [busy, setBusy] = useState(false);
  const [holdNote, setHoldNote] = useState(null);
  const started = useRef(false);
  const inflight = useRef(false); // synchronous guard against double clicks

  const persist = useCallback(
    (next) => {
      setData(next);
      saveCheckout(site, next && Object.keys(next).length ? next : null);
    },
    [site],
  );

  const reset = useCallback(() => {
    persist({});
    setConfig(null);
    setPayment(null);
    setReceipt(null);
    setNotice(null);
    setError(null);
    setStep('plans');
  }, [persist]);

  const fail = useCallback(
    (e) => {
      if (e?.status === 401 || e?.status === 404 || e?.status === 410) {
        // Session gone/expired: never retry a payment automatically.
        reset();
        setError(
          e.status === 410
            ? 'This checkout expired. If you started a payment, please contact support before paying again.'
            : 'This checkout is no longer available. Please choose your plan again.',
        );
        return;
      }
      setError(e?.message || 'Something went wrong.');
    },
    [reset],
  );

  const run = useCallback(
    async (fn) => {
      if (inflight.current) return undefined;
      inflight.current = true;
      setBusy(true);
      setError(null);
      try {
        return await fn();
      } catch (e) {
        fail(e);
        return undefined;
      } finally {
        inflight.current = false;
        setBusy(false);
      }
    },
    [fail],
  );

  // Route an existing session to the right step using the server's status.
  const routeFromStatus = useCallback(
    async (saved) => {
      const s = saved.session;
      const status = await api.getStatus(s);
      if (status.status === 'captured') {
        setReceipt(status);
        setStep('done');
        return 'done';
      }
      if (PENDING.has(status.status)) {
        setReceipt(status);
        setStep('held');
        return 'held';
      }
      let cfg;
      try {
        cfg = await api.getConfiguration(s);
      } catch (e) {
        if (e?.status === 409 && status.status === 'new') {
          // Nothing was paid yet: send the customer back to choose again.
          reset();
          setError('That plan is not available right now. Please choose another plan.');
          return 'plans';
        }
        throw e;
      }
      setConfig(cfg);
      if (status.status === 'awaiting_card') {
        const p = await api.resume(s);
        setPayment(p);
        setStep('payment');
        return 'payment';
      }
      // status "new": back to review if the quote is still fresh, else details.
      const fresh = saved.quote && Date.now() - saved.quote.quotedAt < QUOTE_TTL_MS;
      const next = fresh ? 'review' : 'details';
      setStep(next);
      return next;
    },
    [api, reset],
  );

  const finish = useCallback(
    async (session, intentId) => {
      const result = await api.complete(session, intentId);
      if (result.status === 'captured') {
        setReceipt(result);
        setStep('done');
      } else {
        setReceipt(result);
        setStep('held');
      }
    },
    [api],
  );

  // Initial load: Stripe redirect return → saved session → fresh start.
  useEffect(() => {
    if (started.current) return;
    started.current = true;
    const saved = loadCheckout(site) || {};
    setData(saved);
    const ret = stripeReturnParams();
    (async () => {
      setBusy(true);
      try {
        if (ret && saved.session && saved.publishableKey) {
          cleanUrl();
          const stripe = await getStripe(saved.publishableKey);
          const { paymentIntent, error: se } = await stripe.retrievePaymentIntent(ret.secret);
          if (se) throw se;
          if (paymentIntent.status === 'requires_capture') {
            await finish(saved.session, paymentIntent.id);
            return;
          }
          setError(
            paymentIntent.status === 'requires_payment_method'
              ? 'Your payment was not completed. Please try another payment method.'
              : `Payment status: ${paymentIntent.status}.`,
          );
          await routeFromStatus(saved);
          return;
        }
        if (ret) cleanUrl();
        if (saved.session) {
          await routeFromStatus(saved);
          return;
        }
        setStep('plans');
      } catch (e) {
        fail(e);
        if (!saved.session) setStep('plans');
        // Could not confirm where this checkout stands: show the safe recovery screen.
        else if (![401, 404, 410].includes(e?.status)) {
          setReceipt(null);
          setStep('held');
        }
      } finally {
        setBusy(false);
      }
    })();
  }, [site, finish, routeFromStatus, fail]);

  // Opens the details form right away (customers can type) while the session and
  // configuration load; submitting stays disabled until configuration is verified.
  const selectPlan = async (plan) => {
    if (inflight.current) return;
    inflight.current = true;
    setError(null);
    setNotice(null);
    setConfig(null);
    setPayment(null);
    setReceipt(null);
    const base = { planId: plan.plan_id, contact: data.contact, shippingId: data.shippingId };
    persist(base);
    setStep('details');
    setBusy(true);
    try {
      const created = await api.createSession(plan.plan_id);
      const session = { sessionId: created.session_id, token: created.session_token, expiresAt: created.expires_at };
      persist({ ...base, session });
      const cfg = await api.getConfiguration(session);
      persist({ ...base, session, publishableKey: cfg.publishable_key });
      setConfig(cfg);
    } catch (e) {
      setStep('plans');
      fail(e);
    } finally {
      inflight.current = false;
      setBusy(false);
    }
  };

  const submitDetails = (contact, shippingId) =>
    run(async () => {
      const q = await api.quote(data.session, contact, shippingId);
      persist({ ...data, contact, shippingId, quote: { ...q, quotedAt: Date.now() } });
      setNotice(null);
      setStep('review');
    });

  const preparePayment = (acceptTerms) =>
    run(async () => {
      let quote = data.quote;
      if (!quote || Date.now() - quote.quotedAt >= QUOTE_TTL_MS) {
        // Expired quote: get a fresh one and make the customer review it again.
        const q = await api.quote(data.session, data.contact, data.shippingId);
        const next = { ...q, quotedAt: Date.now() };
        persist({ ...data, quote: next });
        if (q.amount !== quote?.amount || q.payment_terms !== quote?.payment_terms) {
          setNotice('Your total was refreshed. Please review it before continuing.');
          return;
        }
        quote = next;
      }
      let p;
      try {
        p = await api.preparePayment(data.session, quote.quote_id, acceptTerms);
      } catch (e) {
        if (![401, 404, 410].includes(e?.status)) {
          try {
            const st = await api.getStatus(data.session);
            if (!['new', 'awaiting_card', 'captured'].includes(st.status)) {
              setReceipt(st);
              setStep('held');
              return;
            }
          } catch {
            /* fall through to the original error */
          }
        }
        throw e;
      }
      persist({ ...data, quote, publishableKey: p.publishable_key });
      setPayment(p);
      setStep('payment');
    });

  // Called after stripe.confirmPayment succeeds without a redirect.
  const onAuthorized = (paymentIntent) =>
    run(async () => {
      if (paymentIntent.status !== 'requires_capture') {
        setReceipt({ status: paymentIntent.status, payment_pending: true });
        setStep('held');
        return;
      }
      await finish(data.session, paymentIntent.id);
    });

  // "Check payment status": never submits another payment.
  const refreshStatus = async () => {
    if (!data.session) return reset();
    if (inflight.current) return;
    inflight.current = true;
    setBusy(true);
    setHoldNote(null);
    try {
      const next = await routeFromStatus(data);
      if (next === 'held') setHoldNote('The result is still unconfirmed. Please contact the store before trying another payment.');
    } catch (e) {
      if ([401, 404, 410].includes(e?.status)) fail(e);
      else setHoldNote('We couldn’t check the status. Please contact the store before trying another payment.');
    } finally {
      inflight.current = false;
      setBusy(false);
    }
  };

  const changePlan = () => {
    setError(null);
    setNotice(null);
    setStep('plans');
  };

  const back = () => {
    setError(null);
    setNotice(null);
    if (step === 'details') setStep('plans');
    else if (step === 'review') setStep('details');
    else if (step === 'payment') setStep('review');
  };

  // A payment may be in flight: the UI must not let the customer abandon it and pay again.
  const paymentInFlight = step === 'held' && (!receipt || receipt.payment_pending || PENDING.has(receipt.status));

  // Member portal: ask the API for this order's one-time invitation and open it.
  // Errors stay on the receipt screen; the order itself is already complete.
  const [portalBusy, setPortalBusy] = useState(false);
  const openPortal = async () => {
    if (inflight.current || !data.session) return;
    inflight.current = true;
    setPortalBusy(true);
    setError(null);
    try {
      const r = await api.portal(data.session);
      window.location.assign(r.enrollment_url);
    } catch (e) {
      setError(e?.status === 409
        ? 'Your account can’t be created from this order yet. Please contact us and we’ll send you an invitation.'
        : 'We couldn’t open account setup just now. Please try again.');
      setPortalBusy(false);
    } finally {
      inflight.current = false;
    }
  };

  const startOver = () => {
    if (paymentInFlight) return;
    reset();
  };

  return {
    step,
    data,
    config,
    payment,
    receipt,
    error,
    notice,
    busy,
    setError,
    selectPlan,
    submitDetails,
    preparePayment,
    onAuthorized,
    refreshStatus,
    back,
    startOver,
    paymentInFlight,
    holdNote,
    changePlan,
    openPortal,
    portalBusy,
  };
}
