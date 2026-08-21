# KQUANT v2 Week 12 transaction ticket extraction

## Scope

- Extracted the active manual-trade eligibility ticket from `web/src/App.tsx` into `web/src/features/quant/ManualTradeTicketPanel.tsx`.
- Kept the existing read-only presentation contract: no broker, account, position, order, or execution behavior was added.
- Passed the existing display and localization helpers into the component so internal action labels and risk text remain mapped to user-facing language in one place.

## Verification

- Python regression: `200 passed`.
- Frontend tests: `2 passed`.
- Frontend production build: passed; existing single-chunk warning remains (`~544 kB`).
- Read-only boundary: passed; `99` routes, no forbidden broker/account/order routes.
- Browser smoke: stock workspace displayed the manual eligibility ticket; Longbridge status was visible; research-service fallback showed localized text; console errors `0`.

## Gate

- Week 12 implementation gate: **pass** for this refactor slice.
- Product release gate: **NO_GO** remains unchanged. Shadow observation is not started (`0/20` days), the stock OOS gate has not been satisfied, and the backend research-model credential is currently rejected.
