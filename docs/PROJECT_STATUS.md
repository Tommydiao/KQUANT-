# KQUANT Project Status

Last verified: 2026-09-05 UTC. This file is the single current-state index for
the stock, crypto, and unified workspace. Detailed reports must link here
rather than independently claiming release readiness.

| Area | Version / state | Authority | Gate |
| --- | --- | --- | --- |
| Repository baseline | `codex/crypto-evidence-testnet-v1` at `69b4acb` | Git | baseline under integration review |
| Unified workspace | Gateway `kquant_gateway_v2.0.0`, local `8020` | gateway health | available, read-only |
| Stock runtime | local `8001` | stock health | unavailable during the 2026-09-05 probe; must be rechecked before a release claim |
| Crypto runtime | `0.7.0`, schema `21`, local `8010` | crypto health | available, read-only |
| Crypto public collection | Binance market-data-only collector | collector heartbeat | running; collection is not strategy evidence |
| Crypto strategy | `crypto_spot_momentum_v2.1.0` | locked validation report | `NO_GO` |
| Crypto execution | disabled, unarmed, no credentials configured | execution status | `NO_GO` |
| Testnet | no closed testnet trades recorded | execution status | not started |
| Live trading | excluded from this phase | policy | prohibited |

## Non-negotiable interpretation rules

- A running public collector proves only collection continuity for its observed
  period. It does not prove historical coverage, signal quality, or execution
  readiness.
- A build, mock test, Paper/Shadow observation, Testnet result, and live result
  are separate evidence classes and must never be relabelled as one another.
- `NO_GO` remains in force until the exact strategy, market, symbol, direction,
  data snapshot and validation run satisfy the active contract.
- The unified gateway shares login and navigation only. Stock and crypto data,
  registries, strategies, database files, and release gates remain isolated.

See [baseline integration](next-phase/baseline-integration.md) and the
[data and validation contract](next-phase/data-validation-contract.md) for the
current implementation criteria.
