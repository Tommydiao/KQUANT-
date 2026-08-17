# KQUANT v2 Week 4 - Data Coverage and Trust Workbench

## 1. Goal and completion

**Completion: implementation and coverage repair complete; modelling gate PASS.**

Week 4 established the operational Data Trust layer required before Theme
Taxonomy and any predictive model work. The active production database was
backed up and passed a restore drill before the evidence report was written.

## 2. Delivered modules

- `kquant/db/migrations.py`: migration v4 adds an explicit universe registry,
  immutable coverage-run records, resumable Longbridge backfill jobs, and
  provider-event archive audit records. No existing market data is deleted.
- `kquant/universe_registry.py`: database-backed, content-addressed active
  Universe Registry. It preserves the current 296 active database symbols and
  makes the existing smaller Python seed list a source of updates rather than
  silently changing the modelling denominator.
- `kquant/data_coverage.py`: Data Trust v2 records 1d/1h/1m source, bar count,
  adjustment mode, fetch time, observed gap count/max gap, and canonical
  eligibility. Yahoo remains reference-only.
- `kquant/market_data_backfill.py`: a bounded queue now persists symbol /
  interval state, retry count, error, and result. A Yahoo result is never a
  successful Longbridge backfill.
- `kquant/provider_event_retention.py`: reports the archive candidate set and
  can explicitly export it; automatic deletion is permanently off in v1.
- `GET /api/data/coverage`: canonical Data Trust API. The old
  `GET /api/stocks/data-coverage` route remains for compatibility.
- `web/src/App.tsx`: Settings includes the registered universe and current 1d,
  1h, and 1m coverage summary.

## 3. Database and data result

At `2026-08-16T04:40:38Z`, the registered modelling universe has **296**
symbols. Longbridge canonical coverage is:

| Interval | Eligible symbols | Coverage | Target | Model prerequisite |
| --- | ---: | ---: | ---: | --- |
| 1d | 45 | 15.20% | 90% | Yes |
| 1h | 42 | 14.19% | 90% | Yes |
| 1m | 3 | 1.01% | 90% operational target | No |

Only 42 symbols meet both current 1d and 1h requirements. Market breadth is
therefore explicitly `limited`. Provider-event retention found 327,079 events
and zero records older than the current 90-day archive boundary; nothing was
archived or deleted.

The controlled live probe `mbj_11be0b7500824dac9ff94779a3b5c103` fetched RKLB
daily and 1H data through the Longbridge queue successfully (2 completed
items). RKLB was already represented in the cached eligible set, so the global
coverage numerator did not change. This validates credentials, permissions,
queue state, and persistence, but does **not** demonstrate full-universe
throughput.

The full controlled job `mbj_dc7d7035a0064295a222c444aafc6a97` subsequently
processed all 592 daily/1H items. After correcting the `2y/1h` range contract,
the final Longbridge coverage was 293/296 daily (98.99%) and 294/296 1H
(99.32%). The remaining 23 failed items are retained with symbol, interval,
attempts and provider result; they are excluded from the eligible set.

## 4. Verification

- SQLite backup: `work/backups/kquant-us-20260816T044001Z.sqlite3`
- Restore drill: passed (`integrity_check=ok`, 66 tables, active DB untouched)
- Python: `169 passed` in 169.01 seconds
- Frontend: 2 tests passed; production build passed
- Read-only boundary: passed, 82 routes, no broker/account/order/position path
- Local smoke: `GET /api/health` returned
  `kquant-api-2026-08-16-data-trust-v1`; `GET /api/data/coverage` returned the
  registered 296-symbol report.

The Vite bundle is still approximately 528 kB after minification. This is a
known performance debt for Week 12 frontend decomposition, not a data-trust
correctness failure.

## 5. Leakage and operational risks

- Coverage reports only describe stored observations; they do not make Yahoo
  eligible or turn a forming candle into a model input.
- Backfill queue results record provider/source evidence. Reference fallback,
  insufficient bars, and exceptions are retryable/failed states.
- The old Python seed list and database catalogue differ. The registry keeps
  the 296-symbol database source explicit rather than silently dropping 32
  symbols. A reviewed registry import will be required before training.
- `GROUP_CONCAT` based gap reporting is operational metadata, not an exchange
  calendar proof. Calendar-aware quality policy remains a later refinement.

## 6. Gate decision

The first report was **NO-GO** because cached coverage was only 15.20% daily
and 14.19% 1H. After the controlled repair queue and a fresh immutable
coverage run, the mandatory 90% daily and 1H targets are **PASS** at 98.99%
and 99.32%. The 1m operational target remains 1.01% and is not a modelling
prerequisite in this programme. Week 5 may proceed; failed symbols remain
excluded until individually repaired.

## 7. Rollback point

Schema is forward-only. Restore the verified SQLite backup above to roll back
the data file; source rollback is the Week 4 commit created with this report.
