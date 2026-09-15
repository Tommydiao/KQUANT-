# Dual regime candidate sprint

T0: 2026-09-05T06:16:08Z. Deadline: 2026-09-06T06:16:08Z (14:16:08 Beijing).
Baseline HEAD: baac8d1. The working tree was clean at T0.

The controlling specification is KQUANT_24H_Dual_Regime_Strategy_Plan_V2.0.md.
Only BTCUSDT, ETHUSDT and SOLUSDT spot are candidates. Policy A and B differ
only in the two target parameters defined by that document. Prior historical
exposure is assumed until independent evidence proves otherwise.

## Milestones

- T+1h: frozen policy, source document, baseline and data manifests.
- T+6h: real dual-timeframe historical trades and equity.
- T+8h: live public-market candidate simulation.
- T+24h: CLI, reports, recovery evidence and separate engineering/data/performance verdicts.

Existing public collector PIDs at baseline: 40088 / 36116. Candidate workers
must not stop these processes or write original validation/EVAL/PAPER/SHADOW.
Original data and execution gates retain their original definitions.

## Current status

Implementation started. No new strategy performance or engineering PASS is claimed.
The candidate database is crypto/work/candidate_simulation.sqlite3.
The public collection and whole-universe backfill are outside the critical path.
