import { FormEvent, KeyboardEvent, MouseEvent, useEffect, useMemo, useState } from "react";
import CandidatePanel from "./CandidatePanel";
import OptionsWorkspace from "./OptionsWorkspace";
import {
  I18nProvider,
  actionText,
  backendText,
  formatUiNumber,
  statusText,
  translate,
  useI18n,
  type MessageKey,
  type UiLanguage,
  type UiTheme,
} from "./i18n";
import {
  DEFAULT_SYMBOL,
  canonicalWorkspaceUrl,
  symbolFromSearch,
  viewFromSearch,
  workspaceFromSearch,
  workspaceLabel,
  workspaceSearchPlaceholder,
  type ViewName,
  type WorkspaceId,
} from "./workspace";
import {
  Activity,
  AlertTriangle,
  ArrowDownRight,
  ArrowUpRight,
  BarChart3,
  Bell,
  BookOpen,
  ChartCandlestick,
  ChevronRight,
  CircleHelp,
  Database,
  FileText,
  LayoutDashboard,
  LineChart,
  Languages,
  LogOut,
  Menu,
  Minus,
  Moon,
  PanelRight,
  Radar,
  RefreshCw,
  Search,
  Settings,
  ShieldCheck,
  Sparkles,
  Sun,
  Trash2,
  TrendingUp,
  Undo2,
  X,
} from "lucide-react";

type Json = Record<string, any>;
type Market = "stocks" | "crypto";
type AuthState = "checking" | "ready" | "login" | "error";

type Session = {
  authentication_required: boolean;
  authenticated: boolean;
  configured: boolean;
  email?: string | null;
  mode?: string;
};

type DomainData = {
  health: Json;
  market: Json;
  opportunities: Json;
  context: Json;
  alerts: Json;
  detail: Json;
  candles: Json;
  journal: Json;
  runtime: Json;
  research: Json;
  safety: Json;
  validation: Json;
  coverage: Json;
  notifications: Json;
  discovery: Json;
  simulation: Json;
  evaluations: Json;
  holders: Json;
};

type DrawingKind = "hline" | "trend";
type Drawing = { id: string; kind: DrawingKind; x1: number; y1: number; x2?: number; y2?: number; label: string; color: string };
type DrawingTool = "none" | DrawingKind;
type ResearchMessage = { role: "user" | "system"; text: string };

function emptyDomainData(): DomainData {
  return { health: {}, market: {}, opportunities: {}, context: {}, alerts: {}, detail: {}, candles: {}, journal: {}, runtime: {}, research: {}, safety: {}, validation: {}, coverage: {}, notifications: {}, discovery: {}, simulation: {}, evaluations: {}, holders: {} };
}

const VIEWS: Array<{ id: ViewName; label: MessageKey; icon: typeof LayoutDashboard }> = [
  { id: "today", label: "Today", icon: LayoutDashboard },
  { id: "opportunities", label: "Opportunities", icon: Radar },
  { id: "chart", label: "Chart", icon: ChartCandlestick },
  { id: "plans", label: "Plans", icon: FileText },
  { id: "review", label: "Review", icon: BookOpen },
];

function workspaceUiLabel(workspace: WorkspaceId, language: UiLanguage): string {
  return workspaceLabel(workspace, language);
}

function storedPreference<T extends string>(key: string, fallback: T): T {
  try {
    return (window.localStorage.getItem(key) as T | null) ?? fallback;
  } catch {
    return fallback;
  }
}

function useWorkspaceI18n() {
  const { language, t } = useI18n();
  return {
    language,
    t,
    actionLabel: (value: unknown) => actionText(value, language),
    statusLabel: (value: unknown) => statusText(value, language),
    humanizeText: (value: unknown) => backendText(value, language),
    localizedNumber: (value: unknown, digits = 2) => formatUiNumber(value, language, digits),
  };
}

function isRecord(value: unknown): value is Json {
  return Boolean(value && typeof value === "object" && !Array.isArray(value));
}

function textValue(...values: unknown[]): string {
  for (const value of values) {
    if (value !== null && value !== undefined && String(value).trim() !== "") return String(value);
  }
  return "-";
}

function numberValue(...values: unknown[]): number | null {
  for (const value of values) {
    const parsed = typeof value === "number" ? value : Number(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return null;
}

function formatNumber(value: unknown, digits = 2): string {
  const number = numberValue(value);
  const locale = typeof document !== "undefined" && document.documentElement.lang.startsWith("zh") ? "zh-CN" : "en-US";
  return number === null ? "-" : number.toLocaleString(locale, { maximumFractionDigits: digits });
}

function formatPercent(value: unknown): string {
  const number = numberValue(value);
  if (number === null) return "-";
  const locale = typeof document !== "undefined" && document.documentElement.lang.startsWith("zh") ? "zh-CN" : "en-US";
  const ratio = Math.abs(number) <= 1 ? number : number / 100;
  return new Intl.NumberFormat(locale, { style: "percent", minimumFractionDigits: 1, maximumFractionDigits: 1 }).format(ratio);
}

function extractRows(payload: unknown, preferredKeys: string[] = []): Json[] {
  const seen = new Set<object>();
  const output: Json[] = [];
  const visit = (value: unknown, depth: number) => {
    if (depth > 3 || !isRecord(value) || seen.has(value)) return;
    seen.add(value);
    for (const key of preferredKeys) {
      const candidate = value[key];
      if (Array.isArray(candidate)) {
        for (const item of candidate) if (isRecord(item)) output.push(item);
      }
    }
    for (const candidate of Object.values(value)) {
      if (Array.isArray(candidate)) {
        for (const item of candidate) if (isRecord(item)) output.push(item);
      } else if (isRecord(candidate)) {
        visit(candidate, depth + 1);
      }
    }
  };
  visit(payload, 0);
  const unique = new Map<string, Json>();
  for (const row of output) {
    const key = textValue(row.id, row.symbol, row.asset_id, row.roll_id, row.evaluation_id, JSON.stringify(row).slice(0, 80));
    if (!unique.has(key)) unique.set(key, row);
  }
  return [...unique.values()];
}

function extractCandles(payload: unknown): Json[] {
  return extractRows(payload, ["candles", "bars", "items", "data", "klines"])
    .filter((row) => numberValue(row.close, row.c) !== null && numberValue(row.open, row.o) !== null)
    .map((row) => ({
      time: textValue(row.time, row.start_time, row.timestamp, row.t),
      open: numberValue(row.open, row.o) ?? 0,
      high: numberValue(row.high, row.h) ?? 0,
      low: numberValue(row.low, row.l) ?? 0,
      close: numberValue(row.close, row.c) ?? 0,
      volume: numberValue(row.volume, row.v) ?? 0,
    }));
}

function cryptoAssetPath(symbol: string): string {
  const asset = symbol.replace(/USDT$/i, "").replace(/[^a-z0-9:_-]/gi, "").toLowerCase() || "btc";
  return `asset%3A${encodeURIComponent(asset)}`;
}

function emaSeries(values: number[], period: number): Array<number | null> {
  if (!values.length) return [];
  const result: Array<number | null> = Array(values.length).fill(null);
  if (values.length < period) return result;
  let previous = values.slice(0, period).reduce((sum, value) => sum + value, 0) / period;
  result[period - 1] = previous;
  const multiplier = 2 / (period + 1);
  for (let index = period; index < values.length; index += 1) {
    previous = (values[index] - previous) * multiplier + previous;
    result[index] = previous;
  }
  return result;
}

function compactValue(value: unknown): string {
  const number = numberValue(value);
  if (number === null) return textValue(value);
  if (Math.abs(number) >= 1_000_000) return `${(number / 1_000_000).toFixed(1)}M`;
  if (Math.abs(number) >= 1_000) return `${(number / 1_000).toFixed(1)}K`;
  return formatNumber(number, 2);
}

function errorText(error: unknown, language: UiLanguage = "zh"): string {
  if (!(error instanceof Error)) return translate(language, "Data is temporarily unavailable");
  return backendText(error.message, language);
}

async function getJson<T extends Json>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, { credentials: "same-origin", cache: "no-store", ...init });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(isRecord(body) && body.detail ? String(body.detail) : `Request failed (${response.status})`);
  return body as T;
}

function LoginScreen({ mode, language, onAuthenticated }: { mode: AuthState; language: UiLanguage; onAuthenticated: () => Promise<void> }) {
  const t = (key: MessageKey) => translate(language, key);
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setMessage("");
    try {
      const response = await fetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        credentials: "same-origin",
        body: JSON.stringify({ email, password }),
      });
      const body = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(body.detail || t("Email or password is incorrect"));
      await onAuthenticated();
    } catch (error) {
      setMessage(errorText(error, language));
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="auth-shell">
      <section className="auth-panel" aria-labelledby="login-title">
        <div className="brand-mark large">KQ</div>
        <p className="eyebrow">KQUANT WORKSPACE</p>
        <h1 id="login-title">{t("Enter research workspace")}</h1>
        <p className="auth-lede">{t("Stocks, options, and Crypto share one entrance while their data, plans, and results remain isolated.")}</p>
        {mode === "error" ? <p className="form-error">{t("The unified gateway is unavailable. Check that it is running.")}</p> : null}
        <form className="auth-form" onSubmit={submit}>
          <label>{t("Email")}<input type="email" autoComplete="username" value={email} onChange={(event) => setEmail(event.target.value)} required /></label>
          <label>{t("Password")}<input type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} required /></label>
          {message ? <p className="form-error">{message}</p> : null}
          <button className="primary-button" type="submit" disabled={busy}>{busy ? t("Signing in") : t("Enter workspace")}<ChevronRight size={16} /></button>
        </form>
        <p className="auth-note"><ShieldCheck size={15} /> {t("Research, simulation, and observation only. No account access or order submission.")}</p>
      </section>
    </main>
  );
}

function StatusChip({ label, tone = "neutral" }: { label: string; tone?: "positive" | "caution" | "negative" | "info" | "neutral" }) {
  return <span className={`status-chip ${tone}`}><span className="status-dot" />{label}</span>;
}

function statusTone(value: unknown): "positive" | "caution" | "negative" | "info" | "neutral" {
  const raw = String(value ?? "").toLowerCase();
  if (["available", "live", "ok", "online", "healthy", "complete", "connected", "ready", "passed"].some((item) => raw.includes(item))) return "positive";
  if (["caution", "stale", "partial", "closed", "limited", "pending", "unknown", "需确认", "过期", "收盘", "有限", "等待"].some((item) => raw.includes(item))) return "caution";
  if (["unavailable", "failed", "blocked", "rejected", "error", "offline", "不可用", "不足", "未通过", "失效"].some((item) => raw.includes(item))) return "negative";
  if (["armed", "watch", "research"].some((item) => raw.includes(item))) return "info";
  return "neutral";
}

function LoadingLine({ label }: { label?: string }) {
  const { t } = useWorkspaceI18n();
  return <div className="loading-line"><RefreshCw size={15} className="spin" />{label ?? t("Loading data")}</div>;
}

function EmptyState({ title, detail }: { title: string; detail: string }) {
  return <div className="empty-state"><CircleHelp size={19} /><strong>{title}</strong><span>{detail}</span></div>;
}

function MetricStrip({ items }: { items: Array<{ label: string; value: string; tone?: string }> }) {
  const { statusLabel } = useWorkspaceI18n();
  return <div className="metric-strip">{items.map((item) => <div className="metric" key={item.label}><span>{item.label}</span><strong className={item.tone ? `tone-${item.tone}` : ""}>{statusLabel(item.value)}</strong></div>)}</div>;
}

function EvidenceList({ detail, market }: { detail: Json; market: Market }) {
  const { t, humanizeText } = useWorkspaceI18n();
  const evidence = extractRows(detail.decision_evidence ?? detail.evidence ?? detail.supporting_factors, ["items", "supporting", "opposing", "factors"]);
  const fallback = market === "stocks"
    ? [t("Stock structure, relative strength, and price-volume evidence use closed data."), t("Live data and market hours affect manual-review eligibility."), t("Research conclusions are not order instructions.")]
    : [t("Market regime, liquidity, and safety snapshots jointly determine eligibility."), t("Forming market data cannot directly upgrade a simulation plan."), t("Crypto plans must pass the final evaluation layer.")];
  return <div className="evidence-list">{(evidence.length ? evidence.slice(0, 5).map((item) => humanizeText(textValue(item.message, item.reason, item.label, item.factor, item.name))) : fallback).map((item, index) => <div className="evidence-row" key={`${item}-${index}`}><span className="evidence-mark">{index < 3 ? "•" : "—"}</span><span>{item}</span></div>)}</div>;
}

function OpportunityTable({ market, rows, onSelect }: { market: Market; rows: Json[]; onSelect: (symbol: string) => void }) {
  const { t, actionLabel, statusLabel } = useWorkspaceI18n();
  const visible = rows.slice(0, 12);
  return <div className="table-wrap">
    {visible.length ? <table><thead><tr><th>{t("Asset")}</th><th>{t("Decision")}</th><th>{t("Score")}</th><th>{t("Status")}</th><th>{t("Time")}</th></tr></thead><tbody>{visible.map((row, index) => {
      const symbol = textValue(row.symbol, row.ticker, row.asset_id).replace(/^asset:/, "").toUpperCase();
      const action = textValue(row.action, row.decision, row.stage, row.status);
      const score = textValue(formatNumber(row.score, 1), formatNumber(row.setup_score, 1));
      const source = textValue(row.source_status, row.data_status?.source, row.trust_status, row.provider_status);
      return <tr key={`${symbol}-${index}`} onClick={() => onSelect(symbol)} tabIndex={0} onKeyDown={(event) => { if (event.key === "Enter") onSelect(symbol); }}>
        <td><strong>{symbol}</strong><small>{textValue(row.name, row.company_name, row.asset_type)}</small></td>
        <td><span className="table-action">{actionLabel(action)}</span></td>
        <td className="mono">{score}</td>
        <td><StatusChip label={statusLabel(source)} tone={statusTone(source)} /></td>
        <td className="muted mono">{textValue(row.as_of_time, row.generated_at, row.updated_at).slice(0, 16)}</td>
      </tr>;
    })}</tbody></table> : <EmptyState title={t("No candidates to display")} detail={market === "stocks" ? t("Run a stock scan or check Longbridge data.") : t("Waiting for CEX data collection.")} />}
  </div>;
}

function PriceChart({ payload, market, symbol }: { payload: Json; market: Market; symbol: string }) {
  const { t, localizedNumber } = useWorkspaceI18n();
  const candles = extractCandles(payload).slice(-220);
  const [tool, setTool] = useState<DrawingTool>("none");
  const [drawings, setDrawings] = useState<Drawing[]>([]);
  const [pendingPoint, setPendingPoint] = useState<{ x: number; y: number } | null>(null);
  const [label, setLabel] = useState("Line");
  const [color, setColor] = useState("#5ea8ff");

  useEffect(() => {
    setDrawings([]);
    setPendingPoint(null);
    setTool("none");
  }, [market, symbol]);

  if (!candles.length) return <EmptyState title={t("No chart data")} detail={t("No closed candles are available for this market.")} />;
  const width = 1000;
  const height = 380;
  const plotTop = 18;
  const plotBottom = 270;
  const volumeTop = 292;
  const volumeBottom = 360;
  const closes = candles.map((item) => Number(item.close));
  const rawLow = Math.min(...candles.map((item) => Number(item.low)));
  const rawHigh = Math.max(...candles.map((item) => Number(item.high)));
  const padding = Math.max((rawHigh - rawLow) * 0.04, Math.abs(rawHigh) * 0.002, 0.000001);
  const low = rawLow - padding;
  const high = rawHigh + padding;
  const range = Math.max(high - low, 0.000001);
  const x = (index: number) => (index / Math.max(candles.length - 1, 1)) * width;
  const y = (value: number) => plotBottom - ((value - low) / range) * (plotBottom - plotTop);
  const pointsFor = (values: Array<number | null>) => values.reduce<string[]>((points, value, index) => {
    if (value !== null && Number.isFinite(value)) points.push(`${x(index)},${y(value)}`);
    return points;
  }, []).join(" ");
  const ema20 = emaSeries(closes, 20);
  const ema50 = emaSeries(closes, 50);
  const ema200 = emaSeries(closes, 200);
  const volumes = candles.map((item) => numberValue(item.volume) ?? 0);
  const maxVolume = Math.max(...volumes, 1);
  const candleWidth = Math.max(2, Math.min(10, (width / Math.max(candles.length - 1, 1)) * 0.62));
  const up = closes[closes.length - 1] >= closes[0];

  const handleChartClick = (event: MouseEvent<SVGSVGElement>) => {
    if (tool === "none") return;
    const rect = event.currentTarget.getBoundingClientRect();
    const nextPoint = {
      x: Math.max(0, Math.min(width, ((event.clientX - rect.left) / rect.width) * width)),
      y: Math.max(plotTop, Math.min(plotBottom, ((event.clientY - rect.top) / rect.height) * height)),
    };
    if (tool === "hline") {
      setDrawings((current) => [...current, { id: `${Date.now()}-${current.length}`, kind: "hline", x1: 0, y1: nextPoint.y, x2: width, y2: nextPoint.y, label, color }]);
      setTool("none");
      setPendingPoint(null);
      return;
    }
    if (!pendingPoint) {
      setPendingPoint(nextPoint);
      return;
    }
    setDrawings((current) => [...current, { id: `${Date.now()}-${current.length}`, kind: "trend", x1: pendingPoint.x, y1: pendingPoint.y, x2: nextPoint.x, y2: nextPoint.y, label, color }]);
    setPendingPoint(null);
    setTool("none");
  };

  return <div className="chart-block">
    <div className="chart-head"><div><span className="eyebrow">{market === "stocks" ? "Longbridge" : "CEX"} {t("Chart")}</span><h3>{symbol}</h3></div><div className="chart-last"><strong>{localizedNumber(closes[closes.length - 1], 4)}</strong><span className={up ? "positive-text" : "negative-text"}>{up ? <ArrowUpRight size={15} /> : <ArrowDownRight size={15} />}{formatPercent(((closes[closes.length - 1] / closes[0]) - 1) * 100)}</span></div></div>
    <div className="chart-tools" role="toolbar" aria-label={t("Manual drawing tools")}>
      <button type="button" className={tool === "hline" ? "chart-tool active" : "chart-tool"} onClick={() => { setTool(tool === "hline" ? "none" : "hline"); setPendingPoint(null); }} title={t("Click the chart to add a horizontal line")}><Minus size={15} />{t("Horizontal line")}</button>
      <button type="button" className={tool === "trend" ? "chart-tool active" : "chart-tool"} onClick={() => { setTool(tool === "trend" ? "none" : "trend"); setPendingPoint(null); }} title={t("Click two chart points to add a trend line")}><TrendingUp size={15} />{t("Trend line")}</button>
      <select value={label} onChange={(event) => setLabel(event.target.value)} aria-label={t("Line label")}><option>Line</option><option>Entry</option><option>Stop</option><option>Target</option><option>Alert</option></select>
      <label className="color-picker" title={t("Choose line color")}><input type="color" value={color} onChange={(event) => setColor(event.target.value)} aria-label={t("Line color")} /></label>
      <button type="button" className="chart-tool" onClick={() => { setDrawings((current) => current.slice(0, -1)); setPendingPoint(null); }} disabled={!drawings.length} title={t("Undo last line")}><Undo2 size={15} />{t("Undo")}</button>
      <button type="button" className="chart-tool" onClick={() => { setDrawings([]); setPendingPoint(null); setTool("none"); }} disabled={!drawings.length && !pendingPoint} title={t("Clear all chart annotations")}><Trash2 size={15} />{t("Clear")}</button>
      <span className="chart-tool-hint">{tool === "hline" ? t("Click once to place a horizontal line") : tool === "trend" ? (pendingPoint ? t("Click once more to finish the trend line") : t("Click two points to connect a trend line")) : t("Lines are drawn only after selecting a tool")}</span>
    </div>
    <svg className="price-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${symbol} ${t("Price chart and manual drawings")}`} preserveAspectRatio="none" onClick={handleChartClick}>
      {[plotTop, 80, 145, 210, plotBottom].map((line) => <line key={line} x1="0" x2={width} y1={line} y2={line} className="chart-grid-line" />)}
      <line x1="0" x2={width} y1={volumeTop - 8} y2={volumeTop - 8} className="chart-volume-divider" />
      <polyline points={pointsFor(ema20)} className="chart-ema ema20" />
      <polyline points={pointsFor(ema50)} className="chart-ema ema50" />
      <polyline points={pointsFor(ema200)} className="chart-ema ema200" />
      {candles.map((item, index) => {
        const open = Number(item.open);
        const close = Number(item.close);
        const highValue = Number(item.high);
        const lowValue = Number(item.low);
        const rising = close >= open;
        const bodyTop = y(Math.max(open, close));
        const bodyHeight = Math.max(1.5, Math.abs(y(open) - y(close)));
        return <g key={`${item.time}-${index}`} className={rising ? "candle rising" : "candle falling"}>
          <line x1={x(index)} x2={x(index)} y1={y(highValue)} y2={y(lowValue)} className="candle-wick" />
          <rect x={x(index) - candleWidth / 2} y={bodyTop} width={candleWidth} height={bodyHeight} className="candle-body" />
          <rect x={x(index) - candleWidth / 2} y={volumeBottom - ((volumes[index] / maxVolume) * (volumeBottom - volumeTop))} width={candleWidth} height={Math.max(1, (volumes[index] / maxVolume) * (volumeBottom - volumeTop))} className="chart-volume" />
        </g>;
      })}
      {drawings.map((drawing) => {
        const x2 = drawing.x2 ?? drawing.x1;
        const y2 = drawing.y2 ?? drawing.y1;
        const labelX = drawing.kind === "hline" ? 12 : Math.min(drawing.x1, x2) + 8;
        const labelY = Math.max(plotTop + 12, Math.min(plotBottom - 2, Math.min(drawing.y1, y2) - 6));
        const labelWidth = Math.max(42, drawing.label.length * 7 + 14);
        return <g key={drawing.id} className="user-drawing">
          <line x1={drawing.x1} y1={drawing.y1} x2={x2} y2={y2} stroke={drawing.color} className={drawing.kind === "hline" ? "drawing-line horizontal" : "drawing-line"} />
          <rect x={labelX} y={labelY - 11} width={labelWidth} height="16" rx="3" fill={drawing.color} />
          <text x={labelX + 7} y={labelY + 1} fill="#08111d">{drawing.label}</text>
        </g>;
      })}
      {pendingPoint ? <circle cx={pendingPoint.x} cy={pendingPoint.y} r="5" className="drawing-pending" /> : null}
    </svg>
    <div className="chart-foot"><span>{candles.length} {t("closed candles")} · EMA20 / EMA50 / EMA200</span><span>{textValue(candles[0].time).slice(0, 16)} → {textValue(candles[candles.length - 1].time).slice(0, 16)}</span></div>
  </div>;
}

function ResearchDrawer({ market, symbol, messages, onMessagesChange, onClose, onSubmit }: { market: Market; symbol: string; messages: ResearchMessage[]; onMessagesChange: (update: (current: ResearchMessage[]) => ResearchMessage[]) => void; onClose: () => void; onSubmit: (question: string) => Promise<string> }) {
  const { t, language } = useWorkspaceI18n();
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (!question.trim() || busy) return;
    const current = question.trim();
    setQuestion("");
    onMessagesChange((items) => [...items, { role: "user", text: current }]);
    setBusy(true);
    try {
      const answer = await onSubmit(current);
      onMessagesChange((items) => [...items, { role: "system", text: answer }]);
    } catch (error) {
      onMessagesChange((items) => [...items, { role: "system", text: errorText(error, language) }]);
    } finally {
      setBusy(false);
    }
  };
  const prompts = market === "stocks" ? [t("What are the main risks for this stock?"), t("What would strengthen the current decision?"), t("Review the entry zone and invalidation conditions.")] : [t("How does the current market regime affect this asset?"), t("What are the liquidity and safety risks?"), t("When would this be eligible for simulation observation?")];
  return <aside className="research-drawer" aria-label={t("Research drawer")}>
    <div className="drawer-head"><div><span className="eyebrow">{t("Research drawer")}</span><h2>{symbol}</h2></div><button className="icon-button" onClick={onClose} title={t("Close research")}><X size={18} /></button></div>
    <div className="drawer-context"><StatusChip label={market === "stocks" ? t("Stock research") : t("Crypto research")} tone="info" /><span>{t("Current asset")}: {symbol}</span></div>
    <div className="drawer-messages">{messages.length ? messages.map((message, index) => <div className={`drawer-message ${message.role}`} key={`${message.role}-${index}`}>{message.text}</div>) : <div className="drawer-empty"><PanelRight size={22} /><strong>{t("Put your question here")}</strong><span>{t("The research drawer follows the selected asset; answers are stored separately from decisions.")}</span></div>}</div>
    <div className="quick-prompts">{prompts.map((prompt) => <button key={prompt} className="text-button" onClick={() => setQuestion(prompt)}>{prompt}</button>)}</div>
    <form className="research-form" onSubmit={submit}><textarea value={question} onChange={(event) => setQuestion(event.target.value)} placeholder={t("Ask about risks, price action, entry conditions, or evidence to review...")} rows={3} /><button className="primary-button" disabled={busy || !question.trim()}>{busy ? t("Thinking") : t("Start research")}<ChevronRight size={16} /></button></form>
  </aside>;
}

function Workspace({ onLogout }: { onLogout: () => Promise<void> }) {
  const initialWorkspace = workspaceFromSearch(window.location.search);
  const [workspace, setWorkspace] = useState<WorkspaceId>(initialWorkspace);
  const [view, setView] = useState<ViewName>(() => viewFromSearch(window.location.search, initialWorkspace));
  const [symbol, setSymbol] = useState(() => symbolFromSearch(window.location.search, initialWorkspace));
  const [search, setSearch] = useState("");
  const [data, setData] = useState<DomainData>(emptyDomainData);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState("");
  const [researchOpen, setResearchOpen] = useState(false);
  const [researchMessagesByKey, setResearchMessagesByKey] = useState<Record<string, ResearchMessage[]>>({});
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [liveAlerts, setLiveAlerts] = useState<Json[]>([]);
  const [streamStatus, setStreamStatus] = useState<"connecting" | "connected" | "offline">("connecting");
  const [refreshNonce, setRefreshNonce] = useState(0);
  const [language, setLanguage] = useState<UiLanguage>(() => storedPreference<UiLanguage>("kquant-unified:language", "zh"));
  const [theme, setTheme] = useState<UiTheme>(() => storedPreference<UiTheme>("kquant-unified:theme", "dark"));
  const market: Market = workspace === "crypto" ? "crypto" : "stocks";
  const t = (key: MessageKey) => translate(language, key);
  const actionLabel = (value: unknown) => actionText(value, language);
  const statusLabel = (value: unknown) => statusText(value, language);

  useEffect(() => {
    document.documentElement.lang = language === "zh" ? "zh-CN" : "en";
    document.documentElement.dataset.theme = theme;
    try {
      window.localStorage.setItem("kquant-unified:language", language);
      window.localStorage.setItem("kquant-unified:theme", theme);
    } catch {
      // Preference persistence is optional in strict browser privacy contexts.
    }
  }, [language, theme]);

  const loadWorkspace = async (nextWorkspace: WorkspaceId, nextSymbol: string, nextView: ViewName, signal: AbortSignal) => {
    setLoading(true);
    setMessage("");
    const encoded = encodeURIComponent(nextSymbol);
    const stockCalls: Record<keyof DomainData, string> = {
      health: "/api/stocks/health",
      market: "/api/stocks/market-data/status",
      opportunities: "/api/stocks/signals/latest?source=live&universe=default&profile=swing_long_v1",
      context: "/api/stocks/themes/ranking",
      alerts: "/api/stocks/alerts",
      detail: `/api/stocks/analyze?symbol=${encoded}&source=live&profile=swing_long_v1`,
      candles: `/api/stocks/candles?symbol=${encoded}&range=1y&interval=1d&source=live`,
      journal: `/api/stocks/signal-journal?symbol=${encoded}&limit=30`,
      runtime: `/api/stocks/realtime-snapshot?symbol=${encoded}`,
      research: `/api/stocks/${encoded}/factor-snapshot?profile=swing_long_v1`,
      safety: "/api/stocks/production-readiness",
      validation: `/api/stocks/${encoded}/early-trend`,
      coverage: "/api/stocks/quant/overview",
      notifications: "/api/stocks/notifications/status",
      discovery: "/api/stocks/themes/ranking",
      simulation: "/api/stocks/quant/stocks/validation/latest",
      evaluations: "/api/stocks/ai-review/status",
      holders: "/api/stocks/health",
    };
    const cryptoCalls: Record<keyof DomainData, string> = {
      health: "/api/crypto/health",
      market: "/api/crypto/providers/status",
      opportunities: "/api/crypto/instructions/current",
      context: "/api/crypto/market-regime/current",
      alerts: "/api/crypto/alerts",
      detail: `/api/crypto/assets/${cryptoAssetPath(nextSymbol)}/market-snapshot`,
      candles: `/api/crypto/assets/${cryptoAssetPath(nextSymbol)}/market-snapshot`,
      journal: "/api/crypto/roll-journal",
      runtime: "/api/crypto/runtime/supervisor-status",
      research: "/api/crypto/research/bayesian/asset:eth",
      safety: "/api/crypto/security/latest?limit=12",
      validation: "/api/crypto/validation/latest",
      coverage: "/api/crypto/evidence/coverage",
      notifications: "/api/crypto/notifications/status",
      discovery: "/api/crypto/dex/pairs/latest?limit=12",
      simulation: "/api/crypto/research/monte-carlo/asset:eth",
      evaluations: "/api/crypto/evaluations/latest",
      holders: `/api/crypto/assets/${cryptoAssetPath(nextSymbol)}/holders/latest`,
    };
    const keysByView: Record<ViewName, Array<keyof DomainData>> = {
      today: ["health", "market", "opportunities", "context", "alerts", "detail", "runtime"],
      opportunities: ["health", "market", "opportunities", "context", "discovery", "coverage"],
      chart: ["health", "market", "detail", "candles", "runtime"],
      plans: ["health", "market", "opportunities", "detail", "runtime", "safety", "validation", "notifications", "simulation", "evaluations"],
      review: ["health", "market", "alerts", "detail", "journal", "research", "safety", "validation", "simulation", "notifications", "evaluations", "holders", "coverage"],
      settings: ["health", "market", "runtime", "safety", "coverage", "notifications"],
    };
    let calls: Partial<Record<keyof DomainData, string>>;
    if (nextWorkspace === "options") {
      calls = {
        health: "/api/stocks/health",
        market: "/api/options/status",
        alerts: "/api/stocks/alerts",
        runtime: "/api/options/radar/status",
        notifications: "/api/stocks/notifications/status",
        ...(nextView === "chart" ? { candles: stockCalls.candles, detail: stockCalls.detail } : {}),
      };
    } else {
      const source = nextWorkspace === "crypto" ? cryptoCalls : stockCalls;
      calls = Object.fromEntries(keysByView[nextView].map((key) => [key, source[key]]));
    }
    const entries = await Promise.all(Object.entries(calls).map(async ([key, path]) => {
      try { return [key, await getJson<Json>(String(path), { signal })] as const; }
      catch (error) { return [key, { status: "unavailable", error: errorText(error) }] as const; }
    }));
    if (signal.aborted) return;
    setData({ ...emptyDomainData(), ...Object.fromEntries(entries) });
    const failures = entries.filter(([, value]) => value.status === "unavailable");
    if (entries.length && failures.length === entries.length) setMessage(t("The current workspace has no usable data. Check its backend service."));
    setLoading(false);
  };

  useEffect(() => {
    const controller = new AbortController();
    void loadWorkspace(workspace, symbol, view, controller.signal);
    return () => controller.abort();
  }, [workspace, symbol, view, refreshNonce, language]);

  useEffect(() => {
    const source = new EventSource("/api/alerts/stream");
    const handleReady = () => setStreamStatus("connected");
    const handleAlert = (event: Event) => {
      try {
        const outer = JSON.parse((event as MessageEvent).data) as Json;
        const payload = typeof outer.payload === "string" ? JSON.parse(outer.payload) as Json : (outer.payload ?? outer);
        const domain = textValue(outer.domain, payload.market, payload.domain);
        const alertWorkspace = String(payload.event_type ?? payload.type ?? "").includes("option") || payload.opportunity_id ? "options" : domain;
        const row = { ...payload, market: domain, workspace: alertWorkspace };
        const key = textValue(row.id, row.alert_id, row.notification_id, row.event_id, JSON.stringify(row).slice(0, 80));
        setLiveAlerts((current) => [row, ...current.filter((item) => textValue(item.id, item.alert_id, item.notification_id, item.event_id, JSON.stringify(item).slice(0, 80)) !== key)].slice(0, 50));
        if (alertWorkspace === workspace) setRefreshNonce((value) => value + 1);
      } catch {
        // One malformed upstream event must not break the unified alert stream.
      }
    };
    const handleError = () => setStreamStatus("offline");
    source.addEventListener("ready", handleReady);
    source.addEventListener("alert", handleAlert);
    source.addEventListener("error", handleError);
    return () => {
      source.removeEventListener("ready", handleReady);
      source.removeEventListener("alert", handleAlert);
      source.removeEventListener("error", handleError);
      source.close();
    };
  }, [workspace]);

  useEffect(() => {
    window.history.replaceState({}, "", canonicalWorkspaceUrl(window.location.href, workspace, view, symbol));
  }, []);

  useEffect(() => {
    const onPopState = () => {
      const nextWorkspace = workspaceFromSearch(window.location.search);
      setWorkspace(nextWorkspace);
      setView(viewFromSearch(window.location.search, nextWorkspace));
      setSymbol(symbolFromSearch(window.location.search, nextWorkspace));
      setMobileNavOpen(false);
      setResearchOpen(false);
    };
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, []);

  const rows = useMemo(() => {
    const keys = market === "stocks" ? ["signals", "items", "daily_candidates", "buy_setups", "watch", "rows"] : ["items", "instructions", "evaluations", "rolls"];
    return extractRows(data.opportunities, keys);
  }, [data.opportunities, market]);
  const alertRows = useMemo(() => {
    const stored: Json[] = extractRows(data.alerts, ["items", "alerts", "events"]).map((row): Json => ({ ...row, market, workspace: String(row.event_type ?? "").includes("option") ? "options" : market }));
    const current = liveAlerts.filter((row) => String(row.workspace ?? row.market).toLowerCase() === workspace);
    const relevantStored = stored.filter((row) => workspace === "options" ? row.workspace === "options" : row.workspace !== "options");
    const unique = new Map<string, Json>();
    for (const row of [...current, ...relevantStored]) {
      const key = textValue(row.id, row.alert_id, row.notification_id, row.event_id, JSON.stringify(row).slice(0, 80));
      if (!unique.has(key)) unique.set(key, row);
    }
    return [...unique.values()];
  }, [data.alerts, liveAlerts, market, workspace]);
  const healthStatus = textValue(data.health.status, data.health.providers ? "available" : "unavailable");
  const healthReady = ["available", "ok", "online", "healthy", "ready"].some((item) => healthStatus.toLowerCase().includes(item));
  const marketStatus = workspace === "options"
    ? statusLabel(textValue(data.runtime.opra_status, data.market.status, "PENDING"))
    : market === "stocks"
      ? statusLabel(textValue(data.market.status, data.market.source, data.market.freshness))
      : statusLabel(textValue(data.context.regime, data.market.status));

  const navigate = (nextWorkspace: WorkspaceId, nextView: ViewName, nextSymbol: string) => {
    window.history.pushState({}, "", canonicalWorkspaceUrl(window.location.href, nextWorkspace, nextView, nextSymbol));
    setWorkspace(nextWorkspace);
    setView(nextView);
    setSymbol(nextSymbol);
  };
  const changeView = (nextView: ViewName) => { navigate(workspace, nextView, symbol); setMobileNavOpen(false); };
  const changeWorkspace = (nextWorkspace: WorkspaceId) => {
    if (nextWorkspace === workspace) return;
    setResearchOpen(false);
    navigate(nextWorkspace, nextWorkspace === "options" ? "opportunities" : "today", DEFAULT_SYMBOL[nextWorkspace]);
  };
  const selectSymbol = (next: string) => {
    const normalized = next.trim().toUpperCase();
    if (!normalized) return;
    navigate(workspace, "chart", normalized);
  };
  const changeSymbolOnly = (next: string) => navigate(workspace, view, next.trim().toUpperCase());
  const submitSearch = (event: FormEvent) => { event.preventDefault(); selectSymbol(search); setSearch(""); };
  const onSearchKey = (event: KeyboardEvent<HTMLInputElement>) => { if (event.key === "Enter") { event.preventDefault(); selectSymbol(search); setSearch(""); } };
  const submitResearch = async (question: string) => {
    if (market === "crypto") return language === "zh" ? "Crypto 研究栏使用市场状态、流动性、安全和最终审核结果作为上下文；完整证据位于复盘页。" : "Crypto research uses market regime, liquidity, safety, and final evaluation as context. Full evidence is available in Review.";
    const response = await getJson<Json>("/api/stocks/research-chat", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ symbol, profile: "tactical_1w_v1", question, language: language === "zh" ? "zh" : "en" }) });
    return textValue(response.answer, response.message, response.summary, language === "zh" ? "研究服务暂时没有返回内容。" : "The research service returned no content.");
  };

  const researchKey = `${market}:${symbol}`;
  const acknowledgeAlert = async (row: Json) => {
    const id = textValue(row.id, row.alert_id, row.notification_id, row.event_id);
    if (id === "-") return;
    const path = market === "stocks" ? `/api/stocks/alerts/${encodeURIComponent(id)}/ack` : `/api/crypto/alerts/${encodeURIComponent(id)}/ack`;
    try {
      await getJson<Json>(path, { method: "POST" });
      setLiveAlerts((current) => current.map((item) => textValue(item.id, item.alert_id, item.notification_id, item.event_id) === id ? { ...item, acknowledged_at: new Date().toISOString(), status: "acknowledged" } : item));
    } catch (error) {
      setMessage(errorText(error, language));
    }
  };

  const optionChart = <section className="work-surface chart-surface"><PriceChart payload={data.candles} market="stocks" symbol={symbol} /></section>;
  const viewTitle = view === "settings" ? t("Settings") : t((VIEWS.find((item) => item.id === view) ?? VIEWS[0]).label);
  const optionRealtimeReady = String(data.runtime.opra_status ?? data.market.opra_status).toLowerCase() === "available";
  const serviceLabel = workspace === "options" && !optionRealtimeReady ? t("Option data limited") : healthReady ? t("Service ready") : t("Connecting");
  const serviceTone = workspace === "options" && !optionRealtimeReady ? "caution" : statusTone(healthStatus);
  return <I18nProvider language={language}><div className={`workspace-shell ${researchOpen ? "research-open" : ""}`}>
    <header className="workspace-topbar">
      <div className="brand-lockup"><div className="brand-mark">KQ</div><div><strong>KQUANT</strong><span>{t("Unified research workspace")}</span></div></div>
      <form className="global-search" onSubmit={submitSearch}><Search size={17} /><input value={search} onChange={(event) => setSearch(event.target.value)} onKeyDown={onSearchKey} placeholder={workspaceSearchPlaceholder(workspace, language)} aria-label={t("Search this workspace")} /><kbd>Enter</kbd></form>
      <div className="topbar-actions"><div className="market-switch" role="tablist" aria-label={t("Switch workspace")}>{(["stocks", "options", "crypto"] as WorkspaceId[]).map((item) => <button className={workspace === item ? "active" : ""} onClick={() => changeWorkspace(item)} type="button" key={item}>{workspaceUiLabel(item, language)}</button>)}</div><StatusChip label={serviceLabel} tone={serviceTone} /><button className="icon-button alert-button" onClick={() => changeView("review")} title={t("Open alerts and review")}><Bell size={17} />{alertRows.length ? <b>{Math.min(alertRows.length, 99)}</b> : null}</button>{workspace !== "options" ? <button className="icon-button research-toggle" onClick={() => setResearchOpen((value) => !value)} title={t("Open research")}><PanelRight size={17} /></button> : null}<button className="icon-button desktop-only" onClick={() => void onLogout()} title={t("Sign out")}><LogOut size={17} /></button><button className="icon-button mobile-menu" onClick={() => setMobileNavOpen((value) => !value)} title={t("Open navigation")}><Menu size={18} /></button></div>
    </header>
    <div className="workspace-layout">
      <aside className={`workspace-nav ${mobileNavOpen ? "open" : ""}`}><div className="nav-market-label"><span>{workspaceUiLabel(workspace, language)}</span><StatusChip label={marketStatus} tone={statusTone(marketStatus)} /></div><nav>{VIEWS.map((item) => { const Icon = item.icon; return <button key={item.id} className={view === item.id ? "active" : ""} onClick={() => changeView(item.id)}><Icon size={17} /><span>{t(item.label)}</span>{item.id === "review" && alertRows.length ? <b>{alertRows.length}</b> : null}</button>; })}</nav><div className="nav-footer">{workspace !== "options" ? <button onClick={() => setResearchOpen(true)}><Sparkles size={16} /><span>{t("Research")}</span></button> : null}<button className={view === "settings" ? "active" : ""} onClick={() => changeView("settings")}><Settings size={16} /><span>{t("Settings")}</span></button><div className="boundary-note"><ShieldCheck size={15} /><span>{t("Research and manual review")}</span></div></div></aside>
      <main className="workspace-content"><div className="content-head"><div><span className="content-context">{workspaceUiLabel(workspace, language)} · {symbol}</span><h1>{viewTitle}</h1></div><div className="content-head-right"><span className={`stream-indicator ${streamStatus}`} title={t("Unified alert stream")}><span className="status-dot" />{streamStatus === "connected" ? t("Alerts online") : streamStatus === "connecting" ? t("Connecting alerts") : t("Alerts offline")}</span><button className="refresh-button" onClick={() => setRefreshNonce((value) => value + 1)}><RefreshCw size={15} />{t("Refresh")}</button></div></div>{message ? <div className="inline-notice"><AlertTriangle size={16} /><span>{message}</span></div> : null}{loading && workspace !== "options" ? <LoadingLine /> : null}{workspace === "options" ? <OptionsWorkspace view={view} symbol={symbol} refreshNonce={refreshNonce} chart={optionChart} onSymbolChange={changeSymbolOnly} language={language} theme={theme} onLanguageChange={setLanguage} onThemeChange={setTheme} /> : <>{view === "today" ? <TodayView market={market} data={data} rows={rows} alerts={alertRows} symbol={symbol} onSelect={selectSymbol} /> : null}{view === "opportunities" ? <DiscoverView market={market} data={data} rows={rows} onSelect={selectSymbol} /> : null}{view === "chart" ? <ChartView market={market} data={data} symbol={symbol} /> : null}{view === "plans" ? <PlanView market={market} data={data} rows={rows} symbol={symbol} /> : null}{view === "review" ? <ReviewView market={market} data={data} symbol={symbol} alerts={alertRows} onOpen={() => setResearchOpen(true)} onAcknowledge={acknowledgeAlert} /> : null}{view === "settings" ? <SettingsView market={market} data={data} language={language} theme={theme} onLanguageChange={setLanguage} onThemeChange={setTheme} /> : null}</>}</main>
    </div>
    {researchOpen && workspace !== "options" ? <ResearchDrawer key={researchKey} market={market} symbol={symbol} messages={researchMessagesByKey[researchKey] ?? []} onMessagesChange={(update) => setResearchMessagesByKey((current) => ({ ...current, [researchKey]: update(current[researchKey] ?? []) }))} onClose={() => setResearchOpen(false)} onSubmit={submitResearch} /> : null}
  </div></I18nProvider>;
}

function TodayView({ market, data, rows, alerts, symbol, onSelect }: { market: Market; data: DomainData; rows: Json[]; alerts: Json[]; symbol: string; onSelect: (symbol: string) => void }) {
  const { t, actionLabel, statusLabel, localizedNumber } = useWorkspaceI18n();
  const detail = data.detail;
  const decision = textValue(detail.action, detail.decision, detail.stage, detail.strategy_stage);
  const price = numberValue(detail.price, detail.last, detail.features?.close, detail.quote?.last, detail.last_price);
   return <>
     <section className="decision-band"><div className="decision-copy"><span className="eyebrow">{t("Current asset")} · {symbol}</span><h2>{textValue(detail.company_name, detail.name, symbol)}</h2><p>{market === "stocks" ? t("Review structure first, then confirm whether the data permits manual review.") : t("Review market regime, liquidity, and safety before simulation observation.")}</p><div className="decision-tags"><StatusChip label={actionLabel(decision)} tone={statusTone(decision)} /><StatusChip label={statusLabel(textValue(detail.data_status?.source, detail.source_status, market === "stocks" ? "Longbridge" : "CEX_DATA"))} tone="info" /><StatusChip label={statusLabel(textValue(detail.data_status?.freshness, detail.trust, "PENDING"))} tone={statusTone(detail.data_status?.freshness ?? detail.trust)} /></div></div><div className="decision-number"><span>{t("Current decision")}</span><strong>{actionLabel(decision)}</strong><small>{price === null ? t("Price pending") : localizedNumber(price, 4)}</small></div></section>
     <MetricStrip items={market === "stocks" ? [{ label: t("Price"), value: price === null ? "-" : localizedNumber(price) }, { label: t("Score"), value: localizedNumber(detail.score, 1) }, { label: t("Data status"), value: statusLabel(textValue(detail.data_status?.freshness, "PENDING")) }, { label: t("Entry condition"), value: textValue(detail.entry_zone, detail.entry, actionLabel("WAIT")) }] : [{ label: t("Price"), value: price === null ? "-" : localizedNumber(price, 4) }, { label: t("Market regime"), value: statusLabel(textValue(data.context.regime, "PENDING")) }, { label: t("Evaluation"), value: actionLabel(textValue(detail.evaluation_status, detail.decision, "WAIT")) }, { label: t("Alerts"), value: String(alerts.length) }]} />
    <div className="two-column"><section className="work-surface"><div className="surface-head"><div><span className="eyebrow">{t("Priority")}</span><h3>{market === "stocks" ? t("Today's stock opportunities") : t("Current Crypto opportunities")}</h3></div><button className="text-button" onClick={() => onSelect(symbol)}>{t("Open chart")} <ChevronRight size={14} /></button></div><OpportunityTable market={market} rows={rows} onSelect={onSelect} /></section><section className="work-surface"><div className="surface-head"><div><span className="eyebrow">{t("Rationale")}</span><h3>{t("Why this decision")}</h3></div><LineChart size={18} className="surface-icon" /></div><EvidenceList detail={detail} market={market} /><div className="next-step"><span>{t("Next step")}</span><strong>{market === "stocks" ? t("Confirm Longbridge data and entry invalidation conditions") : t("Confirm liquidity, safety snapshot, and final evaluation")}</strong></div></section></div>
  </>;
}

function DiscoverView({ market, data, rows, onSelect }: { market: Market; data: DomainData; rows: Json[]; onSelect: (symbol: string) => void }) {
  const { t, actionLabel } = useWorkspaceI18n();
  const contextRows = extractRows(data.context, ["items", "themes", "ranking", "members", "providers"]);
  return <div className="stack"><section className="work-surface"><div className="surface-head"><div><span className="eyebrow">{t("Discovery")}</span><h2>{market === "stocks" ? t("Stock universe and themes") : t("CEX, DEX, and MEME")}</h2><p className="surface-lede">{t("Filter by decision, data quality, and update time. Candidates cannot bypass final evaluation.")}</p></div><StatusChip label={market === "stocks" ? "Longbridge" : t("Public market data")} tone="info" /></div><OpportunityTable market={market} rows={rows} onSelect={onSelect} /></section><section className="work-surface compact-surface"><div className="surface-head"><div><span className="eyebrow">{t("Environment")}</span><h3>{market === "stocks" ? t("Theme rotation") : t("Market regime")}</h3></div><BarChart3 size={18} className="surface-icon" /></div>{contextRows.length ? <div className="rank-list">{contextRows.slice(0, 8).map((row, index) => <div className="rank-row" key={`${textValue(row.symbol, row.name, row.id)}-${index}`}><span className="rank-number">{String(index + 1).padStart(2, "0")}</span><strong>{textValue(row.name, row.symbol, row.theme, row.regime)}</strong><span>{actionLabel(textValue(row.status, row.action, row.direction))}</span><b>{formatNumber(row.score, 1)}</b></div>)}</div> : <EmptyState title={t("No environment snapshot")} detail={t("Run data collection to populate the market context.")} />}<ExtendedDataPanel market={market} data={data} /></section><DiscoveryDetailPanel market={market} data={data} /></div>;
}

function ChartView({ market, data, symbol }: { market: Market; data: DomainData; symbol: string }) {
  const { t, statusLabel } = useWorkspaceI18n();
  return <div className="stack"><section className="work-surface chart-surface"><div className="surface-head"><div><span className="eyebrow">{t("Chart")}</span><h2>{symbol} {t("Price action")}</h2><p className="surface-lede">{t("Only closed data is shown; forming bars do not directly change research decisions.")}</p></div><div className="chart-legend"><span><i className="legend-line blue" />EMA20</span><span><i className="legend-line amber" />EMA50</span><span><i className="legend-line teal" />EMA200</span></div></div><PriceChart payload={data.candles} market={market} symbol={symbol} /></section><section className="work-surface compact-surface"><div className="surface-head"><div><span className="eyebrow">{t("Data source")}</span><h3>{t("Current data status")}</h3></div><Activity size={18} className="surface-icon" /></div><MetricStrip items={[{ label: t("Source status"), value: statusLabel(textValue(data.detail.source, data.detail.data_status?.source, market === "stocks" ? "Longbridge" : "CEX")) }, { label: t("Status"), value: statusLabel(textValue(data.detail.status, data.market.status, "PENDING")) }, { label: t("Updated"), value: textValue(data.detail.as_of_time, data.detail.updated_at, "-") }, { label: t("Trust"), value: statusLabel(textValue(data.detail.trust, data.detail.data_status?.freshness, "PENDING")) }]} /><ExtendedDataPanel market={market} data={data} /></section></div>;
}

function factorLabel(value: unknown, language: UiLanguage): string {
  const raw = String(value ?? "").trim();
  const labels: Record<string, [string, string]> = {
    ema8_9_reclaim: ["EMA8/9 转强", "EMA8/9 reclaim"],
    ema20_slope: ["EMA20 斜率", "EMA20 slope"],
    relative_strength: ["相对强弱", "Relative strength"],
    relative_strength_acceleration: ["相对强弱加速度", "Relative-strength acceleration"],
    relative_volume: ["相对成交量", "Relative volume"],
    atr_compression: ["波动收缩", "ATR compression"],
    breakout_distance: ["突破距离", "Breakout distance"],
    price_above_ema20: ["价格站上 EMA20", "Price above EMA20"],
    price_above_ema50: ["价格站上 EMA50", "Price above EMA50"],
    price_above_ema200: ["价格站上 EMA200", "Price above EMA200"],
  };
  if (labels[raw]) return labels[raw][language === "zh" ? 0 : 1];
  return backendText(raw.replace(/[_-]+/g, " "), language) || (language === "zh" ? "已注册因素" : "Registered factor");
}

function ExtendedDataPanel({ market, data }: { market: Market; data: DomainData }) {
  const { language, t, statusLabel, humanizeText } = useWorkspaceI18n();
  if (market === "stocks") {
    const factorRows = extractRows(data.research, ["factors", "items", "contributions", "factor_snapshot"]).slice(0, 8);
    const early = data.validation;
    const runtime = data.runtime;
    return <div className="extended-data"><div className="subsection-head"><span className="eyebrow">{t("Research evidence")}</span><span className="muted">{t("Registered factors")}</span></div><div className="data-summary-grid"><div><span>{t("Structure stage")}</span><strong>{statusLabel(textValue(early.strategy_stage, early.stage, early.status, "PENDING"))}</strong></div><div><span>{t("Live status")}</span><strong>{statusLabel(textValue(runtime.trust, runtime.data_quality, runtime.provider_status, "PENDING"))}</strong></div><div><span>{t("Data time")}</span><strong className="mono">{textValue(runtime.quote?.time, runtime.as_of_time, data.detail.as_of_time, "-").slice(0, 19)}</strong></div></div>{factorRows.length ? <div className="factor-list">{factorRows.map((row, index) => <div className="factor-row" key={`${textValue(row.id, row.factor_id, row.name, index)}`}><span>{factorLabel(textValue(row.label, row.factor_id, row.id, row.name), language)}</span><b>{formatNumber(row.contribution, 2)}</b><small>{statusLabel(textValue(row.status, row.missing, row.source, "RECORDED"))}</small></div>)}</div> : <EmptyState title={t("No factor snapshot")} detail={t("Registered factors and their contributions appear after analysis.")} />}</div>;
  }
  const posterior = isRecord(data.research.item) && isRecord(data.research.item.posterior) ? data.research.item.posterior : {};
  const safetyRows = extractRows(data.safety, ["items", "snapshots"]).slice(0, 6);
  const holder = isRecord(data.holders.item) ? data.holders.item : data.holders;
  const coverage = data.coverage;
  const holderCount = numberValue(holder.holder_count, holder.holders, holder.count);
  return <div className="extended-data"><div className="subsection-head"><span className="eyebrow">{t("Evidence summary")}</span><span className="muted">{t("Read-only data")}</span></div><div className="data-summary-grid"><div><span>{t("Market regime")}</span><strong>{statusLabel(textValue(data.context.regime, data.context.status, "PENDING"))}</strong></div><div><span>{t("Regime estimate")}</span><strong>{statusLabel(textValue(posterior.most_likely_state, posterior.evidence_status, "NOT_COLLECTED"))}</strong></div><div><span>{t("Coverage")}</span><strong>{textValue(coverage.asset_count, coverage.status, t("Pending"))}</strong></div><div><span>{t("Positive return probability")}</span><strong>{posterior.positive_return_probability == null ? t("No data") : formatPercent(posterior.positive_return_probability)}</strong></div><div><span>{t("Holder structure")}</span><strong>{holderCount === null ? statusLabel(textValue(holder.status, "NOT_COLLECTED")) : compactValue(holderCount)}</strong></div></div>{safetyRows.length ? <div className="factor-list">{safetyRows.map((row, index) => <div className="factor-row" key={`${textValue(row.security_snapshot_id, row.asset_id, index)}`}><span>{textValue(row.asset_id, row.symbol, t("Token"))}</span><b>{statusLabel(textValue(row.status, row.risk_level, "PENDING"))}</b><small>{humanizeText(textValue(row.reason, row.message, row.eval_allowed === false ? t("Safety conditions are not met") : t("Safety snapshot recorded")))}</small></div>)}</div> : <EmptyState title={t("No safety snapshot")} detail={t("Crypto remains observation-only until safety data is confirmed.")} />}</div>;
}

function DiscoveryDetailPanel({ market, data }: { market: Market; data: DomainData }) {
  const { t, statusLabel } = useWorkspaceI18n();
  if (market === "stocks") {
    const themes = extractRows(data.discovery, ["items", "themes", "ranking"]).slice(0, 8);
    return <section className="work-surface"><div className="surface-head"><div><span className="eyebrow">{t("Themes and coverage")}</span><h3>{t("Research scope")}</h3></div><BarChart3 size={18} className="surface-icon" /></div>{themes.length ? <div className="rank-list">{themes.map((row, index) => <div className="rank-row" key={`${textValue(row.id, row.theme, row.name, index)}`}><span className="rank-number">{String(index + 1).padStart(2, "0")}</span><strong>{textValue(row.name, row.theme, row.symbol, t("Theme"))}</strong><span>{statusLabel(textValue(row.status, row.data_status, "RECORDED"))}</span><b>{formatNumber(row.score, 1)}</b></div>)}</div> : <EmptyState title={t("No theme snapshot")} detail={t("Theme ranking appears after data refresh.")} />}</section>;
  }
  const pools = extractRows(data.discovery, ["items", "pairs", "snapshots"]).slice(0, 8);
  return <section className="work-surface"><div className="surface-head"><div><span className="eyebrow">{t("Pool discovery")}</span><h3>{t("New DEX / MEME pools")}</h3></div><Radar size={18} className="surface-icon" /></div>{pools.length ? <div className="discovery-list">{pools.map((row, index) => <div className="discovery-row" key={`${textValue(row.snapshot_id, row.pair_address, row.asset_id, index)}`}><div><strong>{textValue(row.base_symbol, row.symbol, row.asset_id, t("Unknown token"))}/{textValue(row.quote_symbol, "USDC")}</strong><small>{textValue(row.chain_id, row.chain, t("Unknown chain"))} · {textValue(row.dex_id, row.dex, t("Unknown venue"))}</small></div><span>{t("Liquidity")} {compactValue(row.liquidity_usd)}</span><span>5m {compactValue(row.volume_5m_usd)}</span><StatusChip label={statusLabel(textValue(row.trust_status, row.status, "PENDING"))} tone={statusTone(row.trust_status ?? row.status)} /></div>)}</div> : <EmptyState title={t("No new pool snapshot")} detail={t("Enable a public DEX provider to display discoveries.")} />}</section>;
}

function PlanEvidencePanel({ market, data }: { market: Market; data: DomainData }) {
  const { t, statusLabel } = useWorkspaceI18n();
  if (market === "stocks") {
    const readiness = data.safety;
    const validation = data.simulation;
    return <div className="plan-audit"><MetricStrip items={[{ label: t("Trade eligibility"), value: statusLabel(textValue(readiness.decision, readiness.status, "PENDING")) }, { label: t("Historical validation"), value: statusLabel(textValue(validation.status, validation.gate_status, "PENDING")) }, { label: t("Live status"), value: statusLabel(textValue(data.runtime.trust, data.runtime.data_quality, "PENDING")) }, { label: t("Notifications"), value: statusLabel(textValue(data.notifications.status, data.notifications.enabled ? "available" : "disabled", "PENDING")) }]} /></div>;
  }
  const posterior = isRecord(data.research.item) && isRecord(data.research.item.posterior) ? data.research.item.posterior : {};
  const horizons = isRecord(data.simulation.item) && isRecord(data.simulation.item.horizons) ? data.simulation.item.horizons : {};
  const horizon = isRecord(horizons["24h"]) ? horizons["24h"] : (isRecord(horizons["24H"]) ? horizons["24H"] : {});
  const evaluations = extractRows(data.evaluations, ["items", "evaluations"]).slice(0, 4);
  return <div className="plan-audit"><MetricStrip items={[{ label: t("Final evaluation"), value: statusLabel(textValue(evaluations[0]?.decision, evaluations[0]?.evaluation_status, "PENDING")) }, { label: t("Market regime"), value: statusLabel(textValue(posterior.most_likely_state, data.context.regime, "PENDING")) }, { label: t("Target probability"), value: horizon.p_target_before_stop == null ? t("No data") : formatPercent(horizon.p_target_before_stop) }, { label: t("Simulation status"), value: statusLabel(textValue(data.simulation.item?.status, data.simulation.status, "NOT_COLLECTED")) }]} /><div className="audit-note">{t("Crypto results require market, liquidity, safety, and evaluation evidence. Missing evidence remains observation-only.")}</div></div>;
}

function PlanView({ market, data, rows, symbol }: { market: Market; data: DomainData; rows: Json[]; symbol: string }) {
  const { t, actionLabel, statusLabel, humanizeText } = useWorkspaceI18n();
  const selected = rows.find((row) => textValue(row.symbol, row.ticker, row.asset_id).toUpperCase().includes(symbol.replace("USDT", ""))) ?? data.detail;
  const blockers = extractRows(selected, ["blockers", "warnings", "reasons", "conditions"]);
  const planFields = [
    [t("Decision"), actionLabel(textValue(selected.action, selected.decision, selected.status))],
    [t("Entry"), textValue(selected.entry_zone, selected.entry, t("To be completed"))],
    [t("Stop"), textValue(selected.stop_zone, selected.stop, t("To be completed"))],
    [t("Target"), textValue(selected.target_zone, selected.target, t("To be completed"))],
    [t("Valid until"), textValue(selected.expires_at, selected.valid_until, t("To be completed"))],
    [t("Review status"), statusLabel(textValue(selected.evaluation_status, selected.evidence_grade, market === "stocks" ? t("Manual review") : t("Awaiting final evaluation")))],
  ];
  return <div className="stack">
    <section className="decision-band plan-band"><div className="decision-copy"><span className="eyebrow">{t("Plan")} · {symbol}</span><h2>{market === "stocks" ? t("Manual review plan") : t("Simulation and observation plan")}</h2><p>{market === "stocks" ? t("Review the conclusion, price levels, and invalidation conditions separately.") : t("Crypto plans require final evaluation; failed plans remain observation-only.")}</p></div><StatusChip label={actionLabel(textValue(selected.action, selected.decision, selected.status))} tone={statusTone(selected.action ?? selected.decision ?? selected.status)} /></section>
    {market === "crypto" ? <CandidatePanel /> : null}
    <section className="work-surface"><div className="surface-head"><div><span className="eyebrow">{t("Plan details")}</span><h3>{t("Confirm these items first")}</h3></div><ShieldCheck size={18} className="surface-icon" /></div><div className="plan-grid">{planFields.map(([label, value]) => <div className="plan-field" key={label}><span>{label}</span><strong>{value}</strong></div>)}</div><div className="plan-evidence"><span className="eyebrow">{t("Blocks and reminders")}</span>{blockers.length ? blockers.slice(0, 6).map((item, index) => <div className="evidence-row" key={index}><AlertTriangle size={14} /><span>{humanizeText(textValue(item.message, item.reason, item.code, item.label))}</span></div>) : <div className="evidence-row"><ShieldCheck size={14} /><span>{t("No additional blockers; manually confirm the current data status.")}</span></div>}</div><PlanEvidencePanel market={market} data={data} /></section>
  </div>;
}

function ResearchView({ market, data, symbol, onOpen }: { market: Market; data: DomainData; symbol: string; onOpen: () => void }) {
  const { t, statusLabel } = useWorkspaceI18n();
  return <div className="stack"><section className="research-intro"><div><span className="eyebrow">{t("Research")}</span><h2>{symbol} {t("Evidence workspace")}</h2><p>{market === "stocks" ? t("Review trend, volume, relative strength, and data status together.") : t("Review market regime, liquidity, safety, and historical evidence together.")}</p></div><button className="primary-button" onClick={onOpen}><PanelRight size={16} />{t("Open research")}</button></section><div className="two-column"><section className="work-surface"><div className="surface-head"><div><span className="eyebrow">{t("Deterministic evidence")}</span><h3>{t("Current explainable factors")}</h3></div><LineChart size={18} className="surface-icon" /></div><EvidenceList detail={data.detail} market={market} /><ExtendedDataPanel market={market} data={data} /></section><section className="work-surface"><div className="surface-head"><div><span className="eyebrow">{t("Data and versions")}</span><h3>{t("Research context")}</h3></div><FileText size={18} className="surface-icon" /></div><div className="context-list"><div><span>{t("Data source")}</span><strong>{statusLabel(textValue(data.detail.source, data.detail.data_status?.source, market === "stocks" ? "Longbridge" : "PUBLIC_CEX"))}</strong></div><div><span>{t("Market regime")}</span><strong>{statusLabel(textValue(data.context.regime, data.market.status, "PENDING"))}</strong></div><div><span>{t("Snapshot time")}</span><strong className="mono">{textValue(data.detail.as_of_time, data.detail.generated_at, "-")}</strong></div><div><span>{t("Research boundary")}</span><strong>{t("Read-only research")}</strong></div></div><PlanEvidencePanel market={market} data={data} /></section></div></div>;
}

function JournalView({ market, data, alerts, onAcknowledge }: { market: Market; data: DomainData; alerts: Json[]; onAcknowledge: (row: Json) => Promise<void> }) {
  const { t, statusLabel, humanizeText } = useWorkspaceI18n();
  const journalRows = extractRows(data.journal, ["items", "entries", "events", "ledger"]);
  const rows = journalRows.length ? journalRows : alerts;
  return <div className="stack"><section className="work-surface"><div className="surface-head"><div><span className="eyebrow">{t("Logs and alerts")}</span><h2>{market === "stocks" ? t("Stock review records") : t("Crypto evaluation and observation records")}</h2><p className="surface-lede">{t("Status changes and manual-review context are stored here; observations are not live performance.")}</p></div><Bell size={18} className="surface-icon" /></div>{rows.length ? <div className="event-list">{rows.slice(0, 20).map((row, index) => { const id = textValue(row.id, row.alert_id, row.notification_id, row.event_id); const alertId = textValue(row.alert_id, row.notification_id); const acknowledged = Boolean(row.acknowledged_at) || ["acknowledged", "read"].includes(String(row.status ?? "").toLowerCase()); return <div className="event-row" key={`${id}-${index}`}><div className="event-icon"><Bell size={14} /></div><div className="event-copy"><strong>{textValue(row.title, row.symbol, row.event_type, row.action)}</strong><span>{humanizeText(textValue(row.message, row.body, row.reason, row.note, "RECORDED"))}</span></div><time>{textValue(row.created_at, row.occurred_at, row.as_of_time).slice(0, 19)}</time><div className="event-actions"><StatusChip label={acknowledged ? t("Acknowledged") : statusLabel(textValue(row.severity, row.status, row.delivery_status))} tone={acknowledged ? "positive" : statusTone(row.severity ?? row.status)} />{!acknowledged && alertId !== "-" ? <button className="event-ack" type="button" onClick={() => void onAcknowledge(row)} title={t("Acknowledge this alert")}>{t("Acknowledge")}</button> : null}</div></div>; })}</div> : <EmptyState title={t("No log entries")} detail={t("New alerts, observations, and manual reviews appear here.")} />}</section><section className="work-surface compact-surface"><div className="surface-head"><div><span className="eyebrow">{t("Operating boundary")}</span><h3>{t("Current permissions")}</h3></div><ShieldCheck size={18} className="surface-icon" /></div><MetricStrip items={[{ label: t("Market data access"), value: t("Allowed") }, { label: t("Research and simulation"), value: t("Allowed") }, { label: t("Alert stream"), value: statusLabel(textValue(data.runtime.status, data.notifications.status, "PENDING")) }, { label: t("Accounts, wallets, and orders"), value: t("Blocked"), tone: "negative" }]} /></section></div>;
}

function ReviewView({ market, data, symbol, alerts, onOpen, onAcknowledge }: { market: Market; data: DomainData; symbol: string; alerts: Json[]; onOpen: () => void; onAcknowledge: (row: Json) => Promise<void> }) {
  const { t } = useWorkspaceI18n();
  const [section, setSection] = useState<"evidence" | "journal">("evidence");
  return <div className="stack"><div className="section-switch" role="tablist" aria-label={t("Review content")}><button type="button" role="tab" aria-selected={section === "evidence"} className={section === "evidence" ? "active" : ""} onClick={() => setSection("evidence")}><LineChart size={15} />{t("Evidence")}</button><button type="button" role="tab" aria-selected={section === "journal"} className={section === "journal" ? "active" : ""} onClick={() => setSection("journal")}><BookOpen size={15} />{t("Logs and alerts")}{alerts.length ? <b>{alerts.length}</b> : null}</button></div>{section === "evidence" ? <ResearchView market={market} data={data} symbol={symbol} onOpen={onOpen} /> : <JournalView market={market} data={data} alerts={alerts} onAcknowledge={onAcknowledge} />}</div>;
}

function SettingsView({ market, data, language, theme, onLanguageChange, onThemeChange }: { market: Market; data: DomainData; language: UiLanguage; theme: UiTheme; onLanguageChange: (language: UiLanguage) => void; onThemeChange: (theme: UiTheme) => void }) {
  const { t, statusLabel } = useWorkspaceI18n();
  const providerRows = extractRows(data.market, ["providers", "items", "sources"]);
  const providerStatus = textValue(data.market.status, data.health.status, "PENDING");
  const coverageStatus = textValue(data.coverage.status, data.coverage.coverage_status, data.coverage.asset_count, "PENDING");
  const notificationStatus = textValue(data.notifications.status, data.notifications.enabled ? "available" : "disabled", "PENDING");
  return <div className="settings-layout"><section className="settings-section"><div className="surface-head"><div><span className="eyebrow">{t("Display preferences")}</span><h2>{t("Appearance")}</h2><p className="surface-lede">{t("Preferences stay in this browser and do not affect data, strategies, or risk controls.")}</p></div><Settings size={18} className="surface-icon" /></div><div className="settings-lines preference-lines"><div><div><span>{t("Language")}</span><small>{t("Navigation and unified workspace")}</small></div><div className="preference-control" role="group" aria-label={t("Language")}><button type="button" className={language === "zh" ? "active" : ""} onClick={() => onLanguageChange("zh")}><Languages size={14} />中文</button><button type="button" className={language === "en" ? "active" : ""} onClick={() => onLanguageChange("en")}>English</button></div></div><div><div><span>{t("Appearance")}</span><small>{t("Dark and light themes")}</small></div><div className="preference-control" role="group" aria-label={t("Appearance")}><button type="button" className={theme === "dark" ? "active" : ""} onClick={() => onThemeChange("dark")}><Moon size={14} />{t("Dark")}</button><button type="button" className={theme === "light" ? "active" : ""} onClick={() => onThemeChange("light")}><Sun size={14} />{t("Light")}</button></div></div></div><div className="surface-head settings-subhead"><div><span className="eyebrow">{t("Runtime")}</span><h3>{t("Data and notifications")}</h3><p className="surface-lede">{t("Daily pages show decisions; operational diagnostics stay here.")}</p></div></div><div className="settings-lines"><div><span>{t("Workspace")}</span><strong>{market === "stocks" ? t("US stock research") : t("Crypto research")}</strong></div><div><span>{t("Market data")}</span><StatusChip label={statusLabel(providerStatus)} tone={statusTone(providerStatus)} /></div><div><span>{t("Coverage")}</span><strong>{statusLabel(coverageStatus)}</strong></div><div><span>{t("Notifications")}</span><StatusChip label={statusLabel(notificationStatus)} tone={statusTone(notificationStatus)} /></div><div><span>{t("Operating boundary")}</span><strong>{t("Research, simulation, and manual review")}</strong></div><div><span>{t("Accounts and orders")}</span><strong className="danger-text">{t("Not available")}</strong></div></div></section><section className="settings-section"><div className="surface-head"><div><span className="eyebrow">{t("Service status")}</span><h3>{t("Providers and versions")}</h3></div><Database size={18} className="surface-icon" /></div>{providerRows.length ? <div className="provider-list">{providerRows.slice(0, 12).map((row, index) => <div className="provider-row" key={`${textValue(row.name, row.provider, row.source, index)}`}><div><strong>{textValue(row.name, row.provider, row.source, t("Source"))}</strong><small>{textValue(row.last_success_at, row.updated_at, row.as_of, t("No update time"))}</small></div><StatusChip label={statusLabel(textValue(row.status, row.health, row.freshness, "PENDING"))} tone={statusTone(row.status ?? row.health ?? row.freshness)} /></div>)}</div> : <div className="settings-lines"><div><span>{t("Application version")}</span><strong className="mono">{textValue(data.health.app_version, data.health.version, "-")}</strong></div><div><span>{t("Schema version")}</span><strong className="mono">{textValue(data.health.schema_version, data.health.database?.schema_version, "-")}</strong></div><div><span>{t("Runtime status")}</span><strong>{statusLabel(textValue(data.runtime.status, data.runtime.supervisor_status, "PENDING"))}</strong></div></div>}<details className="diagnostic-details"><summary>{t("Full diagnostics")}</summary><pre>{JSON.stringify({ health: data.health, market: data.market, runtime: data.runtime, coverage: data.coverage, notifications: data.notifications }, null, 2)}</pre></details></section></div>;
}

export default function App() {
  const [authState, setAuthState] = useState<AuthState>("checking");
  const [session, setSession] = useState<Session | null>(null);
  const [initialLanguage] = useState<UiLanguage>(() => storedPreference<UiLanguage>("kquant-unified:language", "zh"));
  useEffect(() => { document.documentElement.lang = initialLanguage === "zh" ? "zh-CN" : "en"; }, [initialLanguage]);
  const refreshSession = async () => {
    try {
      const payload = await getJson<Session>("/api/auth/session");
      setSession(payload);
      setAuthState(!payload.authentication_required || payload.authenticated ? "ready" : "login");
    } catch {
      setSession(null);
      setAuthState("error");
    }
  };
  useEffect(() => { void refreshSession(); }, []);
  const logout = async () => {
    await fetch("/api/auth/logout", { method: "POST", credentials: "same-origin" });
    setSession(null);
    setAuthState("login");
  };
  if (authState === "checking") return <div className="auth-loading"><div className="brand-mark">KQ</div><span>{translate(initialLanguage, "Opening KQUANT")}</span></div>;
  if (authState !== "ready") return <LoginScreen mode={authState} language={initialLanguage} onAuthenticated={refreshSession} />;
  return <Workspace onLogout={logout} />;
}
