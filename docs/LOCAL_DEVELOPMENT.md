# Local development

Use **Python 3.12** and **Node.js 22** for the main application and CI. Python 3.9/MySQL packaging is a separate AWS compatibility target. Start from a shell without production credentials, database settings or a production publication manifest. Do not source a hosted environment file.

## Install and start

From the repository root:

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r tools/stripe-v2-checkout/requirements-dev.txt
npm --prefix tools/stripe-v2-checkout/qa ci --ignore-scripts
tools/stripe-v2-checkout/qa/node_modules/.bin/playwright install chromium
```

On Linux, the browser may require system libraries; the CI workflow installs them with `playwright install --with-deps chromium`. Do not run a system dependency installer on a shared server as part of local setup.

Start the synthetic application:

```sh
env -u CHECKOUT_DB_BACKEND -u SITE_API_MANIFEST \
  .venv/bin/python tools/stripe-v2-checkout/dev.py
```

Open **http://localhost:8081/admin**. On first start, the terminal prints a private local owner-setup URL; open it privately and choose your own local account. Keep setup links out of reports. Use `localhost` in Chrome for the app's Secure cookies; the service binds only to loopback.

The runner explicitly enables the synthetic catalog and blocks payment authorization/capture. It requires no Sticky, Stripe or WLMD credentials. Use Demo Brand/campaign 422 or create a synthetic campaign through the admin. These fixture plans are examples, not approved clinical or commercial catalog data.

Development state persists under `tools/stripe-v2-checkout/.state/development`. Test fixtures create separate temporary state. Do not copy hosted databases, keys, orders or patient records into either location. `CHECKOUT_DB_BACKEND` is process-wide, which is why the command above clears it rather than inheriting a MySQL target.

## Verify changes

Repository preflight:

```sh
python3 scripts/check_repository_hygiene.py
python3 -m unittest discover -s scripts/tests -p 'test_*.py'
git diff --check
```

Full application suite from the repository root:

```sh
.venv/bin/python tools/stripe-v2-checkout/qa/run.py
```

The runner executes backend tests, JavaScript syntax checks and Chromium scenarios using fake services. Browser requests to external providers are blocked by their fixtures. It writes ignored artifacts to `tools/stripe-v2-checkout/qa/results` and regenerates `docs/QA_REPORT.md`; review any report change before committing it.

For a focused backend change:

```sh
cd tools/stripe-v2-checkout
../../.venv/bin/python -m unittest -v test_checkout test_site_api_runtime
```

For a focused browser change, from the repository root:

```sh
QA_PYTHON="$PWD/.venv/bin/python" \
  tools/stripe-v2-checkout/qa/node_modules/.bin/playwright test \
  --config tools/stripe-v2-checkout/qa/playwright.config.cjs sites.spec.cjs
```

The browser config detects standard macOS Chrome and Linux Chromium locations. Set `QA_CHROMIUM_EXECUTABLE` to an installed browser's absolute path when needed. The optional `source scripts/dev-env.sh` adds an existing repository `.venv` and `.tools/node/bin` to the current shell's PATH.

The migration work may add separate MySQL persistence tests. Those must use a disposable database; ordinary development on this branch uses SQLite. Never point a test suite at a shared or production database.

## What the tests establish

Automated tests verify application behavior with controlled providers. They do not establish live gateway settlement, pharmacy fulfillment, clinician messaging or hosted readiness. Any provider integration test needs its own explicit scope and evidence. See [Contributing](../CONTRIBUTING.md) and [Security](../SECURITY.md).
