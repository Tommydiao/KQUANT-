import {
  Activity,
  BarChart3,
  CheckCircle2,
  Database,
  Languages,
  Lock,
  Moon,
  RefreshCw,
  ShieldCheck,
  Sun,
} from "lucide-react";
import {
  CandlestickSeries,
  createChart,
  HistogramSeries,
  LineSeries,
  type CandlestickData,
  type HistogramData,
  type IChartApi,
  type LineData,
  type Time,
} from "lightweight-charts";
import { useEffect, useMemo, useRef, useState } from "react";

type Lang = "en" | "zh";
type Theme = "light" | "dark";
type Source = "fixture" | "live";
type Level = "BUY SETUP" | "WATCH" | "PASS";

type Candle = {
  time: Time;
  open_time?: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
};

type StockSignal = {
  symbol: string;
  score: number;
  level: Level;
  direction: "LONG";
  trend_summary: string;
  trigger_summary: string;
  risk_warnings: string[];
  manual_checklist: string[];
  data_status: {
    daily_provider_status: string;
    hourly_provider_status: string;
    daily_candles: number;
    hourly_candles: number;
    source: string;
    freshness: string;
    data_quality?: string;
    live_does_not_fallback_to_fixture?: boolean;
  };
  features: Record<string, number>;
  historical_edge: {
    sample_count: number;
    win_rate_5d: number;
    target_hit_rate_5d: number;
    avg_forward_return_3d: number;
    avg_forward_return_5d: number;
    avg_forward_return_10d: number;
    avg_max_drawdown_5d: number;
    verdict: string;
  };
};

type SignalRun = {
  run_id: string;
  source: Source | string;
  universe: string;
  profile: { name: string; buy_setup_threshold: number; watch_threshold: number; direction: string };
  provider_status: string;
  provider_error_count: number;
  historical_validation?: {
    sample_count: number;
    win_rate_5d: number;
    target_hit_rate_5d: number;
    avg_forward_return_5d: number;
    avg_max_drawdown_5d: number;
  };
  counts: { buy_setup: number; watch: number; pass: number; total: number };
  signals: StockSignal[];
  llm_signal_core_enabled: boolean;
  broker_order_wiring_enabled: boolean;
};

type UniverseStock = {
  symbol: string;
  name: string;
  sector: string;
  layer: string;
  tags: string[];
  rank: number;
};

type OhlcState = {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
};

const copy = {
  en: {
    title: "KQUANT US Stock Signal Terminal",
    subtitle: "Long-only stock setups first. Options return later as expression tools.",
    source: "Source",
    fixture: "Fixture",
    live: "Live",
    refresh: "Run Stock Scan",
    readOnly: "Read-only research",
    llmLocked: "LLM core locked",
    db: "New DB",
    buySetups: "BUY SETUP",
    watch: "WATCH",
    pass: "PASS",
    provider: "Provider",
    universe: "Universe",
    historicalValidation: "Historical Validation",
    historicalEdge: "Historical Edge",
    winRate: "5D Win Rate",
    samples: "Samples",
    avgReturn: "Avg 5D Return",
    dataQuality: "Data Quality",
    today: "Today’s Stock Setups",
    selected: "Selected Stock Review",
    daily: "Daily K-Line",
    hourly: "1H K-Line",
    reasons: "Signal Reasons",
    risks: "Risk Warnings",
    checklist: "Manual Checklist",
    layers: "Market Layers",
    data: "Data Status",
    optionsLater: "Options module is parked until the stock signal is stable.",
    noBroker: "No broker, no account read, no paper/live/testnet order path.",
    dailyHint: "Daily trend: EMA20 / EMA50 / EMA200",
    hourlyHint: "1h confirmation: momentum and entry timing",
    ohlc: "Move crosshair over chart for OHLC",
    noCandles: "No candles from the selected source.",
    report: "Report",
    fallback: "Using local fixture fallback because API is unavailable.",
    apiReady: "Connected to local KQUANT API.",
    clean: "Clean",
    caution: "Caution",
    chinese: "中文",
    english: "EN",
    light: "Light",
    dark: "Dark",
  },
  zh: {
    title: "KQUANT 美股正股信号终端",
    subtitle: "先做好 Long-only 正股信号，期权后续只作为表达工具。",
    source: "数据源",
    fixture: "演示",
    live: "真实",
    refresh: "运行正股扫描",
    readOnly: "只读研究",
    llmLocked: "大模型核心锁定",
    db: "新数据库",
    buySetups: "买入形态",
    watch: "观察",
    pass: "跳过",
    provider: "数据源",
    universe: "股票池",
    historicalValidation: "历史验证",
    historicalEdge: "历史优势",
    winRate: "5日胜率",
    samples: "样本数",
    avgReturn: "平均5日收益",
    dataQuality: "数据质量",
    today: "今日正股信号",
    selected: "当前股票复核",
    daily: "日线 K 线",
    hourly: "1H K 线",
    reasons: "信号理由",
    risks: "风险提醒",
    checklist: "手工复核清单",
    layers: "市场分类",
    data: "数据状态",
    optionsLater: "期权模块先暂停，等正股信号稳定后再回归。",
    noBroker: "无券商、无账户读取、无 paper/live/testnet 下单路径。",
    dailyHint: "日线趋势：EMA20 / EMA50 / EMA200",
    hourlyHint: "1h 确认：动量和入场节奏",
    ohlc: "移动十字光标查看 OHLC",
    noCandles: "当前数据源没有返回 K 线。",
    report: "报告",
    fallback: "本地 API 不可用，正在使用内置演示数据。",
    apiReady: "已连接本地 KQUANT API。",
    clean: "干净",
    caution: "谨慎",
    chinese: "中文",
    english: "EN",
    light: "浅色",
    dark: "深色",
  },
} as const;

const STOCKS: UniverseStock[] = [
  "SPY:SPDR S&P 500 ETF:ETF:Index ETFs",
  "QQQ:Invesco QQQ Trust:ETF:Index ETFs",
  "IWM:iShares Russell 2000 ETF:ETF:Index ETFs",
  "DIA:SPDR Dow Jones ETF:ETF:Index ETFs",
  "AAPL:Apple:Technology:Mega Cap Tech",
  "MSFT:Microsoft:Technology:AI Cloud",
  "NVDA:NVIDIA:Technology:AI Compute",
  "TSLA:Tesla:Consumer Discretionary:High Beta Growth",
  "AMZN:Amazon:Consumer Discretionary:AI Cloud",
  "META:Meta Platforms:Communication Services:AI Cloud",
  "GOOGL:Alphabet:Communication Services:AI Cloud",
  "AMD:Advanced Micro Devices:Technology:AI Compute",
  "AVGO:Broadcom:Technology:Semis / Foundry / Tools",
  "NFLX:Netflix:Communication Services:Consumer Internet",
  "COST:Costco:Consumer Staples:Defensive Growth",
  "JPM:JPMorgan Chase:Financials:Financials",
  "BAC:Bank of America:Financials:Financials",
  "WFC:Wells Fargo:Financials:Financials",
  "GS:Goldman Sachs:Financials:Financials",
  "MS:Morgan Stanley:Financials:Financials",
  "XOM:Exxon Mobil:Energy:Energy",
  "CVX:Chevron:Energy:Energy",
  "COP:ConocoPhillips:Energy:Energy",
  "UNH:UnitedHealth:Healthcare:Healthcare",
  "LLY:Eli Lilly:Healthcare:Healthcare",
  "MRK:Merck:Healthcare:Healthcare",
  "JNJ:Johnson & Johnson:Healthcare:Healthcare",
  "ABBV:AbbVie:Healthcare:Healthcare",
  "HD:Home Depot:Consumer Discretionary:Industrials / Consumer",
  "WMT:Walmart:Consumer Staples:Defensive Growth",
  "MCD:McDonald's:Consumer Discretionary:Industrials / Consumer",
  "NKE:Nike:Consumer Discretionary:Industrials / Consumer",
  "BA:Boeing:Industrials:Industrials / Consumer",
  "CAT:Caterpillar:Industrials:Industrials / Consumer",
  "GE:GE Aerospace:Industrials:Industrials / Consumer",
  "DIS:Disney:Communication Services:Consumer Internet",
  "T:AT&T:Communication Services:Defensive Value",
  "V:Visa:Financials:Payments",
  "MA:Mastercard:Financials:Payments",
  "CRM:Salesforce:Technology:AI Software / Data",
  "ORCL:Oracle:Technology:AI Cloud",
  "ADBE:Adobe:Technology:AI Software / Data",
  "INTC:Intel:Technology:Semis / Foundry / Tools",
  "MU:Micron:Technology:Semis / Foundry / Tools",
  "QCOM:Qualcomm:Technology:Semis / Foundry / Tools",
  "SMCI:Super Micro Computer:Technology:AI Compute",
  "PLTR:Palantir:Technology:AI Software / Data",
  "COIN:Coinbase:Financials:Crypto / Fintech Beta",
  "SHOP:Shopify:Technology:AI Software / Data",
  "UBER:Uber:Industrials:AI Software / Data",
  "ARM:Arm Holdings:Technology:AI Compute",
  "MRVL:Marvell:Technology:AI Semis",
  "TSM:Taiwan Semiconductor:Technology:Semis / Foundry / Tools",
  "ASML:ASML:Technology:Semis / Foundry / Tools",
  "ANET:Arista Networks:Technology:AI Infra",
  "DELL:Dell Technologies:Technology:AI Infra",
  "NOW:ServiceNow:Technology:AI Software / Data",
  "SNOW:Snowflake:Technology:AI Software / Data",
  "DDOG:Datadog:Technology:AI Infra",
  "MDB:MongoDB:Technology:AI Software / Data",
  "CRWD:CrowdStrike:Technology:AI Security",
  "PANW:Palo Alto Networks:Technology:AI Security",
  "NET:Cloudflare:Technology:AI Infra",
  "AI:C3.ai:Technology:AI Software / Data",
  "PATH:UiPath:Technology:AI Software / Data",
].map((row, index) => {
  const [symbol, name, sector, layer] = row.split(":");
  return { symbol, name, sector, layer, tags: [], rank: index + 1 };
});

function App() {
  const [lang, setLang] = useStoredState<Lang>("kquant-stock:lang", "en");
  const [theme, setTheme] = useStoredState<Theme>("kquant-stock:theme", "light");
  const [source, setSource] = useStoredState<Source>("kquant-stock:source", "fixture");
  const [run, setRun] = useState<SignalRun>(() => makeLocalSignalRun(source));
  const [universe, setUniverse] = useState<UniverseStock[]>(STOCKS);
  const [selectedSymbol, setSelectedSymbol] = useStoredState<string>("kquant-stock:selected", "NVDA");
  const [dailyCandles, setDailyCandles] = useState<Candle[]>(() => makeCandles("NVDA", "1y", "1d"));
  const [hourlyCandles, setHourlyCandles] = useState<Candle[]>(() => makeCandles("NVDA", "5d", "1h"));
  const [apiState, setApiState] = useState<"api" | "fallback">("fallback");
  const text = copy[lang];

  const selected =
    run.signals.find((signal) => signal.symbol === selectedSymbol) ??
    run.signals[0] ??
    makeLocalSignalRun(source).signals[0];
  const selectedMeta = universe.find((stock) => stock.symbol === selected.symbol) ?? STOCKS[0];
  const layerGroups = useMemo(() => groupByLayer(universe, run.signals), [run.signals, universe]);

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    document.documentElement.lang = lang === "zh" ? "zh-CN" : "en";
  }, [lang, theme]);

  useEffect(() => {
    void loadSignals(source, false);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [source]);

  useEffect(() => {
    void loadCandles(selected.symbol, source);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected.symbol, source]);

  async function loadSignals(nextSource: Source, forceScan: boolean) {
    try {
      const endpoint = forceScan ? "/api/stocks/signals" : "/api/stocks/signals/latest";
      const response = await fetch(`${endpoint}?source=${nextSource}&universe=default&profile=swing_long_v1&limit=100`);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const payload = (await response.json()) as SignalRun;
      const universeResponse = await fetch("/api/stocks/universe?universe=default");
      if (universeResponse.ok) {
        const universePayload = await universeResponse.json();
        setUniverse(universePayload.stocks ?? STOCKS);
      }
      setRun(payload);
      setApiState("api");
      if (!payload.signals.some((signal) => signal.symbol === selectedSymbol)) {
        setSelectedSymbol(payload.signals[0]?.symbol ?? "NVDA");
      }
    } catch {
      const fallback = makeLocalSignalRun(nextSource);
      setRun(fallback);
      setUniverse(STOCKS);
      setApiState("fallback");
    }
  }

  async function loadCandles(symbol: string, nextSource: Source) {
    const fallbackDaily = makeCandles(symbol, "1y", "1d");
    const fallbackHourly = makeCandles(symbol, "5d", "1h");
    try {
      const [dailyResponse, hourlyResponse] = await Promise.all([
        fetch(`/api/stocks/candles?symbol=${symbol}&range=1y&interval=1d&source=${nextSource}`),
        fetch(`/api/stocks/candles?symbol=${symbol}&range=5d&interval=1h&source=${nextSource}`),
      ]);
      if (!dailyResponse.ok || !hourlyResponse.ok) throw new Error("candles unavailable");
      const [dailyPayload, hourlyPayload] = await Promise.all([dailyResponse.json(), hourlyResponse.json()]);
      setDailyCandles(normalizeCandles(dailyPayload.candles, nextSource === "fixture" ? fallbackDaily : []));
      setHourlyCandles(normalizeCandles(hourlyPayload.candles, nextSource === "fixture" ? fallbackHourly : []));
    } catch {
      setDailyCandles(fallbackDaily);
      setHourlyCandles(fallbackHourly);
    }
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <div className="brand">
          <div className="brand-mark">KQ</div>
          <div>
            <h1>{text.title}</h1>
            <p>{text.subtitle}</p>
          </div>
        </div>
        <div className="top-actions">
          <Segmented
            value={lang}
            options={[
              ["en", text.english],
              ["zh", text.chinese],
            ]}
            onChange={(value) => setLang(value as Lang)}
            icon={<Languages size={14} />}
          />
          <Segmented
            value={theme}
            options={[
              ["light", text.light],
              ["dark", text.dark],
            ]}
            onChange={(value) => setTheme(value as Theme)}
            icon={theme === "light" ? <Sun size={14} /> : <Moon size={14} />}
          />
          <Segmented
            value={source}
            options={[
              ["fixture", text.fixture],
              ["live", text.live],
            ]}
            onChange={(value) => setSource(value as Source)}
          />
          <button className="primary-action" type="button" onClick={() => void loadSignals(source, true)}>
            <RefreshCw size={15} />
            {text.refresh}
          </button>
        </div>
      </header>

      <section className="status-rail" aria-label="System status">
        <Pill tone="good" icon={<ShieldCheck size={14} />} label={text.readOnly} />
        <Pill tone="neutral" icon={<Lock size={14} />} label={text.llmLocked} />
        <Pill tone="neutral" icon={<Database size={14} />} label={`${text.db}: work/kquant_us.sqlite3`} />
        <Pill tone={apiState === "api" ? "good" : "warn"} icon={<Activity size={14} />} label={apiState === "api" ? text.apiReady : text.fallback} />
        <Pill tone="neutral" icon={<BarChart3 size={14} />} label={text.noBroker} />
      </section>

      <section className="metrics-grid">
        <Metric label={text.buySetups} value={String(run.counts.buy_setup)} tone="good" />
        <Metric label={text.watch} value={String(run.counts.watch)} tone="watch" />
        <Metric label={text.pass} value={String(run.counts.pass)} />
        <Metric label={text.provider} value={`${run.provider_status} / ${run.provider_error_count}`} tone={run.provider_error_count ? "warn" : "good"} />
        <Metric label={text.universe} value={`${run.counts.total || universe.length} stocks`} />
        <Metric
          label={text.historicalValidation}
          value={`${run.historical_validation?.sample_count ?? 0} / ${formatNumber(run.historical_validation?.win_rate_5d)}%`}
          tone={(run.historical_validation?.win_rate_5d ?? 0) >= 52 ? "good" : "watch"}
        />
      </section>

      <section className="main-grid">
        <aside className="panel queue-panel">
          <PanelTitle title={text.today} detail={run.profile.name} />
          <div className="signal-list">
            {run.signals.slice(0, 24).map((signal) => (
              <button
                type="button"
                className={`signal-card ${signal.symbol === selected.symbol ? "active" : ""}`}
                key={signal.symbol}
                onClick={() => setSelectedSymbol(signal.symbol)}
              >
                <div className="signal-card-top">
                  <strong>{signal.symbol}</strong>
                  <span className={`level ${levelClass(signal.level)}`}>{levelLabel(signal.level, lang)}</span>
                </div>
                <div className="score-line">
                  <span>{selectedMetaBySymbol(universe, signal.symbol)?.layer ?? "US Stock"}</span>
                  <b>{signal.score}/100</b>
                </div>
                <div className="edge-line">
                  <span>
                    {text.winRate} {formatNumber(signal.historical_edge?.win_rate_5d)}%
                  </span>
                  <span>
                    {text.samples} {signal.historical_edge?.sample_count ?? 0}
                  </span>
                </div>
                <p>{signal.trigger_summary}</p>
              </button>
            ))}
          </div>
        </aside>

        <section className="review-stack">
          <section className="panel selected-panel">
            <PanelTitle title={text.selected} detail={selectedMeta.layer} />
            <div className="selected-row">
              <div>
                <span>{selectedMeta.name}</span>
                <h2>{selected.symbol} · {levelLabel(selected.level, lang)}</h2>
              </div>
              <div className="selected-score">{selected.score}/100</div>
            </div>
            <div className="fact-grid">
              <Fact label="Close" value={formatNumber(selected.features.close)} />
              <Fact label="EMA20" value={formatNumber(selected.features.ema20)} />
              <Fact label="EMA50" value={formatNumber(selected.features.ema50)} />
              <Fact label="EMA200" value={formatNumber(selected.features.ema200)} />
              <Fact label="ATR" value={`${formatNumber(selected.features.atr_pct)}%`} />
              <Fact label="Volume" value={`${formatNumber(selected.features.volume_ratio)}x`} />
              <Fact label={text.winRate} value={`${formatNumber(selected.historical_edge?.win_rate_5d)}%`} />
              <Fact label={text.avgReturn} value={`${formatNumber(selected.historical_edge?.avg_forward_return_5d)}%`} />
              <Fact label={text.samples} value={String(selected.historical_edge?.sample_count ?? 0)} />
            </div>
            <p className="secondary-note">{text.optionsLater}</p>
          </section>

          <div className="chart-grid">
            <ChartPanel
              title={text.daily}
              subtitle={`${selected.symbol} · 1Y / 1D · ${text.dailyHint}`}
              candles={dailyCandles}
              theme={theme}
              ohlcHint={text.ohlc}
              emptyText={text.noCandles}
            />
            <ChartPanel
              title={text.hourly}
              subtitle={`${selected.symbol} · 5D / 1H · ${text.hourlyHint}`}
              candles={hourlyCandles}
              theme={theme}
              ohlcHint={text.ohlc}
              emptyText={text.noCandles}
            />
          </div>

          <section className="panel detail-grid">
            <Narrative title={text.reasons} items={[selected.trend_summary, selected.trigger_summary]} />
            <Narrative
              title={text.historicalEdge}
              items={[
                `${text.samples}: ${selected.historical_edge?.sample_count ?? 0}`,
                `${text.winRate}: ${formatNumber(selected.historical_edge?.win_rate_5d)}% / ${text.avgReturn}: ${formatNumber(selected.historical_edge?.avg_forward_return_5d)}%`,
                `Verdict: ${selected.historical_edge?.verdict ?? "missing"}`,
              ]}
            />
            <Narrative title={text.risks} items={selected.risk_warnings} />
            <Narrative title={text.checklist} items={selected.manual_checklist} />
            <div className="data-box">
              <h3>{text.data}</h3>
              <Fact label="Daily" value={`${selected.data_status.daily_provider_status} / ${selected.data_status.daily_candles}`} />
              <Fact label="1H" value={`${selected.data_status.hourly_provider_status} / ${selected.data_status.hourly_candles}`} />
              <Fact label={text.dataQuality} value={selected.data_status.data_quality === "clean" ? text.clean : text.caution} />
              <Fact label={text.source} value={`${selected.data_status.source} / ${selected.data_status.freshness}`} />
              <Fact label={text.report} value={run.run_id} />
            </div>
          </section>
        </section>
      </section>

      <section className="panel layers-panel">
        <PanelTitle title={text.layers} detail={`${universe.length} selected stocks / options secondary`} />
        <div className="layer-grid">
          {layerGroups.map((layer) => (
            <div className="layer-card" key={layer.name}>
              <div className="layer-head">
                <strong>{layer.name}</strong>
                <span>{layer.stocks.length}</span>
              </div>
              <div className="symbol-wrap">
                {layer.stocks.slice(0, 16).map((stock) => {
                  const signal = run.signals.find((item) => item.symbol === stock.symbol);
                  return (
                    <button
                      className={stock.symbol === selected.symbol ? "symbol-chip active" : "symbol-chip"}
                      type="button"
                      key={stock.symbol}
                      onClick={() => setSelectedSymbol(stock.symbol)}
                    >
                      {stock.symbol}
                      {signal ? <span>{Math.round(signal.score)}</span> : null}
                    </button>
                  );
                })}
              </div>
            </div>
          ))}
        </div>
      </section>
    </main>
  );
}

function ChartPanel({
  title,
  subtitle,
  candles,
  theme,
  ohlcHint,
  emptyText,
}: {
  title: string;
  subtitle: string;
  candles: Candle[];
  theme: Theme;
  ohlcHint: string;
  emptyText: string;
}) {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [hover, setHover] = useState<OhlcState | null>(null);
  const indicators = useMemo(() => ({ ema20: ema(candles, 20), ema50: ema(candles, 50), vwap: vwap(candles) }), [candles]);

  useEffect(() => {
    if (!containerRef.current) return;
    const container = containerRef.current;
    container.innerHTML = "";
    const dark = theme === "dark";
    const chart = createChart(container, {
      width: container.clientWidth,
      height: container.clientHeight,
      autoSize: true,
      layout: {
        background: { color: dark ? "#0f172a" : "#ffffff" },
        textColor: dark ? "#94a3b8" : "#64748b",
        fontFamily: "Inter, ui-sans-serif, system-ui, sans-serif",
      },
      grid: {
        vertLines: { color: dark ? "#1e293b" : "#eef2f7" },
        horzLines: { color: dark ? "#1e293b" : "#eef2f7" },
      },
      rightPriceScale: { borderColor: dark ? "#263241" : "#e5e7eb" },
      timeScale: { borderColor: dark ? "#263241" : "#e5e7eb", timeVisible: true },
      handleScroll: { mouseWheel: false, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: false },
      handleScale: { mouseWheel: false, pinch: true, axisPressedMouseMove: true },
    });

    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: "#16a34a",
      downColor: "#ef4444",
      wickUpColor: "#16a34a",
      wickDownColor: "#ef4444",
      borderVisible: false,
      priceLineColor: "#2563eb",
    });
    candleSeries.setData(candles as CandlestickData<Time>[]);

    const volumeSeries = chart.addSeries(HistogramSeries, {
      color: "rgba(99, 102, 241, 0.22)",
      priceFormat: { type: "volume" },
      priceScaleId: "",
    });
    volumeSeries.priceScale().applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
    volumeSeries.setData(
      candles.map((bar) => ({
        time: bar.time,
        value: bar.volume,
        color: bar.close >= bar.open ? "rgba(22, 163, 74, 0.24)" : "rgba(239, 68, 68, 0.22)",
      })) as HistogramData<Time>[],
    );

    addLine(chart, indicators.ema20, "#2563eb");
    addLine(chart, indicators.ema50, "#f59e0b");
    addLine(chart, indicators.vwap, "#7c3aed");
    chart.timeScale().fitContent();
    chart.subscribeCrosshairMove((param) => {
      const point = param.seriesData.get(candleSeries);
      if (!point || !("open" in point)) {
        setHover(null);
        return;
      }
      setHover({
        time: String(point.time),
        open: point.open,
        high: point.high,
        low: point.low,
        close: point.close,
      });
    });
    return () => chart.remove();
  }, [candles, indicators.ema20, indicators.ema50, indicators.vwap, theme]);

  return (
    <section className="panel chart-panel">
      <div className="chart-header">
        <div>
          <h3>{title}</h3>
          <p>{subtitle}</p>
        </div>
        <div className="indicator-tags">
          <span>EMA20</span>
          <span>EMA50</span>
          <span>VWAP</span>
        </div>
      </div>
      <div className="ohlc-row">
        {hover ? (
          <>
            <span>{hover.time}</span>
            <span>O {hover.open.toFixed(2)}</span>
            <span>H {hover.high.toFixed(2)}</span>
            <span>L {hover.low.toFixed(2)}</span>
            <span>C {hover.close.toFixed(2)}</span>
          </>
        ) : (
          <span>{ohlcHint}</span>
        )}
      </div>
      {candles.length ? <div className="chart-canvas" ref={containerRef} /> : <div className="chart-empty">{emptyText}</div>}
    </section>
  );
}

function PanelTitle({ title, detail }: { title: string; detail: string }) {
  return (
    <div className="panel-title">
      <h2>{title}</h2>
      <span>{detail}</span>
    </div>
  );
}

function Segmented({
  value,
  options,
  onChange,
  icon,
}: {
  value: string;
  options: [string, string][];
  onChange: (value: string) => void;
  icon?: React.ReactNode;
}) {
  return (
    <div className="segmented">
      {icon}
      {options.map(([key, label]) => (
        <button className={value === key ? "active" : ""} key={key} type="button" onClick={() => onChange(key)}>
          {label}
        </button>
      ))}
    </div>
  );
}

function Pill({ label, icon, tone }: { label: string; icon: React.ReactNode; tone: "good" | "warn" | "neutral" }) {
  return (
    <span className={`pill ${tone}`}>
      {icon}
      {label}
    </span>
  );
}

function Metric({ label, value, tone }: { label: string; value: string; tone?: "good" | "watch" | "warn" }) {
  return (
    <div className={`metric ${tone ?? ""}`}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div className="fact">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function Narrative({ title, items }: { title: string; items: string[] }) {
  return (
    <div className="narrative">
      <h3>{title}</h3>
      {items.map((item) => (
        <p key={item}>{item}</p>
      ))}
    </div>
  );
}

function makeLocalSignalRun(source: Source): SignalRun {
  const signals = STOCKS.slice(0, 100).map((stock) => buildLocalSignal(stock.symbol));
  signals.sort((a, b) => b.score - a.score);
  return {
    run_id: "local-fixture-stock-run",
    source,
    universe: "default",
    profile: { name: "swing_long_v1", buy_setup_threshold: 82, watch_threshold: 65, direction: "long_only" },
    provider_status: source === "fixture" ? "fixture_read_only" : "api_unavailable",
    provider_error_count: source === "fixture" ? 0 : 1,
    historical_validation: {
      sample_count: signals.reduce((total, signal) => total + signal.historical_edge.sample_count, 0),
      win_rate_5d: round(avg(signals.map((signal) => signal.historical_edge.win_rate_5d))),
      target_hit_rate_5d: round(avg(signals.map((signal) => signal.historical_edge.target_hit_rate_5d))),
      avg_forward_return_5d: round(avg(signals.map((signal) => signal.historical_edge.avg_forward_return_5d))),
      avg_max_drawdown_5d: round(avg(signals.map((signal) => signal.historical_edge.avg_max_drawdown_5d))),
    },
    counts: {
      buy_setup: signals.filter((signal) => signal.level === "BUY SETUP").length,
      watch: signals.filter((signal) => signal.level === "WATCH").length,
      pass: signals.filter((signal) => signal.level === "PASS").length,
      total: signals.length,
    },
    signals,
    llm_signal_core_enabled: false,
    broker_order_wiring_enabled: false,
  };
}

function buildLocalSignal(symbol: string): StockSignal {
  const daily = makeCandles(symbol, "1y", "1d");
  const hourly = makeCandles(symbol, "5d", "1h");
  const closes = daily.map((bar) => bar.close);
  const hCloses = hourly.map((bar) => bar.close);
  const ema20 = lastEma(closes, 20);
  const ema50 = lastEma(closes, 50);
  const ema200 = lastEma(closes, 200);
  const close = closes[closes.length - 1] ?? 0;
  const previousClose = closes[Math.max(0, closes.length - 8)] ?? close;
  const hLast = hCloses[hCloses.length - 1] ?? 0;
  const hPrevious = hCloses[Math.max(0, hCloses.length - 8)] ?? hLast;
  const hMomentum = ((hLast / Math.max(hPrevious, 0.01)) - 1) * 100;
  const volumeRatio = (daily[daily.length - 1]?.volume ?? 0) / Math.max(avg(daily.slice(-21, -1).map((bar) => bar.volume)), 1);
  const atr = avg(daily.slice(-15).map((bar) => ((bar.high - bar.low) / Math.max(bar.close, 0.01)) * 100));
  const hEma20 = lastEma(hCloses, 20);
  const edge = localHistoricalEdge(symbol);
  const score = clamp(
    (close > ema20 ? 14 : 0) +
      (ema20 > ema50 ? 14 : 0) +
      (ema50 > ema200 ? 14 : 0) +
      clamp(((close / Math.max(previousClose, 0.01)) - 1) * 100 * 2.2, -8, 18) +
      (hLast > hEma20 ? 13 : 0) +
      clamp(hMomentum * 3, -8, 11) +
      clamp((volumeRatio - 0.75) * 18, 0, 18) +
      clamp(18 - Math.max(0, atr - 5) * 1.4, 0, 18),
    0,
    100,
  );
  const level: Level = score >= 82 ? "BUY SETUP" : score >= 65 ? "WATCH" : "PASS";
  return {
    symbol,
    score: Math.round(score * 10) / 10,
    level,
    direction: "LONG",
    trend_summary: `Daily close ${close.toFixed(2)} vs EMA20 ${ema20.toFixed(2)}, EMA50 ${ema50.toFixed(2)}, EMA200 ${ema200.toFixed(2)}.`,
    trigger_summary: `1h momentum ${hMomentum.toFixed(2)}%; volume ${volumeRatio.toFixed(2)}x recent average.`,
    risk_warnings:
      atr > 5
        ? ["ATR risk is elevated; wait for a cleaner pullback before acting."]
        : ["No hard data blocker. Still confirm candles manually before action."],
    manual_checklist: [
      "Review daily trend and EMA20/50/200 alignment.",
      "Confirm 1h entry structure and avoid chasing extended candles.",
      "Check volume expansion and ATR risk before any manual trade.",
      "Only after a stock BUY SETUP should ATM options be considered.",
    ],
    data_status: {
      daily_provider_status: "fixture_read_only",
      hourly_provider_status: "fixture_read_only",
      daily_candles: daily.length,
      hourly_candles: hourly.length,
      source: "fixture_read_only",
      freshness: "fixture",
      data_quality: "clean",
      live_does_not_fallback_to_fixture: false,
    },
    features: {
      close,
      ema20,
      ema50,
      ema200,
      atr_pct: atr,
      volume_ratio: volumeRatio,
    },
    historical_edge: edge,
  };
}

function localHistoricalEdge(symbol: string): StockSignal["historical_edge"] {
  const seed = [...symbol].reduce((total, char, index) => total + char.charCodeAt(0) * (index + 1), 0);
  const sampleCount = 18 + (seed % 38);
  const winRate = 42 + (seed % 28);
  const avgReturn = -0.4 + (seed % 24) / 10;
  return {
    sample_count: sampleCount,
    win_rate_5d: round(winRate),
    target_hit_rate_5d: round(Math.max(20, winRate - 12)),
    avg_forward_return_3d: round(avgReturn * 0.62),
    avg_forward_return_5d: round(avgReturn),
    avg_forward_return_10d: round(avgReturn * 1.35),
    avg_max_drawdown_5d: round(-1.2 - (seed % 20) / 10),
    verdict: winRate >= 52 && avgReturn > 0.2 ? "positive" : "unproven",
  };
}

function makeCandles(symbol: string, range: "1y" | "5d", interval: "1d" | "1h"): Candle[] {
  const count = range === "1y" ? 252 : 130;
  const step = range === "1y" ? 86400 : 3600;
  const seed = [...symbol].reduce((total, char, index) => total + char.charCodeAt(0) * (index + 1), 0);
  let price = 45 + (seed % 420) + (["SPY", "QQQ", "DIA"].includes(symbol) ? 160 : 0);
  const start = Date.UTC(2025, 5, 18, 13, 30) / 1000;
  return Array.from({ length: count }, (_, index) => {
    const wave = Math.sin((index + seed) * 0.17) * 0.015 + Math.cos((index + seed) * 0.043) * 0.01;
    const bias = (["NVDA", "MSFT", "AVGO", "AMZN", "AMD", "PLTR"].includes(symbol) ? 0.0014 : 0.0004) + ((seed % 17) - 7) / 12000;
    const open = price;
    const close = Math.max(2, price * (1 + bias + wave * 0.16));
    const spread = Math.max(close * (0.006 + Math.abs(wave) * 0.7), 0.05);
    price = close;
    return {
      time: (start + index * step) as Time,
      open: round(open),
      high: round(Math.max(open, close) + spread),
      low: round(Math.max(0.5, Math.min(open, close) - spread)),
      close: round(close),
      volume: Math.round(950_000 + (seed % 900_000) + Math.abs(wave) * 30_000_000 + (index % 13) * 32_000),
    };
  });
}

function normalizeCandles(input: unknown, fallback: Candle[]): Candle[] {
  if (!Array.isArray(input) || input.length === 0) return fallback;
  return input
    .map((bar) => {
      const item = bar as Record<string, unknown>;
      return {
        time: Number(item.time ?? 0) as Time,
        open_time: String(item.open_time ?? ""),
        open: Number(item.open ?? 0),
        high: Number(item.high ?? 0),
        low: Number(item.low ?? 0),
        close: Number(item.close ?? 0),
        volume: Number(item.volume ?? 0),
      };
    })
    .filter((bar) => Number.isFinite(bar.open) && Number.isFinite(bar.time) && bar.time);
}

function groupByLayer(stocks: UniverseStock[], signals: StockSignal[]) {
  const scoreBySymbol = new Map(signals.map((signal) => [signal.symbol, signal.score]));
  const groups = new Map<string, UniverseStock[]>();
  for (const stock of stocks) {
    groups.set(stock.layer, [...(groups.get(stock.layer) ?? []), stock]);
  }
  return [...groups.entries()]
    .map(([name, layerStocks]) => ({
      name,
      stocks: layerStocks.sort((a, b) => (scoreBySymbol.get(b.symbol) ?? 0) - (scoreBySymbol.get(a.symbol) ?? 0)),
    }))
    .sort((a, b) => b.stocks.length - a.stocks.length);
}

function selectedMetaBySymbol(stocks: UniverseStock[], symbol: string) {
  return stocks.find((stock) => stock.symbol === symbol);
}

function addLine(chart: IChartApi, data: LineData<Time>[], color: string) {
  const series = chart.addSeries(LineSeries, { color, lineWidth: 2, lastValueVisible: false, priceLineVisible: false });
  series.setData(data);
}

function ema(candles: Candle[], period: number): LineData<Time>[] {
  let current = candles[0]?.close ?? 0;
  const multiplier = 2 / (period + 1);
  return candles.map((bar, index) => {
    current = index === 0 ? bar.close : (bar.close - current) * multiplier + current;
    return { time: bar.time, value: round(current) };
  });
}

function vwap(candles: Candle[]): LineData<Time>[] {
  let priceVolume = 0;
  let volume = 0;
  return candles.map((bar) => {
    const typical = (bar.high + bar.low + bar.close) / 3;
    priceVolume += typical * bar.volume;
    volume += bar.volume;
    return { time: bar.time, value: round(priceVolume / Math.max(volume, 1)) };
  });
}

function lastEma(values: number[], period: number) {
  const series = ema(values.map((value, index) => ({ time: index as Time, open: value, high: value, low: value, close: value, volume: 0 })), period);
  return series[series.length - 1]?.value ?? 0;
}

function useStoredState<T extends string>(key: string, initial: T): [T, (value: T) => void] {
  const [value, setValue] = useState<T>(() => {
    try {
      return (window.localStorage.getItem(key) as T | null) ?? initial;
    } catch {
      return initial;
    }
  });
  const setStored = (next: T) => {
    setValue(next);
    try {
      window.localStorage.setItem(key, next);
    } catch {
      // localStorage may be unavailable in strict privacy modes.
    }
  };
  return [value, setStored];
}

function levelClass(level: Level) {
  if (level === "BUY SETUP") return "buy";
  if (level === "WATCH") return "watch";
  return "pass";
}

function levelLabel(level: Level, lang: Lang) {
  if (lang === "en") return level;
  if (level === "BUY SETUP") return "买入形态";
  if (level === "WATCH") return "观察";
  return "跳过";
}

function avg(values: number[]) {
  return values.reduce((total, value) => total + value, 0) / Math.max(values.length, 1);
}

function round(value: number) {
  return Math.round(value * 100) / 100;
}

function clamp(value: number, min: number, max: number) {
  return Math.min(Math.max(value, min), max);
}

function formatNumber(value: number | undefined) {
  if (value === undefined || Number.isNaN(value)) return "-";
  return value.toFixed(value > 50 ? 2 : 1);
}

export default App;
