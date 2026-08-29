# Historical Signal Reconstruction

`kquant.stock_signals.reconstruct_signal` rebuilds a signal from caller-supplied
daily and hourly candle payloads at one `historical_timestamp`. It requires the
matching immutable strategy version and strips every forming or future-dated bar
before invoking the normal deterministic signal builder.

The response records the cutoff, completed bar counts, and final source-bar
timestamps. This creates a testable no-future-data boundary for the later
portfolio backtest runner; it does not fetch a new provider dataset or invoke an
LLM.
