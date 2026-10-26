# Collaboration and releases

Use feature branches and reviewed pull requests. Repository cleanup, passing tests and merging a PR do not deploy an application or authorize changes to GitHub access, production data or provider configuration.

## Shared code

The active application lives under `tools/stripe-v2-checkout`. Follow [Contributing](../CONTRIBUTING.md) and [local development](LOCAL_DEVELOPMENT.md). Stage specific files and preserve unrelated changes in a shared checkout.

The [Tests workflow](../.github/workflows/tests.yml) runs on pull requests and configured branch pushes. It uses synthetic/fake providers rather than live payment credentials. Check the actual GitHub branch protections, required reviews and environment settings before relying on them; these settings are not enforced merely by a Markdown file.

## Fly staging

[Deploy Fly staging](../.github/workflows/fly-staging.yml) is a manual `workflow_dispatch` workflow. It runs verification before deploying the selected revision, using the GitHub `staging` environment and `FLY_STAGING_API_TOKEN` secret. The token must be scoped to the staging app.

`fly.staging.toml` targets a separate app and `staging_data` volume. Synthetic mode blocks payment authorization. Never supply live customer databases, invitations or provider credentials to this environment. Check existing infrastructure and credentials instead of blindly recreating them.

Read-only configuration checks, from the repository root:

```sh
.venv/bin/python scripts/check_staging.py
.venv/bin/python scripts/check_staging.py --health
```

The first checks the committed app/volume/environment separation. The second also checks the hosted health response and therefore needs network access. It does not deploy or submit payment.

## Shared live Fly application

The current shared product environment is `wlmd-stripe-test-0f89b1bb`; its historical name does not make its payments synthetic. The repository has no automatic live deployment on merge.

An authorized release operator should:

1. Choose the reviewed source revision and run relevant checks. Inspect the build inputs; do not package unrelated local experiments or AWS adaptations accidentally.
2. Inspect active payment operations, storage capacity and current release identity. Back up persistent databases and private keys without putting them in Git or build artifacts.
3. Build a reviewed image and record its immutable digest and rollback image. Preserve the existing app, volume and account records.
4. Deploy during an appropriate window, then verify health, authentication boundaries, asset/source identity and record preservation. Routine smoke tests must not charge, retry payments or create provider orders.
5. Record sanitized evidence and any remaining limitations. A healthy process is not full checkout or clinical integration verification.

The current Fly deployment uses one machine/worker and local persistent SQLite state. Do not scale it horizontally without changing its coordination/storage design. Preserve uncertain payment attempts, databases and private account keys across restarts.

For implementation details, consult [capture setup reuse](CAPTURE_SETUP_REUSE_2026-10-26.md), [Fly operations](../tools/stripe-v2-checkout/FLY.md), and dated release evidence such as [payment confirmation timing](PAYMENT_CONFIRMATION_TIMING_2026-10-26.md). Older provisioning commands and environment-specific paths are historical; inspect current resources before using them.

## AWS target

AWS/MySQL and native Python 3.9 compatibility work is a separate migration target. This cleanup branch does not add those packages or release them through the Fly workflow. Validate schema compatibility, credentials, route prefixes, TLS and process isolation for that target before claiming it is ready. Do not stop unrelated services or import a data package as a side effect of a code release.

See [the AWS plan](AWS_PLATFORM_PLAN.md). Historical setup instructions must be checked against the target environment; an already-running server needs an update procedure, not first-install commands.
