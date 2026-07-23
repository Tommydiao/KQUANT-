# Hourly Confirmation Module

`kquant.entry_confirmation.analyze_hourly_confirmation` accepts only completed
1H bars. It returns the existing strict EMA20/50 plus momentum confirmation,
and separately records breakout, pullback reclaim, and hourly-volume context.

Forming bars are visible only as an exclusion count. They cannot create a
breakout, alter momentum, or satisfy a strict confirmation. The canonical
strategy continues to use the frozen EMA/momentum condition; the new fields are
audit context rather than unversioned rule changes.
