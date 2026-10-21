# Master category dropdown — QA

Verified 22 October 2026. All 12 affected category/master Chromium scenarios passed with no skipped or flaky cases. Tests use disposable state and fake Sticky services. Backend code was unchanged. Existing categories, adding a category, blank-name validation, Uncategorized, category regrouping without price/URL changes, and mobile layout were checked. Container checks and hosted asset matching passed; owner, configuration, review and checkout records matched pre-deployment hashes. No live catalog or payment writes.

| Scenario | Result |
| --- | --- |
| GRP-01 brand directory scopes links and creation to the selected brand and groups categories | Pass |
| GRP-02 category edit regroups existing checkouts without reassignment or URL changes | Pass |
| GRP-03 design shortcut targets the owning brand and existing links retain independent colors | Pass |
| GRP-04 mobile brand directory and grouped checkout links fit the viewport | Pass |
| GRP-05 master category dropdown selects existing groups, clears to Uncategorized and validates new names on mobile | Pass |
| MST-01 agreed preset saves five intervals without a Sticky write | Pass |
| MST-02 test brand, assignment preview, private link and repeated assignment | Pass |
| MST-03 quote validation checks each assigned billing choice without charging | Pass |
| MST-04 every preset interval can complete a distinct simulated checkout | Pass |
| MST-05 new master revision shows update available without changing assigned checkout | Pass |
| MST-06 partial assignment holds created IDs and blocks a fresh attempt | Pass |
| MST-07 mobile master setup and approval remain usable | Pass |
