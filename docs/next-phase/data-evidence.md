# P2 Data Evidence

Verified: 2026-09-05 UTC. Runtime data and Parquet archives are intentionally
not committed to Git; this document records the reproducible commands and
their evidence classification.

## Completed recovery batches

| Instrument | Market | Interval | Archive window | Result |
| --- | --- | --- | --- | --- |
| `PUMPUSDT` | Spot | 1H, 5m | 2025-09 through 2026-08 | checksum-verified, compacted |
| `ARBUSDT` | Spot | 1H, 5m | 2023-03 through 2026-08 | checksum-verified, compacted |
| `ZECUSDT` | Spot | 1H, 5m | 2021-01 through 2026-08 | checksum-verified, compacted |
| `HYPEUSDT` | USD-M perpetual | 1H, 5m | 2025-05 through 2026-08 | checksum-verified, compacted research data |

The source is Binance public monthly archives. Each archive import verifies the
published SHA-256 checksum before writing append-only Parquet events. The
symbol's configured listing month is the lower bound; no pre-listing data are
created.

## Closed-bar snapshots

The above Spot assets were compacted into market-specific `1H` and `5m`
snapshots. The coverage endpoint now reports ARB, PUMP, and ZEC as eligible for
the minimum 220 closed-bar research threshold on both intervals.

During this work, the coverage reader was corrected to prefer market-specific
snapshots over legacy generic snapshots. Previously it read both and could
double-count the same bars. Legacy snapshots remain on disk for audit and
compatibility but no longer inflate the active coverage gate.

## Current gate result

The research-Universe historical coverage Gate remains `NO_GO`. The eligible
Spot symbols are currently `ARBUSDT`, `PUMPUSDT`, and `ZECUSDT`; the configured
Universe still needs the remaining symbols and the core assets need their 5m
validation snapshots compacted under the current contract. This is not a
strategy result and does not authorize Paper, Shadow, Testnet, or Live use.

The independent 24-hour public collector is still running for BTC, ETH, SOL,
ARB, PUMP, and ZEC. Its report becomes continuous-collection evidence only
after the requested duration completes and the final report passes integrity,
gap, and liveness checks.

## Reproducible commands

```powershell
cd crypto
python scripts/plan_research_backfill.py --as-of 2026-09-05T00:00:00+00:00
python scripts/backfill_binance_archive.py --symbol PUMPUSDT --interval 1h --start-month 2025-09 --end-month 2026-08 --market-type spot
python scripts/compact_crypto_klines.py --interval 1h --market-type spot --symbol PUMPUSDT
python scripts/compact_crypto_klines.py --interval 5m --market-type spot --symbol PUMPUSDT
```

Use equivalent commands for ARB, ZEC, and HYPE only with their registered
market type and actual listing month. Do not use this evidence to enlarge the
execution allowlist.

## Next P2 work

1. Complete 1H/5m backfill and market-specific compaction for the rest of the
   frozen research Universe.
2. Compact the core BTC/ETH/SOL 5m validation snapshots under the current
   contract.
3. Complete and archive the independent 24-hour collector report.
4. Re-run coverage, gap, duplicate, ordering, and point-in-time checks before
   starting the P3 strategy experiments.
