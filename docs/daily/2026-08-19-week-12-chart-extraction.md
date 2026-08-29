# KQUANT v2 Week 12 chart extraction

- Moved the active chart renderer to `web/src/features/quant/ChartPanel.tsx`.
- Preserved Longbridge source metadata, EMA20/EMA50/EMA200, volume, timezone controls, fullscreen, horizontal lines, trend lines, labels, color selection, undo, and clear.
- Removed the old inline chart renderer from `web/src/App.tsx`; the remaining chart call sites use `ChartPanelView`.
- Browser smoke confirmed `longbridge_candles`, EMA labels, drawing controls, horizontal-line undo, and trend-line clear behavior. No console errors were reported.
- Production build and frontend tests passed. The single large bundle warning remains a later performance task.
