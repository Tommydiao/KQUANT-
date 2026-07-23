# Trade Risk Module

`kquant.trade_risk.assess_trade_risk` audits a manual plan after entry, stop,
and targets have been calculated. It reports structural stop validity, risk per
share, R:R, recent swing-low context, average daily dollar volume, Gap/ATR/
extension warnings, and a maximum account-risk policy of 0.5%.

The module does not know an account value, calculate an order quantity, connect
to a broker, or submit an order. It can block the manual money-review and probe
eligibility paths while leaving the frozen strategy score and historical signal
classification unchanged.
