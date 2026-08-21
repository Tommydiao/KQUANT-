# KQUANT v2 Week 12 readiness extraction

- Moved the active market-readiness and manual runbook renderer to `web/src/features/operations/ReadinessPanel.tsx`.
- Preserved the existing status, checks, reasons, risk rules, and runbook content without changing eligibility calculations.
- The main application now renders `ReadinessPanelView`; the old inline renderer is removed from `App.tsx`.
- This is a read-only presentation change. It does not create Shadow sessions or change the `NO_GO` gate.
