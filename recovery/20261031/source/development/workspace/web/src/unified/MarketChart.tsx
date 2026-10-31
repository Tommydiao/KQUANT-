import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createChart, CandlestickSeries, HistogramSeries, LineSeries, type IChartApi, type ISeriesApi, type Time } from "lightweight-charts";
import { ArrowRight, Crosshair, Maximize, Minus, RefreshCw, Trash2, TrendingUp, Undo2 } from "lucide-react";
import { useI18n } from "./i18n";
import { chartText } from "./marketChartText";
import { changeFrom, cleanBars, indicatorValues, validNumber, type ChartBar } from "./marketChartMath";
import "./market-chart.css";

type Json = Record<string, any>;
type Drawing = { id: string; kind: "horizontal" | "trend"; time: Time; price: number; endTime?: Time; endPrice?: number; color: string };
const PRESETS = [["line", "Intraday"], ["1m", "1m"], ["5m", "5m"], ["15m", "15m"], ["30m", "30m"], ["1h", "1H"], ["1d", "Daily"], ["1wk", "Weekly"], ["1mo", "Monthly"]];
const LONG = new Set(["1d", "1wk", "1mo"]);
const COLORS = ["--color-accent", "--color-caution", "--color-positive", "--color-negative", "--color-ink-2", "--color-accent-strong", "--color-muted"];
function chartColor(element: HTMLElement, token: string) {
  const canvas = document.createElement("canvas"), ctx = canvas.getContext("2d")!;
  ctx.fillStyle = getComputedStyle(element).getPropertyValue(token).trim() || "#888888";
  ctx.fillRect(0, 0, 1, 1);
  const [r, g, b] = ctx.getImageData(0, 0, 1, 1).data;
  return `rgb(${r},${g},${b})`;
}

export function MarketChart({ symbol, theme, refreshNonce = 0, onOpenChain }: { symbol: string; theme: "light" | "dark"; refreshNonce?: number; onOpenChain: (symbol: string) => void }) {
  const { language, locale } = useI18n();
  const tx = useCallback((key: string) => language === "zh" ? chartText[key as keyof typeof chartText] ?? key : key, [language]);
  const [preset, setPreset] = useState(() => { const saved = localStorage.getItem("kquant-chart:preset"); return PRESETS.some(([value]) => value === saved) ? saved! : "5m"; });
  const interval = preset === "line" ? "1m" : preset;
  const [session, setSession] = useState("regular"), [adjustment, setAdjustment] = useState(LONG.has(interval) ? "forward" : "none");
  const [timezone, setTimezone] = useState("America/New_York");
  const [selected, setSelected] = useState(["EMA20", "EMA50"]), [subpanel, setSubpanel] = useState("none");
  const [showVolume, setShowVolume] = useState(true);
  const [depthOpen, setDepthOpen] = useState(() => window.innerWidth > 1000);
  const [model, setModel] = useState<{ key: string; candles: ChartBar[]; meta: Json; quote: Json; depth: Json }>({ key: "", candles: [], meta: {}, quote: {}, depth: {} });
  const key = `${symbol}:${interval}:${session}:${adjustment}`;
  const keyRef = useRef(key); keyRef.current = key;
  const current = model.key === key ? model : { key, candles: [], meta: {}, quote: {}, depth: {} };
  const [refresh, setRefresh] = useState(0), [loading, setLoading] = useState(false), [stream, setStream] = useState("Connecting");
  const [pageError, setPageError] = useState("");
  const [hover, setHover] = useState<ChartBar | null>(null);
  const [tool, setTool] = useState<"none" | "horizontal" | "trend">("none");
  const [color, setColor] = useState("#5ea8ff"), [drawings, setDrawings] = useState<Drawing[]>([]);
  const box = useRef<HTMLDivElement>(null), shell = useRef<HTMLElement>(null);
  const chart = useRef<IChartApi | null>(null), candle = useRef<ISeriesApi<"Candlestick"> | null>(null), line = useRef<ISeriesApi<"Line"> | null>(null);
  const volume = useRef<ISeriesApi<"Histogram"> | null>(null), overlays = useRef<ISeriesApi<"Line">[]>([]);
  const macdHistogram = useRef<ISeriesApi<"Histogram"> | null>(null);
  const priceLine = useRef<ReturnType<ISeriesApi<"Candlestick">["createPriceLine"]> | null>(null);
  const drawLines = useRef<ReturnType<ISeriesApi<"Candlestick">["createPriceLine"]>[]>([]), drawSeries = useRef<ISeriesApi<"Line">[]>([]);
  const anchor = useRef<Drawing | null>(null), drawState = useRef({ tool, color });
  drawState.current = { tool, color };
  const dataRef = useRef(current.candles); dataRef.current = current.candles;
  const fitted = useRef(false), [chartVersion, setChartVersion] = useState(0);
  const previousFirstBar = useRef<string | null>(null);
  const fmt = (value: unknown, digits = 2) => validNumber(value) ? value.toLocaleString(locale, { maximumFractionDigits: digits }) : "—";
  const formatTime = useCallback((value: unknown) => {
    if (!value) return "—";
    const date = new Date(String(value));
    return Number.isFinite(date.getTime()) ? new Intl.DateTimeFormat(locale, { timeZone: timezone, month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }).format(date) : "—";
  }, [locale, timezone]);
  const barTime = useCallback((bar: ChartBar): Time => LONG.has(interval) ? bar.trading_date : Math.floor(Date.parse(bar.open_time) / 1000) as Time, [interval]);
  const params = useMemo(() => new URLSearchParams({ symbol, interval, session, adjustment, mode: "chart" }).toString(), [key]);
  const errorText = (code?: string) => tx(({ HISTORY_QUOTA: "History quota reached", PERMISSION_REQUIRED: "Permission required", TIMEOUT: "Request timed out", INVALID_REQUEST: "Invalid chart request" } as Record<string, string>)[code || ""] || "Provider unavailable");

  useEffect(() => {
    const abort = new AbortController(); let alive = true, events: EventSource | null = null, timer: ReturnType<typeof setInterval>;
    let connected = false, pulling = false, lastBarsPull = 0, marketSession = "closed";
    const patch = (values: Partial<typeof model>) => {
      if (!alive) return;
      setModel(previous => {
        const base = previous.key === key ? previous : { key, candles: [], meta: {}, quote: {}, depth: {} };
        return { ...base, ...values, key,
          quote: values.quote ? { ...base.quote, ...values.quote } : base.quote,
          depth: values.depth ? { ...base.depth, ...values.depth } : base.depth };
      });
    };
    const read = async (url: string) => { const response = await fetch(url, { signal: abort.signal }); if (!response.ok) throw new Error("NETWORK_ERROR"); return response.json(); };
    const barsPull = async () => {
      lastBarsPull = Date.now();
      try { const result = await read(`/api/stocks/candles?${params}`); patch({ meta: result }); if (result.candles?.length) patch({ candles: cleanBars(result.candles) }); }
      catch { patch({ meta: { status: "unavailable", error_code: "NETWORK_ERROR" } }); }
    };
    const snapshot = async () => {
      if (pulling || document.hidden) return;
      pulling = true; setLoading(true);
      await Promise.all([
        barsPull(),
        read(`/api/stocks/quote?symbol=${encodeURIComponent(symbol)}&mode=chart`).then(quote => { marketSession = quote.market_session || "closed"; patch({ quote }); }).catch(() => patch({ quote: { status: "unavailable" } })),
        read(`/api/stocks/depth?symbol=${encodeURIComponent(symbol)}`).then(depth => patch({ depth })).catch(() => patch({ depth: { status: "unavailable" } })),
      ]);
      pulling = false; if (alive) setLoading(false);
    };
    const connect = () => {
      if (document.hidden || !alive || events) return;
      setStream("Connecting"); events = new EventSource(`/api/stocks/chart/stream?${params}`);
      events.addEventListener("ready", () => { connected = true; setStream("Connected"); });
      events.addEventListener("failure", () => { connected = false; setStream("Disconnected"); });
      events.onerror = () => { connected = false; if (alive) setStream("Disconnected"); };
      events.onmessage = e => {
        if (!alive) return;
        let message: Json; try { message = JSON.parse(e.data); } catch { return; } if (message.symbol !== symbol) return;
        if (message.payload?.market_session) marketSession = message.payload.market_session;
        setModel(previous => {
          if (previous.key !== key) return previous;
          if (message.kind === "candle") {
            const incoming = message.payload as ChartBar;
            const same = previous.candles.find(b => b.open_time === incoming.open_time);
            if (same?.bar_state === "closed" && incoming.bar_state !== "closed") return previous;
            return { ...previous, candles: cleanBars([...previous.candles, incoming]) };
          }
          const field = message.kind === "depth" ? "depth" : "quote";
          if (previous[field].received_at && message.received_at < previous[field].received_at) return previous;
          const priorQuote = message.payload.session && message.payload.session !== "regular" ? previous.quote[message.payload.session] : previous.quote;
          if (field === "quote" && priorQuote?.event_time && message.payload.event_time && Date.parse(message.payload.event_time) < Date.parse(priorQuote.event_time)) return previous;
          const useful = Object.fromEntries(Object.entries(message.payload).filter(([, value]) => value !== null && value !== undefined));
          if (field === "quote" && message.payload.session !== "regular") {
            const part = message.payload.session;
            return { ...previous, quote: { ...previous.quote, market_session: message.payload.market_session, [part]: { ...previous.quote[part], ...useful } } };
          }
          return { ...previous, [field]: { ...previous[field], ...useful, status: "available" } };
        });
        if ((adjustment === "forward" || session !== "regular") && Date.now() - lastBarsPull >= 15000) void barsPull();
      };
    };
    void snapshot().then(connect);
    const visibility = () => { if (document.hidden) { events?.close(); events = null; connected = false; } else { void snapshot().then(connect); } };
    document.addEventListener("visibilitychange", visibility);
    timer = setInterval(() => { if (!connected && !document.hidden && marketSession !== "closed") void snapshot(); }, 15000);
    setPageError("");
    return () => { alive = false; abort.abort(); events?.close(); clearInterval(timer); document.removeEventListener("visibilitychange", visibility); };
  }, [key, params, refresh, refreshNonce]);

  useEffect(() => {
    anchor.current = null; setTool("none");
    try { setDrawings(JSON.parse(localStorage.getItem(`kquant-chart:drawings:${key}`) || "[]")); } catch { setDrawings([]); }
  }, [key]);
  const changeDrawings = (fn: (previous: Drawing[]) => Drawing[]) => setDrawings(previous => { const next = fn(previous); localStorage.setItem(`kquant-chart:drawings:${key}`, JSON.stringify(next)); return next; });
  const drawUpdate = useRef(changeDrawings); drawUpdate.current = changeDrawings;

  useEffect(() => {
    if (!box.current) return;
    const element = box.current;
    const colorFor = (token: string) => chartColor(element, token);
    const instance = createChart(element, { autoSize: true, layout: { background: { color: colorFor("--color-bg") }, textColor: colorFor("--color-ink-2"), fontSize: 12, attributionLogo: true },
      grid: { vertLines: { visible: false }, horzLines: { color: colorFor("--color-rule") } },
      rightPriceScale: { borderColor: colorFor("--color-rule") },
      timeScale: { timeVisible: !LONG.has(interval), secondsVisible: false, borderColor: colorFor("--color-rule") },
      localization: { locale }, handleScroll: { mouseWheel: true, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: false },
    });
    chart.current = instance;
    candle.current = instance.addSeries(CandlestickSeries, { upColor: colorFor("--color-positive"), downColor: colorFor("--color-negative"), wickUpColor: colorFor("--color-positive"), wickDownColor: colorFor("--color-negative"), borderVisible: false });
    line.current = instance.addSeries(LineSeries, { color: colorFor("--color-accent"), lineWidth: 2 });
    volume.current = instance.addSeries(HistogramSeries, { priceFormat: { type: "volume" }, lastValueVisible: false, priceLineVisible: false }, 1);
    instance.panes()[0].setStretchFactor(4); instance.panes()[1].setStretchFactor(1);
    instance.subscribeCrosshairMove(p => { const value = p.seriesData.get(candle.current!) || p.seriesData.get(line.current!); setHover(value ? dataRef.current.find(b => String(barTime(b)) === String(value.time)) || null : null); });
    instance.subscribeClick(p => {
      const { tool: active, color: drawingColor } = drawState.current;
      if (active === "none" || !p.point || p.time === undefined || p.paneIndex !== 0) return;
      const price = candle.current?.coordinateToPrice(p.point.y); if (price == null) return;
      const point: Drawing = { id: crypto.randomUUID(), kind: active, time: p.time, price, color: drawingColor };
      if (active === "horizontal") { drawUpdate.current(previous => [...previous, point]); setTool("none"); }
      else if (anchor.current && String(anchor.current.time) !== String(point.time)) {
        const first = anchor.current; drawUpdate.current(previous => [...previous, { ...first, endTime: point.time, endPrice: price }]); anchor.current = null; setTool("none");
      } else anchor.current = point;
    });
    fitted.current = false; previousFirstBar.current = null; overlays.current = []; macdHistogram.current = null; drawLines.current = []; drawSeries.current = []; priceLine.current = null;
    setChartVersion(v => v + 1);
    return () => { instance.remove(); chart.current = null; candle.current = null; line.current = null; volume.current = null; };
  }, [key, theme, locale]);

  useEffect(() => {
    if (!chart.current || !candle.current || !line.current || !volume.current) return;
    const bars = current.candles;
    const visibleRange = fitted.current ? chart.current.timeScale().getVisibleLogicalRange() : null;
    const offset = previousFirstBar.current ? Math.max(0, bars.findIndex(b => b.open_time === previousFirstBar.current)) : 0;
    candle.current.setData(bars.map(b => ({ time: barTime(b), open: b.open, high: b.high, low: b.low, close: b.close })));
    line.current.setData(bars.map(b => ({ time: barTime(b), value: b.close })));
    candle.current.applyOptions({ visible: preset !== "line" }); line.current.applyOptions({ visible: preset === "line" });
    const up = chartColor(box.current!, "--color-positive"), down = chartColor(box.current!, "--color-negative");
    volume.current.setData(bars.filter(b => validNumber(b.volume)).map(b => ({ time: barTime(b), value: b.volume!, color: b.close >= b.open ? up : down })));
    volume.current.applyOptions({ visible: showVolume });
    if (bars.length && !fitted.current) {
      const first = bars.find(b => b.open_time === current.meta.visible_from) || bars[0];
      chart.current.timeScale().setVisibleRange({ from: barTime(first), to: barTime(bars[bars.length - 1]) }); fitted.current = true;
    } else if (visibleRange && bars.length) chart.current.timeScale().setVisibleLogicalRange({ from: visibleRange.from + offset, to: visibleRange.to + offset });
    previousFirstBar.current = bars[0]?.open_time || null;
  }, [current.candles, preset, showVolume, chartVersion]);

  useEffect(() => {
    const instance = chart.current; if (!instance) return;
    instance.applyOptions({ localization: { timeFormatter: (time: Time) => typeof time === "number" ? formatTime(new Date(time * 1000).toISOString()) : typeof time === "string" ? time : `${time.year}-${time.month}-${time.day}` },
      timeScale: { tickMarkFormatter: (time: Time) => typeof time === "number" ? new Intl.DateTimeFormat(locale, { timeZone: timezone, month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hour12: false }).format(new Date(time * 1000)) : typeof time === "string" ? time : `${time.year}/${time.month}/${time.day}` } });
  }, [timezone, locale, chartVersion, formatTime]);

  useEffect(() => {
    const instance = chart.current; if (!instance || !box.current) return;
    overlays.current.forEach(series => instance.removeSeries(series)); overlays.current = [];
    if (macdHistogram.current) { instance.removeSeries(macdHistogram.current); macdHistogram.current = null; }
    const names = [...selected, ...(subpanel === "none" ? [] : subpanel === "MACD" ? ["MACD", "MACD_SIGNAL"] : ["RSI"])];
    names.forEach((name, i) => {
      const values = indicatorValues(current.candles, name);
      const points = current.candles.flatMap((b, j) => values[j] === null ? [] : [{ time: barTime(b), value: values[j]! }]);
      if (!points.length) return;
      const series = instance.addSeries(LineSeries, { color: chartColor(box.current!, COLORS[i % COLORS.length]), lineWidth: 1, lastValueVisible: false, priceLineVisible: false }, name === "RSI" || name.startsWith("MACD") ? 2 : 0);
      series.setData(points); overlays.current.push(series);
    });
    if (subpanel === "MACD") {
      const values = indicatorValues(current.candles, "MACD_HISTOGRAM");
      macdHistogram.current = instance.addSeries(HistogramSeries, { lastValueVisible: false, priceLineVisible: false }, 2);
      macdHistogram.current.setData(current.candles.flatMap((b, i) => values[i] === null ? [] : [{ time: barTime(b), value: values[i]!, color: chartColor(box.current!, values[i]! >= 0 ? "--color-positive" : "--color-negative") }]));
    }
  }, [current.candles, selected, subpanel, chartVersion]);

  const quote = current.quote, depth = current.depth;
  const price = quote.last, lastBar = current.candles[current.candles.length - 1];
  const change = changeFrom(price, quote.previous_close), rangeChange = changeFrom(lastBar?.close, current.candles[0]?.close);
  const quoteAge = quote.event_time ? (Date.now() - Date.parse(quote.event_time)) / 1000 : null;
  const quoteState = quote.status !== "available" ? "Unavailable" : quoteAge !== null && quoteAge < -5 ? "Time conflict" : quote.market_session === "closed" ? "Market closed" : quoteAge === null || quoteAge > 120 ? "Reference" : "Available";
  useEffect(() => {
    if (!candle.current) return;
    if (priceLine.current) candle.current.removePriceLine(priceLine.current);
    priceLine.current = validNumber(price) && quoteState !== "Time conflict" && adjustment === "none" ? candle.current.createPriceLine({ price, color: chartColor(box.current!, "--color-accent"), lineWidth: 1, lineStyle: 2, title: tx("Last") }) : null;
  }, [price, quoteState, adjustment, chartVersion, tx]);
  useEffect(() => {
    if (!chart.current || !candle.current) return;
    drawLines.current.forEach(l => candle.current!.removePriceLine(l)); drawSeries.current.forEach(s => chart.current!.removeSeries(s));
    drawLines.current = []; drawSeries.current = [];
    drawings.forEach(d => {
      if (d.kind === "horizontal") drawLines.current.push(candle.current!.createPriceLine({ price: d.price, color: d.color, lineWidth: 1, lineStyle: 2, title: tx("Line") }));
      else if (d.endTime !== undefined && d.endPrice !== undefined) {
        const series = chart.current!.addSeries(LineSeries, { color: d.color, lineWidth: 1, priceLineVisible: false, lastValueVisible: false });
        series.setData([{ time: d.time, value: d.price }, { time: d.endTime, value: d.endPrice }].sort((a, b) => String(a.time).localeCompare(String(b.time)))); drawSeries.current.push(series);
      }
    });
  }, [drawings, chartVersion, tx]);
  const loadEarlier = async () => {
    const cursor = current.meta.next_before; if (!cursor || loading) return;
    setLoading(true); const requestKey = key;
    try {
      const response = await fetch(`/api/stocks/candles?${params}&before=${encodeURIComponent(cursor)}`); const result = await response.json();
      setModel(previous => previous.key !== requestKey ? previous : { ...previous, meta: { ...previous.meta, ...result }, candles: cleanBars([...(result.candles || []), ...previous.candles]) });
      if (keyRef.current === requestKey) setPageError(result.error_code ? errorText(result.error_code) : !result.candles?.length ? tx("No earlier data returned") : "");
    } catch { if (keyRef.current === requestKey) setPageError(tx("Provider unavailable")); } finally { if (keyRef.current === requestKey) setLoading(false); }
  };
  const displayBar = hover || lastBar;
  const iconButton = (title: string, icon: React.ReactNode, action: () => void, disabled = false) => <button type="button" className="icon-button" title={tx(title)} aria-label={tx(title)} onClick={action} disabled={disabled}>{icon}</button>;
  return <section className="market-chart" ref={shell} aria-label={`${symbol} ${tx("Candles")}`}>
    <header className="mc-quote-header"><div><span className="eyebrow">Longbridge · {tx(quoteState)}</span><h2>{symbol}</h2><div className="mc-name">{quote.name || ""}</div><small>{tx("Event time")}: {formatTime(quote.event_time)} · {timezone === "America/New_York" ? "ET" : "UTC+8"}</small></div>
      <div className="mc-price"><strong>{fmt(price)}</strong><span className={change && change.amount >= 0 ? "mc-up" : "mc-down"}>{change ? `${change.amount >= 0 ? "+" : ""}${fmt(change.amount)} (${fmt(change.percent)}%)` : "—"}</span><small>{tx("Regular session")} · {tx("Previous close")} {fmt(quote.previous_close)}</small></div>
      <dl className="mc-stats">{[["Open", quote.open], ["High", quote.high], ["Low", quote.low], ["Volume", quote.volume], ["Turnover", quote.turnover]].map(([label, value]) => <div key={label}><dt>{tx(label)}</dt><dd>{fmt(value)}</dd></div>)}</dl>
    </header>
{(quote.pre_market || quote.post_market) && <div className="mc-extended">{["pre_market", "post_market"].map(name => { const q = quote[name]; if (!q) return null; const delta = changeFrom(q.last, q.previous_close); const conflict = q.event_time && Date.parse(q.event_time) > Date.now() + 5000; return <span key={name}>{tx(name === "pre_market" ? "Premarket" : "After hours")} {conflict && <b className="mc-warning">{tx("Time conflict")} · </b>} <b>{fmt(q.last)}</b> {delta ? `${fmt(delta.amount)} (${fmt(delta.percent)}%)` : "—"} · {tx("Previous close")} {fmt(q.previous_close)} · {formatTime(q.event_time)}</span>; })}</div>}
    <div className="mc-toolbar"><div className="mc-periods" role="group" aria-label={tx("Period")}>{PRESETS.map(([value, label]) => <button key={value} aria-pressed={preset === value} onClick={() => { setPreset(value); localStorage.setItem("kquant-chart:preset", value); setAdjustment(LONG.has(value) ? "forward" : "none"); }}>{tx(label)}</button>)}</div>
      <select aria-label={tx("Session")} value={session} onChange={e => setSession(e.target.value)}><option value="regular">{tx("Regular")}</option><option value="extended">{tx("Extended")}</option></select>
      <select aria-label={tx("Adjustment")} value={adjustment} onChange={e => setAdjustment(e.target.value)}><option value="none">{tx("Unadjusted")}</option><option value="forward">{tx("Forward adjusted")}</option></select>
      <select aria-label={tx("Event time")} value={timezone} onChange={e => setTimezone(e.target.value)}><option value="America/New_York">{tx("New York ET")}</option><option value="Asia/Shanghai">{tx("Beijing")}</option></select>
      <details className="mc-indicators"><summary>{tx("Indicators")}</summary><div>{["EMA20", "EMA50", "EMA200", "MA20", "MA50", "MA200", "VWAP"].map(name => <label key={name}><input type="checkbox" checked={selected.includes(name)} disabled={name === "VWAP" && LONG.has(interval)} onChange={() => setSelected(previous => previous.includes(name) ? previous.filter(n => n !== name) : [...previous, name])} />{name}</label>)}<label><input type="checkbox" checked={showVolume} onChange={e => setShowVolume(e.target.checked)} />{tx("Volume")}</label><select aria-label={tx("Indicators")} value={subpanel} onChange={e => setSubpanel(e.target.value)}><option value="none">{tx("None")}</option><option>MACD</option><option>RSI</option></select></div></details>
      <div className="mc-tools">{iconButton("Horizontal line", <Minus size={16} />, () => { setTool(tool === "horizontal" ? "none" : "horizontal"); anchor.current = null; })}{iconButton("Trend line", <TrendingUp size={16} />, () => { setTool(tool === "trend" ? "none" : "trend"); anchor.current = null; })}<input type="color" aria-label={tx("Color")} value={color} onChange={e => setColor(e.target.value)} />{iconButton("Undo", <Undo2 size={16} />, () => { if (anchor.current) anchor.current = null; else changeDrawings(d => d.slice(0, -1)); })}{iconButton("Clear", <Trash2 size={16} />, () => { changeDrawings(() => []); anchor.current = null; setTool("none"); })}{iconButton("Latest", <Crosshair size={16} />, () => chart.current?.timeScale().scrollToRealTime())}{iconButton("Fullscreen", <Maximize size={16} />, () => { void shell.current?.requestFullscreen(); })}{iconButton("Refresh", <RefreshCw size={16} />, () => setRefresh(v => v + 1), loading)}</div>
    </div>
    {current.meta.future_bars_rejected > 0 && <p className="mc-warning">{tx("Time conflict")}: {current.meta.future_bars_rejected} {tx("Future bars excluded")}</p>}
    <div className="mc-body"><div className="mc-main"><div className="mc-ohlc" aria-live="off">{displayBar ? <><span>{LONG.has(interval) ? displayBar.trading_date : formatTime(displayBar.open_time)}</span>{([['O', displayBar.open], ['H', displayBar.high], ['L', displayBar.low], ['C', displayBar.close], [tx("Volume"), displayBar.volume]] as const).map(([label, value]) => <span key={label}>{label} <b>{fmt(value)}</b></span>)}<span>{tx(displayBar.bar_state === "forming" ? "Forming" : "Closed bar")}</span></> : <span>{tx(loading ? "Loading" : "No chart data")}</span>}</div>
      <div className={`mc-canvas ${tool !== "none" ? "mc-drawing" : ""}`} ref={box} />
      {!current.candles.length && <div className="mc-empty" role="status">{tx(loading ? "Loading" : "No chart data")}{current.meta.error_code && <small>{errorText(current.meta.error_code)}</small>}</div>}
      <div className="mc-legend">{selected.map((name, i) => { const values = indicatorValues(current.candles, name); const index = hover ? current.candles.findIndex(b => b.open_time === hover.open_time) : values.length - 1; return <span key={name} style={{ color: `var(${COLORS[i % COLORS.length]})` }}>{name} {values[index] == null ? tx("Missing inputs") : fmt(values[index])}</span>; })}{subpanel !== "none" && <span>{subpanel === "MACD" ? "MACD(12,26,9)" : "RSI(14)"}</span>}</div>
      <footer className="mc-chart-footer"><span>{current.candles.length} {tx("Candles")} · {tx("Range change")}: {rangeChange ? `${fmt(rangeChange.percent)}%` : "—"}</span><button onClick={() => void loadEarlier()} disabled={!current.meta.next_before || loading}>{tx("Load earlier")}</button></footer>{pageError && <p role="status">{pageError}</p>}
      {current.candles.length > 0 && <div className="mc-coverage">{tx("Trading date")}: {current.candles[0].trading_date} – {lastBar.trading_date} · {tx(adjustment === "forward" ? "Forward adjusted" : "Unadjusted")}</div>}
</div><aside className="mc-depth"><details open={depthOpen} onToggle={e => setDepthOpen(e.currentTarget.open)}><summary>{tx("Depth")}</summary><div className="mc-book"><span>{tx("Bid")}</span><strong className="mc-up">{fmt(depth.bid)}</strong><span>{tx("Size")} {fmt(depth.bid_size, 0)}</span><span>{tx("Ask")}</span><strong className="mc-down">{fmt(depth.ask)}</strong><span>{tx("Size")} {fmt(depth.ask_size, 0)}</span></div><dl><div><dt>{tx("Spread")}</dt><dd>{validNumber(depth.bid) && validNumber(depth.ask) && depth.ask >= depth.bid ? fmt(depth.ask - depth.bid, 4) : "—"}</dd></div><div><dt>{tx("Received")}</dt><dd>{formatTime(depth.received_at)}</dd></div><div><dt>{tx("Bid")} · {tx("Event time")}</dt><dd>{formatTime(depth.bid_event_time)}</dd></div><div><dt>{tx("Ask")} · {tx("Event time")}</dt><dd>{formatTime(depth.ask_event_time)}</dd></div></dl>{!depth.native_time_verified && <p className="mc-warning">{tx("Native depth time unavailable")}</p>}</details><button className="mc-chain" onClick={() => onOpenChain(symbol)}>{tx("Option chain")} <ArrowRight size={16} /></button></aside></div>
    <div className="mc-status"><span>{tx("Quote")}: {tx(quoteState)}</span><span>{tx("Candles")}: {current.meta.error_code ? errorText(current.meta.error_code) : tx(current.candles.length ? "Available" : "Unavailable")}</span><span>{tx("Depth")}: {tx(depth.status === "available" ? "Available" : "Unavailable")}</span><span>{tx("Connection")}: {tx(stream)}</span></div>
    <details className="mc-diagnostics"><summary>{tx("Diagnostics")}</summary><pre>{JSON.stringify({ candle: { ...current.meta, candles: undefined }, quote: current.quote, depth: current.depth }, null, 2)}</pre></details>
    <details className="mc-diagnostics"><summary>{tx("Research evidence")}</summary><a href={`?workspace=${new URLSearchParams(location.search).get("workspace") === "options" ? "options" : "stocks"}&view=review&symbol=${encodeURIComponent(symbol)}`}>{tx("Review")}</a></details>
  </section>;
}
