# Security and sensitive data

This application handles payments, identity information and patient records. This document describes contributor practices; it is not a compliance certification or a claim that every integration is production-ready.

## Report privately

Send suspected vulnerabilities to the repository owner or designated security maintainer through an established private channel. Use GitHub private vulnerability reporting if it is enabled for this repository. Do not open a public issue containing credentials, patient details, database extracts, exploitable account links or reproduction tokens.

Include the affected component, commit/release if known, expected and observed behavior, and a sanitized reproduction. A synthetic account is preferred. Do not test against another patient's account or perform a charge to demonstrate a report.

## Keep secrets and records out of Git

- Supply credentials through the deployment's secret store or a private environment file outside the served web directory. Do not place them in source, browser bundles, command arguments, screenshots or CI output.
- Keep database files/backups, session tokens, owner setup links, ID images, SSN data, intake answers and provider request/response dumps out of commits, issues and build artifacts.
- Use synthetic test fixtures. Do not copy a production database into local development, CI or staging.
- Review diffs and files before pushing. `.gitignore` and repository hygiene checks are limited safeguards; previously tracked files can remain in Git history.

If a credential or sensitive record is exposed, notify the owner privately. Revoke or rotate the exposed credential through its provider and assess affected access. Removing the visible text alone does not revoke it. Coordinate any history remediation; do not force-push shared history without approval.

## Application boundaries to preserve

Site and patient ownership checks belong on every server action. Knowing an email address or order number is not proof of access. Keep owner sessions, patient sessions and checkout session tokens distinct.

Card entry must use the approved provider-hosted payment interface. Never add raw card-number/CVV fields to our API, logs or database. Display caches must not become authority for charges or permission to retry a financial write.

Keep identity and intake reuse scoped to the authorized site/account. Recorded answers or a verification upload must not be presented as clinician approval. Do not label disconnected provider actions as completed.

## Operational verification

Use read-only health checks and isolated automated fixtures for routine verification. Provider Dry Run orders, live payment tests, imports and credential changes require explicit authorization for their scope. Preserve existing orders, attempts and private encryption keys during a release; follow [release procedures](docs/COLLABORATION.md).
