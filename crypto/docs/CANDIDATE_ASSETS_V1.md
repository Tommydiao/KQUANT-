# Candidate Assets v1

## Scope

`crypto_universe_v1.2.0` registers four candidate execution instruments while
leaving the automatic execution allowlist unchanged.

| Asset | Venue | Market | Strategy | Research risk cap | Initial status |
| --- | --- | --- | --- | ---: | --- |
| ARB | Binance | Spot | `crypto_spot_momentum_v2.0.0` | 0.50% | `RESEARCH_ONLY` |
| ZEC | Binance | Spot | `crypto_spot_momentum_v2.0.0` | 0.50% | `RESEARCH_ONLY` |
| PUMP | Binance | Spot | `crypto_spot_momentum_v2.0.0` | 0.25% | `RESEARCH_ONLY` |
| HYPE | Binance | USD-M perpetual | `crypto_perpetual_long_v2.0.0` | 0.25% | `RESEARCH_ONLY` |

HYPE has no Spot identity in the registry. PUMP retains Seed, MEME and
high-volatility risk tags. ZEC carries privacy-policy and regional-liquidity
flags. Runtime `exchangeInfo` verification is authoritative for current
tradability and exchange filters.

## Data contract

History starts no earlier than each instrument's configured listing time. The
backfill planner covers closed 1m, 5m, 1H, 4H and 1D bars. HYPE additionally
collects public funding and open-interest history, then persists a current
funding, open-interest, mark-price, index-price and basis snapshot for the
perpetual contract. Hyperliquid data is a public cross-check only and has no
wallet, account or order authority.

Use `scripts/backfill_candidate_assets.py` without `--execute` to inspect the
download plan. Importing the full 1m history is an explicit operator action.
Missing archives, regional Binance restrictions or incomplete derivatives
history remain visible blockers; they are not synthesized.

## Mathematical evidence

Every candidate plan must bind a `crypto_model_evidence_v1.0.0` packet with:

- Bayesian regime posterior.
- Entry/stop/target-bound Monte Carlo result.
- Logistic start probability.
- Quantile expected-return range.
- Calibration state, source snapshot IDs and point-in-time history bounds.

PUMP-specific model inputs include gap risk, volume decay and abnormal
volatility. HYPE-specific inputs include funding, OI change, basis and
deleveraging risk, and its Monte Carlo contract must be `perpetual`.

Incomplete, uncalibrated, limited-history or mismatched evidence returns
`RESEARCH_ONLY`. EVAL will not promote a candidate plan without a matching
packet.

## Promotion gates

Promotion is per instrument and never inherited from BTC, ETH or SOL:

```text
RESEARCH_ONLY -> SHADOW_ELIGIBLE -> TESTNET_CANDIDATE -> TESTNET_ENABLED
```

The validation endpoint accepts symbol, product, direction and strategy. A
unit must have an aggregate validation PASS plus at least 30 independent test
trades and the configured bootstrap, Profit Factor, payoff and drawdown gates.
The execution orchestrator then rechecks EVAL, instrument identity, current
exchange rules, allowlist status and the candidate risk cap.

No candidate is added to Testnet or Live merely by this registration change.
The default allowlist remains BTCUSDT, ETHUSDT and SOLUSDT.
