import { FormEvent, KeyboardEvent, MouseEvent, useEffect, useMemo, useState } from "react";
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
  LogOut,
  Menu,
  Minus,
  PanelRight,
  Radar,
  RefreshCw,
  Search,
  Settings,
  ShieldCheck,
  Sparkles,
  Trash2,
  TrendingUp,
  Undo2,
  X,
} from "lucide-react";

type Json = Record<string, any>;
type Market = "stocks" | "crypto";
type ViewName = "today" | "discover" | "chart" | "plan" | "research" | "journal";
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

const VIEWS: Array<{ id: ViewName; label: string; icon: typeof LayoutDashboard }> = [
  { id: "today", label: "今日", icon: LayoutDashboard },
  { id: "discover", label: "发现", icon: Radar },
  { id: "chart", label: "图表", icon: ChartCandlestick },
  { id: "plan", label: "计划", icon: FileText },
  { id: "research", label: "研究", icon: BookOpen },
  { id: "journal", label: "日志", icon: Database },
];

const ACTION_LABELS: Record<string, string> = {
  BUY: "买入复核",
  BUY_REVIEW: "买入复核",
  WATCH: "观察",
  EARLY_WATCH: "早期观察",
  ARMED: "等待触发",
  PASS: "暂不关注",
  AVOID: "暂不关注",
  AI_AVOID: "暂不关注",
  PAPER_REVIEW: "模拟复核",
  SHADOW_ELIGIBLE: "观察记录",
  HOLD_CORE: "继续观察",
  ROLL_BUY: "滚仓复核",
  ROLL_ADD: "加仓复核",
  ROTATE_TO: "轮换复核",
  REDUCE: "减少风险",
  WAIT: "等待",
  EXIT_REVIEW: "退出复核",
  REJECTED: "已阻断",
  WATCH_ONLY: "仅观察",
  MONITORING: "观察中",
  TRIGGERED: "已触发",
  INVALIDATED: "已失效",
  EXPIRED: "已过期",
  INFO: "提示",
  ACTION: "需要复核",
  RISK: "风险",
  CRITICAL: "紧急",
  DATA_CAUTION: "数据需确认",
  DATA_BLOCKED: "数据不足",
  MARKET_CLOSED: "市场已收盘",
  STALE: "数据已过期",
  UNAVAILABLE: "暂不可用",
};

const STATUS_LABELS: Record<string, string> = {
  OK: "正常",
  AVAILABLE: "可用",
  LIVE: "实时",
  LIVE_QUOTE: "实时行情",
  LONG_BRIDGE_CANDLES: "Longbridge K 线",
  LONGBRIDGE_CANDLES: "Longbridge K 线",
  LONGBRIDGE: "Longbridge",
  MARKET_CLOSED: "市场已收盘",
  CLOSED: "已收盘",
  STALE: "数据已过期",
  STALE_LONG_BRIDGE_CACHE: "缓存已过期",
  STALE_LONGBRIDGE_CACHE: "缓存已过期",
  PARTIAL: "数据不完整",
  DATA_CAUTION: "数据需确认",
  DATA_BLOCKED: "数据不足",
  PROVIDER_UNAVAILABLE: "数据源不可用",
  UNAVAILABLE: "暂不可用",
  NOT_COLLECTED: "等待采集",
  DISABLED: "未启用",
  UNKNOWN: "未知",
  LIMITED: "证据有限",
  PASSED: "已通过",
  FAILED: "未通过",
  REJECTED: "未通过",
  CEX: "CEX 行情",
  CEX_DATA: "CEX 行情",
  PUBLIC_CEX: "公开行情",
  YAHOO_REFERENCE_ONLY: "参考数据",
  YAHOO_REFERENCE: "参考数据",
};

function actionLabel(value: unknown): string {
  const key = String(value ?? "").toUpperCase();
  return ACTION_LABELS[key] ?? (key ? "待复核" : "等待数据");
}

function statusLabel(value: unknown): string {
  const raw = String(value ?? "").trim();
  const key = raw.toUpperCase().replace(/[\s-]+/g, "_");
  if (STATUS_LABELS[key]) return STATUS_LABELS[key];
  if (ACTION_LABELS[key]) return ACTION_LABELS[key];
  if (key.includes("LONGBRIDGE")) return "Longbridge";
  if (key.includes("YAHOO")) return "参考数据";
  if (key.includes("CEX")) return "CEX 行情";
  if (key.includes("STALE")) return "数据已过期";
  if (key.includes("CAUTION")) return "数据需确认";
  if (key.includes("UNAVAILABLE")) return "暂不可用";
  return raw || "等待确认";
}

function humanizeText(value: unknown): string {
  const raw = String(value ?? "").trim();
  if (!raw) return "等待确认";
  return raw
    .replace(/AI_AVOID/gi, "暂不关注")
    .replace(/DATA_CAUTION/gi, "数据需确认")
    .replace(/DATA_BLOCKED/gi, "数据不足")
    .replace(/HARD[_ -]?VETO/gi, "关键条件未满足")
    .replace(/PAPER_REVIEW/gi, "模拟复核")
    .replace(/SHADOW_ELIGIBLE/gi, "观察记录")
    .replace(/WATCH_ONLY/gi, "仅观察")
    .replace(/HTTPError/gi, "研究服务暂时不可用")
    .replace(/EVAL/gi, "最终审核");
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
  return number === null ? "-" : number.toLocaleString("en-US", { maximumFractionDigits: digits });
}

function formatPercent(value: unknown): string {
  const number = numberValue(value);
  if (number === null) return "-";
  return `${(Math.abs(number) <= 1 ? number * 100 : number).toFixed(1)}%`;
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

function errorText(error: unknown): string {
  return error instanceof Error ? error.message : "服务暂时不可用";
}

async function getJson<T extends Json>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, { credentials: "same-origin", cache: "no-store", ...init });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(isRecord(body) && body.detail ? String(body.detail) : `请求失败（${response.status}）`);
  return body as T;
}

function viewFromUrl(): ViewName {
  const raw = new URLSearchParams(window.location.search).get("view");
  return VIEWS.some((item) => item.id === raw) ? (raw as ViewName) : "today";
}

function marketFromUrl(): Market {
  return new URLSearchParams(window.location.search).get("market") === "crypto" ? "crypto" : "stocks";
}

function LoginScreen({ mode, onAuthenticated }: { mode: AuthState; onAuthenticated: () => Promise<void> }) {
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
      if (!response.ok) throw new Error(body.detail || "邮箱或密码不正确");
      await onAuthenticated();
    } catch (error) {
      setMessage(errorText(error));
    } finally {
      setBusy(false);
    }
  };

  return (
    <main className="auth-shell">
      <section className="auth-panel" aria-labelledby="login-title">
        <div className="brand-mark large">KQ</div>
        <p className="eyebrow">KQUANT WORKSPACE</p>
        <h1 id="login-title">进入研究工作台</h1>
        <p className="auth-lede">股票与 Crypto 共用一个入口，行情、研究计划和日志仍按市场独立保存。</p>
        {mode === "error" ? <p className="form-error">统一入口暂时无法连接，请确认网关正在运行。</p> : null}
        <form className="auth-form" onSubmit={submit}>
          <label>邮箱<input type="email" autoComplete="username" value={email} onChange={(event) => setEmail(event.target.value)} required /></label>
          <label>密码<input type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} required /></label>
          {message ? <p className="form-error">{message}</p> : null}
          <button className="primary-button" type="submit" disabled={busy}>{busy ? "正在验证" : "进入工作台"}<ChevronRight size={16} /></button>
        </form>
        <p className="auth-note"><ShieldCheck size={15} /> 仅限研究、模拟与观察，不读取账户，不提交订单。</p>
      </section>
    </main>
  );
}

function StatusChip({ label, tone = "neutral" }: { label: string; tone?: "positive" | "caution" | "negative" | "info" | "neutral" }) {
  return <span className={`status-chip ${tone}`}><span className="status-dot" />{label}</span>;
}

function statusTone(value: unknown): "positive" | "caution" | "negative" | "info" | "neutral" {
  const raw = String(value ?? "").toLowerCase();
  if (["available", "live", "ok", "complete", "connected", "ready", "passed"].some((item) => raw.includes(item))) return "positive";
  if (["caution", "stale", "partial", "closed", "limited", "pending", "unknown", "需确认", "过期", "收盘", "有限", "等待"].some((item) => raw.includes(item))) return "caution";
  if (["unavailable", "failed", "blocked", "rejected", "error", "offline", "不可用", "不足", "未通过", "失效"].some((item) => raw.includes(item))) return "negative";
  if (["armed", "watch", "research"].some((item) => raw.includes(item))) return "info";
  return "neutral";
}

function LoadingLine({ label = "正在读取数据" }: { label?: string }) {
  return <div className="loading-line"><RefreshCw size={15} className="spin" />{label}</div>;
}

function EmptyState({ title, detail }: { title: string; detail: string }) {
  return <div className="empty-state"><CircleHelp size={19} /><strong>{title}</strong><span>{detail}</span></div>;
}

function MetricStrip({ items }: { items: Array<{ label: string; value: string; tone?: string }> }) {
  return <div className="metric-strip">{items.map((item) => <div className="metric" key={item.label}><span>{item.label}</span><strong className={item.tone ? `tone-${item.tone}` : ""}>{statusLabel(item.value)}</strong></div>)}</div>;
}

function EvidenceList({ detail, market }: { detail: Json; market: Market }) {
  const evidence = extractRows(detail.decision_evidence ?? detail.evidence ?? detail.supporting_factors, ["items", "supporting", "opposing", "factors"]);
  const fallback = market === "stocks"
    ? ["趋势、相对强弱和量价结构由系统按已收盘数据计算。", "实时数据和交易时段会影响人工复核资格。", "研究结论不等于下单指令。"]
    : ["市场状态、流动性和安全快照共同决定观察资格。", "形成中的行情不会直接升级为模拟计划。", "Crypto 计划必须经过最终审核层。"];
  return <div className="evidence-list">{(evidence.length ? evidence.slice(0, 5).map((item) => humanizeText(textValue(item.message, item.reason, item.label, item.factor, item.name))) : fallback).map((item, index) => <div className="evidence-row" key={`${item}-${index}`}><span className="evidence-mark">{index < 3 ? "•" : "—"}</span><span>{item}</span></div>)}</div>;
}

function OpportunityTable({ market, rows, onSelect }: { market: Market; rows: Json[]; onSelect: (symbol: string) => void }) {
  const visible = rows.slice(0, 12);
  return <div className="table-wrap">
    {visible.length ? <table><thead><tr><th>标的</th><th>结论</th><th>分数</th><th>状态</th><th>时间</th></tr></thead><tbody>{visible.map((row, index) => {
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
    })}</tbody></table> : <EmptyState title="暂无可展示候选" detail={market === "stocks" ? "先运行一次股票扫描或检查 Longbridge 数据。" : "等待 CEX 数据采集完成。"} />}
  </div>;
}

function PriceChart({ payload, market, symbol }: { payload: Json; market: Market; symbol: string }) {
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

  if (!candles.length) return <EmptyState title="暂无图表数据" detail="当前市场没有可用的已收盘 K 线。" />;
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
    <div className="chart-head"><div><span className="eyebrow">{market === "stocks" ? "Longbridge K线" : "CEX K线"}</span><h3>{symbol}</h3></div><div className="chart-last"><strong>{formatNumber(closes[closes.length - 1], 4)}</strong><span className={up ? "positive-text" : "negative-text"}>{up ? <ArrowUpRight size={15} /> : <ArrowDownRight size={15} />}{formatPercent(((closes[closes.length - 1] / closes[0]) - 1) * 100)}</span></div></div>
    <div className="chart-tools" role="toolbar" aria-label="手动画线工具">
      <button type="button" className={tool === "hline" ? "chart-tool active" : "chart-tool"} onClick={() => { setTool(tool === "hline" ? "none" : "hline"); setPendingPoint(null); }} title="点击图表添加水平线"><Minus size={15} />水平线</button>
      <button type="button" className={tool === "trend" ? "chart-tool active" : "chart-tool"} onClick={() => { setTool(tool === "trend" ? "none" : "trend"); setPendingPoint(null); }} title="点击图表两点添加趋势线"><TrendingUp size={15} />趋势线</button>
      <select value={label} onChange={(event) => setLabel(event.target.value)} aria-label="线条标签"><option>Line</option><option>Entry</option><option>Stop</option><option>Target</option><option>Alert</option></select>
      <label className="color-picker" title="选择线条颜色"><input type="color" value={color} onChange={(event) => setColor(event.target.value)} aria-label="线条颜色" /></label>
      <button type="button" className="chart-tool" onClick={() => { setDrawings((current) => current.slice(0, -1)); setPendingPoint(null); }} disabled={!drawings.length} title="撤销最后一条线"><Undo2 size={15} />撤销</button>
      <button type="button" className="chart-tool" onClick={() => { setDrawings([]); setPendingPoint(null); setTool("none"); }} disabled={!drawings.length && !pendingPoint} title="清除当前图表的所有标注"><Trash2 size={15} />清除</button>
      <span className="chart-tool-hint">{tool === "hline" ? "点击一次放置水平线" : tool === "trend" ? (pendingPoint ? "再点击一次完成趋势线" : "点击两个点连接趋势线") : "线条只在你点击工具后绘制"}</span>
    </div>
    <svg className="price-chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`${symbol} 价格走势与手动画线`} preserveAspectRatio="none" onClick={handleChartClick}>
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
    <div className="chart-foot"><span>{candles.length} 根已收盘 K 线 · EMA20 / EMA50 / EMA200</span><span>{textValue(candles[0].time).slice(0, 16)} → {textValue(candles[candles.length - 1].time).slice(0, 16)}</span></div>
  </div>;
}

function ResearchDrawer({ market, symbol, messages, onMessagesChange, onClose, onSubmit }: { market: Market; symbol: string; messages: ResearchMessage[]; onMessagesChange: (update: (current: ResearchMessage[]) => ResearchMessage[]) => void; onClose: () => void; onSubmit: (question: string) => Promise<string> }) {
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
      onMessagesChange((items) => [...items, { role: "system", text: errorText(error) }]);
    } finally {
      setBusy(false);
    }
  };
  const prompts = market === "stocks" ? ["这只股票的主要风险是什么？", "哪些条件会让结论转强？", "帮我复核入场区和失效条件。"] : ["当前市场状态如何影响这个币？", "有哪些流动性和安全风险？", "什么条件下才值得进入模拟观察？"];
  return <aside className="research-drawer" aria-label="深度研究">
    <div className="drawer-head"><div><span className="eyebrow">深度研究</span><h2>{symbol}</h2></div><button className="icon-button" onClick={onClose} title="关闭研究栏"><X size={18} /></button></div>
    <div className="drawer-context"><StatusChip label={market === "stocks" ? "股票研究" : "Crypto 研究"} tone="info" /><span>当前标的：{symbol}</span></div>
    <div className="drawer-messages">{messages.length ? messages.map((message, index) => <div className={`drawer-message ${message.role}`} key={`${message.role}-${index}`}>{message.text}</div>) : <div className="drawer-empty"><PanelRight size={22} /><strong>把问题放在这里</strong><span>研究栏会随当前标的切换，回答与结论分开保存。</span></div>}</div>
    <div className="quick-prompts">{prompts.map((prompt) => <button key={prompt} className="text-button" onClick={() => setQuestion(prompt)}>{prompt}</button>)}</div>
    <form className="research-form" onSubmit={submit}><textarea value={question} onChange={(event) => setQuestion(event.target.value)} placeholder="询问风险、走势、入场条件或需要复核的证据…" rows={3} /><button className="primary-button" disabled={busy || !question.trim()}>{busy ? "整理中" : "开始研究"}<ChevronRight size={16} /></button></form>
  </aside>;
}

function Workspace({ onLogout }: { onLogout: () => Promise<void> }) {
  const [market, setMarket] = useState<Market>(marketFromUrl);
  const [view, setView] = useState<ViewName>(viewFromUrl);
  const [symbol, setSymbol] = useState(() => marketFromUrl() === "crypto" ? "BTCUSDT" : "NVDA");
  const [search, setSearch] = useState("");
  const [data, setData] = useState<DomainData>(emptyDomainData);
  const [loading, setLoading] = useState(true);
  const [message, setMessage] = useState("");
  const [researchOpen, setResearchOpen] = useState(false);
  const [researchMessagesByKey, setResearchMessagesByKey] = useState<Record<string, ResearchMessage[]>>({});
  const [mobileNavOpen, setMobileNavOpen] = useState(false);
  const [liveAlerts, setLiveAlerts] = useState<Json[]>([]);
  const [streamStatus, setStreamStatus] = useState<"connecting" | "connected" | "offline">("connecting");

  const loadMarket = async (nextMarket: Market, nextSymbol: string) => {
    setLoading(true);
    setMessage("");
    const encoded = encodeURIComponent(nextSymbol);
    setData(emptyDomainData());
    const calls: Record<keyof DomainData, string> = nextMarket === "stocks" ? {
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
    } : {
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
    const entries = await Promise.all(Object.entries(calls).map(async ([key, path]) => {
      try { return [key, await getJson<Json>(path)] as const; } catch (error) { return [key, { status: "unavailable", error: errorText(error) }] as const; }
    }));
    const next = Object.fromEntries(entries) as DomainData;
    setData(next);
    const failures = entries.filter(([, value]) => value.status === "unavailable");
    if (failures.length === entries.length) setMessage("当前市场暂时没有可用数据，请检查对应后端。");
    setLoading(false);
  };

  useEffect(() => { void loadMarket(market, symbol); }, [market, symbol]);
  useEffect(() => {
    const source = new EventSource("/api/alerts/stream");
    const handleReady = () => setStreamStatus("connected");
    const handleAlert = (event: Event) => {
      try {
        const outer = JSON.parse((event as MessageEvent).data) as Json;
        const payload = typeof outer.payload === "string" ? JSON.parse(outer.payload) as Json : (outer.payload ?? outer);
        const domain = textValue(outer.domain, payload.market, payload.domain);
        const row = { ...payload, market: domain };
        const key = textValue(row.id, row.alert_id, row.notification_id, row.event_id, JSON.stringify(row).slice(0, 80));
        setLiveAlerts((current) => [row, ...current.filter((item) => textValue(item.id, item.alert_id, item.notification_id, item.event_id, JSON.stringify(item).slice(0, 80)) !== key)].slice(0, 50));
      } catch {
        // A malformed upstream event must not break the unified workspace stream.
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
  }, []);
  useEffect(() => {
    const url = new URL(window.location.href);
    url.searchParams.set("market", market);
    url.searchParams.set("view", view);
    window.history.replaceState({}, "", url);
  }, [market, view]);

  const rows = useMemo(() => {
    const keys = market === "stocks" ? ["signals", "items", "daily_candidates", "buy_setups", "watch", "rows"] : ["items", "instructions", "evaluations", "rolls"];
    return extractRows(data.opportunities, keys);
  }, [data.opportunities, market]);
  const alertRows = useMemo(() => {
    const stored: Json[] = extractRows(data.alerts, ["items", "alerts", "events"]).map((row): Json => ({ ...row, market }));
    const current: Json[] = liveAlerts.filter((row): row is Json => !row.market || String(row.market).toLowerCase() === market);
    const unique = new Map<string, Json>();
    const merged: Json[] = [...current, ...stored];
    for (const row of merged) {
      const key = textValue(row.id, row.alert_id, row.notification_id, row.event_id, JSON.stringify(row).slice(0, 80));
      if (!unique.has(key)) unique.set(key, row);
    }
    return [...unique.values()];
  }, [data.alerts, liveAlerts, market]);
  const healthStatus = textValue(data.health.status, data.health.providers ? "available" : "unavailable");
  const marketStatus = market === "stocks" ? statusLabel(textValue(data.market.status, data.market.source, data.market.freshness)) : statusLabel(textValue(data.context.regime, data.market.status));

  const changeView = (nextView: ViewName) => { setView(nextView); setMobileNavOpen(false); };
  const changeMarket = (nextMarket: Market) => {
    if (nextMarket === market) return;
    setMarket(nextMarket);
    setSymbol(nextMarket === "stocks" ? "NVDA" : "BTCUSDT");
    setView("today");
    setLiveAlerts((current) => current.filter((row) => String(row.market).toLowerCase() === nextMarket));
  };
  const selectSymbol = (next: string) => {
    const normalized = next.trim().toUpperCase();
    if (!normalized) return;
    setSymbol(normalized);
    setView("chart");
  };
  const submitSearch = (event: FormEvent) => { event.preventDefault(); selectSymbol(search); setSearch(""); };
  const onSearchKey = (event: KeyboardEvent<HTMLInputElement>) => { if (event.key === "Enter") { event.preventDefault(); selectSymbol(search); setSearch(""); } };
  const submitResearch = async (question: string) => {
    if (market === "crypto") return "Crypto 研究栏当前使用市场状态、流动性、安全和最终审核结果作为上下文；请在计划页查看完整证据。";
    const response = await getJson<Json>("/api/stocks/research-chat", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ symbol, profile: "tactical_1w_v1", question, language: "zh" }) });
    return textValue(response.answer, response.message, response.summary, "研究服务暂时没有返回内容。");
  };

  const researchKey = `${market}:${symbol}`;

  const acknowledgeAlert = async (row: Json) => {
    const id = textValue(row.id, row.alert_id, row.notification_id, row.event_id);
    if (id === "-") return;
    const path = market === "stocks" ? `/api/stocks/alerts/${encodeURIComponent(id)}/ack` : `/api/crypto/alerts/${encodeURIComponent(id)}/ack`;
    try {
      await getJson<Json>(path, { method: "POST" });
      setLiveAlerts((current) => current.map((item) => textValue(item.id, item.alert_id, item.notification_id, item.event_id) === id ? { ...item, acknowledged_at: new Date().toISOString(), status: "acknowledged" } : item));
      setData((current) => ({ ...current, alerts: { ...current.alerts, items: extractRows(current.alerts, ["items", "alerts", "events"]).map((item) => textValue(item.id, item.alert_id, item.notification_id, item.event_id) === id ? { ...item, acknowledged_at: new Date().toISOString(), status: "acknowledged" } : item) } }));
    } catch (error) {
      setMessage(errorText(error));
    }
  };

  return <div className={`workspace-shell ${researchOpen ? "research-open" : ""}`}>
    <header className="workspace-topbar">
      <div className="brand-lockup"><div className="brand-mark">KQ</div><div><strong>KQUANT</strong><span>统一研究工作台</span></div></div>
      <form className="global-search" onSubmit={submitSearch}><Search size={17} /><input value={search} onChange={(event) => setSearch(event.target.value)} onKeyDown={onSearchKey} placeholder={market === "stocks" ? "搜索股票、主题或代码" : "搜索 BTC、ETH、SOL 或代币"} aria-label="搜索标的" /><kbd>Enter</kbd></form>
      <div className="topbar-actions"><div className="market-switch" role="tablist" aria-label="市场切换"><button className={market === "stocks" ? "active" : ""} onClick={() => changeMarket("stocks")} type="button">股票</button><button className={market === "crypto" ? "active" : ""} onClick={() => changeMarket("crypto")} type="button">Crypto</button></div><StatusChip label={healthStatus === "available" || healthStatus === "ok" ? "服务正常" : "待连接"} tone={statusTone(healthStatus)} /><button className="icon-button alert-button" onClick={() => changeView("journal")} title="打开预警与日志"><Bell size={17} />{alertRows.length ? <b>{Math.min(alertRows.length, 99)}</b> : null}</button><button className="icon-button" onClick={() => setResearchOpen((value) => !value)} title="打开深度研究"><PanelRight size={17} /></button><button className="icon-button desktop-only" onClick={() => void onLogout()} title="退出登录"><LogOut size={17} /></button><button className="icon-button mobile-menu" onClick={() => setMobileNavOpen((value) => !value)} title="打开导航"><Menu size={18} /></button></div>
    </header>
    <div className="workspace-layout">
      <aside className={`workspace-nav ${mobileNavOpen ? "open" : ""}`}><div className="nav-market-label"><span>{market === "stocks" ? "美股" : "Crypto"}</span><StatusChip label={marketStatus} tone={statusTone(marketStatus)} /></div><nav>{VIEWS.map((item) => { const Icon = item.icon; return <button key={item.id} className={view === item.id ? "active" : ""} onClick={() => changeView(item.id)}><Icon size={17} /><span>{item.label}</span>{item.id === "journal" && alertRows.length ? <b>{alertRows.length}</b> : null}</button>; })}</nav><div className="nav-footer"><button onClick={() => setResearchOpen(true)}><Sparkles size={16} /><span>深度研究</span></button><button onClick={() => changeView("journal")}><Settings size={16} /><span>系统状态</span></button><div className="boundary-note"><ShieldCheck size={15} /><span>只读研究</span></div></div></aside>
      <main className="workspace-content"><div className="content-head"><div><span className="eyebrow">{market === "stocks" ? "US EQUITIES" : "DIGITAL ASSETS"}</span><h1>{VIEWS.find((item) => item.id === view)?.label}</h1></div><div className="content-head-right"><span className={`stream-indicator ${streamStatus}`} title="统一预警流状态"><span className="status-dot" />{streamStatus === "connected" ? "预警在线" : streamStatus === "connecting" ? "连接预警" : "预警离线"}</span><span className="selected-symbol">{symbol}</span><button className="refresh-button" onClick={() => void loadMarket(market, symbol)}><RefreshCw size={15} />刷新</button></div></div>{message ? <div className="inline-notice"><AlertTriangle size={16} /><span>{message}</span></div> : null}{loading ? <LoadingLine /> : null}{view === "today" ? <TodayView market={market} data={data} rows={rows} alerts={alertRows} symbol={symbol} onSelect={selectSymbol} /> : null}{view === "discover" ? <DiscoverView market={market} data={data} rows={rows} onSelect={selectSymbol} /> : null}{view === "chart" ? <ChartView market={market} data={data} symbol={symbol} /> : null}{view === "plan" ? <PlanView market={market} data={data} rows={rows} symbol={symbol} /> : null}{view === "research" ? <ResearchView market={market} data={data} symbol={symbol} onOpen={() => setResearchOpen(true)} /> : null}{view === "journal" ? <JournalView market={market} data={data} alerts={alertRows} onAcknowledge={acknowledgeAlert} /> : null}</main>
    </div>
    {researchOpen ? <ResearchDrawer key={researchKey} market={market} symbol={symbol} messages={researchMessagesByKey[researchKey] ?? []} onMessagesChange={(update) => setResearchMessagesByKey((current) => ({ ...current, [researchKey]: update(current[researchKey] ?? []) }))} onClose={() => setResearchOpen(false)} onSubmit={submitResearch} /> : null}
  </div>;
}

function TodayView({ market, data, rows, alerts, symbol, onSelect }: { market: Market; data: DomainData; rows: Json[]; alerts: Json[]; symbol: string; onSelect: (symbol: string) => void }) {
  const detail = data.detail;
  const decision = textValue(detail.action, detail.decision, detail.stage, detail.strategy_stage);
  const price = numberValue(detail.price, detail.last, detail.features?.close, detail.quote?.last, detail.last_price);
   return <>
     <section className="decision-band"><div className="decision-copy"><span className="eyebrow">当前标的 · {symbol}</span><h2>{textValue(detail.company_name, detail.name, symbol)}</h2><p>{market === "stocks" ? "先看结构，再看数据是否允许人工复核。" : "先看市场状态、流动性和安全，再看是否进入模拟观察。"}</p><div className="decision-tags"><StatusChip label={actionLabel(decision)} tone={statusTone(decision)} /><StatusChip label={statusLabel(textValue(detail.data_status?.source, detail.source_status, market === "stocks" ? "Longbridge" : "CEX 数据"))} tone="info" /><StatusChip label={statusLabel(textValue(detail.data_status?.freshness, detail.trust, "等待更新"))} tone={statusTone(detail.data_status?.freshness ?? detail.trust)} /></div></div><div className="decision-number"><span>当前结论</span><strong>{actionLabel(decision)}</strong><small>{price === null ? "价格待更新" : formatNumber(price, 4)}</small></div></section>
     <MetricStrip items={market === "stocks" ? [{ label: "价格", value: price === null ? "-" : formatNumber(price) }, { label: "评分", value: formatNumber(detail.score, 1) }, { label: "数据状态", value: textValue(detail.data_status?.freshness, "待确认") }, { label: "入场条件", value: textValue(detail.entry_zone, detail.entry, "待复核") }] : [{ label: "价格", value: price === null ? "-" : formatNumber(price, 4) }, { label: "市场状态", value: statusLabel(textValue(data.context.regime, "待确认")) }, { label: "审核结果", value: actionLabel(textValue(detail.evaluation_status, detail.decision, "等待数据")) }, { label: "预警", value: String(alerts.length) }]} />
    <div className="two-column"><section className="work-surface"><div className="surface-head"><div><span className="eyebrow">优先查看</span><h3>{market === "stocks" ? "今天的股票机会" : "当前 Crypto 机会"}</h3></div><button className="text-button" onClick={() => onSelect(symbol)}>打开图表 <ChevronRight size={14} /></button></div><OpportunityTable market={market} rows={rows} onSelect={onSelect} /></section><section className="work-surface"><div className="surface-head"><div><span className="eyebrow">判断依据</span><h3>为什么是这个结论</h3></div><LineChart size={18} className="surface-icon" /></div><EvidenceList detail={detail} market={market} /><div className="next-step"><span>下一步</span><strong>{market === "stocks" ? "确认 Longbridge 行情和入场失效条件" : "确认流动性、安全快照和最终审核状态"}</strong></div></section></div>
  </>;
}

function DiscoverView({ market, data, rows, onSelect }: { market: Market; data: DomainData; rows: Json[]; onSelect: (symbol: string) => void }) {
  const contextRows = extractRows(data.context, ["items", "themes", "ranking", "members", "providers"]);
  return <div className="stack"><section className="work-surface"><div className="surface-head"><div><span className="eyebrow">发现</span><h2>{market === "stocks" ? "股票池与主题" : "CEX、DEX 与 MEME"}</h2><p className="surface-lede">按结论、数据质量和更新时间筛选，候选不会绕过最终审核。</p></div><StatusChip label={market === "stocks" ? "Longbridge" : "公开行情"} tone="info" /></div><OpportunityTable market={market} rows={rows} onSelect={onSelect} /></section><section className="work-surface compact-surface"><div className="surface-head"><div><span className="eyebrow">环境</span><h3>{market === "stocks" ? "主题轮动" : "市场状态"}</h3></div><BarChart3 size={18} className="surface-icon" /></div>{contextRows.length ? <div className="rank-list">{contextRows.slice(0, 8).map((row, index) => <div className="rank-row" key={`${textValue(row.symbol, row.name, row.id)}-${index}`}><span className="rank-number">{String(index + 1).padStart(2, "0")}</span><strong>{textValue(row.name, row.symbol, row.theme, row.regime)}</strong><span>{actionLabel(textValue(row.status, row.action, row.direction))}</span><b>{formatNumber(row.score, 1)}</b></div>)}</div> : <EmptyState title="暂无环境快照" detail="运行一次数据采集后，这里会显示市场背景。" />}<ExtendedDataPanel market={market} data={data} /></section><DiscoveryDetailPanel market={market} data={data} /></div>;
}

function ChartView({ market, data, symbol }: { market: Market; data: DomainData; symbol: string }) {
  return <div className="stack"><section className="work-surface chart-surface"><div className="surface-head"><div><span className="eyebrow">图表</span><h2>{symbol} 价格走势</h2><p className="surface-lede">只显示已收盘数据；形成中的行情不会直接改变研究结论。</p></div><div className="chart-legend"><span><i className="legend-line blue" />EMA20</span><span><i className="legend-line amber" />EMA50</span><span><i className="legend-line teal" />EMA200</span></div></div><PriceChart payload={data.candles} market={market} symbol={symbol} /></section><section className="work-surface compact-surface"><div className="surface-head"><div><span className="eyebrow">数据来源</span><h3>当前数据状态</h3></div><Activity size={18} className="surface-icon" /></div><MetricStrip items={[{ label: "来源", value: textValue(data.detail.source, data.detail.data_status?.source, market === "stocks" ? "Longbridge" : "CEX") }, { label: "状态", value: textValue(data.detail.status, data.market.status, "待确认") }, { label: "更新时间", value: textValue(data.detail.as_of_time, data.detail.updated_at, "-") }, { label: "可信度", value: textValue(data.detail.trust, data.detail.data_status?.freshness, "待确认") }]} /><ExtendedDataPanel market={market} data={data} /></section></div>;
}

function factorLabel(value: unknown): string {
  const raw = String(value ?? "").trim();
  const labels: Record<string, string> = {
    ema8_9_reclaim: "EMA8/9 转强",
    ema20_slope: "EMA20 斜率",
    relative_strength: "相对强弱",
    relative_strength_acceleration: "相对强弱加速度",
    relative_volume: "相对成交量",
    atr_compression: "波动收缩",
    breakout_distance: "突破距离",
    price_above_ema20: "价格站上 EMA20",
    price_above_ema50: "价格站上 EMA50",
    price_above_ema200: "价格站上 EMA200",
  };
  if (labels[raw]) return labels[raw];
  return humanizeText(raw.replace(/[_-]+/g, " ")) || "已注册因素";
}

function ExtendedDataPanel({ market, data }: { market: Market; data: DomainData }) {
  if (market === "stocks") {
    const factorRows = extractRows(data.research, ["factors", "items", "contributions", "factor_snapshot"]).slice(0, 8);
    const early = data.validation;
    const runtime = data.runtime;
    return <div className="extended-data"><div className="subsection-head"><span className="eyebrow">研究依据</span><span className="muted">已注册因素</span></div><div className="data-summary-grid"><div><span>结构阶段</span><strong>{statusLabel(textValue(early.strategy_stage, early.stage, early.status, "待确认"))}</strong></div><div><span>实时状态</span><strong>{statusLabel(textValue(runtime.trust, runtime.data_quality, runtime.provider_status, "待确认"))}</strong></div><div><span>数据时间</span><strong className="mono">{textValue(runtime.quote?.time, runtime.as_of_time, data.detail.as_of_time, "-").slice(0, 19)}</strong></div></div>{factorRows.length ? <div className="factor-list">{factorRows.map((row, index) => <div className="factor-row" key={`${textValue(row.id, row.factor_id, row.name, index)}`}><span>{factorLabel(textValue(row.label, row.factor_id, row.id, row.name))}</span><b>{formatNumber(row.contribution, 2)}</b><small>{statusLabel(textValue(row.status, row.missing, row.source, "已记录"))}</small></div>)}</div> : <EmptyState title="暂无因素快照" detail="分析完成后，这里会列出每个已注册因素及其贡献。" />}</div>;
  }
  const posterior = isRecord(data.research.item) && isRecord(data.research.item.posterior) ? data.research.item.posterior : {};
  const safetyRows = extractRows(data.safety, ["items", "snapshots"]).slice(0, 6);
  const holder = isRecord(data.holders.item) ? data.holders.item : data.holders;
  const coverage = data.coverage;
  const holderCount = numberValue(holder.holder_count, holder.holders, holder.count);
  return <div className="extended-data"><div className="subsection-head"><span className="eyebrow">证据摘要</span><span className="muted">只读数据</span></div><div className="data-summary-grid"><div><span>市场状态</span><strong>{statusLabel(textValue(data.context.regime, data.context.status, "待确认"))}</strong></div><div><span>状态判断</span><strong>{statusLabel(textValue(posterior.most_likely_state, posterior.evidence_status, "等待采集"))}</strong></div><div><span>数据覆盖</span><strong>{textValue(coverage.asset_count, coverage.status, "待确认")}</strong></div><div><span>上涨概率</span><strong>{posterior.positive_return_probability == null ? "暂无" : formatPercent(posterior.positive_return_probability)}</strong></div><div><span>持有人结构</span><strong>{holderCount === null ? statusLabel(textValue(holder.status, "等待采集")) : compactValue(holderCount)}</strong></div></div>{safetyRows.length ? <div className="factor-list">{safetyRows.map((row, index) => <div className="factor-row" key={`${textValue(row.security_snapshot_id, row.asset_id, index)}`}><span>{textValue(row.asset_id, row.symbol, "代币")}</span><b>{statusLabel(textValue(row.status, row.risk_level, "待确认"))}</b><small>{humanizeText(textValue(row.reason, row.message, row.eval_allowed === false ? "安全条件未满足" : "安全快照已记录"))}</small></div>)}</div> : <EmptyState title="暂无安全快照" detail="安全数据未确认前，Crypto 只保留观察状态。" />}</div>;
}

function DiscoveryDetailPanel({ market, data }: { market: Market; data: DomainData }) {
  if (market === "stocks") {
    const themes = extractRows(data.discovery, ["items", "themes", "ranking"]).slice(0, 8);
    return <section className="work-surface"><div className="surface-head"><div><span className="eyebrow">主题与覆盖</span><h3>研究范围</h3></div><BarChart3 size={18} className="surface-icon" /></div>{themes.length ? <div className="rank-list">{themes.map((row, index) => <div className="rank-row" key={`${textValue(row.id, row.theme, row.name, index)}`}><span className="rank-number">{String(index + 1).padStart(2, "0")}</span><strong>{textValue(row.name, row.theme, row.symbol, "主题")}</strong><span>{statusLabel(textValue(row.status, row.data_status, "已记录"))}</span><b>{formatNumber(row.score, 1)}</b></div>)}</div> : <EmptyState title="暂无主题快照" detail="主题排名将在数据更新后显示。" />}</section>;
  }
  const pools = extractRows(data.discovery, ["items", "pairs", "snapshots"]).slice(0, 8);
  return <section className="work-surface"><div className="surface-head"><div><span className="eyebrow">池发现</span><h3>DEX / MEME 新池</h3></div><Radar size={18} className="surface-icon" /></div>{pools.length ? <div className="discovery-list">{pools.map((row, index) => <div className="discovery-row" key={`${textValue(row.snapshot_id, row.pair_address, row.asset_id, index)}`}><div><strong>{textValue(row.base_symbol, row.symbol, row.asset_id, "未知代币")}/{textValue(row.quote_symbol, "USDC")}</strong><small>{textValue(row.chain_id, row.chain, "未知链")} · {textValue(row.dex_id, row.dex, "未知平台")}</small></div><span>流动性 {compactValue(row.liquidity_usd)}</span><span>5m {compactValue(row.volume_5m_usd)}</span><StatusChip label={statusLabel(textValue(row.trust_status, row.status, "待确认"))} tone={statusTone(row.trust_status ?? row.status)} /></div>)}</div> : <EmptyState title="暂无新池快照" detail="启用公开 DEX 数据源后，这里会显示发现结果。" />}</section>;
}

function PlanEvidencePanel({ market, data }: { market: Market; data: DomainData }) {
  if (market === "stocks") {
    const readiness = data.safety;
    const validation = data.simulation;
    return <div className="plan-audit"><MetricStrip items={[{ label: "交易资格", value: statusLabel(textValue(readiness.decision, readiness.status, "待确认")) }, { label: "历史验证", value: statusLabel(textValue(validation.status, validation.gate_status, "待确认")) }, { label: "实时状态", value: statusLabel(textValue(data.runtime.trust, data.runtime.data_quality, "待确认")) }, { label: "通知", value: statusLabel(textValue(data.notifications.status, data.notifications.enabled ? "available" : "disabled", "待确认")) }]} /></div>;
  }
  const posterior = isRecord(data.research.item) && isRecord(data.research.item.posterior) ? data.research.item.posterior : {};
  const horizons = isRecord(data.simulation.item) && isRecord(data.simulation.item.horizons) ? data.simulation.item.horizons : {};
  const horizon = isRecord(horizons["24h"]) ? horizons["24h"] : (isRecord(horizons["24H"]) ? horizons["24H"] : {});
  const evaluations = extractRows(data.evaluations, ["items", "evaluations"]).slice(0, 4);
  return <div className="plan-audit"><MetricStrip items={[{ label: "最终审核", value: statusLabel(textValue(evaluations[0]?.decision, evaluations[0]?.evaluation_status, "等待审核")) }, { label: "市场状态", value: statusLabel(textValue(posterior.most_likely_state, data.context.regime, "待确认")) }, { label: "目标概率", value: horizon.p_target_before_stop == null ? "暂无" : formatPercent(horizon.p_target_before_stop) }, { label: "模拟状态", value: statusLabel(textValue(data.simulation.item?.status, data.simulation.status, "等待采集")) }]} /><div className="audit-note">Crypto 结果必须同时具备市场、流动性、安全和审核证据；证据缺失时只保留观察。</div></div>;
}

function PlanView({ market, data, rows, symbol }: { market: Market; data: DomainData; rows: Json[]; symbol: string }) {
  const selected = rows.find((row) => textValue(row.symbol, row.ticker, row.asset_id).toUpperCase().includes(symbol.replace("USDT", ""))) ?? data.detail;
  const blockers = extractRows(selected, ["blockers", "warnings", "reasons", "conditions"]);
  return <div className="stack"><section className="decision-band plan-band"><div className="decision-copy"><span className="eyebrow">计划 · {symbol}</span><h2>{market === "stocks" ? "人工复核计划" : "模拟与观察计划"}</h2><p>{market === "stocks" ? "研究结论、价格区间和失效条件分开确认。" : "Crypto 计划必须经过最终审核；未通过时只保留观察。"}</p></div><StatusChip label={actionLabel(textValue(selected.action, selected.decision, selected.status))} tone={statusTone(selected.action ?? selected.decision ?? selected.status)} /></section><section className="work-surface"><div className="surface-head"><div><span className="eyebrow">计划内容</span><h3>先确认这几项</h3></div><ShieldCheck size={18} className="surface-icon" /></div><div className="plan-grid">{[["结论", actionLabel(textValue(selected.action, selected.decision, selected.status))], ["入场", textValue(selected.entry_zone, selected.entry, "待补充")], ["止损", textValue(selected.stop_zone, selected.stop, "待补充")], ["目标", textValue(selected.target_zone, selected.target, "待补充")], ["有效期", textValue(selected.expires_at, selected.valid_until, "待补充")], ["审核", statusLabel(textValue(selected.evaluation_status, selected.evidence_grade, market === "stocks" ? "人工复核" : "等待最终审核"))]].map(([label, value]) => <div className="plan-field" key={label}><span>{label}</span><strong>{value}</strong></div>)}</div><div className="plan-evidence"><span className="eyebrow">阻断与提醒</span>{blockers.length ? blockers.slice(0, 6).map((item, index) => <div className="evidence-row" key={index}><AlertTriangle size={14} /><span>{humanizeText(textValue(item.message, item.reason, item.code, item.label))}</span></div>) : <div className="evidence-row"><ShieldCheck size={14} /><span>暂无额外阻断；仍需结合当前数据状态人工确认。</span></div>}</div><PlanEvidencePanel market={market} data={data} /></section></div>;
}

function ResearchView({ market, data, symbol, onOpen }: { market: Market; data: DomainData; symbol: string; onOpen: () => void }) {
  return <div className="stack"><section className="research-intro"><div><span className="eyebrow">研究</span><h2>{symbol} 的证据工作台</h2><p>{market === "stocks" ? "把趋势、量价、相对强弱和数据状态放在同一个复核上下文里。" : "把市场状态、流动性、安全和历史证据放在同一个复核上下文里。"}</p></div><button className="primary-button" onClick={onOpen}><PanelRight size={16} />打开深度研究</button></section><div className="two-column"><section className="work-surface"><div className="surface-head"><div><span className="eyebrow">确定性依据</span><h3>当前可解释因素</h3></div><LineChart size={18} className="surface-icon" /></div><EvidenceList detail={data.detail} market={market} /><ExtendedDataPanel market={market} data={data} /></section><section className="work-surface"><div className="surface-head"><div><span className="eyebrow">数据与版本</span><h3>研究上下文</h3></div><FileText size={18} className="surface-icon" /></div><div className="context-list"><div><span>数据来源</span><strong>{statusLabel(textValue(data.detail.source, data.detail.data_status?.source, market === "stocks" ? "Longbridge" : "公开 CEX"))}</strong></div><div><span>市场状态</span><strong>{statusLabel(textValue(data.context.regime, data.market.status, "待确认"))}</strong></div><div><span>快照时间</span><strong className="mono">{textValue(data.detail.as_of_time, data.detail.generated_at, "-")}</strong></div><div><span>研究边界</span><strong>只读研究</strong></div></div><PlanEvidencePanel market={market} data={data} /></section></div></div>;
}

function JournalView({ market, data, alerts, onAcknowledge }: { market: Market; data: DomainData; alerts: Json[]; onAcknowledge: (row: Json) => Promise<void> }) {
  const journalRows = extractRows(data.journal, ["items", "entries", "events", "ledger"]);
  const rows = journalRows.length ? journalRows : alerts;
  return <div className="stack"><section className="work-surface"><div className="surface-head"><div><span className="eyebrow">日志与预警</span><h2>{market === "stocks" ? "股票复核记录" : "Crypto 审核与观察记录"}</h2><p className="surface-lede">这里保存状态变化和人工复核上下文，不把观察结果命名为实盘业绩。</p></div><Bell size={18} className="surface-icon" /></div>{rows.length ? <div className="event-list">{rows.slice(0, 20).map((row, index) => { const id = textValue(row.id, row.alert_id, row.notification_id, row.event_id); const alertId = textValue(row.alert_id, row.notification_id); const acknowledged = Boolean(row.acknowledged_at) || ["acknowledged", "read"].includes(String(row.status ?? "").toLowerCase()); return <div className="event-row" key={`${id}-${index}`}><div className="event-icon"><Bell size={14} /></div><div className="event-copy"><strong>{textValue(row.title, row.symbol, row.event_type, row.action)}</strong><span>{humanizeText(textValue(row.message, row.body, row.reason, row.note, "状态已记录"))}</span></div><time>{textValue(row.created_at, row.occurred_at, row.as_of_time).slice(0, 19)}</time><div className="event-actions"><StatusChip label={acknowledged ? "已确认" : statusLabel(textValue(row.severity, row.status, row.delivery_status))} tone={acknowledged ? "positive" : statusTone(row.severity ?? row.status)} />{!acknowledged && alertId !== "-" ? <button className="event-ack" type="button" onClick={() => void onAcknowledge(row)} title="确认这条预警">确认</button> : null}</div></div>; })}</div> : <EmptyState title="暂无日志记录" detail="新的预警、观察和人工复核会出现在这里。" />}</section><section className="work-surface compact-surface"><div className="surface-head"><div><span className="eyebrow">运行边界</span><h3>当前权限</h3></div><ShieldCheck size={18} className="surface-icon" /></div><MetricStrip items={[{ label: "行情读取", value: "允许" }, { label: "研究与模拟", value: "允许" }, { label: "预警流", value: statusLabel(textValue(data.runtime.status, data.notifications.status, "待确认")) }, { label: "账户、钱包、订单", value: "禁止", tone: "negative" }]} /></section></div>;
}

export default function App() {
  const [authState, setAuthState] = useState<AuthState>("checking");
  const [session, setSession] = useState<Session | null>(null);
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
  if (authState === "checking") return <div className="auth-loading"><div className="brand-mark">KQ</div><span>正在打开 KQUANT</span></div>;
  if (authState !== "ready") return <LoginScreen mode={authState} onAuthenticated={refreshSession} />;
  return <Workspace onLogout={logout} />;
}
