# FortifyHP patient portal delivery

Updated 23 October 2026. The shared release is deployed and the branded portal
responds at https://wlmd-stripe-test-0f89b1bb.fly.dev/portal/fortifyhp.
The user approved the restart; unfinished attempts were preserved. See
FORTIFYHP_ONBOARDING.md for the immutable release and validation evidence.
Provider-dependent clinical and payment capabilities still require their
actual integrations; publication alone does not prove those workflows.

## Site and appearance

- Use site ID `fortifyhp`, campaign 195, and a separate site/brand record.
- `/portal/fortifyhp` selects the FortifyHP theme from server configuration.
  Its ivory, porcelain, onyx and terracotta colors come from the existing
  Lovable source. Other sites retain their current theme.
- The real portal keeps orders, subscriptions, intake, included refills,
  notifications, tracking, address updates, account access and messaging views.
  Existing provider capability checks remain authoritative.
- The verified Code Pro font and FortifyHP logo exported from the authorized
  Lovable source are served locally through an explicit portal asset allowlist.
  They load only for FortifyHP; other sites keep their current styling.

## Shared platform deployment

The user explicitly selected one shared platform for all client sites. FortifyHP
is a tenant in the existing application, not a separate client application or
database. Its patient entry point is `/portal/fortifyhp` on the platform's public
origin. Existing brands, patients and orders retain their existing site IDs.

The canonical `admin_config` site record is also the member portal's site; no
second registration or dummy patient is required. The full engine already
installs the member portal and receipt-invitation handler. The old private
loopback preview alone is not a published patient URL.

`member_portal/site_setup.py` fills only FortifyHP's plan snapshots and missing
`site_refill_policy` records. Shared masters, test activations, other brands'
policies and patient records remain untouched. Site rules override the shared
master rule only for that site. Re-running bootstrap preserves later owner
policy edits, including disabling claims.

Staff can edit these rules at `/portal-admin/fortifyhp` → **Refill settings**.
The API is `/api/admin/sites/fortifyhp/portal/refill-rules`; updates require
owner authentication, CSRF protection, assigned-product membership and the
current site rule revision. Intake binding and included-shipment checkpoints
are validated before saving. Patient pages never expose these settings.

The new checkout's successful, verified receipt must issue a single-use,
site-bound portal invitation. Verify the checkout-to-account handoff on the
shared deployment and distinguish account creation from account recovery/email
delivery capabilities. A separate-app deployment was considered and rejected;
do not use it as the rollout architecture.

## Production included-refill contract

Native included-refill claims now accept the explicit FortifyHP contract in
`external_fulfillment.py`: campaign 195, dedicated gateway 269, the approved
6/12-month SKU families, quarterly native prepaid cycles and zero shipping/tax.
Fresh provider checks remain mandatory before a write. Other campaigns retain
their existing non-shippable restriction. A shipped or externally posted earlier
order remains a valid paid entitlement; unknown posting state is rejected.

The existing initial-intake and prior-check-in requirements, day-80/170/260
windows, paid-term ownership, native child lineage, duplicate-claim journal,
$0 intermediate-order verification, next-date anchoring and refusal to claim
the full-price renewal cycle remain in force. The implementation never creates
an independent sale for an included refill or overrides the client's gateway.

The client has confirmed an external fulfillment system collects Sticky
orders. Do not add a new manual pharmacy release workflow as an assumed
requirement. Preserve that established responsibility while validating the
native prepaid order/child-cycle behavior and avoiding duplicate claims.

No client patient accounts or orders were seeded for visual QA. Automated
browser checks use an isolated offline fixture and never call a real gateway.
