# Contributing

Start with [local development](docs/LOCAL_DEVELOPMENT.md). Routine development and automated checks use synthetic providers and disposable state; they do not need Sticky, Stripe, WLMD or Fly credentials.

## Make a focused change

1. Work on a feature branch. The existing convention is `codex/describe-the-change`; use your team's branch policy if different.
2. Inspect `git status` before editing. Preserve unrelated work and stage specific files.
3. Change the shared backend or API contract before adding a site-specific workaround. Keep site/customer authorization enforced on the server.
4. Run the checks appropriate to the change and record their results in the pull request.
5. Have another maintainer review changes before merging. Verify GitHub's actual branch and environment protections; documentation does not enforce them.

Keep API compatibility, price/renewal disclosures, refill rules and existing records explicit in reviews. For a state-machine change, cover retries, concurrent requests and uncertain provider outcomes. For a UI change, verify the affected flow at desktop and mobile widths, including failure and loading states.

## Preflight

From the repository root:

```sh
python3 scripts/check_repository_hygiene.py
python3 -m unittest discover -s scripts/tests -p 'test_*.py'
git diff --check
git status --short
```

Run the backend/browser commands in [local development](docs/LOCAL_DEVELOPMENT.md). The **Tests** workflow checks repository hygiene and application tests. Passing CI does not certify a live provider integration, an AWS deployment or clinical readiness.

Never commit `.env` files, credentials, bearer/setup URLs, runtime databases, patient data, identity images, production logs or exported order records. The hygiene check catches selected file types and packaging mistakes; it does not replace reviewing the actual diff. See [Security](SECURITY.md).

## Payments and provider changes

Unit/browser fixtures may simulate payment actions. Running orders against Sticky's Dry Run gateway still creates provider records and requires explicit owner authorization for that test scope. Real charges, subscription billing, refunds, catalog/gateway changes and patient-data imports require their own authorized scope and reviewer scrutiny; a PR or test command is not permission to perform them.

Never resolve an uncertain financial response by deleting its local record or automatically submitting a new charge. Preserve durable identifiers, idempotency and ownership checks. Never send PAN/CVV to this backend or put provider secrets in frontend code.

## Pull requests and releases

Describe the concrete behavior change, relevant validation, and any configuration or migration work still needed. Include sanitized screenshots when they explain UI behavior; use synthetic accounts. Separate measured results from assumptions.

A merge is not a deployment. Follow [Collaboration and releases](docs/COLLABORATION.md) for the target environment. Avoid unrelated refactors in a payment incident or release fix.
