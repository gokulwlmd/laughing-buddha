# Combined purchase choices — QA

Verified 22 October 2026. 26 affected Chromium scenarios passed, with no skipped or flaky cases. Backend code was unchanged; the prior full-suite baseline is 122 backend tests and 55 browser scenarios. This targeted run covers visible one-time/subscription checkboxes, both selected together, save/edit retention, all five subscription intervals, campaign assignment and customer options, independent pricing, prepaid isolation, loading guards, and mobile usability.

Tests use disposable state and fake Sticky/Stripe services. No live catalog changes or payments were submitted. Container persistence checks passed. The deployed immutable image and hosted assets match the tested source; owner, configuration, reviews and checkout rows match their pre-deployment hashes. Desktop/mobile hosted sign-in checks passed.

| Scenario | Result |
| --- | --- |
| PLAN-01 product duration, one-time price and subscription price map without naming offers | Pass |
| PLAN-02 legacy five intervals retain IDs, names and exact schedules when duration changes | Pass |
| PLAN-03 mobile purchase setup needs no offer labels and changing type clears incompatible schedules | Pass |
| PLAN-04 both purchase checkboxes retain all subscription intervals through save, edit, assignment and checkout | Pass |
| PLAN-05 neither purchase type prevents save and selecting both restores a valid choice | Pass |
| PRE-01 prepaid setup shows upfront price, produces a private link and captures the whole term once | Pass |
| PRE-02 changing prepaid type preserves one interval and validates cent-exact total | Pass |
| PRE-03 mobile prepaid setup displays total and fixed shipment count without overflow | Pass |
| PRE-04 add prepaid to an existing product preserves its original option and edits without duplication | Pass |
| PRE-05 mobile prepaid shortcut keeps unsaved product fields and updates schedule and currency | Pass |
| PRE-06 physical product saves a prepaid catalog option with an explicit assignment limitation | Pass |
| PRE-07 missing 90-day model never substitutes a different schedule or erases the draft | Pass |
| MST-01 agreed preset saves five intervals without a Sticky write | Pass |
| MST-02 test brand, assignment preview, private link and repeated assignment | Pass |
| MST-03 quote validation checks each assigned billing choice without charging | Pass |
| MST-04 every preset interval can complete a distinct simulated checkout | Pass |
| MST-05 new master revision shows update available without changing assigned checkout | Pass |
| MST-06 partial assignment holds created IDs and blocks a fresh attempt | Pass |
| MST-07 mobile master setup and approval remain usable | Pass |
| SIM-01 four primary screens, local master and one-review existing campaign assignment | Pass |
| SIM-02 new campaign name and template include every master SKU and ready links | Pass |
| SIM-03 automatically selected choices and generated link address with public/private control | Pass |
| SIM-04 uncertain campaign creation cannot duplicate through a fresh setup | Pass |
| SIM-05 mobile master campaign and links need no advanced settings | Pass |
| SIM-06 choose a brand before checkout creation and retain all accessible campaign choices | Pass |
| SIM-07 existing Sticky SKU creates a checkout under the selected brand | Pass |
