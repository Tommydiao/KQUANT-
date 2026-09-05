# P0 Baseline Integration

## Verified starting point

The active local branch is `codex/crypto-evidence-testnet-v1` at `69b4acb`.
The working tree was clean when this report was created. The branch combines
the stock terminal at the repository root, the isolated crypto terminal under
`crypto/`, and the local workspace gateway on port `8020`.

| Surface | Normal endpoint | Fallback / debug endpoint | Build command |
| --- | --- | --- | --- |
| Unified workspace | `http://127.0.0.1:8020/` | gateway health at `/api/gateway/health` | `web: npm run build:unified` |
| US stocks | rendered through workspace | `http://127.0.0.1:8001/` | `web: npm run build` |
| Crypto | rendered through workspace | `http://127.0.0.1:8010/` | `crypto/web: npm run build` |

The gateway proxies an explicit research-route allow-list. It does not merge
databases or permit account, wallet, position, order, trade, or swap routes.
The crypto execution code may exist for Testnet preflight, but its default
configuration is disabled and no release gate currently permits a strategy to
create an order.

## Integration decisions

1. The `8020` workspace is the product entry point. Ports `8001` and `8010`
   are supported diagnostics and development fallbacks.
2. The current branch remains the integration baseline. `main` may contain
   independent changes and must be compared in an isolated integration branch;
   it must not be force-overwritten.
3. CI now builds `web/dist-unified` in addition to the stock and crypto
   frontends. A successful legacy frontend build is not sufficient evidence for
   the workspace release.
4. Runtime health is authoritative only when the reported build SHA, API
   contract, frontend contract, and schema are mutually compatible. A local
   `build_sha=local` is development evidence, not a release identifier.

## Current verification snapshot

On 2026-09-05, Crypto health returned schema `21`, the expected API contract,
and execution state `disabled`. Gateway health could reach Crypto and reported
the two runtimes as isolated. The stock health probe timed out; this is an
unavailable dependency, not evidence that the stock runtime is healthy.

The active Binance collector was public-market-data-only. Its heartbeat may be
used for collection diagnostics, but validation, EVAL, Paper, Shadow, Testnet,
and Live evidence counts remain independent and must be checked separately.

## Required P0 verification

```powershell
python -m pytest -q
cd web; npm.cmd test -- --run; npm.cmd run build; npm.cmd run build:unified
cd ..\crypto; python -m pytest -q
cd web; npm.cmd test -- --run; npm.cmd run build
cd ..; python scripts/verify_read_only_boundary.py
git diff --check
```

Before a release candidate, run the same commands in a fresh checkout without
local `.env`, runtime database, Parquet, or frontend build artifacts. Record
the exact commit SHA and CI run URL in the release note.

## Rollback point

`69b4acb` is the known local rollback point for the unified workspace. Any
future integration branch must preserve this commit in history and document
its own revert or rollback SHA.
