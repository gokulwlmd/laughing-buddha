# Developer help needed: prioritized backlog

Scope as of 28 October 2026. The [handoff](DEVELOPER_HANDOFF_2026-10-28.md) distinguishes current implementation from live provider acceptance. The [SDK plan](POST_CHECKOUT_SDK_PLAN.md) defines the proposed integration package.

## P0 — Establish an accurate source and release baseline

**Problem:** GitHub default/feature branches, a dirty local workspace and the deployed image are different states. Some chronological documentation contradicts newer implementation.

**Work:** recover the verified source/build inputs for the live image, compare the runtime manifest, bring matching tests into a focused reviewed branch, and separate AWS/MySQL work from the Fly product branch. Consolidate the current capability table and link a release commit to each promoted image. Review the stacked PR graph rather than merging unrelated histories blindly.

**Done when:** a clean clone can reproduce the intended application and run its disposable tests; the exact release commit, immutable image and change list are recorded; no patient records, runtime keys, credentials or logs enter Git. Deploying from that branch does not accidentally package unrelated local changes. Documentation links clearly identify current versus historical behavior.

## P1 — Strengthen Sticky operation outcomes and recovery

**Already present:** durable payment/action journals, same-attempt resumption, exact receipt matching, a per-site Needs attention queue and bounded read-only recovery. Do not replace these with blanket retries.

**Work:** standardize accepted/rejected/uncertain results and operation IDs across payment, membership, subscription, card, refill and upgrade adapters. Add sanitized correlated timing/trace data, useful staff explanations and supported recovery where a write response was lost. Current payment recovery cannot resolve every lost `new_order` response without an acknowledged exact order ID; verify a provider-supported lookup/event contract rather than search by email. Extend the existing queue rather than build a second disconnected one.

**Done when:** accepted-write/connection-drop, readback failure, browser refresh, restart and concurrent-action cases cannot create another charge/order or falsely show failure/success. Staff can trace the exact site/operation and recover by authoritative reads, or retain an explicit unresolved case. No patient data or card tokens enter logs.

## P1 — Generalize multi-client provisioning and publication

**Already present:** reusable masters/templates, site records, reviewed provisioning, exact object readback and public site publications.

**Work:** replace Fortify-specific bootstrap/prepaid/fulfillment gates and ad hoc rollout scripts with reviewed, versioned per-site capabilities. Model brand, campaigns, actual gateway routes, WLMD site, therapy/form mappings, prices, coupons, refill policy, domain and publication separately. Persist setup job stages and exact created object IDs, including interruption/reconciliation state. Coordinate the separate publication manifest with the reviewed setup job and rollback plan.

Fix the shared post-checkout component's current public-site/portal-site ID equality assumption. The backend permits distinct IDs, but the component constructs/validates `/portal/${this.site}`. Resolve the canonical portal destination from trusted backend configuration, with allowed origin/path checks. The acceptance sites must exercise different public and portal IDs.

Relevant areas: `sites.py`, `master.py`, `admin.py`, `external_fulfillment.py`, `member_portal/site_setup.py`, `demo/registry.py`, `demo/runtime.py` and client-specific provisioning scripts.

**Done when:** two new synthetic clients can independently select therapies, prices and provider mappings through the same setup flow; failure after object creation does not duplicate it; one client's edit cannot affect another's offers, patients or checkout destinations. Public checkout remains unavailable until required readiness checks pass. A copied site cannot inherit the source site's clinical tenant or confidential records.

## P1 — Add durable order/subscription synchronization

**Already present:** normalized local order snapshots, subscription lineage and explicit provider refresh. Admin campaign/model indexes have separate display snapshots.

**Work:** verify Sticky's available event payload/authentication/replay contract, then add an authenticated durable event inbox, idempotent processors and bounded scheduled reconciliation. Use canonical provider reads when events are incomplete. Record last successful sync, freshness and failures. Add pagination/continuation where bounded descendant traversal currently stops. Financial writes still perform the necessary fresh ownership/price/schedule checks.

**Done when:** duplicate/out-of-order events, long subscription histories and temporary outages cannot duplicate orders, lose children, regress newer state or cross sites. The portal renders saved orders promptly; an outage is visible without blocking all site browsing. No webhook is trusted merely because its body names a valid order/site.

## P1 — Package the post-checkout SDK

**Already present:** shared `<wlmd-purchase-intake>` component and site-scoped post-purchase APIs. A versioned package is absent.

**Work:** implement the hosted wrapper and typed headless client in the [SDK plan](POST_CHECKOUT_SDK_PLAN.md). Provide pinned versions, explicit events/errors, mount/unmount, theme contract, examples and an integration snippet generated from published site configuration. Keep price, identity, clinical and refill decisions on the backend.

**Done when:** two sites on different frontend stacks complete the same account/intake/portal flow without copying UI code, questions or provider credentials. Refresh, partial save, expiry, multiple receipts and returning-member behavior pass. Post-checkout actions start only from verified captured receipts; uncertain payments remain distinct.

## P1 — Complete the WLMD intake adapter

**Already present:** reusable local draft/revision/answer-profile logic, final-step identity gate, SSN/ID adapters and live question/compilation endpoint experiments.

**Work:** obtain exact initial/check-in therapy mappings, a versioned question/conditional/requiredness schema, populated answer and attachment formats, exact order binding, explicit accepted acknowledgement, idempotency and submission readback. Introduce a provider delivery journal separate from local form status. Fetch templates outside DB locks and pin the version in each draft. Do not call `/answers` for autosave: the observed minimal call creates a compilation record.

**Done when:** a scoped authorized synthetic test demonstrates populated answers persisted against the intended order and can be read back; duplicates/timeouts cannot create duplicate clinical submissions. Refill forms target their actual child orders and configured check-in type. Checkout/portal drafts resume correctly, identity stays last, and stable-answer reuse does not conceal changing health information. Local Saved/Submitted and provider Accepted remain distinguishable.

## P1 — Finish the provider acceptance matrix

**Work:** record acceptance evidence for tokenized card replacement and subsequent renewal, pause/resume, eligible current/future addresses, paid early renewal, included $0 delivery, replacement subscription and any new cancellation flow. Use each site's actual configured gateway/capability. Define a scheduler-safe mechanism for overdue missing included cycles; do not turn a generic force-bill into a repair shortcut.

**Done when:** supported actions have exact preconditions, verified provider outcomes, concurrency tests, uncertainty handling and site capability flags. Unsupported combinations return a clear explanation. Real transactions or order mutations require explicit authorized test scope; synthetic/browser fixtures alone are not certification. Wallets remain deferred unless the owner reopens that work.

## P2 — Unify editable, versioned SKU/site policies

**Already present:** global SKU refill policies, site overrides and saved care-plan snapshots; some gates remain hardcoded and current overrides can replace whole records.

**Work:** define documented Master → SKU → Site policy precedence, field merge/validation rules, policy versions, audit history and safe publication. Separate billing term, supply length, shipment cadence, included entitlement, claim lead time, intake/check-in requirement, paid renewal and upgrade availability. Default changes apply to new purchases; changes to existing purchased entitlements need explicit reviewed migration.

**Done when:** staff can change a policy through an approved admin/API flow and preview its effects. An existing prepaid plan cannot silently lose included deliveries or gain an unauthorized charge. The same SKU works for initial and refill orders; form kind comes from verified lineage plus policy.

## P2 — Multi-client operations, domains and capacity

**Work:** define operator roles and designated production approvers, provision client subdomains with DNS/TLS verification and trusted tenant resolution, add per-site metrics/rate limits and fair background job limits, and exercise backup/restore procedures. Configure actual GitHub environment protections and scoped deployment credentials; files alone do not enable them.

Current one-worker SQLite coordination must be replaced or redesigned before horizontal scaling. Benchmark realistic catalogs, patients, portal histories and provider latency before claiming support for 200 clients. A later database migration needs data/locking/compatibility work, not simply another worker or a MySQL connection string.

**Done when:** an independently branded second/third client uses the same release, domains cannot route into another tenant, staff access is scoped as intended, releases promote a tested immutable image, and a recovery drill proves the documented restoration path. Publish measured budgets and limits rather than promise instantaneous upstream payments.

## Suggested delivery sequence and people

1. **Senior backend/integration engineer:** source baseline, Sticky reliability contracts, two-client provisioning and synchronization.
2. **TypeScript/frontend integration engineer:** post-checkout SDK and sample integrations, working against the same backend contract.
3. **Backend engineer with the WLMD API owner:** clinical payload/mapping/readback completion and provider delivery journal.
4. **QA/product owner:** isolated provider acceptance, multi-product failure scenarios and two-site customer walkthroughs.
5. **Platform/release engineer as needed:** protected promotion, recovery, custom domains and measured capacity.

Keep the initial milestone small: **a reproducible baseline plus a second independently configured client running the same checkout/post-checkout integration**. Review each operational/provider change separately; do not bundle a broad rewrite, database migration and SDK rollout into one release.
