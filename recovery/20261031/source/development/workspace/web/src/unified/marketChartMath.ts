export type ChartBar = { open_time: string; close_time: string; trading_date: string; open: number; high: number; low: number; close: number; volume: number | null; turnover: number | null; bar_state: string };
export const validNumber = (v: unknown): v is number => typeof v === "number" && Number.isFinite(v);
export function cleanBars(rows: ChartBar[]): ChartBar[] {
  return [...new Map(rows.filter(b => [b.open, b.high, b.low, b.close].every(v => validNumber(v) && v > 0) && Number.isFinite(Date.parse(b.open_time))).map(b => [b.open_time, b])).values()].sort((a, b) => a.open_time.localeCompare(b.open_time));
}
export function average(values: Array<number | null>, period: number, exponential = false): Array<number | null> {
  let previous: number | null = null;
  return values.map((value, i) => {
    if (i < period - 1 || value === null) return null;
    const window = values.slice(i - period + 1, i + 1);
    if (window.some(v => v === null)) { previous = null; return null; }
    previous = exponential && previous !== null ? value * 2 / (period + 1) + previous * (1 - 2 / (period + 1)) : (window as number[]).reduce((s, v) => s + v, 0) / period;
    return previous;
  });
}
export function indicatorValues(bars: ChartBar[], key: string): Array<number | null> {
  const prices = bars.map(b => b.close);
  const match = /^(EMA|MA)(\d+)$/.exec(key);
  if (match) return average(prices, Number(match[2]), match[1] === "EMA");
  if (key === "VWAP") {
    let session = "", amount = 0, volume = 0, valid = true;
    return bars.map(b => {
      if (session !== b.trading_date) { session = b.trading_date; amount = 0; volume = 0; valid = true; }
      if (!validNumber(b.turnover) || !validNumber(b.volume) || b.volume < 0 || b.turnover < 0) valid = false;
      if (!valid) return null;
      amount += b.turnover!; volume += b.volume!;
      return volume > 0 ? amount / volume : null;
    });
  }
  if (key === "RSI") {
    let gain = 0, loss = 0;
    return prices.map((v, i) => {
      if (!i) return null;
      const change = v - prices[i - 1];
      if (i <= 14) { gain += Math.max(0, change) / 14; loss += Math.max(0, -change) / 14; }
      else { gain = (gain * 13 + Math.max(0, change)) / 14; loss = (loss * 13 + Math.max(0, -change)) / 14; }
      return i < 14 ? null : gain === 0 && loss === 0 ? 50 : loss === 0 ? 100 : 100 - 100 / (1 + gain / loss);
    });
  }
  const fast = average(prices, 12, true), slow = average(prices, 26, true);
  const macd = fast.map((v, i) => v !== null && slow[i] !== null ? v - slow[i]! : null);
  const signal = average(macd, 9, true);
  if (key === "MACD_HISTOGRAM") return macd.map((v, i) => v !== null && signal[i] !== null ? v - signal[i]! : null);
  return key === "MACD_SIGNAL" ? signal : macd;
}
export function changeFrom(price: unknown, reference: unknown) {
  return validNumber(price) && validNumber(reference) && reference > 0 ? { amount: price - reference, percent: (price / reference - 1) * 100 } : null;
}
