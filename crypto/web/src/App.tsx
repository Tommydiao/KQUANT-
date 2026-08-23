import { FormEvent, useEffect, useState } from "react";

type Session = { authenticated: boolean; email?: string | null; configured: boolean };
type Health = { app_version: string; providers: Record<string, { enabled: boolean; status: string }>; eval_policy_version: string; read_only: boolean };
type Evaluation = { evaluation_id: string; decision: string; evaluation_status: string; blockers: Array<{ message: string }>; warnings: Array<{ message: string }> };
type SignalStatus = { status: string; strategy_version: string; events_seen: number; candidates_seen: number; evaluations_created: number; skipped_insufficient_history: number; last_evaluation_at: string | null; last_error: string | null; paper_enabled: boolean; shadow_enabled: boolean; order_submission: boolean };
type ValidationLatest = { status: string; report?: { test_evidence_status?: string; feature_scope?: string; oos_fold_count?: number; partitions?: { test?: { summary?: { sample_count?: number } } }; dataset_coverage?: { storage_mode?: string; closed_bar_count?: number; eligible_series_count?: number } } };
type NotificationStatus = { enabled: boolean; web_push: { configured: boolean; active_subscriptions: number }; delivery_mode: string; read_only: boolean };
type DexPair = { snapshot_id: string; pool_id: string; chain_id: string; dex_id: string; base_symbol: string; quote_symbol: string; liquidity_usd: number | null; volume_5m_usd: number | null; buys_5m: number | null; sells_5m: number | null; trust_status: string };
type DexSecurity = { security_snapshot_id: string; asset_id: string; chain_id: string; status: string; risk_level: string; eval_allowed: boolean; payload?: { decision?: { blockers?: Array<{ code: string }> } } };
type SecurityCoverage = { status: string; token_assets: number; checked_assets: number; coverage_ratio: number; provider_enabled: boolean; unknown_security_eval_allowed: boolean };
type ModelBenchmarks = { status: string; model_benchmarks?: { evidence_status?: string; sample_counts?: Record<string, { complete_factor_rows: number; raw_trade_rows: number }>; models?: Array<{ model_type: string; status: string; calibration?: Record<string, { status: string }> }> } | null };

async function getJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, { credentials: "same-origin", ...init });
  if (!response.ok) throw new Error((await response.json().catch(() => null))?.detail ?? "请求失败");
  return response.json() as Promise<T>;
}

function decodeBase64Url(value: string): Uint8Array {
  const padding = "=".repeat((4 - (value.length % 4)) % 4);
  const raw = window.atob((value + padding).replace(/-/g, "+").replace(/_/g, "/"));
  return Uint8Array.from(raw, (character) => character.charCodeAt(0));
}

function Login({ onLogin }: { onLogin: (session: Session) => void }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setError("");
    try {
      const session = await getJson<Session>("/api/auth/login", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email, password }) });
      onLogin(session);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "登录失败");
    }
  };
  return <main className="auth-shell"><section className="auth-card">
    <div className="brand-mark">KQ</div><p className="eyebrow">KQUANT CRYPTO</p>
    <h1>加密资产研究终端</h1><p className="muted">只读行情、启动监测和最终计划审核。没有账户、钱包或下单权限。</p>
    <form onSubmit={submit} className="login-form">
      <label>邮箱<input type="email" autoComplete="username" value={email} onChange={(event) => setEmail(event.target.value)} required /></label>
      <label>密码<input type="password" autoComplete="current-password" value={password} onChange={(event) => setPassword(event.target.value)} required /></label>
      {error && <p className="error">{error}</p>}<button type="submit">进入研究终端</button>
    </form>
  </section></main>;
}

function Dashboard({ session, onLogout }: { session: Session; onLogout: () => void }) {
  const [health, setHealth] = useState<Health | null>(null);
  const [signalStatus, setSignalStatus] = useState<SignalStatus | null>(null);
  const [validation, setValidation] = useState<ValidationLatest | null>(null);
  const [evaluations, setEvaluations] = useState<Evaluation[]>([]);
  const [notificationStatus, setNotificationStatus] = useState<NotificationStatus | null>(null);
  const [dexPairs, setDexPairs] = useState<DexPair[]>([]);
  const [dexSecurity, setDexSecurity] = useState<DexSecurity[]>([]);
  const [securityCoverage, setSecurityCoverage] = useState<SecurityCoverage | null>(null);
  const [modelBenchmarks, setModelBenchmarks] = useState<ModelBenchmarks | null>(null);
  const [notificationMessage, setNotificationMessage] = useState("");
  const [error, setError] = useState("");
  useEffect(() => {
    Promise.all([getJson<Health>("/api/health"), getJson<SignalStatus>("/api/crypto/runtime/signal-status"), getJson<ValidationLatest>("/api/crypto/validation/latest"), getJson<{ items: Evaluation[] }>("/api/crypto/evaluations/latest"), getJson<NotificationStatus>("/api/notifications/status"), getJson<{ items: DexPair[] }>("/api/crypto/dex/pairs/latest?limit=12"), getJson<{ items: DexSecurity[] }>("/api/crypto/security/latest?limit=12"), getJson<SecurityCoverage>("/api/crypto/security/coverage"), getJson<ModelBenchmarks>("/api/crypto/validation/model-benchmarks/latest")])
      .then(([nextHealth, nextSignalStatus, nextValidation, nextEvaluations, nextNotifications, nextDexPairs, nextDexSecurity, nextSecurityCoverage, nextModelBenchmarks]) => { setHealth(nextHealth); setSignalStatus(nextSignalStatus); setValidation(nextValidation); setEvaluations(nextEvaluations.items); setNotificationStatus(nextNotifications); setDexPairs(nextDexPairs.items); setDexSecurity(nextDexSecurity.items); setSecurityCoverage(nextSecurityCoverage); setModelBenchmarks(nextModelBenchmarks); })
      .catch((reason) => setError(reason instanceof Error ? reason.message : "加载失败"));
  }, []);
  const logout = async () => { await getJson("/api/auth/logout", { method: "POST" }); onLogout(); };
  const enableNotifications = async () => {
    setNotificationMessage("");
    if (!("serviceWorker" in navigator) || !("PushManager" in window) || !("Notification" in window)) { setNotificationMessage("This browser does not support Web Push."); return; }
    const key = await getJson<{ configured: boolean; public_key: string | null }>("/api/notifications/web-push/public-key");
    if (!key.configured || !key.public_key) { setNotificationMessage("Web Push is not configured on this server yet."); return; }
    const permission = await Notification.requestPermission();
    if (permission !== "granted") { setNotificationMessage("Notification permission was not granted."); return; }
    const registration = await navigator.serviceWorker.register("/service-worker.js");
    const existing = await registration.pushManager.getSubscription();
    const subscription = existing ?? await registration.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: decodeBase64Url(key.public_key) });
    await getJson("/api/notifications/web-push/subscribe", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(subscription.toJSON()) });
    await getJson("/api/notifications/preferences", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ enabled: true, web_push_enabled: true, telegram_enabled: false, timezone: "Asia/Shanghai" }) });
    setNotificationStatus((current) => current ? { ...current, web_push: { ...current.web_push, active_subscriptions: current.web_push.active_subscriptions + (existing ? 0 : 1) } } : current);
    setNotificationMessage("This device is ready for KQUANT alerts.");
  };
  const sendTestNotification = async () => {
    const result = await getJson<{ status: string; attempted: number; delivered: number }>("/api/notifications/web-push/test", { method: "POST" });
    setNotificationMessage(`Test result: ${result.status} (${result.delivered}/${result.attempted})`);
  };
  const enabledProviders = health ? Object.entries(health.providers).filter(([, value]) => value.enabled).map(([key]) => key) : [];
  const monitoringTitle = signalStatus?.events_seen ? "公共行情监测中" : "等待闭合行情数据";
  const testSummary = validation?.report?.partitions?.test?.summary;
  const validationScope = validation?.report?.feature_scope === "ohlcv_only_limited" ? "OHLCV-only / limited evidence" : validation?.report?.feature_scope ?? "未生成";
  return <main className="app-shell">
    <header className="topbar"><div className="brand"><div className="brand-mark small">KQ</div><div><strong>KQUANT CRYPTO</strong><span>启动监测与计划审核</span></div></div><div className="top-actions"><span className="status-pill green">研究只读</span><span className="status-pill amber">EVAL 锁定</span><button className="quiet-button" onClick={logout}>退出</button></div></header>
    <div className="workspace"><aside className="sidebar"><p className="eyebrow">导航</p><button className="nav-item active">今日监测</button><button className="nav-item">市场状态</button><button className="nav-item">CEX 雷达</button><button className="nav-item">DEX / MEME</button><button className="nav-item">预警中心</button><button className="nav-item">数据可信度</button><div className="sidebar-footer"><span>{session.email}</span><small>所有动作均需经过 EVAL</small></div></aside>
      <section className="content"><div className="page-heading"><div><p className="eyebrow">今日监测</p><h1>{monitoringTitle}</h1><p className="muted">系统只使用闭合 K 线生成研究草案；任何候选都必须先经过确定性 EVAL，数据不足时保持观察状态。</p></div><span className="timestamp">策略版本：{signalStatus?.strategy_version ?? "loading"}</span></div>
        {error && <div className="notice red">{error}</div>}
        <div className="metric-grid"><article className="metric"><span>市场状态</span><strong>等待数据</strong><small>形成中 K 线不能触发审核</small></article><article className="metric"><span>候选计划</span><strong>{evaluations.length}</strong><small>尚无可审核计划</small></article><article className="metric"><span>预警投递</span><strong>已关闭</strong><small>只接受 EVAL 通过结果</small></article><article className="metric"><span>数据源</span><strong>{enabledProviders.length ? enabledProviders.join(", ") : "未启用"}</strong><small>公共行情接入将在后续周次开启</small></article></div>
        <section className="panel eval-panel"><div className="panel-heading"><div><p className="eyebrow">最终审核层</p><h2>EVAL Agent</h2></div><span className="status-pill amber">只读观察</span></div><p className="muted">安全、数据、流动性、市场状态、模型证据和计划完整性按固定顺序检查。LLM 只能解释，不能改变结果。</p><div className="eval-flow"><span>计划草案</span><b>→</b><span>确定性审核</span><b>→</b><span>预警 / Paper / Shadow</span></div></section>
        <section className="panel"><div className="panel-heading"><div><p className="eyebrow">最近审核</p><h2>计划结果</h2></div><span className="muted">{health ? health.eval_policy_version : "加载中"}</span></div>{evaluations.length === 0 ? <div className="empty-state"><strong>还没有交易计划</strong><span>接入行情和信号模块后，所有计划仍会先进入 EVAL。</span></div> : <div className="evaluation-list">{evaluations.map((item) => <div className="evaluation-row" key={item.evaluation_id}><strong>{item.decision}</strong><span>{item.evaluation_status}</span><small>{item.blockers[0]?.message ?? item.warnings[0]?.message ?? "无补充信息"}</small></div>)}</div>}</section>
        <section className="panel runtime-panel"><div className="panel-heading"><div><p className="eyebrow">运行状态</p><h2>信号与验证证据</h2></div><span className="status-pill amber">{signalStatus?.paper_enabled ? "PAPER" : "观察模式"}</span></div><p className="muted">这里只展示采集和研究证据，不代表交易许可。形成中 K 线、数据过期或模型 Gate 未通过时，EVAL 会阻断后续动作。</p><div className="runtime-grid"><div><span>已接收事件</span><strong>{signalStatus?.events_seen ?? "-"}</strong></div><div><span>候选草案</span><strong>{signalStatus?.candidates_seen ?? "-"}</strong></div><div><span>EVAL 审核</span><strong>{signalStatus?.evaluations_created ?? "-"}</strong></div><div><span>测试证据</span><strong>{testSummary?.sample_count ?? 0} 笔 / {validation?.report?.test_evidence_status ?? "未生成"}</strong></div><div><span>OOS folds</span><strong>{validation?.report?.oos_fold_count ?? 0}</strong></div><div><span>历史证据范围</span><strong>{validationScope}</strong></div><div><span>安全快照覆盖</span><strong>{securityCoverage ? `${securityCoverage.checked_assets}/${securityCoverage.token_assets}` : "-"}</strong></div><div><span>模型校准</span><strong>{modelBenchmarks?.model_benchmarks?.models?.find((item) => item.model_type === "logistic_numpy")?.calibration?.platt?.status ?? "未生成"}</strong></div></div>{signalStatus?.last_error && <p className="notice red">运行组件暂时异常：{signalStatus.last_error}</p>}</section>
        <section className="panel notification-panel"><div className="panel-heading"><div><p className="eyebrow">DEVICE ALERTS</p><h2>iPhone Web Push</h2></div><span className="status-pill green">READ ONLY</span></div><p className="muted">Enable this device for EVAL-approved research alerts. No account, wallet, or order access is involved.</p><div className="notification-meta"><span>Server: {notificationStatus?.delivery_mode ?? "loading"}</span><span>Active devices: {notificationStatus?.web_push.active_subscriptions ?? 0}</span></div><div className="button-row"><button className="primary-button" onClick={enableNotifications}>Enable on this device</button><button className="quiet-button" onClick={sendTestNotification}>Send test</button></div>{notificationMessage && <p className="notice-inline">{notificationMessage}</p>}</section>
        <section className="panel dex-panel"><div className="panel-heading"><div><p className="eyebrow">DISCOVERY RADAR</p><h2>DEX pools</h2></div><span className="status-pill green">READ ONLY</span></div>{dexPairs.length === 0 ? <div className="empty-state"><strong>No DEX discovery snapshots</strong><span>Enable the public DEX Screener provider to collect new-pool observations.</span></div> : <div className="dex-list">{dexPairs.map((item) => <div className="dex-row" key={item.snapshot_id}><div><strong>{item.base_symbol}/{item.quote_symbol}</strong><small>{item.chain_id} · {item.dex_id}</small></div><span>Liquidity ${item.liquidity_usd == null ? "n/a" : Math.round(item.liquidity_usd).toLocaleString()}</span><span>5m vol ${item.volume_5m_usd == null ? "n/a" : Math.round(item.volume_5m_usd).toLocaleString()}</span><span>B/S {item.buys_5m ?? "-"}/{item.sells_5m ?? "-"}</span><em>{item.trust_status}</em></div>)}</div>}<div className="security-summary"><div><p className="eyebrow">TOKEN SAFETY</p><h3>安全快照</h3><span className="muted">覆盖 {securityCoverage ? `${securityCoverage.checked_assets}/${securityCoverage.token_assets}` : "-"} · {securityCoverage?.status ?? "loading"}</span></div>{dexSecurity.length === 0 ? <p className="muted">尚无安全快照。安全信息未确认时，EVAL 会拒绝 DEX / MEME Paper 计划。</p> : <div className="security-list">{dexSecurity.map((item) => <div className="security-row" key={item.security_snapshot_id}><strong>{item.asset_id}</strong><span className={item.status === "passed" ? "safe" : "blocked"}>{item.status}</span><span>{item.risk_level}</span><em>{item.eval_allowed ? "可进入后续审核" : "禁止 Paper"}</em></div>)}</div>}</div></section>
      </section>
    </div>
  </main>;
}

export default function App() {
  const [session, setSession] = useState<Session | null>(null);
  const [checking, setChecking] = useState(true);
  useEffect(() => { getJson<Session>("/api/auth/session").then(setSession).catch(() => setSession({ authenticated: false, configured: false })).finally(() => setChecking(false)); }, []);
  if (checking) return <div className="loading">确认本机登录状态…</div>;
  if (!session?.authenticated) return <Login onLogin={setSession} />;
  return <Dashboard session={session} onLogout={() => setSession({ authenticated: false, configured: session.configured })} />;
}
