# Hard-Veto Policy

`hard_veto_v1` is the deterministic no-buy policy bound to
`swing_long_v1.1.0`. It evaluates data quality, provider/source state, regular
session, market regime, structural stop, R:R, liquidity, extension, and
historical evidence.

When any reason is active, `buy_actions_allowed` is false and the deterministic
trade conclusion is forced to `WAIT`. AI cannot override this result. This is a
research and manual-review safety boundary only: KQUANT still has no broker,
account, position, or order-submission path.
