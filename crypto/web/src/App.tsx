import { FormEvent, useEffect, useState } from "react";

type Session = { authenticated: boolean; email?: string | null; configured: boolean };
type Health = { app_version: string; build_sha?: string; environment?: string; providers: Record<string, { enabled: boolean; status: string }>; eval_policy_version: string; read_only: boolean };
type Evaluation = { evaluation_id: string; decision: string; evaluation_status: string; blockers: Array<{ message: string }>; warnings: Array<{ message: string }> };
type SignalStatus = { status: string; strategy_version: string; events_seen: number; candidates_seen: number; evaluations_created: number; skipped_insufficient_history: number; last_evaluation_at: string | null; last_error: string | null; paper_enabled: boolean; shadow_enabled: boolean; order_submission: boolean };
type ValidationLatest = { status: string; report?: { test_evidence_status?: string; feature_scope?: string; oos_fold_count?: number; partitions?: { test?: { summary?: { sample_count?: number } } }; dataset_coverage?: { storage_mode?: string; closed_bar_count?: number; eligible_series_count?: number } } };
type NotificationStatus = { enabled: boolean; web_push: { configured: boolean; active_subscriptions: number }; delivery_mode: string; read_only: boolean };
type DexPair = { snapshot_id: string; pool_id: string; chain_id: string; dex_id: string; base_symbol: string; quote_symbol: string; liquidity_usd: number | null; volume_5m_usd: number | null; buys_5m: number | null; sells_5m: number | null; trust_status: string };
type DexSecurity = { security_snapshot_id: string; asset_id: string; chain_id: string; status: string; risk_level: string; eval_allowed: boolean; payload?: { decision?: { blockers?: Array<{ code: string }> } } };
type SecurityCoverage = { status: string; token_assets: number; checked_assets: number; coverage_ratio: number; provider_enabled: boolean; unknown_security_eval_allowed: boolean };
type EvidenceCoverageItem = { expected_assets: string[]; observed_assets: string[]; verified_assets: string[]; missing_assets: string[]; observed_ratio: number; verified_ratio: number; status: string };
type EvidenceCoverage = { status: string; categories: Record<string, EvidenceCoverageItem>; missing_value_policy: string; unknown_values_are_blocked: boolean; research_only: boolean };
type ModelBenchmarks = { status: string; model_benchmarks?: { evidence_status?: string; sample_counts?: Record<string, { complete_factor_rows: number; raw_trade_rows: number }>; models?: Array<{ model_type: string; status: string; calibration?: Record<string, { status: string }> }> } | null };
type RollDecision = { roll_id: string; symbol: string; action: string; status: string; rationale: string; blockers: string[]; warnings: string[]; strategy_version: string; roll_capital: number; remaining_risk: number; source_status: string; coverage: number; payload?: { evaluation_status?: string; allowed_alert?: boolean; allowed_paper?: boolean; allowed_shadow?: boolean } };
type BayesianResult = { status: string; item?: { posterior?: { most_likely_state: string; data_confidence: number; evidence_status: string; target_before_stop_probability: number | null; positive_return_probability: number | null } } | null };
type MonteCarloResult = { status: string; item?: { status: string; horizons?: Record<string, { p_target_before_stop: number; expected_r: number | null; p50_return: number; p90_max_drawdown: number }> } | null };
type ShadowSummary = { status: string; observed_trading_days: number; required_trading_days: number; observation_count: number; completed_outcomes: number; validation_gate_status: string; note: string };
type RollDeskResult = { decision: RollDecision; evaluation: Evaluation | null; research_only: boolean; execution_enabled: boolean };
type JournalPreview = { preview_id: string; symbol: string | null; realized_profit: number | null; rolled_capital: number | null; remaining_risk: number | null; user_note: string; missing_fields: string[]; status: string; write_allowed: boolean };

async function getJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, { credentials: "same-origin", ...init });
  if (!response.ok) throw new Error((await response.json().catch(() => null))?.detail ?? "请求失败");
  return response.json() as Promise<T>;
}

function decodeBase64Url(value: string): ArrayBuffer {
  const padding = "=".repeat((4 - (value.length % 4)) % 4);
  const raw = window.atob((value + padding).replace(/-/g, "+").replace(/_/g, "/"));
  return Uint8Array.from(raw, (character) => character.charCodeAt(0)).buffer;
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

type RollForm = {
  symbol: string;
  marketState: string;
  sourceStatus: string;
  realizedProfit: string;
  floatingPnl: string;
  currentExposure: string;
  proposedCapital: string;
  stateProbability: string;
  targetProbability: string;
  positiveProbability: string;
  drawdownProbability: string;
  probabilityImprovement: string;
  currentScore: string;
  rotationScore: string;
  rotationTarget: string;
};

const INITIAL_ROLL_FORM: RollForm = {
  symbol: "ETH",
  marketState: "ACCUMULATION",
  sourceStatus: "live",
  realizedProfit: "0",
  floatingPnl: "0",
  currentExposure: "0",
  proposedCapital: "0",
  stateProbability: "0.60",
  targetProbability: "0.60",
  positiveProbability: "0.60",
  drawdownProbability: "0.25",
  probabilityImprovement: "0",
  currentScore: "0.50",
  rotationScore: "0.50",
  rotationTarget: "",
};

function rollAssetType(symbol: string): string {
  if (["ETHU", "MSTU"].includes(symbol)) return "crypto_leveraged_etf";
  if (symbol === "MSTR") return "crypto_equity_proxy";
  return "crypto_spot";
}

function rollInstrument(symbol: string): string {
  const listed: Record<string, string> = { ETHU: "listed:US:ETHU", MSTR: "listed:US:MSTR", MSTU: "listed:US:MSTU" };
  return listed[symbol] ?? `binance:spot:${symbol}USDT`;
}

function RollDesk() {
  const [form, setForm] = useState<RollForm>(INITIAL_ROLL_FORM);
  const [journal, setJournal] = useState({ symbol: "ETH", realizedProfit: "", rolledCapital: "", remainingRisk: "", note: "" });
  const [ocrText, setOcrText] = useState("");
  const [preview, setPreview] = useState<JournalPreview | null>(null);
  const [result, setResult] = useState<RollDeskResult | null>(null);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const updateForm = (key: keyof RollForm, value: string) => setForm((current) => ({ ...current, [key]: value }));
  const number = (value: string) => Number.isFinite(Number(value)) ? Number(value) : 0;

  const evaluate = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setMessage("");
    const symbol = form.symbol.trim().toUpperCase();
    const now = new Date();
    const validUntil = new Date(now.getTime() + 24 * 60 * 60 * 1000);
    const featureSnapshot = `manual_roll_feature_${now.toISOString().slice(0, 10)}`;
    try {
      const response = await getJson<RollDeskResult>("/api/crypto/roll/evaluate", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          asset_id: `asset:${symbol.toLowerCase()}`,
          symbol,
          asset_type: rollAssetType(symbol),
          instrument_id: rollInstrument(symbol),
          as_of_time: now.toISOString(),
          data_cutoff_time: now.toISOString(),
          source_status: form.sourceStatus,
          coverage: 1,
          market_state: form.marketState,
          state_probability: number(form.stateProbability),
          target_before_stop_probability: number(form.targetProbability),
          positive_return_probability: number(form.positiveProbability),
          drawdown_probability: number(form.drawdownProbability),
          realized_profit: number(form.realizedProfit),
          floating_pnl: number(form.floatingPnl),
          current_exposure: number(form.currentExposure),
          proposed_capital: number(form.proposedCapital),
          probability_improvement: number(form.probabilityImprovement),
          current_score: number(form.currentScore),
          rotation_score: number(form.rotationScore),
          rotation_target: form.rotationTarget.trim() || null,
          feature_snapshot_id: featureSnapshot,
          model_version: "manual-research-contract-v1",
          source_snapshot_ids: ["manual_roll_input"],
          research_only: true,
          trade_plan: {
            plan_id: `roll_desk_${now.getTime()}`,
            proposed_stage: "ARMED",
            identity_status: "known",
            data_quality_status: form.sourceStatus,
            security_status: "unknown",
            liquidity_status: "unknown",
            market_regime: form.marketState,
            model_status: "unavailable",
            factor_snapshot_hash: featureSnapshot,
            source_snapshot_ids: ["manual_roll_input"],
            snapshot_bindings: { market: "manual_roll_input", factor: featureSnapshot, plan: `roll_desk_${now.getTime()}`, eval_policy: "crypto_eval_v1.0.2" },
            factor_ids: ["trend_score"],
            entry_zone: ["manual_review"],
            stop_zone: ["manual_review"],
            target_zone: ["manual_review"],
            risk_reward: 1,
            valid_until: validUntil.toISOString(),
            invalid_conditions: ["manual_review_required"],
            requested_execution_class: "research_only",
            payload: { provider_status: form.sourceStatus, bbo_valid: false },
          },
        }),
      });
      setResult(response);
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "Roll evaluation failed");
    } finally {
      setBusy(false);
    }
  };

  const previewOcr = async () => {
    setMessage("");
    try {
      const value = await getJson<JournalPreview>("/api/crypto/roll/ledger/ocr-preview", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text: ocrText }) });
      setPreview(value);
      if (value.symbol) setJournal((current) => ({ ...current, symbol: value.symbol ?? current.symbol }));
      if (value.realized_profit != null) setJournal((current) => ({ ...current, realizedProfit: String(value.realized_profit) }));
      if (value.rolled_capital != null) setJournal((current) => ({ ...current, rolledCapital: String(value.rolled_capital) }));
      if (value.remaining_risk != null) setJournal((current) => ({ ...current, remainingRisk: String(value.remaining_risk) }));
      if (value.user_note) setJournal((current) => ({ ...current, note: value.user_note }));
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "OCR preview failed");
    }
  };

  const saveJournal = async () => {
    setMessage("");
    try {
      await getJson("/api/crypto/roll/ledger", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({
        asset_id: `asset:${journal.symbol.trim().toLowerCase()}`,
        symbol: journal.symbol.trim().toUpperCase(),
        event_type: "manual_confirmed_journal",
        realized_profit: number(journal.realizedProfit),
        rolled_capital: number(journal.rolledCapital),
        remaining_risk: number(journal.remainingRisk),
        preview_id: preview?.preview_id,
        confirm_write: true,
        user_note: journal.note,
        occurred_at: new Date().toISOString(),
      }) });
      setMessage("Roll Journal 已确认写入。它仍是研究记录，不是交易执行。");
    } catch (reason) {
      setMessage(reason instanceof Error ? reason.message : "Journal write failed");
    }
  };

  const fields: Array<[keyof RollForm, string]> = [
    ["realizedProfit", "已实现利润"], ["floatingPnl", "浮动盈亏"], ["currentExposure", "当前风险"], ["proposedCapital", "拟滚入资本"],
    ["stateProbability", "状态概率"], ["targetProbability", "目标先于止损"], ["positiveProbability", "正收益概率"], ["drawdownProbability", "大回撤概率"],
    ["probabilityImprovement", "概率改善"], ["currentScore", "当前评分"], ["rotationScore", "目标评分"],
  ];
  return <section className="panel roll-desk-panel">
    <div className="panel-heading"><div><p className="eyebrow">ROLL DESK</p><h2>滚仓研究工作台</h2></div><span className="status-pill amber">RESEARCH ONLY</span></div>
    <p className="muted">输入同一时点的已实现利润、风险和概率证据。系统只生成 `crypto_roll_v1.0.0` 研究动作，并把草案交给 EVAL；未知安全、流动性或模型数据会被阻断。</p>
    <form className="roll-form" onSubmit={evaluate}>
      <label>标的<input value={form.symbol} onChange={(event) => updateForm("symbol", event.target.value)} /></label>
      <label>市场状态<select value={form.marketState} onChange={(event) => updateForm("marketState", event.target.value)}><option>BULL</option><option>ACCUMULATION</option><option>DISTRIBUTION</option><option>BEAR_STRESS</option></select></label>
      <label>数据状态<select value={form.sourceStatus} onChange={(event) => updateForm("sourceStatus", event.target.value)}><option>live</option><option>closed</option><option>partial</option><option>stale</option></select></label>
      {fields.map(([key, label]) => <label key={key}>{label}<input inputMode="decimal" value={form[key]} onChange={(event) => updateForm(key, event.target.value)} /></label>)}
      <label>轮动目标<input value={form.rotationTarget} onChange={(event) => updateForm("rotationTarget", event.target.value)} placeholder="可留空" /></label>
      <div className="roll-form-actions"><button className="primary-button" type="submit" disabled={busy}>{busy ? "评估中…" : "生成滚仓研究结果"}</button><span className="muted">执行权限：关闭</span></div>
    </form>
    {result && <div className="roll-result"><div><span>确定性动作</span><strong>{result.decision.action}</strong></div><div><span>状态</span><strong>{result.decision.status}</strong></div><div><span>滚入资本</span><strong>{result.decision.roll_capital}</strong></div><div><span>EVAL</span><strong>{result.evaluation?.decision ?? "未提交交易计划"}</strong></div><p>{result.decision.rationale}</p>{result.decision.blockers.length > 0 && <small>阻断：{result.decision.blockers.join("、")}</small>}</div>}
    <div className="journal-divider"><div><p className="eyebrow">ROLL JOURNAL</p><h3>已实现利润记录</h3></div><span className="muted">OCR 只预览，确认后才写入</span></div>
    <div className="journal-grid"><label>OCR 文本<textarea value={ocrText} onChange={(event) => setOcrText(event.target.value)} placeholder="symbol: ETH\nrealized profit: 120\nroll capital: 80\nremaining risk: 40\nnote: ..." /></label><div className="journal-fields"><label>标的<input value={journal.symbol} onChange={(event) => setJournal({ ...journal, symbol: event.target.value })} /></label><label>已实现利润<input value={journal.realizedProfit} onChange={(event) => setJournal({ ...journal, realizedProfit: event.target.value })} /></label><label>滚入资本<input value={journal.rolledCapital} onChange={(event) => setJournal({ ...journal, rolledCapital: event.target.value })} /></label><label>剩余风险<input value={journal.remainingRisk} onChange={(event) => setJournal({ ...journal, remainingRisk: event.target.value })} /></label><label className="wide-field">备注<input value={journal.note} onChange={(event) => setJournal({ ...journal, note: event.target.value })} /></label></div></div>
    <div className="button-row"><button className="quiet-button" type="button" onClick={previewOcr}>预览 OCR</button><button className="primary-button" type="button" onClick={saveJournal}>确认写入 Roll Journal</button></div>
    {preview && <div className={`notice ${preview.status === "preview_ready" ? "green-notice" : "red"}`}>预览状态：{preview.status}；写入权限：{preview.write_allowed ? "允许" : "需人工确认"}。{preview.missing_fields.length ? `缺少：${preview.missing_fields.join("、")}` : "字段已填充，请确认后写入。"}</div>}
    {message && <p className="notice-inline">{message}</p>}
  </section>;
}

function EvidenceCoveragePanel({ data }: { data: EvidenceCoverage | null }) {
  const labels: Record<string, string> = {
    etf_flow: "ETF flow",
    exchange_derivatives: "Exchange derivatives",
    onchain: "On-chain",
    whale: "Whale transfers",
    market_structure: "Market structure",
    protocol_metric: "Protocol metrics",
  };
  return <section className="panel evidence-panel"><div className="panel-heading"><div><p className="eyebrow">DATA TRUST</p><h2>Evidence coverage</h2></div><span className="status-pill amber">{data?.status ?? "loading"}</span></div><p className="muted">Only persisted provider snapshots are shown. Missing values remain N/A and cannot unlock EVAL.</p>{!data ? <div className="empty-state"><strong>Loading coverage</strong></div> : <div className="evidence-grid">{Object.entries(data.categories).map(([category, item]) => <div className="evidence-row" key={category}><div><strong>{labels[category] ?? category}</strong><small>{item.missing_assets.length ? `${item.missing_assets.length} scoped assets missing` : "All scoped assets observed"}</small></div><span>Observed {Math.round(item.observed_ratio * 100)}%</span><span>Verified {Math.round(item.verified_ratio * 100)}%</span><em className={item.status === "complete" ? "safe" : "blocked"}>{item.status}</em></div>)}</div>}<small className="evidence-footnote">Unknown values blocked: {data?.unknown_values_are_blocked ? "yes" : "no"} · Missing value policy: {data?.missing_value_policy ?? "N/A"}</small></section>;
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
  const [evidenceCoverage, setEvidenceCoverage] = useState<EvidenceCoverage | null>(null);
  const [modelBenchmarks, setModelBenchmarks] = useState<ModelBenchmarks | null>(null);
  const [rollDecisions, setRollDecisions] = useState<RollDecision[]>([]);
  const [bayesian, setBayesian] = useState<BayesianResult | null>(null);
  const [monteCarlo, setMonteCarlo] = useState<MonteCarloResult | null>(null);
  const [shadowSummary, setShadowSummary] = useState<ShadowSummary | null>(null);
  const [notificationMessage, setNotificationMessage] = useState("");
  const [error, setError] = useState("");
  useEffect(() => {
    Promise.all([getJson<Health>("/api/health"), getJson<SignalStatus>("/api/crypto/runtime/signal-status"), getJson<ValidationLatest>("/api/crypto/validation/latest"), getJson<{ items: Evaluation[] }>("/api/crypto/evaluations/latest"), getJson<NotificationStatus>("/api/notifications/status"), getJson<{ items: DexPair[] }>("/api/crypto/dex/pairs/latest?limit=12"), getJson<{ items: DexSecurity[] }>("/api/crypto/security/latest?limit=12"), getJson<SecurityCoverage>("/api/crypto/security/coverage"), getJson<EvidenceCoverage>("/api/crypto/evidence/coverage"), getJson<ModelBenchmarks>("/api/crypto/validation/model-benchmarks/latest"), getJson<{ items: RollDecision[] }>("/api/crypto/roll/current"), getJson<BayesianResult>("/api/crypto/research/bayesian/asset:ETH"), getJson<MonteCarloResult>("/api/crypto/research/monte-carlo/asset:ETH")])
      .then(([nextHealth, nextSignalStatus, nextValidation, nextEvaluations, nextNotifications, nextDexPairs, nextDexSecurity, nextSecurityCoverage, nextEvidenceCoverage, nextModelBenchmarks, nextRolls, nextBayesian, nextMonteCarlo]) => { setHealth(nextHealth); setSignalStatus(nextSignalStatus); setValidation(nextValidation); setEvaluations(nextEvaluations.items); setNotificationStatus(nextNotifications); setDexPairs(nextDexPairs.items); setDexSecurity(nextDexSecurity.items); setSecurityCoverage(nextSecurityCoverage); setEvidenceCoverage(nextEvidenceCoverage); setModelBenchmarks(nextModelBenchmarks); setRollDecisions(nextRolls.items); setBayesian(nextBayesian); setMonteCarlo(nextMonteCarlo); })
      .catch((reason) => setError(reason instanceof Error ? reason.message : "加载失败"));
  }, []);
  useEffect(() => { getJson<ShadowSummary>("/api/crypto/shadow/summary").then(setShadowSummary).catch(() => setShadowSummary(null)); }, []);
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
  return <main className="app-shell"><span className="build-sha-badge">Build {health?.build_sha?.slice(0, 8) ?? "unknown"}</span><a className="mode-link gateway-link" href="http://127.0.0.1:8020/">KQUANT workspace gateway · Shadow {shadowSummary?.status ?? "loading"}</a>
    <header className="topbar"><div className="brand"><div className="brand-mark small">KQ</div><div><strong>KQUANT CRYPTO</strong><span>启动监测与计划审核</span></div></div><div className="top-actions"><a className="mode-link" href="http://127.0.0.1:8001/">Stocks</a><span className="status-pill green">研究只读</span><span className="status-pill amber">EVAL 锁定</span><button className="quiet-button" onClick={logout}>退出</button></div></header>
    <div className="workspace"><aside className="sidebar"><p className="eyebrow">导航</p><button className="nav-item active">今日监测</button><button className="nav-item">市场状态</button><button className="nav-item">CEX 雷达</button><button className="nav-item">DEX / MEME</button><button className="nav-item">预警中心</button><button className="nav-item">数据可信度</button><div className="sidebar-footer"><span>{session.email}</span><small>所有动作均需经过 EVAL</small></div></aside>
      <section className="content"><div className="page-heading"><div><p className="eyebrow">今日监测</p><h1>{monitoringTitle}</h1><p className="muted">系统只使用闭合 K 线生成研究草案；任何候选都必须先经过确定性 EVAL，数据不足时保持观察状态。</p></div><span className="timestamp">策略版本：{signalStatus?.strategy_version ?? "loading"}</span></div>
        {error && <div className="notice red">{error}</div>}
        <div className="metric-grid"><article className="metric"><span>市场状态</span><strong>等待数据</strong><small>形成中 K 线不能触发审核</small></article><article className="metric"><span>候选计划</span><strong>{evaluations.length}</strong><small>尚无可审核计划</small></article><article className="metric"><span>预警投递</span><strong>已关闭</strong><small>只接受 EVAL 通过结果</small></article><article className="metric"><span>数据源</span><strong>{enabledProviders.length ? enabledProviders.join(", ") : "未启用"}</strong><small>公共行情接入将在后续周次开启</small></article></div>
        <section className="panel eval-panel"><div className="panel-heading"><div><p className="eyebrow">最终审核层</p><h2>EVAL Agent</h2></div><span className="status-pill amber">只读观察</span></div><p className="muted">安全、数据、流动性、市场状态、模型证据和计划完整性按固定顺序检查。LLM 只能解释，不能改变结果。</p><div className="eval-flow"><span>计划草案</span><b>→</b><span>确定性审核</span><b>→</b><span>预警 / Paper / Shadow</span></div></section>
        <section className="panel"><div className="panel-heading"><div><p className="eyebrow">最近审核</p><h2>计划结果</h2></div><span className="muted">{health ? health.eval_policy_version : "加载中"}</span></div>{evaluations.length === 0 ? <div className="empty-state"><strong>还没有交易计划</strong><span>接入行情和信号模块后，所有计划仍会先进入 EVAL。</span></div> : <div className="evaluation-list">{evaluations.map((item) => <div className="evaluation-row" key={item.evaluation_id}><strong>{item.decision}</strong><span>{item.evaluation_status}</span><small>{item.blockers[0]?.message ?? item.warnings[0]?.message ?? "无补充信息"}</small></div>)}</div>}</section>
        <section className="panel runtime-panel"><div className="panel-heading"><div><p className="eyebrow">运行状态</p><h2>信号与验证证据</h2></div><span className="status-pill amber">{signalStatus?.paper_enabled ? "PAPER" : "观察模式"}</span></div><p className="muted">这里只展示采集和研究证据，不代表交易许可。形成中 K 线、数据过期或模型 Gate 未通过时，EVAL 会阻断后续动作。</p><div className="runtime-grid"><div><span>已接收事件</span><strong>{signalStatus?.events_seen ?? "-"}</strong></div><div><span>候选草案</span><strong>{signalStatus?.candidates_seen ?? "-"}</strong></div><div><span>EVAL 审核</span><strong>{signalStatus?.evaluations_created ?? "-"}</strong></div><div><span>测试证据</span><strong>{testSummary?.sample_count ?? 0} 笔 / {validation?.report?.test_evidence_status ?? "未生成"}</strong></div><div><span>OOS folds</span><strong>{validation?.report?.oos_fold_count ?? 0}</strong></div><div><span>历史证据范围</span><strong>{validationScope}</strong></div><div><span>安全快照覆盖</span><strong>{securityCoverage ? `${securityCoverage.checked_assets}/${securityCoverage.token_assets}` : "-"}</strong></div><div><span>模型校准</span><strong>{modelBenchmarks?.model_benchmarks?.models?.find((item) => item.model_type === "logistic_numpy")?.calibration?.platt?.status ?? "未生成"}</strong></div></div>{signalStatus?.last_error && <p className="notice red">运行组件暂时异常：{signalStatus.last_error}</p>}</section>
        <section className="panel notification-panel"><div className="panel-heading"><div><p className="eyebrow">DEVICE ALERTS</p><h2>iPhone Web Push</h2></div><span className="status-pill green">READ ONLY</span></div><p className="muted">Enable this device for EVAL-approved research alerts. No account, wallet, or order access is involved.</p><div className="notification-meta"><span>Server: {notificationStatus?.delivery_mode ?? "loading"}</span><span>Active devices: {notificationStatus?.web_push.active_subscriptions ?? 0}</span></div><div className="button-row"><button className="primary-button" onClick={enableNotifications}>Enable on this device</button><button className="quiet-button" onClick={sendTestNotification}>Send test</button></div>{notificationMessage && <p className="notice-inline">{notificationMessage}</p>}</section>
        <section className="panel dex-panel"><div className="panel-heading"><div><p className="eyebrow">DISCOVERY RADAR</p><h2>DEX pools</h2></div><span className="status-pill green">READ ONLY</span></div>{dexPairs.length === 0 ? <div className="empty-state"><strong>No DEX discovery snapshots</strong><span>Enable the public DEX Screener provider to collect new-pool observations.</span></div> : <div className="dex-list">{dexPairs.map((item) => <div className="dex-row" key={item.snapshot_id}><div><strong>{item.base_symbol}/{item.quote_symbol}</strong><small>{item.chain_id} · {item.dex_id}</small></div><span>Liquidity ${item.liquidity_usd == null ? "n/a" : Math.round(item.liquidity_usd).toLocaleString()}</span><span>5m vol ${item.volume_5m_usd == null ? "n/a" : Math.round(item.volume_5m_usd).toLocaleString()}</span><span>B/S {item.buys_5m ?? "-"}/{item.sells_5m ?? "-"}</span><em>{item.trust_status}</em></div>)}</div>}<div className="security-summary"><div><p className="eyebrow">TOKEN SAFETY</p><h3>安全快照</h3><span className="muted">覆盖 {securityCoverage ? `${securityCoverage.checked_assets}/${securityCoverage.token_assets}` : "-"} · {securityCoverage?.status ?? "loading"}</span></div>{dexSecurity.length === 0 ? <p className="muted">尚无安全快照。安全信息未确认时，EVAL 会拒绝 DEX / MEME Paper 计划。</p> : <div className="security-list">{dexSecurity.map((item) => <div className="security-row" key={item.security_snapshot_id}><strong>{item.asset_id}</strong><span className={item.status === "passed" ? "safe" : "blocked"}>{item.status}</span><span>{item.risk_level}</span><em>{item.eval_allowed ? "可进入后续审核" : "禁止 Paper"}</em></div>)}</div>}</div></section>
        <EvidenceCoveragePanel data={evidenceCoverage} />
        <RollDesk />
        <section className="panel research-panel"><div className="panel-heading"><div><p className="eyebrow">RESEARCH EVIDENCE</p><h2>滚仓统计证据</h2></div><span className="status-pill amber">RESEARCH ONLY</span></div><p className="muted">crypto_roll_v1.0.0 使用已实现利润滚入；Bayesian 和 Monte Carlo 只提供可审计证据，EVAL 仍是最终裁决层。</p><div className="research-grid"><div><span>策略版本</span><strong>crypto_roll_v1.0.0</strong><small>crypto_early_v1.0.0 仅作对照</small></div><div><span>当前候选</span><strong>{rollDecisions.length}</strong><small>不代表提醒或 Paper 权限</small></div><div><span>Bayesian 状态</span><strong>{bayesian?.item?.posterior?.most_likely_state ?? "N/A"}</strong><small>{bayesian?.item?.posterior?.evidence_status ?? "not collected"}</small></div><div><span>Monte Carlo</span><strong>{monteCarlo?.item?.status ?? monteCarlo?.status ?? "not collected"}</strong><small>历史不足时不输出概率</small></div></div>{rollDecisions.length === 0 ? <div className="empty-state"><strong>暂无滚仓决策快照</strong><span>在上方输入一个时点数据，生成可审计研究结果。</span></div> : <div className="roll-list">{rollDecisions.slice(0, 8).map((item) => <div className="roll-row" key={item.roll_id}><strong>{item.symbol}</strong><span className={`roll-action ${item.action === "DATA_BLOCKED" ? "blocked" : ""}`}>{item.action}</span><span>{item.rationale}</span><em>{item.source_status} · {Math.round(item.coverage * 100)}%</em></div>)}</div>}</section>
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
