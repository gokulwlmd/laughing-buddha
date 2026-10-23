# Existing patient portal design QA

Final result: passed.

See [the full scope, feature map and QA record](../../../docs/PORTAL_DESIGN_REFRESH.md).

Reference: selected action-first design, `prototypes/patient-portal-option-1/design/reference.png`.
In-app browser comparison: `/private/tmp/portal-design-review/comparison.png` (reference left, implementation right, 1487 × 1058 per side).
Other captures: `home-desktop.png`, `home-mobile.png`, `orders-desktop.png` in that private local directory; these contain isolated fixture data only.
Automated final screenshots: `../qa/results/final-visual/`, and the retained-filter regression result in `../qa/results/final-home-filter/`.

This is a presentation update to the existing working member module. Preserving its complete feature set takes priority over copying the reduced prototype's four-item navigation. Existing site identity, six navigation sections, real plan fields and recorded timelines are intentional adaptations. Desktop table alignment was corrected; responsive checks passed at 1440/720/390. Dialog controls, address forms, intake autosave and the existing server contracts were exercised by the regression suite.

No unresolved P0/P1/P2 design issues were found in the tested states. Further page-specific simplification is a future design iteration, without removing existing features.
