// Thin client for the Site Payment API.
// Docs: <baseUrl>/../../sites/<siteId>/docs  (Swagger)

export class ApiError extends Error {
  constructor(status, detail) {
    super(formatDetail(detail) || `Request failed (${status})`);
    this.status = status;
    this.detail = detail;
  }
}

function formatDetail(detail) {
  if (!detail) return '';
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    // FastAPI 422 validation errors
    return detail
      .map((d) => {
        const field = Array.isArray(d.loc) ? d.loc.filter((p) => p !== 'body').join(' › ') : '';
        return field ? `${field}: ${d.msg}` : d.msg;
      })
      .join('\n');
  }
  return JSON.stringify(detail);
}

export function createApi(site) {
  const base = `${site.api.baseUrl.replace(/\/$/, '')}/${encodeURIComponent(site.siteId)}`;
  const plansMethod = (site.api.plansMethod || 'GET').toUpperCase();

  async function request(method, path, { body, token, signal } = {}) {
    const headers = { Accept: 'application/json' };
    if (body !== undefined) headers['Content-Type'] = 'application/json';
    if (token) headers.Authorization = `Bearer ${token}`;
    let res;
    try {
      res = await fetch(base + path, {
        method,
        headers,
        body: body !== undefined ? JSON.stringify(body) : undefined,
        signal,
      });
    } catch (e) {
      if (e.name === 'AbortError') throw e;
      throw new ApiError(0, 'Could not reach the checkout service. Check your connection and try again.');
    }
    const text = await res.text();
    let data = null;
    try {
      data = text ? JSON.parse(text) : null;
    } catch {
      data = text;
    }
    if (!res.ok) throw new ApiError(res.status, data?.detail ?? data);
    return data;
  }

  return {
    base,

    // Plans: GET today. Switch to POST in sites.json ("plansMethod": "POST")
    // once the backend accepts it; the body below is what we will send.
    getPlans(signal) {
      if (plansMethod === 'POST') {
        return request('POST', '/plans', {
          body: { site_id: site.siteId, domain: window.location.hostname },
          signal,
        });
      }
      return request('GET', '/plans', { signal });
    },

    createSession(planId) {
      return request('POST', '/sessions', { body: { plan_id: planId } });
    },
    getStatus(s) {
      return request('GET', `/sessions/${encodeURIComponent(s.sessionId)}`, { token: s.token });
    },
    getConfiguration(s) {
      return request('GET', `/sessions/${encodeURIComponent(s.sessionId)}/configuration`, { token: s.token });
    },
    quote(s, contact, shippingId) {
      return request('POST', `/sessions/${encodeURIComponent(s.sessionId)}/quote`, {
        token: s.token,
        body: { contact, shipping_id: shippingId ?? null },
      });
    },
    preparePayment(s, quoteId, acceptTerms) {
      return request('POST', `/sessions/${encodeURIComponent(s.sessionId)}/payment`, {
        token: s.token,
        body: { quote_id: quoteId, accept_terms: !!acceptTerms },
      });
    },
    resume(s) {
      return request('POST', `/sessions/${encodeURIComponent(s.sessionId)}/resume`, { token: s.token, body: {} });
    },
    // After capture: one-time member-portal invitation for this order.
    portal(s) {
      return request('POST', `/sessions/${encodeURIComponent(s.sessionId)}/portal`, { token: s.token, body: {} });
    },
    complete(s, paymentIntentId) {
      return request('POST', `/sessions/${encodeURIComponent(s.sessionId)}/complete`, {
        token: s.token,
        body: { payment_intent_id: paymentIntentId },
      });
    },
  };
}
