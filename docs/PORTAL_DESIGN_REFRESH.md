# Patient portal presentation refresh — 23 October 2026

## Scope and decision

The selected action-first visual direction is applied to the existing `member_portal` frontend. The separate limited prototype is not the product implementation. Preserve the existing routes, action handlers, authentication and API contracts; a cleaner home screen must not remove features. Retain the site's actual identity without adding a new brand theme.

Home now presents the highest-priority next care action, its verified plan facts, one row per purchased treatment term, the latest order timeline/shipment details, and shortcuts to messages, refills and updates. Included child orders stay grouped with their original paid term; different purchases of the same medication remain separate. Every native order remains in order history. Home plan facts ignore filters retained from other screens. A scheduled cycle is not described as a payment unless the API supplies `next_billing_date`.

## Feature preservation map

| Capability | Location after refresh |
| --- | --- |
| Login, invitation enrollment, sign out, separate site records | Existing account routes and shell |
| All orders, shipment tracking and timelines | Orders & plans → Orders; latest order also on Home |
| Pause/resume and future subscription address | Orders & plans → Subscriptions or relevant order |
| Current order address and payment-update support action | Relevant order's actions |
| Included claims, remaining count and early requests | Refills and relevant order, under existing eligibility rules |
| Initial intake, check-ins, saved drafts and submitted history | Medical intake and per-order care timeline |
| Native and historical refill history | Orders & plans → Refill history |
| Care-team drafts and existing message history | Messages |
| Shipment/care notifications and read receipts | Notifications and header bell |
| Available same-site paid checkout choices | Existing published-plan sections and refill alternatives |
| Staff orders, imports, invites, policies and test controls | Separate owner views, unchanged |

## Verification

All 17 existing/extended member browser scenarios passed across the full run and targeted corrections. Final affected desktop/mobile/readability and navigation cases passed after the CSS fix; the new retained-filter regression also passed. These exercise the existing backend against an isolated offline Sticky contract fixture, including $0 claims and subscription actions. No test transaction called the live provider. JavaScript syntax and `git diff --check` passed. No backend code was changed in this refresh.

New coverage verifies two same-medication purchase terms remain distinct, an included child does not create another Home treatment, each row opens its exact original order, all six navigation destinations remain available at desktop/mobile sizes, and returning Home from a therapy filter preserves its plan facts.

Visual QA used the in-app browser at 1487 × 1058 and 390 × 844. The reference and implementation were inspected side by side. Automated reflow also covered 1440, 720 and 390 CSS pixels. The neutral palette, prominent next action, restrained borders and table hierarchy follow the chosen direction. Intentional differences retain all six navigation entries, real site identity, account controls and the recorded order timeline. Existing local fonts/icons remain; no patient data or screenshots were committed. The desktop header/row alignment issue was fixed. No browser warnings/errors were captured during manual inspection.

Final result: passed for the presentation refresh and existing offline regression coverage. Authenticated real-data screenshots were not taken: the user chose automated checks instead of signing in.

## Release boundary

Updated only the private preview's `portal.js` and `portal.css` by verified atomic file replacement, with rollback copies. Both private and public worker health checks returned 200 and their process identities were unchanged. No database, credential, order, subscription, payment, or medical record was changed by this release. The original public payment worker was not restarted. See `member-portal-preview.json` for asset hashes.

Existing provider dependencies remain: approved intake/messaging APIs, the verified Stripe Connect v2 card-replacement contract, and physical fulfillment hold/release. This redesign does not claim to complete those integrations.
