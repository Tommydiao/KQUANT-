import { Minus, Trash2, TrendingUp, Undo2 } from "lucide-react";
import {
  CandlestickSeries,
  createChart,
  HistogramSeries,
  LineSeries,
  type CandlestickData,
  type HistogramData,
  type LineData,
  type Time,
} from "lightweight-charts";
import { useEffect, useMemo, useRef, useState } from "react";

type Theme = "light" | "dark";
type DisplayTimezone = "Asia/Shanghai" | "America/New_York";
type ChartPresetKey = "today1m" | "today5m" | "5d15m" | "1h" | "1d" | "1w" | "1m";
type ChartDrawingTool = "none" | "horizontal" | "trend";
type ChartDrawingLabel = "Line" | "Entry" | "Stop" | "Target" | "Alert";
type Candle = { time: Time; open_time?: string; open: number; high: number; low: number; close: number; volume: number };
type ChartPreset = { key: ChartPresetKey; label: string; range: string; interval: string };
type CandleMeta = {
  symbol: string;
  range: string;
  interval: string;
  sourceType: string;
  providerStatus: string;
  freshness: string;
  staleAge: string;
  count: number;
  first: string;
  last: string;
  errors: string[];
  exchangeTimezone?: string;
};
type ChartDrawing = { id: string; kind: Exclude<ChartDrawingTool, "none">; label: ChartDrawingLabel; color: string; price: number; time: Time; endPrice?: number; endTime?: Time };
type OhlcState = { time: string; open: number; high: number; low: number; close: number };

function formatDate(value: string | number | Date, timeZone: DisplayTimezone, withDate: boolean): string {
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return new Intl.DateTimeFormat("en-GB", { timeZone, month: withDate ? "2-digit" : undefined, day: withDate ? "2-digit" : undefined, hour: "2-digit", minute: "2-digit", hour12: false }).format(date);
}

function chartTimeDate(time: Time): Date | null {
  if (typeof time === "number") return new Date(time * 1000);
  if (typeof time === "string") {
    const parsed = new Date(time);
    return Number.isNaN(parsed.getTime()) ? null : parsed;
  }
  if (time && typeof time === "object" && "year" in time && "month" in time && "day" in time) return new Date(Date.UTC(Number(time.year), Number(time.month) - 1, Number(time.day)));
  return null;
}

function formatChartTime(time: Time, timeZone: DisplayTimezone, withDate: boolean): string {
  const date = chartTimeDate(time);
  return date ? formatDate(date, timeZone, withDate) : String(time);
}

function formatCandleTime(candle: Candle | undefined, timeZone: DisplayTimezone): string {
  if (!candle) return "";
  if (candle.open_time) return formatDate(candle.open_time, timeZone, true);
  const seconds = Number(candle.time);
  return Number.isFinite(seconds) ? formatDate(seconds * 1000, timeZone, true) : "";
}

function ema(candles: Candle[], period: number): LineData<Time>[] {
  if (!candles.length) return [];
  const multiplier = 2 / (period + 1);
  let value = candles.slice(0, period).reduce((sum, candle) => sum + candle.close, 0) / Math.min(period, candles.length);
  return candles.map((candle, index) => {
    if (index >= period) value = (candle.close - value) * multiplier + value;
    return { time: candle.time, value };
  }).slice(Math.max(0, period - 1));
}

function addLine(chart: ReturnType<typeof createChart>, data: LineData<Time>[], color: string) {
  if (!data.length) return;
  const series = chart.addSeries(LineSeries, { color, lineWidth: 2, lastValueVisible: false, priceLineVisible: false });
  series.setData(data);
}

function Segmented({ value, options, onChange }: { value: string; options: [string, string][]; onChange: (value: string) => void }) {
  return <div className="segmented">{options.map(([key, label]) => <button className={value === key ? "active" : ""} key={key} type="button" onClick={() => onChange(key)}>{label}</button>)}</div>;
}

export function ChartPanel({
  title,
  subtitle,
  candles,
  theme,
  ohlcHint,
  emptyText,
  meta,
  presets,
  presetKey,
  onPresetChange,
  onReload,
  displayTimezone = "Asia/Shanghai",
  onDisplayTimezoneChange,
  labels,
}: {
  title: string;
  subtitle: string;
  candles: Candle[];
  theme: Theme;
  ohlcHint: string;
  emptyText: string;
  meta: CandleMeta;
  presets: ChartPreset[];
  presetKey: ChartPresetKey;
  onPresetChange: (value: string) => void;
  onReload?: () => void;
  displayTimezone?: DisplayTimezone;
  onDisplayTimezoneChange?: (timezone: DisplayTimezone) => void;
  labels: { source: string; status: string; range: string; candles: string; firstLast: string };
}) {
  const panelRef = useRef<HTMLElement | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [hover, setHover] = useState<OhlcState | null>(null);
  const [drawingTool, setDrawingTool] = useState<ChartDrawingTool>("none");
  const [drawingLabel, setDrawingLabel] = useState<ChartDrawingLabel>("Line");
  const [drawingColor, setDrawingColor] = useState("#5caeff");
  const [drawings, setDrawings] = useState<ChartDrawing[]>([]);
  const [trendAnchor, setTrendAnchor] = useState<ChartDrawing | null>(null);
  const indicators = useMemo(() => ({ ema20: ema(candles, 20), ema50: ema(candles, 50), ema200: ema(candles, 200) }), [candles]);
  const effectiveEmptyText = meta.providerStatus === "refreshing" ? "Refreshing real data..." : emptyText;

  useEffect(() => {
    setDrawings([]);
    setTrendAnchor(null);
    setDrawingTool("none");
  }, [meta.symbol, presetKey]);

  useEffect(() => {
    if (!containerRef.current) return;
    const container = containerRef.current;
    container.innerHTML = "";
    const dark = theme === "dark";
    const chart = createChart(container, {
      width: container.clientWidth,
      height: container.clientHeight,
      autoSize: true,
      layout: { background: { color: dark ? "#0f172a" : "#ffffff" }, textColor: dark ? "#94a3b8" : "#64748b", fontFamily: "Inter, ui-sans-serif, system-ui, sans-serif" },
      grid: { vertLines: { color: dark ? "#1e293b" : "#eef2f7" }, horzLines: { color: dark ? "#1e293b" : "#eef2f7" } },
      rightPriceScale: { borderColor: dark ? "#263241" : "#e5e7eb" },
      localization: { timeFormatter: (time: Time) => formatChartTime(time, displayTimezone, true) },
      timeScale: { borderColor: dark ? "#263241" : "#e5e7eb", timeVisible: true, tickMarkFormatter: (time: Time) => formatChartTime(time, displayTimezone, false) },
      handleScroll: { mouseWheel: false, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: false },
      handleScale: { mouseWheel: false, pinch: true, axisPressedMouseMove: true },
    });
    const candleSeries = chart.addSeries(CandlestickSeries, { upColor: "#16a34a", downColor: "#ef4444", wickUpColor: "#16a34a", wickDownColor: "#ef4444", borderVisible: false, priceLineColor: "#2563eb" });
    candleSeries.setData(candles as CandlestickData<Time>[]);
    const volumeSeries = chart.addSeries(HistogramSeries, { color: "rgba(99, 102, 241, 0.22)", priceFormat: { type: "volume" }, priceScaleId: "" });
    volumeSeries.priceScale().applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
    volumeSeries.setData(candles.map((bar) => ({ time: bar.time, value: bar.volume, color: bar.close >= bar.open ? "rgba(22, 163, 74, 0.24)" : "rgba(239, 68, 68, 0.22)" })) as HistogramData<Time>[]);
    addLine(chart, indicators.ema20, "#2563eb");
    addLine(chart, indicators.ema50, "#f59e0b");
    addLine(chart, indicators.ema200, "#0f766e");
    for (const drawing of drawings) {
      if (drawing.kind === "horizontal") {
        candleSeries.createPriceLine({ price: drawing.price, color: drawing.color, lineWidth: 2, lineStyle: 2, axisLabelVisible: true, title: drawing.label });
      } else if (drawing.endTime !== undefined && drawing.endPrice !== undefined) {
        const line = chart.addSeries(LineSeries, { color: drawing.color, lineWidth: 2, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
        line.setData([{ time: drawing.time, value: drawing.price }, { time: drawing.endTime, value: drawing.endPrice }]);
      }
    }
    chart.timeScale().fitContent();
    chart.subscribeCrosshairMove((param) => {
      const point = param.seriesData.get(candleSeries);
      if (!point || !("open" in point)) { setHover(null); return; }
      setHover({ time: formatChartTime(point.time, displayTimezone, true), open: point.open, high: point.high, low: point.low, close: point.close });
    });
    const handleChartClick = (param: { point?: { y: number }; time?: Time }) => {
      if (drawingTool === "none" || !param.point || param.time === undefined) return;
      const price = candleSeries.coordinateToPrice(param.point.y);
      if (price === null) return;
      const point: ChartDrawing = { id: `${Date.now()}-${Math.random().toString(16).slice(2)}`, kind: drawingTool, label: drawingLabel, color: drawingColor, price, time: param.time };
      if (drawingTool === "horizontal") { setDrawings((current) => [...current, point]); return; }
      if (trendAnchor) { setDrawings((current) => [...current, { ...trendAnchor, endTime: point.time, endPrice: point.price }]); setTrendAnchor(null); setDrawingTool("none"); } else setTrendAnchor(point);
    };
    chart.subscribeClick(handleChartClick);
    return () => { chart.unsubscribeClick(handleChartClick); chart.remove(); };
  }, [candles, displayTimezone, drawingColor, drawingLabel, drawingTool, drawings, indicators.ema20, indicators.ema50, indicators.ema200, theme, trendAnchor]);

  const firstLabel = candles.length ? formatCandleTime(candles[0], displayTimezone) : meta.first;
  const lastLabel = candles.length ? formatCandleTime(candles[candles.length - 1], displayTimezone) : meta.last;
  const timezoneLabel = displayTimezone === "Asia/Shanghai" ? "China UTC+8" : "New York ET";
  const openFullscreen = () => { if (panelRef.current?.requestFullscreen) void panelRef.current.requestFullscreen(); };
  return (
    <section className="panel chart-panel" ref={panelRef}>
      <div className="chart-header"><div><h3>{title}</h3><p>{subtitle}</p></div><div className="chart-tools">
        <Segmented value={presetKey} options={presets.map((preset) => [preset.key, preset.label])} onChange={onPresetChange} />
        {onDisplayTimezoneChange ? <Segmented value={displayTimezone} options={[["Asia/Shanghai", "CN +8"], ["America/New_York", "ET"]]} onChange={(value) => onDisplayTimezoneChange(value as DisplayTimezone)} /> : null}
        <button className="chart-reload" type="button" onClick={onReload}>Reload Real Data</button><button className="chart-reload" type="button" onClick={openFullscreen}>Fullscreen</button>
        <div className="indicator-tags"><span>EMA20</span><span>EMA50</span><span>EMA200</span><span>Volume</span></div>
        <div className="chart-drawing-tools" aria-label="Drawing tools">
          <button className={`chart-tool-button ${drawingTool === "horizontal" ? "active" : ""}`} type="button" title="Horizontal line" onClick={() => { setDrawingTool((tool) => tool === "horizontal" ? "none" : "horizontal"); setTrendAnchor(null); }}><Minus size={15} /></button>
          <button className={`chart-tool-button ${drawingTool === "trend" ? "active" : ""}`} type="button" title="Trend line" onClick={() => { setDrawingTool((tool) => tool === "trend" ? "none" : "trend"); setTrendAnchor(null); }}><TrendingUp size={15} /></button>
          <select aria-label="Drawing label" value={drawingLabel} onChange={(event) => setDrawingLabel(event.target.value as ChartDrawingLabel)}><option value="Line">Line</option><option value="Entry">Entry</option><option value="Stop">Stop</option><option value="Target">Target</option><option value="Alert">Alert</option></select>
          <input aria-label="Drawing color" type="color" value={drawingColor} onChange={(event) => setDrawingColor(event.target.value)} />
          <button className="chart-tool-button" type="button" title="Undo last drawing" disabled={!drawings.length && !trendAnchor} onClick={() => { setTrendAnchor(null); setDrawings((current) => current.slice(0, -1)); }}><Undo2 size={15} /></button>
          <button className="chart-tool-button" type="button" title="Clear drawings" disabled={!drawings.length && !trendAnchor} onClick={() => { setTrendAnchor(null); setDrawings([]); setDrawingTool("none"); }}><Trash2 size={15} /></button>
        </div>
      </div></div>
      <div className="chart-meta"><span>{labels.source}: <b>{meta.sourceType}</b></span><span>{labels.status}: <b>{meta.providerStatus}</b></span><span>Freshness: <b>{meta.freshness}</b></span><span>Stale Age: <b>{meta.staleAge}</b></span><span>{labels.range}: <b>{meta.range} / {meta.interval}</b></span><span>{labels.candles}: <b>{meta.count}</b></span><span>{labels.firstLast}: <b>{firstLabel || "-"} / {lastLabel || "-"}</b></span><span>Display: <b>{timezoneLabel}</b></span>{meta.exchangeTimezone ? <span>Exchange: <b>{meta.exchangeTimezone}</b></span> : null}{meta.errors.length ? <span>Errors: <b>{meta.errors.join("; ").slice(0, 120)}</b></span> : null}</div>
      <div className="ohlc-row">{hover ? <><span>{hover.time}</span><span>O {hover.open.toFixed(2)}</span><span>H {hover.high.toFixed(2)}</span><span>L {hover.low.toFixed(2)}</span><span>C {hover.close.toFixed(2)}</span></> : <span>{ohlcHint}</span>}</div>
      {candles.length ? <div className="chart-canvas" ref={containerRef} /> : <div className="chart-empty"><span>{effectiveEmptyText}</span>{onReload ? <button type="button" onClick={onReload}>Repair Chart With Real Data</button> : null}</div>}
    </section>
  );
}
