import { describe, it, expect } from "vitest";
import { average, changeFrom, cleanBars, indicatorValues, type ChartBar } from "./marketChartMath";
const bar = (day: string, close: number, turnover: number | null = 100): ChartBar => ({ open_time: day + "T13:30:00Z", close_time: day + "T13:35:00Z", trading_date: day, open: close, high: close, low: close, close, volume: 10, turnover, bar_state: "closed" });
describe("chart math is display-only and preserves missing data", () => {
  it("does not confuse session change with interval change", () => { expect(changeFrom(194.25, 173.97)?.amount).toBeCloseTo(20.28); expect(changeFrom(194.25, null)).toBeNull(); expect(changeFrom(0, 100)?.percent).toBe(-100); });
  it("does not invent indicator warmup", () => { expect(average([1, 2], 3)).toEqual([null, null]); expect(average([1, 2, 3, 4], 3, true)).toEqual([null, null, 2, 3]); });
  it("deduplicates updates and keeps legal zero volume", () => { const a = { ...bar("2026-09-18", 10), volume: 0 }; expect(cleanBars([a, { ...a, close: 11 }])).toHaveLength(1); expect(cleanBars([a])[0].volume).toBe(0); });
  it("VWAP resets by trading date, missing turnover remains unknown", () => { expect(indicatorValues([bar("2026-09-18", 10), bar("2026-09-21", 20, 200)], "VWAP")).toEqual([10, 20]); expect(indicatorValues([bar("2026-09-18", 10, null)], "VWAP")).toEqual([null]); });
  it("flat RSI is 50 and insufficient history is unavailable", () => { const bars = Array.from({ length: 16 }, () => bar("2026-09-18", 10)); expect(indicatorValues(bars, "RSI")[14]).toBe(50); expect(indicatorValues(bars, "EMA200").every(v => v === null)).toBe(true); });
});
