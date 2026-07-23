# Strategy Golden Cases

`tests/test_strategy_golden_cases.py` contains 20 fixed deterministic regression
cases for the canonical conclusion and hard-veto boundary. They cover clean
BUY, normal WATCH/PASS, extension and Gap risk, data/provider failures, source
fallback, session restrictions, market states, stop/R:R/liquidity faults, and
insufficient evidence.

These are synthetic safety fixtures, not historical performance evidence. The
later backtest stage will add separately versioned, point-in-time historical
cases from authorised candle and universe datasets. Until then, this suite
protects behavioural safety, not a claim of strategy profitability.
