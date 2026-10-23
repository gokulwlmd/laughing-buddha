# WLMD Checkout Frontend (React)

One codebase and one build for every brand. **The domain picks the brand**: each domain has its own flat JSON file in `sites/<domain>.json`, the same way the member portal works. The design and flow are ported from the original hosted checkout in `laughing-buddha` (`tools/stripe-v2-checkout/web`):

| Original (backend-hosted) | Here (React) |
|---|---|
| `plans.html` + `plan-selector-v4.js/.css` | `src/views/PlansView.jsx` + `src/styles/plans.css` |
| `index.html` + `checkout-v9.js` + `checkout-v4.css` | `src/views/CheckoutView.jsx` + `src/styles/checkout.css` |
| `brand-design-v2.js` | `brandStyle()` in `src/config/siteConfig.js` |
| `checkout-font-v1.css` + Red Hat Display (OFL) | `src/styles/base.css` + `src/assets/fonts/` |
| internal `/api/config`, `/api/quote`, `/api/authorize`, `/api/capture`… | public **Site API** sessions: `/configuration`, `/quote`, `/payment`, `/complete`… |

## Run locally

```sh
npm install
npm run dev        # http://localhost:5173
```

On macOS you can also double-click `start-dev.command`.

- `http://localhost:5173` → `checkout.mastertherapy.example` (change with `DEV_SITE=… npm run dev`)
- `http://localhost:5173/?site=checkout.harborwellness.example` → Harbor Wellness
- `http://localhost:5173/?site=checkout.glowhealth.example` → Glow Health

The `?site=` choice is remembered for the browser tab.

## Site configs

```
public/sites/checkout.mastertherapy.example.json     Master Therapy   (green, system font)
public/sites/checkout.harborwellness.example.json    Harbor Wellness  (navy, serif)
public/sites/checkout.glowhealth.example.json        Glow Health      (plum, rounded, single column)
public/logos/<domain>/logo.svg, favicon.svg
```

All three use backend site `payment-test`, the only site the Site API serves today. The field reference and how to add a brand are in [`deploy/DEPLOY.md`](deploy/DEPLOY.md).

How a config is found:
1. The app loads `config.json`. nginx serves `sites/$host.json` for it (in dev, Vite does the same).
2. `?site=<domain>` loads `sites/<domain>.json`, but **only** on localhost or on a host with no config of its own (e.g. the server IP). On a real brand domain it's ignored.
3. If no config is found, the page shows "Checkout unavailable". It never falls back to another brand.

## Flow

| Screen | API call |
|---|---|
| Plan page: medication (first one, or `?product=tirzepatide`, preselected) → plan length (longest first) → one-time or subscription | `GET /plans` |
| Continue to your details (form opens at once while the session loads) | `POST /sessions`, `GET /sessions/{id}/configuration` |
| Review my order | `POST /sessions/{id}/quote` |
| Continue to payment (consent required for subscriptions) | `POST /sessions/{id}/payment` |
| Pay / Express Checkout | Stripe `confirmPayment`, then `POST /sessions/{id}/complete` |
| Thank you + order number (+ optional **Create your patient account**, when `memberPortal: true`) | `POST /sessions/{id}/portal` |

The flow also handles these cases:
- **Refresh:** the app resumes the same step. On the payment step it calls `/resume`, never a second `/payment`.
- **Bank-verification redirect (3-D Secure):** the app finishes the order automatically.
- **Expired quote:** the app re-quotes automatically. If the total changed, the customer must review it again.
- **Uncertain payment:** the app shows the "Let's check your payment" screen, and "Check payment status" never submits another payment.
- **Double clicks:** they are ignored.

## Build and deploy

```sh
npm run package    # → dist/ and wlmd-checkout-build.zip
```

nginx: `deploy/snippets/unified_checkout.conf` (shared) plus one 5-line file per domain in `deploy/sites-available/`. Full steps: [`deploy/DEPLOY.md`](deploy/DEPLOY.md).

## Tests

The tests use a **mock API and a stub Stripe**, so nothing real is charged.

```sh
npm install && npx playwright install chromium    # first time
npm run build && npm run preview -- --port 4173 &
npm run test:e2e          # happy path + 19 edge cases
npm run test:e2e:pay      # happy path with payments on → order confirmed (mocked)
```

To test against a real nginx using the real domain names:
```sh
export CHROMIUM_ARGS="--host-resolver-rules=MAP *.example 127.0.0.1, MAP test-ip.local 127.0.0.1" FETCH_VIA=127.0.0.1
BASE_PORT=80 node tests/domains.mjs
APP_URL=http://checkout.mastertherapy.example node tests/edge.mjs
```

## Project layout

```
public/sites/                 one config per domain
public/logos/<domain>/        logos + favicons
src/config/siteConfig.js      config loading, flat → internal, brand CSS variables
src/api/client.js             Site API client (plans GET/POST switch)
src/checkout/useCheckout.js   flow state, recovery, double-click guard
src/views/                    PlansView, CheckoutView (ported)
src/styles/                   ported CSS (scoped) + base
deploy/                       nginx snippet, per-domain server blocks, DEPLOY.md
tests/                        browser tests
vite.config.js                dev/preview: config.json → sites/<host>.json
```
