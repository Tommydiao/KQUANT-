# Daily Trend Module

`kquant.trend_analysis.analyze_daily_trend` consumes completed daily candles and
the versioned technical-feature snapshot. It reports EMA20/50/200 alignment,
recent higher-high/lower-low structure, direction, strength, extension risk, and
higher-timeframe risks.

The module's bullish EMA alignment is the existing canonical trend gate. The
additional structure and risk fields are persisted for audit; they do not alter
the frozen score weights or thresholds of `swing_long_v1.0.1`.
