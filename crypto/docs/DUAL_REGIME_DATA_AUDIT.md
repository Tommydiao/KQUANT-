# Dual Regime Data Audit

Audit date: 2026-09-05. Read-only evidence inspection; no model, strategy replay,
collector, database migration or immutable-output rewrite was performed.

## Frozen Dataset

Repository-relative location: `crypto/outputs/dual_regime_v1/frozen/data_manifest.json`.
Canonical manifest SHA-256:
`42b913eca5de81541e89499e2afa846757b724ef4fbe0f365a80d52397a5651a`.
The canonical hash and all six extracted Parquet SHA-256 values were independently
verified by reading the frozen files during this audit.

- Symbols: BTCUSDT, ETHUSDT, SOLUSDT; Binance Spot only.
- Research calendar: `[2025-08-01T00:00:00Z, 2026-08-01T00:00:00Z)`, 365 days.
- Extra warmup: `[2025-07-21T14:00:00Z, 2025-08-01T00:00:00Z)`, 250 hours.
- Per symbol: 9,010 hourly bars and 108,120 five-minute bars including warmup;
  research calendar alone contains 8,760 hourly and 105,120 five-minute bars.
- Last starts: 2026-07-31T23:00:00Z (1h), 2026-07-31T23:55:00Z (5m).
- Frozen quality records show one continuous segment per symbol/timeframe,
  zero gaps, zero exact duplicates, zero conflicting duplicates and no exclusions.
  Upstream compaction may already have removed duplicates; these counts do not
  prove raw ingestion was duplicate-free.
- Historical eligibility is ELIGIBLE for all three; freshness is separately
  STALE_OR_MISSING, with actual receipt unverified and execution admission false.

Authoritative inputs were `crypto/data/market/_compacted/closed_klines_spot_1h.parquet`
and `closed_klines_spot_5m.parquet`. Native 1h candles, not partial aggregates,
were retained only after checking exactly twelve consecutive aligned 5m bars.
Hourly open/maximum high/minimum low/close must match those children within
relative and absolute tolerance 1e-8. This is an OHLC check, not a claim that
hourly volume was independently reconciled. No forward fill or return-based
selection is used. SQL filters venue, spot market, interval, requested symbols
and calendar before materialization, with no arbitrary all-symbol limit.

`available_at` is assumed candle close for historical replay. `received_at`
preserves source receipt/import timestamps separately; archive ingestion is not
evidence of historical live receipt. These inputs cannot establish historical
network latency, bid/ask spread, intrabar path or executable fill availability.

The frozen manifest predates the additive PARTIAL-research eligibility fields.
It remains untouched. Its empty gap lists establish continuity independently;
future manifests must not substitute `historical.eligible` for continuity.

## Exposure Evidence

Inspected `crypto/work/kquant_crypto.sqlite3` using SQLite URI `mode=ro` and
`PRAGMA query_only=ON`. Parsed existing `crypto_validation_runs.split_config_json`
and queried existing `crypto_validation_trades`; did not invoke store writers.
The following stored test calendars each include all 365 frozen research dates:

| Existing run | Created UTC | Stored test dates, inclusive |
| --- | --- | --- |
| validation_5e3e9527ed0744ce865e67b11d33d2d9 | 2026-09-02 12:10:55 | 2025-06-19 to 2026-07-31 |
| validation_da6ee778cb634371849a842262aadb68 | 2026-09-02 12:12:50 | 2025-07-14 to 2026-08-31 |
| validation_be39d73799e0494e867582b3c45c1dac | 2026-09-02 12:20:13 | 2025-07-14 to 2026-08-31 |
| validation_820b868fe2e94f27a1f74152a9c1757f | 2026-09-02 12:23:55 | 2025-07-14 to 2026-08-31 |
| validation_f6dc47254492407a911360df1675158a | 2026-09-02 12:35:25 | 2025-06-19 to 2026-07-31 |
| validation_8a6718e3cd07455fa8631fe6307bf018 | 2026-09-04 15:36:06 | 2025-06-19 to 2026-07-31 |

These calendars span several strategies/markets, not six independent Spot
experiments. Direct Spot evidence is the `crypto_historical_spot_long_v1.0.0`
run `validation_f6dc47254492407a911360df1675158a`: filtering signal timestamps to
the frozen calendar yields 198 BTC, 266 ETH and 231 SOL stored trade rows.
First signals are 2025-08-06 16:00Z, 2025-08-04 16:00Z and 2025-08-06 17:00Z;
latest exits are 2026-07-27 12:00Z, 14:00Z and 14:00Z respectively. Counts are
stored rows, not deduplicated independent samples across runs/partitions.

`crypto/docs/CRYPTO_EVIDENCE_TESTNET_V1_STATUS.md` explicitly publishes the
v2.1 core-Spot run above and its NO_GO result. Its stored frozen-calendar trade
rows include ETH signals from 2025-08-22 and SOL signals from 2025-08-12.
`crypto/docs/daily/2026-08-23-validation-and-collection-gates.md` also publishes
an earlier full-universe replay ID and results, but that ID was not found among
the six runs in this database snapshot; its exact replay dates are unverified.
Report filename dates must not be mistaken for the market-data calendar.

Existing `crypto/outputs/dual_regime_v1/dev_A_base_v1/performance_report.md`
and `dev_A_base_v2/performance_report.md` further disclose candidate results
as historical/exposed. This audit did not generate or recompute them.

Conclusion: previous computed and published results overlap the frozen calendar;
no independently untouched historical holdout is established. Stored calendars
do not prove a person viewed every date, but a new split cannot restore
independence. Treat the entire frozen calendar as exposed/descriptive and retain
PERFORMANCE_UNPROVEN. The immutable manifest's conservative exposure label is
unchanged; this audit supplies additional evidence rather than rewriting it.

## Trading-Rule Proxy

`crypto/outputs/dual_regime_v1/exchange_rules.json` records receipt at
`2026-09-05T06:25:10.862481+00:00` (verbatim recorded timestamp) and
`historical_filter_status=current_rules_proxy_not_historical_rules`.
Its recorded content hash is
`fe77875b539dc5a8cc905cd1c86933376b65ea19a0186a45349d4fdd0308c3ce`.
`frozen_rules()` in the runner fetches current exchangeInfo and freezes its
quantity/notional rules. Applying those rules to 2025-2026 candles is not
point-in-time historical rule reconstruction. Report feasibility as a current
filter proxy, not historically verified exchange acceptance or account fees.

## Read-Only Simulation Review

Reviewed the working file `crypto/kquant_crypto/candidate_simulation.py`, SHA-256
`7be287c6590cade0b55cb14c85733ab9af54370bac73d7ced1608ea1805c2fb0`.
Other agents were editing concurrently; references below describe this snapshot.
No confirmed future-price/1h lookahead was found in the normal replay path:
hours join at their exact close; next-open entries precede current-bar high/low
processing; current closes update marks only afterward. Missing hourly closes
are passed as None while 5m continues, and the kernel resets on missing hours.
This is static inspection, not a new leakage-test execution or full certification.

### Findings Addressed by Integration Owner

Follow-up source inspection on 2026-09-05 verified the parent's fixes below.
Updated `candidate_simulation.py` SHA-256:
`9dea7986d0eab0ca2600df1d94326eba1cb03f36e3107e9cefba93101f6908ba`.
The original hash above identifies the pre-fix review, not the current code.

1. **Addressed: UTC rollover daily-loss accounting (originally P1).** The
   original ordering reset the daily baseline before checking the final candle's
   unrealized loss. Current code calls `_risk(now)` before `_clock(now)` at an
   OHLCV midnight close, retaining required exits across rollover. At the next
   midnight open it updates marks to actual opening prices and calls
   `_clock(start, force=True)` to establish the opening baseline. These source
   changes address the reported ordering defect; it is not listed as unresolved.
   This was temporal risk accounting, not demonstrated future-price leakage.
   The parent reports regression coverage is being added by the kernel agent;
   this documentation-only follow-up does not claim those tests have passed.
2. **Addressed: PARTIAL eligibility versus continuity (originally P1).**
   `compare()` now calculates `data_continuous` from explicit empty coverage gap
   lists for every manifest symbol and both 5m and 1h, not from research
   eligibility. This works for the existing frozen manifest and does not promote
   future PARTIAL research datasets to continuous evidence. The present
   verified full-window freeze was unaffected by the original defect.

These engineering fixes do not alter exposure: existing validation calendars
cover all 365 research dates, with prior stored Spot trades for all three core
symbols. The whole frozen history remains exposed/descriptive, with no proven
independent historical holdout and performance status PERFORMANCE_UNPROVEN.

No simulation, runner, loader or tests were changed in this audit. No model or
backtest was run. Existing immutable outputs, original gates and shared stores
were not modified. Loader tests were not rerun because loader code is unchanged.
