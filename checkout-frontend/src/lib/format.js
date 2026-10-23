// Plan prices from /plans are major-unit strings ("249.00").
// Quote/payment amounts are integer minor units (24900).
// Wording below matches the original checkout (web/plan-selector-v3.js, checkout-v9.js).

export function money(major, currency = 'USD') {
  const n = typeof major === 'string' ? Number(major) : major;
  if (!Number.isFinite(n)) return String(major);
  return new Intl.NumberFormat('en', { style: 'currency', currency: currency.toUpperCase() }).format(n);
}

export function moneyMinor(minor, currency = 'USD') {
  return money(minor / 100, currency);
}

export const isSubscription = (plan) => plan.purchase_type === 'subscription' || !!plan.renewal_days;

export function paymentTitle(plan) {
  return isSubscription(plan) ? 'Subscription' : 'One-time purchase';
}

export function planLengthName(months) {
  return `${months}-month plan`;
}

function deliveries(plan) {
  const days = plan.shipment_days || [];
  return days.length > 1 ? { count: days.length, gap: days[1] - days[0] } : null;
}

// Payment tile copy on the plan page.
export function paymentTerms(plan) {
  const amount = money(plan.price, plan.currency);
  const d = deliveries(plan);
  if (d) {
    return `${amount} upfront. ${d.count} scheduled deliveries, ${d.gap} days apart. ${
      plan.renewal_days ? `Renews every ${plan.renewal_days} days for the full plan price.` : 'No automatic renewal.'
    }`;
  }
  return plan.renewal_days
    ? `${amount} per payment. Renews every ${plan.renewal_days} days.`
    : `${amount} upfront. One payment, no automatic renewal.`;
}

// Order-summary terms on the checkout page.
export function summaryTerms(plan) {
  const d = deliveries(plan);
  if (d) {
    return `${d.count} scheduled deliveries, ${d.gap} days apart. ${
      plan.renewal_days ? `Full plan renews every ${plan.renewal_days} days.` : 'No automatic renewal.'
    }`;
  }
  return plan.renewal_days ? `Renews every ${plan.renewal_days} days.` : 'One payment. No automatic renewal.';
}

// Duration card price line: one price, or each distinct price with its payment type.
export function priceSummary(choices) {
  if (!choices.length) return 'Temporarily unavailable';
  const prices = [...new Set(choices.map((p) => money(p.price, p.currency)))];
  if (prices.length === 1) return `${prices[0]} upfront`;
  return [...new Set(choices.map((p) => `${money(p.price, p.currency)} ${isSubscription(p) ? 'subscription' : 'one-time'}`))].join(' / ');
}

// Duration card sub-line (plan-selector-v4): the delivery schedule when all choices share one.
export function deliverySummary(choices) {
  const schedules = [...new Set(choices.map((p) => {
    const d = deliveries(p);
    return d ? `${d.count} deliveries, ${d.gap} days apart` : 'Full plan paid upfront';
  }))];
  return schedules.length === 1 ? schedules[0] : 'Full plan paid upfront';
}

// Duration card price: "$X" or "From $X" when the choices differ.
export function lowestPrice(choices) {
  if (!choices.length) return null;
  const low = [...choices].sort((a, b) => Number(a.price) - Number(b.price))[0];
  const different = new Set(choices.map((p) => money(p.price, p.currency))).size > 1;
  return (different ? 'From ' : '') + money(low.price, low.currency);
}

// Optional "Equivalent to $X/month" line under the total.
export function monthlyEquivalent(plan) {
  const m = Number(plan.duration_months);
  return m > 1 ? `Equivalent to ${money(Number(plan.price) / m, plan.currency)}/month. Paid in full upfront.` : '';
}
