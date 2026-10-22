# GitHub collaboration and Fly staging

Work from separate local clones and feature branches, open pull requests, and merge after review and passing tests. GitHub is the shared code and decision history; Fly hosts a separate shared staging application. The live Fly app and its database remain independent.

## Branch and review workflow

```sh
git switch main
git pull --ff-only
git switch -c codex/describe-the-change
# Implement and run the documented tests.
git add <specific-files>
git commit -m 'Describe the resulting behavior'
git push -u origin HEAD
```

Open a PR into `main`. The **Tests / Backend and browser tests** job runs without payment credentials on every PR and pushes to `main` or `codex/**`. Review the behavior, QA evidence and affected links before merging. Two collaborators were already visible in GitHub access settings during setup; no new invitation or access change was needed.

`main` now has a GitHub branch protection rule requiring a pull request, one approval and the `Backend and browser tests` check from GitHub Actions. Force pushes and branch deletion remain disallowed. The standard administrator bypass setting remains unchanged. Branch protection is a GitHub setting, not something a committed workflow enforces. Avoid approving your own change as a substitute for collaborator review.

## Isolated staging configuration

`tools/stripe-v2-checkout/fly.staging.toml` targets `wlmd-checkout-staging-0f89b1bb`, using its own `staging_data` volume and synthetic catalog. `fly.toml` still targets the existing live app and remains unchanged.

Staging uses `CHECKOUT_ENVIRONMENT=staging` and forces payment authorization off. Its adapter never contacts Sticky or Stripe. Do not copy live secrets, customer data, invitations or the production database. Staging has its own owner setup; the operator retrieves that URL privately using Fly SSH and the owner creates their own account.

Initial infrastructure, if not already provisioned:

```sh
flyctl auth whoami
flyctl apps create wlmd-checkout-staging-0f89b1bb --org personal
flyctl volumes create staging_data --app wlmd-checkout-staging-0f89b1bb --region iad --size 1 --yes
flyctl ips allocate-v6 --app wlmd-checkout-staging-0f89b1bb
flyctl ips allocate-v4 --shared --app wlmd-checkout-staging-0f89b1bb
```

Check existing resources first; do not repeat creation blindly or replace the live infrastructure. Keep one staging worker and one machine because SQLite and payment intent handling are not designed for horizontal scaling. Staging can stop while idle. Volume storage remains billable while the app is stopped.

Staging was provisioned and deployed on 22 October 2026. Hosted health, private admin access and tested asset hashes passed. See [the non-secret deployment record](../tools/stripe-v2-checkout/staging-deployment.json). The owner has completed staging account setup. Use the existing staging account; do not recreate or seed it.

## Manual deployment button

In GitHub, configure an environment named **staging** and its secret **FLY_STAGING_API_TOKEN**, using a Fly deploy token scoped exclusively to the staging app. The staging environment and this secret were created and their presence verified on 22 October 2026. No secret value is stored in this repository. A local Fly login is not automatically a GitHub Actions secret. Supply the token directly to GitHub Secrets; never commit it or paste it in chat. Use a short expiry and renew deliberately. Do not use the live app's deploy token or an account-wide token.

After the workflow has been merged into the default branch, open **Actions → Deploy Fly staging → Run workflow** and select the branch to test. Deployment runs only on this manual action. It first runs the backend/browser suite, checks the isolated config, deploys with one machine, then checks `/health` for `synthetic=true`, `payments_blocked=true` and `authorization_contract_verified=false`. Tests and deployments report the selected Git commit in GitHub Actions history.

For a first operator deployment before the button is available:

```sh
.venv/bin/python scripts/check_staging.py
cd tools/stripe-v2-checkout
flyctl deploy --config fly.staging.toml --remote-only --ha=false --strategy immediate --yes
```

From the root, run `.venv/bin/python scripts/check_staging.py --health` after deployment. This workflow never deploys `fly.toml` or restarts the live machine. Production requires its separate payment-state checks and deployment procedure.

Fly recommends app-scoped tokens for CI: [Fly access tokens](https://fly.io/docs/security/tokens/). GitHub environments can restrict deployments and protect secrets: [GitHub deployment environments](https://docs.github.com/en/actions/concepts/workflows-and-actions/deployment-environments).
