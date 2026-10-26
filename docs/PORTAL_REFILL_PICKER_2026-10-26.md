# Portal refill purchase picker — 26 October 2026

The next-supply dropdown is replaced with visible medication, duration and payment choices. For a Semaglutide or Tirzepatide order, the picker includes both medications when published in the same site's same therapy. Other products stay within their existing treatment family.

Selections use the existing authenticated store API and exact published plan ID/checkout URL. Duration labels come from the API's generated plan name; they do not determine billing or refill eligibility. The displayed price is the full upfront plan amount. Subscription options disclose automatic renewal; final pricing and schedule remain confirmed by checkout. Medication changes show a medical-review note.

Active subscriptions retain their native renewal flow. Included refill entitlements, claims and check-in requirements are unchanged. No provider writes, payments or medication orders were made to verify this change.

The responsive picker retains keyboard focus and selected states. Offline browser QA checks every Semaglutide/Tirzepatide × 1/3/6/12 month × one-time/subscription destination, different mode prices, therapy isolation, and 1440/390/320-pixel layouts. The full portal regression suite and live release verification are recorded below when complete.

Release contains only portal JavaScript/CSS plus the preceding loading fix, built from the committed Fly baseline. Unrelated local AWS/MySQL work is excluded. Before deployment, 42 SQLite backups passed integrity checks on the private Fly volume.

All 36 portal browser scenarios passed in the complete run (1.8 minutes), including the loading regressions. JavaScript syntax and diff checks passed. Desktop/mobile screenshots were visually reviewed. The release image is `sha256:57940a5798249a43d505fcaaf79f67ca57456794f4db0accfff44b4152a37f3c`.

Deployment completed on the existing Fly machine/volume. Public health passed and live JS/CSS matched the local source exactly. Aggregate checkout statuses and patient counts were unchanged after release. Read-only hosted UI verification is recorded separately; no real checkout was submitted.
