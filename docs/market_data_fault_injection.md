# Market Data Fault-Injection Matrix

The repeatable regression matrix is in
`tests/test_market_data_fault_injection.py`.

| Fault | Expected system response |
| --- | --- |
| Provider HTTP timeout | Provider state is unavailable; data quality is `blocked`. |
| Longbridge unavailable with Yahoo available | Yahoo is shown only as explicit reference fallback; data quality blocks buy/probe eligibility. |
| Future-dated candle | Timestamp integrity fails; data quality is `blocked`. |
| SQLite cache write failure | Response remains usable for display with a recorded cache failure; no clean execution eligibility is manufactured. |

This suite uses mocks only. It never calls a broker, account, order, or real
Longbridge credential. New provider behaviours must add a matching deterministic
failure test before they are treated as safe for pilot observation.
