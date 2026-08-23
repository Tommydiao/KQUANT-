# KQUANT CRYPTO Architecture and EVAL Boundary

## Agent responsibility

Market Data, Discovery, Security, Factor, Signal and Trade Plan components
produce versioned evidence and a draft. The deterministic EVAL Agent is the
only component allowed to decide whether a draft may become an alert, Paper
observation or Shadow candidate. Alert delivery is downstream of EVAL.

The LLM is an advisory side channel. It can explain registered evidence and
raise questions, but its response is never merged into the decision fields.
An unavailable or invalid LLM response therefore cannot make a plan more
permissive.

## Week 1 EVAL contract

`crypto_eval_v1.0.2` checks identity, security, data freshness, liquidity,
market regime, registered factors, model evidence, plan completeness and
expiry/duplication in a fixed order. Security blocks have the highest
precedence. Unknown security is `REJECTED`; other missing evidence is at most
`WATCH_ONLY`.

The foundation gate keeps `allowed_alert`, `allowed_paper` and
`allowed_shadow` false for every result. This is deliberate until provider,
data-trust and out-of-sample gates are implemented in later weeks.

## Data flow

1. Public provider events are normalized into canonical assets and instruments.
2. Snapshots receive source time, received time, availability and content
   hashes.
3. The versioned Factor Registry accepts only the twelve initial low-
   redundancy factor IDs. Signal proposals expose stage, score and factor
   contributions but cannot notify.
4. Trade Plan Agent translates a proposal into an immutable draft with entry,
   stop, target, expiry and invalidation conditions.
5. Trade plan drafts are saved before evaluation.
6. EVAL runs, blockers, evidence and final decisions are immutable audit rows.
7. Alert Agent reads only EVAL-approved records; the foundation cannot approve
   any.

The Parquet layer has one writer boundary: a cross-process lock plus atomic
file replacement. A dashboard process may read the store, but a long-running
collector is the preferred owner of public-event persistence.

## Current version matrix

| Layer | Version | Status |
| --- | --- | --- |
| Application | `0.2.0` | EVAL instruction, signal bridge and indexed market storage |
| API | `kquant-crypto-api-2026-08-23-eval-instruction-v1` | read-only research endpoints |
| Schema | `12` | EVAL, instructions, model evidence, validation partitions and PIT factor values |
| Market contract | `crypto_market_v1.0.0` | public CEX adapters |
| Factor registry | `crypto_factor_v1.0.1` | normalized slope/volume formulas; no production score gate |
| EVAL policy | `crypto_eval_v1.0.2` | deterministic, explicit downstream release flags closed by default |
| Model | `crypto_model_benchmark_v1.0.0` | rules/naive/NumPy Logistic plus validation-only Platt/Isotonic scaffolding; calibration and EVAL integration closed |

## Security boundary

This repository has no account, wallet, private-key, position, order,
trade-execution or swap path. Exchange integrations in later weeks are public
market-data adapters only. The boundary scan checks exact route segments so
the required `trade-plans` resource path is not confused with a trade
submission route.
