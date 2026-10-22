# Local development

Use Python 3.12 and Node.js 22. Development needs no Sticky or Stripe credentials. Its demo database is separate from Fly and from the disposable automated-test state.

From the repository root:

```sh
python3.12 -m venv .venv
.venv/bin/python -m pip install -r tools/stripe-v2-checkout/requirements-dev.txt
npm --prefix tools/stripe-v2-checkout/qa ci --ignore-scripts
tools/stripe-v2-checkout/qa/node_modules/.bin/playwright install chromium
.venv/bin/python tools/stripe-v2-checkout/dev.py
```

For a checkout that already has `.venv` and a project-local Node runtime, run `source scripts/dev-env.sh` from the repository root to make Python, Node and npm available in that terminal. The initial Mac setup installed these dependencies in `~/Projects/laughing-buddha`; `.tools` and `.venv` are ignored by Git.

Open `http://localhost:8081/admin` in Chrome. On first start, the terminal prints a private local owner setup URL; open it privately and choose your own local account. Do not commit, share or paste setup links into issues or reports. Chrome treats localhost as trustworthy for the app's Secure cookies. Use `localhost`, not `127.0.0.1`, in the browser. The server binds to loopback only.

The demo catalog contains clearly labeled synthetic treatment alternatives for 1-, 3-, 6- and 12-month plans. Add a site using Demo Brand and campaign 422 or create a new synthetic campaign. The review/apply flow runs against local persisted fixture objects. Authorization and capture are blocked. The demo's prices and metadata are examples, not medication catalog or clinical decisions.

State persists under `tools/stripe-v2-checkout/.state/development`. Never put a Fly database or real customer records there. Backend tests and browser tests create and remove their own temporary directories and owners independently.

## Verify changes

```sh
.venv/bin/python -m unittest discover -s tools/stripe-v2-checkout -p 'test_*.py'
.venv/bin/python tools/stripe-v2-checkout/qa/run.py
```

The full runner executes backend tests, JavaScript syntax checks and Chromium browser scenarios. It writes ignored artifacts under `tools/stripe-v2-checkout/qa/results` and updates `docs/QA_REPORT.md`. Browser tests use fake Sticky responses, a Stripe contract stub and blocked external requests. On Linux, install browser dependencies with `playwright install --with-deps chromium`.

The browser runner automatically detects Chrome in its standard macOS location. To select another executable explicitly:

```sh
QA_CHROMIUM_EXECUTABLE='/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' \
  .venv/bin/python tools/stripe-v2-checkout/qa/run.py
```

Do not use hosted owner setup or production payments as test fixtures. Consult the committed QA report for the exact passing scope of the current release.
