# Progress Report: EVAL Evidence Binding and Validation v1

## 1. Goal and completion

The EVAL final-review boundary is now explicit in the data contract, and the
first date-level walk-forward validation runner is available. This is a code
milestone only. The 24-hour CEX collection Gate is still open, so no strategy
performance or Paper/Shadow permission is being promoted.

## 2. Code, Schema and API

- Schema v7 adds `snapshot_bindings_json` to trade-plan drafts and evaluation
  runs, with a checksum-tracked migration.
- Every new EVAL input is expected to bind `market`, `regime`, `factor`,
  `security`, `liquidity`, `derivative`, `signal`, `plan`, `model`,
  `universe` and `eval_policy` evidence.
- Missing bindings, mismatched factor or plan IDs, unknown binding types and
  stale EVAL policy versions are recorded as deterministic blockers.
- Bound evidence is persisted as both source evidence and typed binding
  evidence. Legacy drafts remain readable but safely degrade to `WATCH_ONLY`.
- `kquant_crypto.validation` adds a shared-date 60/20/20 runner with warm-up
  history, first-bar embargo, cross-boundary censoring, cost-aware R results,
  Wilson win-rate intervals and fixed-seed bootstrap expected-R intervals.
- `POST /api/crypto/validation/runs` accepts local historical bars for a
  deterministic replay and persists the report; it has no market-account or
  order capability.

## 3. Data and provider status

- The independent dashboard is running at `http://127.0.0.1:8010/`.
- Long-running CEX collection process remains active; its final report is not
  present yet, so the 24-hour Gate is not passed.
- DEX discovery is enabled for public read-only data. Current database counts
  are 202 DEX market snapshots, 102 pools and 103 token identities.
- GoPlus is intentionally disabled without credentials; token security
  snapshots are therefore zero and DEX/MEME cannot pass EVAL.
- No account, wallet, private-key, position, order, swap or trade-submission
  route exists.

## 4. Tests and verification

- Python: `60 passed`.
- Frontend: Vitest `1 passed`.
- Frontend production build: passed.
- Read-only boundary scan: passed.
- Schema health: current/latest `7/7`, integrity `true`.
- PWA manifest and versioned service worker: HTTP 200 and verified.

## 5. Risks and Gate

- Historical CEX coverage, three OOS folds and a sufficient test sample do not
  exist yet.
- The validation runner is a foundation; it does not justify displaying a
  win-rate claim or enabling an EVAL action.
- DEX/MEME security is fail-closed until GoPlus/Solana security snapshots are
  collected and tested.
- The collector currently uses public market data only; reconnect, storage
  growth and full 24-hour continuity remain to be measured.

**Gate: NO-GO.** Continue collection and provider/data-quality work. Do not
call the current report a live win rate, and do not enable Paper or Shadow
decisions from this milestone.

## 6. Git and rollback

- Branch: `codex/crypto-v1-foundation`.
- Commit: `ea5187a feat: bind eval evidence and add walk-forward validation`.
- Previous rollback point: `be67779 feat: add dex discovery radar panel`.

## 7. Next work

1. Let the single CEX collector finish and inspect the continuity report.
2. Add formal CEX coverage and data-gap summaries from Parquet/DuckDB.
3. Complete DEX security status/collection wiring with explicit unknown-state
   rejection and fixed token-risk cases.
4. Keep the EVAL action gate closed until provider, security and OOS gates are
   independently satisfied.
