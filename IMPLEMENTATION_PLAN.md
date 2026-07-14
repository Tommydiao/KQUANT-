# KQUANT Implementation Baseline

The active product is a read-only US stock and ETF research terminal.

## Delivered

- `kquant.dashboard` stock-only FastAPI runtime and route-safety audit.
- Persistent Longbridge quote context, bounded selected-symbol subscriptions, BBO depth, and safe reset.
- Realtime quote plus forming 1m and aggregated 5m chart state.
- XNYS exchange calendar with Longbridge day status and SQLite cache.
- Feature Packet v3.1, material-state hash, backend model cooldown, and manual regenerate bypass.
- Deterministic historical policy replay and separate prospective AI evidence.
- Windows CI for tests, frontend build, and runtime-boundary scanning.

## Operating Rule

Use KQUANT in paper-observed mode until the test split and at least ten market
days of prospective AI actions have been reviewed. Existing thresholds remain
frozen during that observation window.
