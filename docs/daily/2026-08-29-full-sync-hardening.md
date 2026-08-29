# KQUANT Full Sync Hardening - 2026-08-29

## Baseline

- Audited source branch: `origin/codex/full-sync-20260829`.
- Frozen source commit: `a9e4c15e17fdbedaa3d42c8e7c9ba20d006ee45a`.
- Implementation branch: `codex/full-sync-hardening`.
- Product boundary: read-only research; no account, wallet, position or order
  access.

## Completed in this hardening pass

### Engineering baseline

- Fixed the crypto validation experiment syntax error that prevented pytest
  collection.
- Reordered root CI so the stock frontend is built before Dashboard tests that
  require `web/dist`.
- Added CI coverage for `codex/**` branches and `workflow_dispatch`.
- Added production dependency audits, frontend lint/tests/builds, tracked-file
  credential scanning and read-only boundary checks.
- Updated the root frontend dependency lock so the production audit reports no
  high-severity vulnerabilities.

### Release traceability

- Added `/api/version` to Stocks, Crypto and the unified gateway.
- Extended health metadata with build SHA, environment and build time.
- Added `/api/platform/health` and `/api/platform/summary` to the gateway.
- The unified shell displays the gateway build SHA and each backend's health.

### Data trust contract

- Added an additive public source status contract:
  `live_primary`, `stale_primary`, `reference_only`, `unavailable`.
- Longbridge or the configured primary CEX source can be `live_primary`.
- Yahoo and fixture sources are always `reference_only`; they cannot become a
  buy or roll-buy authority through this mapping.
- Existing provider fields remain intact for backward compatibility.

### Unified website v1

- Added `platform/web`, a responsive React shell with `Stocks | Crypto` mode
  switching and the planned common workspaces.
- The shell is served by the local gateway when its production build exists.
- Stock and crypto APIs, databases and sessions remain isolated by design.
- This is a local composition layer, not yet a hosted single-origin reverse
  proxy.

### Roll Journal image intake

- Added a bounded PNG/JPEG/WebP image preview endpoint.
- OCR is optional and local; missing OCR returns `ocr_unavailable` rather than
  fabricated text.
- Image parsing creates a preview only. Ledger writes still require explicit
  user confirmation and remain auditable.

## Verification evidence

- Root Python: 239 passed.
- Crypto Python: 235 passed.
- Root frontend: TypeScript lint, 2 Vitest tests and production build passed.
- Crypto frontend: TypeScript lint, 1 Vitest test and production build passed.
- Unified platform: TypeScript lint, 2 Vitest tests and production build
  passed.
- Production dependency audit: zero high-severity findings in all three
  frontends.
- Tracked-file credential scan and both read-only boundary checks passed.
- Desktop and 390px browser smoke checks passed for the unified shell, Stock
  mode and Crypto mode.
- Local embedding is explicitly limited to the gateway origins through CSP;
  the default stock response remains non-embeddable.

## Remaining blockers

1. Longbridge and CEX continuous-session success, delay, missing-bar and
   duplicate-bar evidence has not met a production SLO.
2. `swing_long_v1` and `crypto_roll_v1` have not passed the locked out-of-sample
   Go thresholds.
3. There are not yet 15 real trading days of Shadow Observation evidence.
4. The unified shell still composes two local origins; hosted API, Postgres,
   shared authentication, backups and rollback are not production-ready.
5. Crypto UI source contains legacy mojibake strings. They do not block the
   build but must be repaired before a public product release.
6. The root stock frontend bundle remains above the preferred chunk size and
   needs workspace-level code splitting.
7. Stock and Crypto authentication sessions remain separate in the local
   composition. Shared authentication is deferred to the hosted platform.
8. Screenshot OCR requires optional local OCR dependencies; without them the
   endpoint returns `ocr_unavailable` and never fabricates extracted text.

## Go/No-Go

Status remains `RESEARCH_ONLY / NO_GO`.

No UI label, AI response or reference-provider candle may override missing
primary data, mathematical validation, hard veto or Shadow evidence.
