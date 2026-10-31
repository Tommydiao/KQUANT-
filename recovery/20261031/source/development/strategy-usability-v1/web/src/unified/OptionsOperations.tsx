import { useEffect, useRef, useState, useSyncExternalStore, type ReactNode, type FormEvent } from "react";
import { operationsStreamConnected, operationsStreamConnectedAt, operationsStreamServerSnapshot, subscribeOperationsStream } from "./operationsStream";
import { ArrowLeft, ArrowRight, BarChart3, BellRing, Check, Copy, Download, Eye, EyeOff, FileText, Layers, X } from "lucide-react";
import { formatUiTime, optionReasonText, optionStateText, useI18n } from "./i18n";
import OptionRuntimeStatus from "./OptionRuntimeStatus";
import OptionsResearchWorkbench from "./OptionsResearchWorkbench";
import { StrategyComparisonCard } from "./StrategyComparisonCard";
import { currentCoverage, displaySymbol, jsonExport, paperRows, planCategory, type RecordData as Json } from "./operationalData";
import { useOperationalResource, type Resource } from "./useOperationalResource";
import { parseReviewedEvents } from "./eventReviewData";
import "./options-operations.css";
import { currentEligibilityValid, currentTrendContract, trendReferenceContract, displayedEligibilityState, currentResearchReady } from "./currentEligibility";
import { openingTrendText } from "./openingTrendText";
import { ManualReportError, reconcileManualReport, sendManualReport, type ManualReportPayload } from "./manualReportRequest";

function useCopy() {
  const { language } = useI18n();
  return (zh: string, en: string) => language === "zh" ? zh : en;
}

function isOpeningPolicy(row: Json) {
  return ["STRAT-OPENING-TREND-PULLBACK-5M-V1", "STRAT-OPENING-MOMENTUM-5M-V1"].includes(row.policy_id);
}

function Tabs({ items, value, change }: { items: [string, string][]; value: string; change: (v: string) => void }) {
  return <div className="ops-tabs" role="tablist">{items.map(([key, label]) => <button type="button" role="tab" key={key} aria-selected={value === key} onClick={() => change(key)}>{label}</button>)}</div>;
}

function Boundary({ resource, children }: { resource: Resource; children: ReactNode }) {
  const c = useCopy();
  return <>{resource.error ? <p role="alert" className="ops-warning">{c("请求失败", "Request failed")} · {resource.error}{resource.data ? ` · ${c("保留上次数据", "Showing previous data")} (${resource.receivedAt})` : ""}</p> : null}
    {!resource.data ? <div className="ops-empty" role="status">{resource.loading ? c("正在加载", "Loading") : c("数据不可用，刷新可重试", "Data unavailable; refresh to retry")}</div> : resource.data.current_policy_available === false ? <PolicyAvailabilityNotice data={resource.data} /> : children}</>;
}

export function PolicyAvailabilityNotice({ data }: { data: Json }) {
  const c = useCopy();
  if (data.current_policy_available !== false) return null;
  return <div role="alert" className="ops-warning">
    <strong>{c("配置未恢复，功能暂不可用", "Configuration unavailable; feature disabled")}</strong>
    <p>{c("相关扫描和确认操作已停用。历史记录与旧持仓状态未获本次核验，不能按空列表或零数量解释。", "Related scans and confirmations are disabled. Historical records and prior positions are unverified; an empty list or zero count is not established.")}</p>
    <small>{data.config_file} · {data.reason}</small>
  </div>;
}

export function copilotPaperAllowed(row: Json, status?: Json | null): boolean {
  if (!status || status.current_policy_available === false) return false;
  const twoHour = row.strategy_id === "STRAT-SHORT-ATM-RANGE-EXPANSION-2H-V1" || Boolean(row.payload?.capital_terms?.approval_hash);
  return Boolean(row.source_kind === "POSITION" && twoHour || (twoHour ? status.two_hour_paper_execution?.enabled : status.paper_execution?.enabled));
}

function Drawer({ title, close, children }: { title: string; close: () => void; children: ReactNode }) {
  const ref = useRef<HTMLDialogElement>(null);
  const c = useCopy();
  useEffect(() => { const element = ref.current; element?.showModal(); return () => element?.close(); }, []);
  return <dialog ref={ref} className="ops-drawer" onCancel={close}><header><h2>{title}</h2><button className="icon-button" title={c("关闭", "Close")} onClick={close}><X size={18} /></button></header><div className="ops-drawer-body">{children}</div></dialog>;
}

function Detail({ item, close }: { item: Json; close: () => void }) {
  const c = useCopy();
  const openingTrend = isOpeningPolicy(item);
  const oneMinute = openingTrend || item.policy_id === "STRAT-INTRADAY-MOMENTUM-1M-V1";
  const evidence = useOperationalResource(item.evaluation_id ? `/api/options/${oneMinute ? "one-minute" : "full-watch"}/evaluations/${encodeURIComponent(item.evaluation_id)}` : null, 0);
  const row = evidence.data?.evaluation ?? evidence.data ?? item;
  const qualification = openingTrend ? row.current_eligibility?.contract_qualification : row.contract_qualification;
  const events = openingTrend ? row.current_eligibility?.event_coverage : row.event_coverage;
  const names: Record<string, string> = { compression: c("收缩", "Compression"), participation: c("参与度", "Participation"), breakout: c("连续两根突破", "Two-bar breakout"), market: c("SPY市场过滤", "SPY filter") };
  return <Drawer title={c("为什么触发 / 尚缺什么", "Why triggered / what is missing")} close={close}>
    <h3>{displaySymbol(row)} · {row.right}</h3>
    {oneMinute ? <><p>{openingTrend ? c("开盘策略研究观察，非买入提示。", "Opening strategy observation, not an entry signal.") : c("一分钟研究观察；只有完整事件与合约资格才可能成为合格信号。", "One-minute research observation; event and contract checks must pass for a qualified signal.")}</p>
      <dl className="settings-lines">{Object.entries(row.factor_evidence ?? {}).filter(([key]) => key !== "history_source_hashes" && key !== "history_sessions").map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{typeof value === "number" ? value.toFixed(3) : JSON.stringify(value)}</dd></div>)}</dl>
      <p>{c("原因", "Reasons")}: {[...(row.current_eligibility?.reasons ?? []), ...(row.reasons ?? [])].map((v: string) => openingTrend ? openingTrendText(v, c("zh", "en")) : v).join(" · ") || c("未记录阻断", "No blocker recorded")}</p>
      <p>{c("合约资格", "Contract qualification")}: {qualification?.status ?? c("未运行", "Not run")}</p>
      <p>{c("事件核验", "Event review")}: {events?.status ?? c("未核验", "Not checked")}</p>
      {qualification?.rejected?.length ? <details><summary>{c("合约未通过的具体原因", "Contract rejection details")}</summary><pre>{JSON.stringify(qualification.rejected, null, 2)}</pre></details> : null}
      {item.evidence_deferred && !evidence.data ? <p role="status">{evidence.error ? c("完整证据读取失败，当前仅为摘要", "Full evidence unavailable; summary only") : c("正在读取完整证据", "Loading full evidence")}</p> : null}
      <button className="quiet-button" disabled={!!item.evidence_deferred && !evidence.data} onClick={() => jsonExport(evidence.data ?? row, `one-minute-${row.evaluation_id ?? "evidence"}`)}><Download size={16} />{c("导出原始证据", "Export raw evidence")}</button>
      <details><summary>{c("原始时间、历史来源与政策哈希", "Raw times, history sources and policy hash")}</summary><pre>{JSON.stringify(evidence.data ?? row, null, 2)}</pre></details></> : <>
    <dl className="settings-lines">{Object.entries(row.conditions ?? {}).map(([key, value]) => <div key={key}><dt>{names[key] ?? key}</dt><dd>{value === true ? c("满足", "Passed") : value === false ? c("未满足", "Not met") : c("待核验", "Unknown")}<small>{JSON.stringify(row.rule_evidence?.[key] ?? {})}</small></dd></div>)}</dl>
    <p>{row.event_reason ?? row.event_coverage?.status ?? c("事件审核信息未提供", "Event review not available")}</p>
    <p>{c("合约资格", "Contract qualification")}: {row.contract_qualification?.status ?? c("尚未验证，不可视为可交易合约", "Not verified; not an actionable contract")}</p>
    {evidence.error ? <p role="alert">{c("历史证据读取失败，保留当前记录", "History unavailable; showing current record")}</p> : null}
    <button className="quiet-button" onClick={() => jsonExport(evidence.data ?? row, `signal-${row.evaluation_id ?? "evidence"}`)}><Download size={16} />{c("导出证据", "Export evidence")}</button>
    <details><summary>{c("原始证据与历次评价", "Raw evidence and evaluation history")}</summary><pre>{JSON.stringify(evidence.data ?? row, null, 2)}</pre></details>
    </>}
  </Drawer>;
}

function ReadPanel({ path, refresh, review, symbol }: { path: string; refresh: number; review?: string; symbol: string }) {
  const result = useOperationalResource(path, refresh);
  const c = useCopy();
  const research = result.data?.research_result;
  return <Boundary resource={result}>{result.data ? review ? <OptionsResearchWorkbench symbol={symbol} payload={{}} {...{ [`review${review.toUpperCase()}`]: result.data }} /> : path.endsWith("workbench") ? <OptionsResearchWorkbench symbol={symbol} payload={result.data} /> : research ? <>
    <h3>CBRM · DEV_ONLY</h3><p>{c("独立开发研究，未用于活动策略筛选", "Independent development research; not used by the active strategy")}</p>
    <dl className="ops-metrics"><div><dt>BASE</dt><dd>{research.event_count ?? "—"}</dd></div>{["CALL", "PUT"].map(right => <div key={right}><dt>{right} F0 / F1 / F2</dt><dd>{["F0", "F1", "F2"].map(group => research.ablation?.[right]?.[group]?.mature ?? "—").join(" / ")}</dd></div>)}</dl>
    <details><summary>{c("拟合、审计与原始证据", "Fit, audit and evidence")}</summary><pre>{JSON.stringify(result.data, null, 2)}</pre></details>
  </> : <pre>{JSON.stringify(result.data, null, 2)}</pre> : null}</Boundary>;
}

function Records({ rows, actions, title, serverPaged = false }: { rows: Json[]; actions: (row: Json) => ReactNode; title: string; serverPaged?: boolean }) {
  const c = useCopy();
  const { language } = useI18n();
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(0);
  const filtered = rows.filter(row => `${displaySymbol(row)} ${row.contract_id ?? row.contract_symbol ?? ""} ${row.right ?? ""}`.toLowerCase().includes(query.toLowerCase()));
  const count = Math.max(1, Math.ceil(filtered.length / 10));
  const current = Math.min(page, count - 1);
  return <section className="ops-records" aria-label={title}>
    <div className="ops-filter"><h3>{title}</h3><input aria-label={c("搜索代码或合约", "Search symbol or contract")} placeholder={c("搜索代码或合约", "Search symbol or contract")} value={query} onChange={event => { setQuery(event.target.value); setPage(0); }} /><button className="icon-button" title={c("导出当前结果", "Export results")} onClick={() => jsonExport(filtered, "kquant-evidence")}><Download size={16} /></button></div>
    <div className="ops-table-scroll"><table><thead><tr><th>{c("标的 / 合约", "Symbol / contract")}</th><th>{c("方向 / 来源", "Right / source")}</th><th>{c("状态 / 原因", "State / reason")}</th><th>{c("时间 ET", "Time ET")}</th><th>{c("操作", "Actions")}</th></tr></thead><tbody>{filtered.slice(current * 10, current * 10 + 10).map((row, index) => <tr key={row.evaluation_id ?? row.intent_id ?? row.position_id ?? `${displaySymbol(row)}:${row.right}:${index}`}>
      <td><strong>{displaySymbol(row)}</strong><small>{row.contract_id ?? row.contract_symbol ?? row.payload?.contract?.contract_id ?? ""}</small></td>
      <td>{row.right ?? "-"}<small>{row.runtime_mode === "SHADOW_RESEARCH" ? c("观察，非买入提示", "Observation, not entry") : row.source_kind ? optionStateText(row.source_kind, language) : ""}</small></td>
      <td>{isOpeningPolicy(row) ? openingTrendText(row.observation_expired ? "EXPIRED" : row.current_eligibility?.state ?? row.state, language) : optionStateText(row.display_state ?? row.state ?? row.status ?? (row.active ? "WATCHING" : "UNKNOWN"), language)}<small>{Array.from(new Set([...(row.current_eligibility?.reasons ?? []), ...(row.blockers ?? []), ...(row.qualification_blockers ?? []), ...(row.reasons ?? []), row.event_reason, row.reason].filter(Boolean))).slice(0, 2).map((reason: string) => isOpeningPolicy(row) ? openingTrendText(reason, language) : optionReasonText(reason, language)).join(" · ")}</small></td>
      <td>{formatUiTime(row.evaluated_at ?? row.updated_at ?? row.watch_created_at ?? row.created_at, language)}</td><td><div className="ops-row-actions">{actions(row)}</div></td>
    </tr>)}</tbody></table>{!filtered.length ? <div className="ops-empty">{c("当前没有记录", "No records")}</div> : null}</div>
    {!serverPaged ? <footer><span>{filtered.length} {c("条记录", "records")}</span><button className="icon-button" title={c("上一页", "Previous page")} disabled={current === 0} onClick={() => setPage(current - 1)}><ArrowLeft size={16} /></button><span>{current + 1} / {count}</span><button className="icon-button" title={c("下一页", "Next page")} disabled={current + 1 >= count} onClick={() => setPage(current + 1)}><ArrowRight size={16} /></button></footer> : null}
  </section>;
}

function TrendHistory({ session, scope, refresh, onReason, strategy = "opening_trend" }: { session: string; scope: string; refresh: number; onReason: (row: Json) => void; strategy?: string }) {
  const c = useCopy();
  const [cursors, setCursors] = useState<(number | null)[]>([null]);
  const cursor = cursors[cursors.length - 1];
  const path = `/api/options/opening-trend/history?session=${encodeURIComponent(session)}&scope_hash=${encodeURIComponent(scope)}&research_strategy=${strategy}&limit=10${cursor === null ? "" : `&before=${cursor}`}`;
  const result = useOperationalResource(path, refresh);
  return <Boundary resource={result}>
    <Records serverPaged rows={result.data?.items ?? []} title={c("历史原判断（本页）", "Original history (this page)")}
      actions={row => <button className="quiet-button" onClick={() => onReason(row)}><FileText size={16} />{c("查看依据", "Evidence")}</button>} />
    <div className="ops-row-actions"><button className="icon-button" title={c("上一页", "Previous page")} disabled={result.loading || cursors.length === 1} onClick={() => setCursors(values => values.slice(0, -1))}><ArrowLeft size={16} /></button>
      <span>{c("页", "Page")} {cursors.length}</span><button className="icon-button" title={c("下一页", "Next page")} disabled={result.loading || !!result.error || !result.data?.next_before} onClick={() => setCursors(values => [...values, result.data!.next_before])}><ArrowRight size={16} /></button></div>
  </Boundary>;
}

export function OpeningTrendPanel({ refresh, onReason, onChain, onReport, onSaved }: { refresh: number; onReason: (row: Json) => void; onChain: (symbol: string) => void; onReport: (row: Json) => void; onSaved: () => void }) {
  const c = useCopy();
  const { language } = useI18n();
  const [tab, setTab] = useState("active");
  const [strategy, setStrategy] = useState<"opening_momentum" | "opening_trend">("opening_momentum");
  const momentum = strategy === "opening_momentum";
  const [eventSymbol, setEventSymbol] = useState("");
  const [comparisonView, setComparisonView] = useState("all");
  const result = useOperationalResource(`/api/options/one-minute/status?research_strategy=${strategy}&compact=true`, refresh, true);
  const live = useOperationalResource(`/api/options/opening-trend/current?research_strategy=${strategy}`, refresh, true);
  const connected = useSyncExternalStore(subscribeOperationsStream, operationsStreamConnected, operationsStreamServerSnapshot);
  const [clock, setClock] = useState(Date.now());
  useEffect(() => { const id = window.setInterval(() => setClock(Date.now()), 1000); return () => window.clearInterval(id); }, []);
  const data = result.data ?? live.data;
  const liveData = live.data;
  useEffect(() => {
    const times = (live.data?.candidates ?? []).flatMap((row: Json) => [
      Date.parse(row.deadline_at), Date.parse(row.current_eligibility?.valid_until),
      Date.parse(row.current_eligibility?.underlying_quote?.received_at) + 3000,
      Date.parse(row.current_eligibility?.contract_qualification?.selected?.snapshot?.bbo_received_at) + 3000,
    ]).filter((value: number) => Number.isFinite(value) && value > Date.now());
    if (!times.length) return;
    const timer = window.setTimeout(() => setClock(Date.now()), Math.max(1, Math.min(...times) - Date.now() + 1));
    return () => window.clearTimeout(timer);
  }, [live.data, clock]);
  const mergedRows = new Map<string, Json>();
  for (const r of [...(data?.evaluations ?? []), ...(liveData?.session === data?.session && liveData?.scope_hash === data?.scope_hash ? liveData?.evaluations ?? [] : [])]) {
    mergedRows.set(r.strategy_comparison?.economic_opportunity_id ?? r.evaluation_id, r);
  }
  const rows = [...mergedRows.values()].map((r: Json) => ({ ...r, observation_expired: !!r.deadline_at && Date.parse(r.deadline_at) <= clock }));
  const active = connected && !live.error && currentResearchReady(liveData) && (live.requestedAt ?? 0) >= operationsStreamConnectedAt() && liveData?.approvals?.qualified_signal_pipeline_enabled === true
    ? (liveData.candidates ?? []).filter((r: Json) => currentEligibilityValid(r, clock)) : [];
  const waiting = rows.filter((r: Json) => !r.strategy_comparison && ["WAIT_TREND", "WAIT_PULLBACK", "NUMERIC_PASS"].includes(r.state) && !r.observation_expired
    && !["WITHDRAWN", "EXPIRED"].includes(r.current_eligibility?.state));
  const technical = rows.filter((r: Json) => !r.strategy_comparison && r.state === "NUMERIC_PASS" && !r.observation_expired
    && !["EXPIRED"].includes(r.current_eligibility?.state) && !active.some((a: Json) => a.evaluation_id === r.evaluation_id));
  const comparisons = rows.filter((r: Json) => r.strategy_comparison && (comparisonView === "all"
    || r.strategy_comparison.s0.state !== r.strategy_comparison.s1.state));
  const actions = (row: Json) => <><button className="quiet-button" onClick={() => onReason(row)}><FileText size={16} />{c("查看依据", "Evidence")}</button><button className="icon-button" title={c("期权链", "Option chain")} onClick={() => onChain(displaySymbol(row))}><Layers size={16} /></button>{row.bar_evidence ? <button className="quiet-button" onClick={() => onReport(row)}>{row.strategy_comparison ? c("按S0登记独立交易", "Report independent S0 trade") : c("登记独立自报交易", "Report independent trade")}</button> : null}</>;
  return <section className="ops-one-minute" aria-label={momentum ? c("早盘顺势", "Opening momentum") : c("开盘趋势回踩", "Opening trend pullback")}>
    <Tabs items={[["opening_momentum", c("早盘顺势", "Opening momentum")], ["opening_trend", c("旧回踩对照", "Pullback comparison")]]} value={strategy} change={value => { setStrategy(value as typeof strategy); setEventSymbol(""); }} />
    <div className="ops-run"><div><strong>{momentum ? c("早盘顺势", "Opening momentum") : c("开盘趋势回踩", "Opening trend pullback")}</strong><small>{momentum ? "09:35–10:00 ET" : "09:30–10:00 ET"} · {c("最晚01:30北京时间退出 · 研究版", "Exit by 01:30 Beijing time · Research")}</small></div></div>
    <Tabs items={[["active", c("机会与资格", "Opportunities and eligibility")], ["waiting", momentum ? c("研究观察", "Observations") : c("等待回踩", "Watching")], ["positions", c("持仓与退出", "Positions and exits")], ["history", c("历史与诊断", "History and diagnostics")]]} value={tab} change={setTab} />
    {!connected ? <p className="ops-warning" role="alert">{c("实时连接不可用，当前资格无法确认", "Live connection unavailable; eligibility cannot be confirmed")}</p> : null}
    {live.error ? <p className="ops-warning" role="alert">{c("当前信号通道不可用，不能确认操作资格", "Current signal channel unavailable; eligibility unverified")}</p> : null}
    {data?.snapshot?.state === "STALE" ? <p className="ops-warning" role="alert">{c("当前显示旧快照，资格无法确认", "Showing a stale snapshot; eligibility is unverified")} · {formatUiTime(data.snapshot.as_of, language)}</p> : null}
    {tab === "positions" ? <OneMinuteManualPanel refresh={refresh} saved={onSaved} /> : <Boundary resource={{ ...result, data }}>{data ? <>
      <TrendStatusHealth data={data} />
      <TrendCalculationSummary coverage={data.checkpoint_coverage} />
      {momentum && (tab === "active" || tab === "waiting") ? <section aria-label="S0/S1">
        <label>{c("S0/S1研究", "S0/S1 research")} <select value={comparisonView} onChange={event => setComparisonView(event.target.value)}><option value="all">{c("全部结果", "All results")}</option><option value="differences">{c("差异结果", "Differences")}</option></select></label>
        <div className="ops-signal-list">{comparisons.map((row: Json) => <StrategyComparisonCard key={row.evaluation_id} row={row} now={clock} connected={connected && !result.error && data.snapshot?.state !== "STALE"} actions={actions(row)} />)}</div>
        {data.evaluations_deferred ? <p>{c("更多标的和检查点见历史与诊断", "More instruments and checkpoints in history and diagnostics")}</p> : null}
      </section> : null}
      <div className="ops-signal-banner" role="status"><strong>{data.session_state === "NON_TRADING_DAY" ? c("休市日 · 等待下一交易日", "Market closed · awaiting next session") : active.length ? `${c("合格信号", "Qualified signals")} ${active.length}` : c("当前没有已核验的可操作信号", "No verified actionable signal")}</strong><span>{data.session_state === "NON_TRADING_DAY" ? `${c("下一交易日", "Next session")}: ${data.scope_observation?.next_session ?? "—"}` : (data.blockers ?? []).map((v: string) => openingTrendText(v, language)).join(" · ")}</span></div>
      <p className="ops-status-line">{c("交易日", "Session")}: {data.session ?? "—"} · {c("最近评价", "Last evaluation")}: {formatUiTime(data.last_evaluation_at, language)} · {c("已评价方向", "Evaluated directions")}: {data.summary?.evaluated_directions ?? "—"}</p>
      {tab === "active" ? active.length ? <div className="ops-signal-list">{active.map((row: Json) => <TrendSignalCard key={row.evaluation_id} row={row} now={clock} actions={actions(row)} />)}</div> : <p className="ops-empty">{data.state === "NOT_STARTED" || data.state === "NO_CURRENT_SESSION_EVALUATIONS" ? c("本版尚无当日评价，不能判断为没有机会", "No evaluation for this session; cannot conclude no opportunity") : c("研究记录不等于买入提示；查看等待回踩或诊断", "Research records are not entry signals; see watching or diagnostics")}</p> : null}
      {tab === "active" && technical.length ? <section aria-label={c("技术机会", "Technical opportunities")}><h3>{c("技术机会 · 非买入提示", "Technical opportunities · not entry signals")}</h3><div className="ops-signal-list">{technical.map((row: Json) => <TrendObservationCard key={row.evaluation_id} row={row} now={clock} connected={connected && !result.error && data.snapshot?.state !== "STALE" && (result.requestedAt ?? 0) >= operationsStreamConnectedAt()} actions={actions(row)} />)}</div></section> : null}
      {tab === "waiting" ? <Records rows={waiting} title={c("观察，非买入提示", "Observations, not entries")} actions={actions} /> : null}
      {tab === "history" ? <>{data.session && data.scope_hash ? <TrendHistory key={`${strategy}:${data.session}:${data.scope_hash}`} strategy={strategy} session={data.session} scope={data.scope_hash} refresh={refresh} onReason={onReason} /> : <p className="ops-warning">{c("历史范围尚未确认", "History scope not confirmed")}</p>}
        <TrendCheckpointCoverage coverage={data.checkpoint_coverage} strategy={strategy} onReason={onReason} />
        <label className="ops-status-line">{c("事件补证标的", "Event evidence symbol")}<select value={eventSymbol} onChange={event => setEventSymbol(event.target.value)}>
          <option value="">{c("选择标的", "Select a symbol")}</option>{(data.registered_items ?? []).map((row: Json) => <option key={row.symbol} value={row.symbol}>{row.symbol}</option>)}
        </select></label>
        {eventSymbol ? <EventSourcesPanel key={`${strategy}:${eventSymbol}`} symbol={eventSymbol} refresh={refresh} strategy={strategy} /> : null}
        <details><summary>{c("版本与运行诊断", "Version and runtime diagnostics")}</summary><pre>{JSON.stringify({ policy: data.policy, worker: data.worker }, null, 2)}</pre></details></> : null}
    </> : null}</Boundary>}
  </section>;
}

export function TrendSignalCard({ row, now, actions }: { row: Json; now: number; actions?: ReactNode }) {
  const c = useCopy();
  const { language } = useI18n();
  const [copyState, setCopyState] = useState("");
  const contract = currentTrendContract(row);
  if (!contract || !currentEligibilityValid(row, now)) return null;
  const number = (value: unknown, digits = 2) => typeof value === "number" && Number.isFinite(value)
    ? value.toLocaleString(language === "zh" ? "zh-CN" : "en-US", { minimumFractionDigits: digits, maximumFractionDigits: 4 }) : "—";
  const currency = typeof contract.quote_currency === "string" && /^[A-Z]{3}$/.test(contract.quote_currency)
    ? contract.quote_currency : c("币种待核验", "Currency unverified");
  const premium = typeof contract.ask === "number" && contract.ask > 0 && Number.isFinite(contract.ask)
    && typeof contract.multiplier === "number" && Number.isSafeInteger(contract.multiplier) && contract.multiplier > 0
    ? contract.ask * contract.multiplier : null;
  const copy = async () => {
    try { await navigator.clipboard.writeText(contract.contract_id); setCopyState(c("已复制", "Copied")); }
    catch { setCopyState(c("复制失败，可选中合约代码", "Copy failed; select the contract code")); }
  };
  return <article className="ops-signal-item ops-trend-signal" aria-label={`${displaySymbol(row)} ${row.right} ${contract.expiry_date} ${contract.strike}`}>
    <div className="ops-signal-identity"><strong>{displaySymbol(row)} · {row.right === "CALL" ? c("看涨 Call", "Call") : c("看跌 Put", "Put")}</strong>
      <div className="ops-row-actions"><span>{contract.contract_id}</span><button className="icon-button" title={c("复制合约代码", "Copy contract code")} onClick={() => void copy()}><Copy size={16} /></button></div>
      {copyState ? <small role="status">{copyState}</small> : null}
      <dl className="ops-contract-facts"><div><dt>{c("到期日", "Expiry date")}</dt><dd>{contract.expiry_date}</dd></div><div><dt>{c("行权价", "Strike price")}</dt><dd>{number(contract.strike)}</dd></div>
        <div><dt>{c("剩余自然日", "Calendar DTE")}</dt><dd>{Number.isInteger(contract.dte) ? contract.dte : "—"}</dd></div><div><dt>{c("报价乘数", "Quote multiplier")}</dt><dd>{number(contract.multiplier, 0)}</dd></div></dl>
    </div>
    <div className="ops-signal-why"><strong>{c("买一 / 卖一", "Bid / ask")}: {number(contract.bid)} / {number(contract.ask)}</strong>
      <p>{c("每张参考权利金（按卖一，未含费用）", "Premium per contract (ask, before fees)")}: {number(premium)} · {currency}</p>
      <small>{c("盘口接收时间", "Depth received")}: {formatUiTime(contract.snapshot?.bbo_received_at, language)}</small>
    </div>
    <div className="ops-signal-when"><strong>{c("正股参考入场区间", "Underlying entry range")}: {row.entry_range?.map((v: number) => number(v)).join(" – ") ?? "—"}</strong>
      <small>{c("结构失效价", "Structure invalidation")}: {number(row.structure_line)}</small>
      <strong>{c("形态剩余", "Setup remaining")}: {Math.max(0, Math.ceil((Date.parse(row.deadline_at) - now) / 1000))}s</strong>
      <small>{c("最近资格核验", "Eligibility checked")}: {formatUiTime(row.current_eligibility?.checked_at, language)}</small>
      <small>{row.research_strategy === "opening_momentum" ? c("当日方向一致，完整5分钟价格形态确认", "Daily direction aligned; complete five-minute price setup") : c("当日方向一致，开盘突破后回踩确认", "Daily trend aligned; opening breakout and pullback confirmed")}</small>
    </div>
    <div className="ops-row-actions">{actions}</div>
    <TrendEventRisk decision={row.current_eligibility?.event_decision} />
  </article>;
}

export function TrendEventRisk({ decision }: { decision?: Json }) {
  const c = useCopy();
  const { language } = useI18n();
  if (!decision) return <p className="ops-warning">{c("事件风险尚未核验", "Event risk not checked")}</p>;
  return <div className={decision.decision === "PASS" ? "ops-status-line" : "ops-warning"} role="status">
    <strong>{openingTrendText(`EVENT_DECISION_${decision.decision}`, language)}</strong>
    {(decision.warnings ?? []).map((reason: string) => <p key={reason}>{openingTrendText(reason, language)}</p>)}
    {[...(decision.blocking_events ?? []), ...(decision.review_events ?? [])].map((event: Json, index: number) => <p key={index}>{event.name ?? event.event_type} · {formatUiTime(event.start_at, language)}{event.decision_reason ? ` · ${openingTrendText(event.decision_reason, language)}` : ""}</p>)}
    <small>{c("风险核验时间", "Risk checked")}: {formatUiTime(decision.checked_at, language)}</small>
  </div>;
}

export function TrendObservationCard({ row, now, connected, actions }: { row: Json; now: number; connected: boolean; actions?: ReactNode }) {
  const c = useCopy();
  const { language } = useI18n();
  const contract = trendReferenceContract(row);
  const current = row.current_eligibility ?? {};
  const number = (value: unknown) => typeof value === "number" && Number.isFinite(value) ? value.toLocaleString(language === "zh" ? "zh-CN" : "en-US", { maximumFractionDigits: 4 }) : "—";
  return <article className="ops-signal-item ops-trend-observation" aria-label={`${displaySymbol(row)} ${row.right} ${c("技术观察", "technical observation")}`}>
    <div className="ops-signal-identity"><strong>{displaySymbol(row)} · {row.right}</strong><p>{c("数学形态通过，非买入提示", "Mathematical setup passed; not an entry signal")}</p>
      <small>{c("原形态期限", "Original setup deadline")}: {formatUiTime(row.deadline_at, language)} · {Math.max(0, Math.ceil((Date.parse(row.deadline_at) - now) / 1000))}s</small></div>
    <div className="ops-signal-why"><strong>{c("正股原参考区间", "Original underlying range")}: {row.entry_range?.map(number).join(" – ") ?? "—"}</strong>
      <p>{openingTrendText(displayedEligibilityState(row, now, connected), language)}</p>{!connected ? <p className="ops-warning">{c("连接不可用，不能确认当前资格", "Connection unavailable; current eligibility unconfirmed")}</p> : null}
      {(current.reasons ?? []).map((reason: string) => <small key={reason}>{openingTrendText(reason, language)}</small>)}</div>
    <div className="ops-signal-when">{contract ? <><strong>{c("具体期权参考，非推荐", "Specific option reference, not a recommendation")}</strong><p>{contract.contract_id}</p>
      <small>{c("到期 / 行权价 / 方向", "Expiry / strike / right")}: {contract.expiry_date} / {number(contract.strike)} / {contract.right}</small>
      <small>{c("原始买一 / 卖一", "Raw bid / ask")}: {number(contract.bid)} / {number(contract.ask)} · {contract.quote_currency ?? c("币种未核验", "Currency unverified")}</small>
      <small>{c("原始报价时间", "Original quote received")}: {formatUiTime(contract.snapshot?.bbo_received_at, language)}</small>
      <p className="ops-warning">{current.reference_contract_status === "PASS" ? c("留档合约核验通过，不代表当前买入资格", "Recorded contract check passed; current entry eligibility is separate") : c("合约未核验，不计算默认每张金额", "Contract unverified; no assumed per-contract amount")}</p></> : <p>{c("具体合约尚未取得或无匹配合约", "Specific contract not available or no matching contract")}</p>}</div>
    <TrendEventRisk decision={current.event_decision} /><div className="ops-row-actions">{actions}</div>
  </article>;
}

function CheckpointWait({ coverage }: { coverage: Json }) {
  const c = useCopy();
  const minutes = (coverage.checkpoint_minutes ?? []).filter((value: unknown) => typeof value === "number" && Number.isFinite(value));
  if (!minutes.length) return <>{c("等待活动策略的首个完整检查点", "Awaiting the active strategy's first complete checkpoint")}</>;
  const first = Math.min(...minutes);
  const time = `${String(9 + Math.floor((30 + first) / 60)).padStart(2, "0")}:${String((30 + first) % 60).padStart(2, "0")} ET`;
  return <>{c("等待首个检查点", "Awaiting the first checkpoint")} · {time}</>;
}

export function TrendCalculationSummary({ coverage }: { coverage?: Json }) {
  const c = useCopy();
  const { language } = useI18n();
  const points = coverage?.checkpoints ?? [];
  const point = points[points.length - 1];
  if (coverage?.projection?.state === "PROJECTION_CATCHING_UP") return <p className="ops-warning" role="status">{c("正在补齐检查点对账，计算结果暂不可确认", "Checkpoint reconciliation catching up; calculation results are not yet confirmed")} · {coverage.projection.records} / {coverage.projection.source_count} {c("条评价记录", "evaluation records")}</p>;
  if (!coverage || ["UNAVAILABLE", "SCOPE_UNAVAILABLE"].includes(coverage.state)) return <p className="ops-warning" role="status">{c("计算覆盖暂不可用，不能判断为没有机会", "Calculation coverage unavailable; no-opportunity conclusion is not available")}</p>;
  if (!point) return <p className="ops-status-line">{coverage.state === "NON_TRADING_DAY" ? c("非交易日，无开盘检查点", "Non-trading day; no opening checkpoints") : <CheckpointWait coverage={coverage} />}</p>;
  const incomplete = typeof point.numeric_directions !== "number" || point.numeric_directions < point.registered_directions;
  const reasons = new Map<string, number>();
  for (const [reason, count] of Object.entries(point.reason_counts ?? {})) reasons.set(reason, Number(count));
  for (const item of point.items ?? []) {
    for (const reason of new Set<string>(item.reasons ?? [])) reasons.set(reason, (reasons.get(reason) ?? 0) + 1);
  }
  const leading = [...reasons].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).slice(0, 5);
  return <section aria-label={c("最新检查点计算结果", "Latest checkpoint calculation")}>
    <p className={incomplete ? "ops-warning" : "ops-status-line"} role="status"><strong>{point.numeric_directions === 0
      ? c("本次数值计算未完成，不能判断为没有机会", "Numeric calculation incomplete; cannot conclude no opportunity")
      : incomplete ? c("本次计算仅部分完成，仍有方向未完成核验", "Calculation partially complete; some directions remain unverified")
      : c("本次数值计算完成，不等于合约或入场资格通过", "Numeric calculation complete; contract and entry eligibility are separate")}</strong></p>
    <p className="ops-status-line">{c("检查点", "Checkpoint")}: {formatUiTime(point.bar_end, language)} · {c("按方向统计，不跨检查点累加", "Direction counts; checkpoints are not summed")}</p>
    <dl className="ops-metrics" aria-label={c("同检查点处理链", "Same-checkpoint pipeline")}>{[
      ["registered", c("登记", "Registered")], ["input_complete", c("输入完整", "Inputs complete")],
      ["numeric_complete", c("数值完成", "Numeric complete")], ["setup_triggered", c("形态触发", "Setup triggered")],
      ["event_passed", c("事件资料完整", "Event coverage complete")], ["event_warned", c("事件缺口提示", "Event coverage warnings")],
      ["contract_passed", c("合约通过", "Contracts passed")],
      ["actionable", c("当前可操作", "Actionable now")],
    ].map(([key, label]) => {
      const stage = point.pipeline_stages?.[key];
      return <div key={key}><dt>{label}</dt><dd>{stage?.state === "COUNTED" && typeof stage.directions === "number" ? stage.directions
        : stage?.state === "NOT_RUN" ? c("未执行", "Not run") : c("不可用", "Unavailable")}</dd></div>;
    })}</dl>
    {point.pipeline_stages ? <p className="ops-status-line">{c("事件与合约按最近留档核验统计，当前可操作另按当前期限与报价检查", "Event and contract stages use the latest recorded checks; actionable status separately checks current deadlines and quotes")}</p> : null}
    <dl className="ops-metrics">{[[c("登记方向", "Registered directions"), point.registered_directions], [c("有评价记录", "Evaluation recorded"), point.evaluated_directions], [c("数值完整", "Numeric complete"), point.numeric_directions], [c("计算不完整", "Calculation incomplete"), point.explicitly_incomplete_directions], [c("系统漏评", "System gaps"), point.missing_directions], [c("身份未确认", "Identity unverified"), point.identity_excluded_directions]].map(([name, value]) => <div key={name}><dt>{name}</dt><dd>{value ?? "—"}</dd></div>)}</dl>
    {leading.length ? <p className="ops-status-line">{c("主要原因（同一方向可有多项）", "Main reasons (a direction may have several)")}: {leading.map(([reason, count]) => `${openingTrendText(reason, language)}: ${count}`).join(" · ")}</p> : null}
  </section>;
}

export function TrendStatusHealth({ data }: { data: Json }) {
  const c = useCopy();
  const { language } = useI18n();
  const clock = data.worker?.qualification?.clock_health;
  const error = data.snapshot?.error_detail;
  const fault = clock?.state === "CLOCK_DISCONTINUITY";
  const external = data.external_clock;
  const synchronized = external?.state === "SYNCED_SYSTEM_REPORT";
  const source = data.worker?.price_action_sources ?? {};
  const budget = data.worker?.source_request_budget ?? {};
  const sourceCall = data.worker?.source_call ?? {};
  const worker = data.worker ?? {};
  const observation = data.service_observation;
  const ready = worker.research_ready === true && (!observation?.enforced || observation.state === "RUNNING");
  return <section aria-label={c("运行与时钟核验", "Runtime and clock checks")}>
    {observation ? <p className={observation.state === "RUNNING" ? "ops-status-line" : "ops-warning"} role={observation.state === "RUNNING" ? "status" : "alert"}>
      {c("实际服务", "Observed service")}: {observation.state ?? "UNAVAILABLE"}
      {" · "}{c("原清单", "Recorded state")}: {observation.reported_state ?? "UNKNOWN"}
      {" · "}{c("最近心跳", "Last heartbeat")}: {formatUiTime(observation.heartbeat_at, language)}
      {" · "}{c("退出原因", "Exit reason")}: {observation.exit_reason ?? "—"}
    </p> : null}
    {observation?.recovery_reason === "PREVIOUS_BOOT_NOT_RESTARTED" ? <p className="ops-warning" role="alert">
      {c("上次运行属于重启前的系统会话，尚未重新启动", "The previous run belongs to an earlier system boot and has not restarted")}
    </p> : null}
    {observation ? <details><summary>{c("运行身份与观察时间", "Run identity and observation time")}</summary>
      <p className="ops-status-line">{c("观察时间", "Observed at")}: {formatUiTime(observation.observed_at, language)}
        {" · "}{c("系统启动", "System boot")}: {formatUiTime(observation.system_boot?.started_at, language)}
        {" · "}{c("运行会话", "Run session")}: {observation.run_session_id ?? "—"}</p>
    </details> : null}
    <p className={ready ? "ops-status-line" : "ops-warning"} role={ready ? "status" : "alert"}>
      {c("研究主循环", "Research loop")}: {ready ? c("已就绪", "Ready") : c("未就绪，不能确认正常扫描", "Not ready; normal scanning is not established")} · {worker.state ?? "UNKNOWN"}
      {" · "}{c("循环次数", "Loop count")}: {worker.loop_count ?? "—"}
      {" · "}{c("最近推进", "Last progress")}: {formatUiTime(worker.last_cycle_at ?? worker.first_loop_at, language)}
      {!ready && worker.failed_stage ? ` · ${worker.failed_stage}` : ""}
      {!ready && worker.error_id ? ` · ${worker.error_id}` : ""}
    </p>
    <p className={fault ? "ops-warning" : "ops-status-line"}>{c("外部校时", "External synchronization")}: {synchronized ? c("Windows报告已同步", "Windows reports synchronized") : external?.state === "SYNC_REPORT_STALE" ? c("同步记录已过时", "Synchronization report stale") : c("未验证", "Not verified")} · {c("运行中时钟", "Runtime clock")}: {fault
      ? c("检测到跳变，即时资格暂停", "Discontinuity detected; immediate eligibility paused")
      : clock?.state === "CONTINUOUS_NOT_SYNC_VERIFIED" ? c("未发现跳变，不代表已经校准", "Continuous, not proof of synchronization")
      : c("未取得检查结果", "Check unavailable")}</p>
    {external?.checked_at ? <p className="ops-status-line">{external.source ?? "—"} · {c("检查时间", "Checked at")}: {formatUiTime(external.checked_at, language)} · {c("系统同步状态不代表精密误差保证或信号批准", "System synchronization is not a precision guarantee or signal approval")}</p> : null}
    {error ? <p role="alert" className="ops-warning">{c("状态读取失败", "Status query failed")}: {error.code} · {error.phase} · {c("退出码", "Exit code")}: {error.returncode ?? "—"} · {error.elapsed_ms ?? "—"}ms · {c("旧快照", "Previous snapshot")}: {formatUiTime(data.snapshot.as_of, language)}</p> : null}
    {data.query_transport ? <details><summary>{c("状态查询诊断", "Status query diagnostics")}</summary><p className="ops-status-line">{c("工作进程总耗时", "Worker process total")}: {data.query_transport.process_ms}ms · {c("响应字节", "Response bytes")}: {data.query_transport.response_bytes}</p><pre>{JSON.stringify(data.query_phases_ms ?? {}, null, 2)}</pre></details> : null}
    <details><summary>{c("来源刷新与请求依据", "Source refresh and request evidence")}</summary>
      <p className="ops-status-line">{c("核对时间", "Checked at")}: {formatUiTime(source.checked_at, language)} · {c("来源调用", "Source call")}: {sourceCall.in_flight === true ? c("仍在执行", "In flight") : sourceCall.in_flight === false ? c("空闲", "Idle") : c("未执行或未知", "Not run or unknown")}</p>
      <dl className="ops-metrics">{[[c("有效来源", "Fresh sources"), source.coverage_counts?.fresh], [c("已过期", "Expired"), source.coverage_counts?.expired], [c("延期", "Deferred"), source.coverage_counts?.deferred], [c("首次覆盖最长等待秒数", "Oldest first-coverage wait seconds"), source.coverage_counts?.oldest_first_coverage_age_seconds]].map(([name, value]) => <div key={name}><dt>{name}</dt><dd>{value ?? "—"}</dd></div>)}</dl>
      <p className="ops-status-line">{c("本地预算 已用/上限", "Local budget used/cap")}: {budget.used ?? "—"}/{budget.local_cap ?? "—"} · {c("供应商额度依据", "Provider limit evidence")}: {budget.provider_limit_verified === true ? c("已核验", "Verified") : c("未核验", "Unverified")}</p>
      {(source.recent_observations ?? []).slice(0, 5).map((item: Json) => <div key={item.symbol}>
        <strong>{item.symbol} · {item.state ?? "UNKNOWN"}</strong>
        <p>{c("所需覆盖", "Desired coverage")}: {item.desired_from ?? "—"} → {item.desired_through ?? "—"} · {c("资料有效截止", "Source valid until")}: {formatUiTime(item.valid_until, language)}</p>
        <p>{c("实际接口参数，非网络抓包", "Actual interface arguments, not a wire capture")}: {item.actual_query ? JSON.stringify(item.actual_query) : c("未取得请求依据", "Request evidence unavailable")} · {item.interface ?? "—"}</p>
        <p>{item.capability ?? ""} {(item.reasons ?? []).join(" · ")}</p>
        <small>{c("观测ID", "Observation ID")}: {item.observation_id ?? "—"}</small>
      </div>)}
      {source.omitted_records > 0 ? <p>{c("其他记录数", "Other records")}: {source.omitted_records}</p> : null}
    </details>
  </section>;
}

export function TrendCheckpointCoverage({ coverage, onReason, strategy = "opening_trend" }: { coverage?: Json; onReason: (row: Json) => void; strategy?: string }) {
  const c = useCopy();
  const { language } = useI18n();
  const [selected, setSelected] = useState("");
  const [offset, setOffset] = useState(0);
  const [reload, setReload] = useState(0);
  const points = coverage?.checkpoints ?? [];
  const point = points.find((r: Json) => r.bar_end === selected) ?? points[points.length - 1];
  const path = point?.items_deferred ? `/api/options/opening-trend/coverage?${new URLSearchParams({
    session: coverage!.session, scope_hash: coverage!.scope_hash, checkpoint: point.bar_end,
    research_strategy: strategy, offset: String(offset), limit: "50" })}` : null;
  const page = useOperationalResource(path, reload);
  if (!coverage || coverage.state === "UNAVAILABLE" || coverage.state === "SCOPE_UNAVAILABLE") return <p className="ops-warning">{c("同检查点覆盖不可用", "Checkpoint coverage unavailable")}</p>;
  if (!point) return <p className="ops-status-line">{coverage.state === "NON_TRADING_DAY" ? c("非交易日，不产生开盘评价", "Non-trading day; no opening evaluation") : <CheckpointWait coverage={coverage} />}</p>;
  const names: Record<string, string> = { IDENTITY_UNRESOLVED: c("身份未确认", "Identity unverified"), MISSING_EVALUATION: c("漏评：无持久记录", "Missing evaluation: no persistent record"), PENDING_EVALUATION: c("等待评价", "Pending evaluation") };
  const rows = (point.items ?? page.data?.items ?? []).map((r: Json) => ({ ...r, display_state: names[r.state] ?? openingTrendText(r.state, language), policy_id: undefined }));
  return <section aria-label={c("同检查点覆盖", "Same-checkpoint coverage")}>
    <label className="ops-status-line">{c("检查点", "Checkpoint")}<select value={point.bar_end} onChange={event => { setSelected(event.target.value); setOffset(0); }}>{points.map((r: Json) => <option key={r.bar_end} value={r.bar_end}>{formatUiTime(r.bar_end, language)}</option>)}</select></label>
    {path ? <div className="ops-row-actions"><button className="icon-button" title={c("上一页", "Previous page")} disabled={offset === 0} onClick={() => setOffset(Math.max(0, offset - 50))}><ArrowLeft size={16} /></button>
      <span>{offset + 1}–{Math.min(offset + 50, page.data?.total ?? point.items_total)} / {page.data?.total ?? point.items_total}</span>
      <button className="icon-button" title={c("下一页", "Next page")} disabled={page.loading || page.data?.next_offset == null} onClick={() => setOffset(page.data!.next_offset)}><ArrowRight size={16} /></button>
      <button className="quiet-button" onClick={() => setReload(v => v + 1)}>{c("刷新明细", "Refresh details")}</button>
      {page.error ? <span role="alert">{c("明细读取失败", "Details unavailable")}: {page.error}</span> : null}</div> : null}
    <dl className="ops-metrics">{[[c("登记方向", "Registered directions"), point.registered_directions], [c("已评价", "Evaluated"), point.evaluated_directions], [c("数值完整", "Numeric complete"), point.numeric_directions], [c("明确缺资料", "Explicitly incomplete"), point.explicitly_incomplete_directions], [c("系统漏评", "System gaps"), point.missing_directions], [c("身份排除", "Identity exclusions"), point.identity_excluded_directions]].map(([name, value]) => <div key={name}><dt>{name}</dt><dd>{value ?? "—"}</dd></div>)}</dl>
    <Records rows={rows} title={c("逐方向对账，非合格信号", "Direction accounting, not qualified signals")} actions={row => row.evaluation_id ? <button className="icon-button" title={c("查看原评价", "View original evaluation")} onClick={() => onReason({ ...row, policy_id: row.policy_id ?? "STRAT-OPENING-TREND-PULLBACK-5M-V1" })}><FileText size={16} /></button> : null} />
  </section>;
}

function Summary({ two }: { two: Json }) {
  const c = useCopy();
  const { language } = useI18n();
  const s = two.summary ?? {};
  const completeDirections = (two.current_evaluations ?? []).filter((row: Json) => row.data_complete === true && !(row.blockers ?? []).length).length;
  return <><div className="ops-run"><div><strong>{c("开盘两小时研究", "Opening two-hour research")}</strong><small>{two.policy?.policy_id ?? "-"} · {s.session ?? "-"} · 09:40–11:30 ET</small></div><span>{optionStateText(two.worker?.state ?? two.status, language)}</span></div>
    <dl className="ops-metrics">{[
      [c("当日自选登记", "Registered today"), s.registered_symbols], [c("已评价标的", "Evaluated symbols"), s.evaluated_symbols],
      [c("就绪但未评价", "Ready but unassessed"), s.unassessed_ready_symbols],
      [c("完整方向计算", "Complete directions"), completeDirections], [c("数值计算齐全", "Numeric calculations"), s.numeric_directions],
      [c("未完成方向", "Incomplete directions"), typeof s.evaluated_directions === "number" ? s.evaluated_directions - completeDirections : null], [c("当前合格信号", "Qualified signals now"), two.qualified_signals?.length],
    ].map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{value ?? "—"}</dd></div>)}</dl>
    <div className="ops-status-line"><span>{c("最新闭合K线", "Latest closed bar")}: {formatUiTime(s.last_bar_end, language)}</span><span>{c("最近计算", "Last calculation")}: {formatUiTime(s.last_evaluation_at, language)}</span><span>{c("迟到记录", "Late records")}: {s.late_records ?? "—"}</span><span>{c("新版Paper待审批 · 实盘关闭", "New Paper approval pending · Live trading disabled")}</span></div></>;
}

export function OneMinutePanel({ one, snapshotRequestedAt = 0, snapshotFailed = false, onReason, onChain, onReport }: { one: Json; snapshotRequestedAt?: number; snapshotFailed?: boolean; onReason: (row: Json) => void; onChain: (symbol: string) => void; onReport: (row: Json) => void }) {
  const c = useCopy();
  const { language } = useI18n();
  const s = one.summary;
  const [clock, setClock] = useState(Date.now());
  useEffect(() => { const id = window.setInterval(() => setClock(Date.now()), 1000); return () => window.clearInterval(id); }, []);
  const candidates = one.candidates ?? [];
  const streamConnected = useSyncExternalStore(subscribeOperationsStream, operationsStreamConnected, operationsStreamServerSnapshot);
  const active = candidates.filter((row: Json) => {
    return streamConnected && !snapshotFailed && snapshotRequestedAt >= operationsStreamConnectedAt()
      && currentEligibilityValid(row, clock)
      && one.snapshot?.state !== "STALE" && one.approvals?.qualified_signal_pipeline_enabled === true;
  });
  const observations = (one.recent_numeric_observations ?? (one.current_evaluations ?? []).filter((row: Json) => row.state === "NUMERIC_PASS_EVENT_PENDING"))
    .map((row: Json) => ({ ...row, display_state: row.observation_expired ? "EXPIRED" : row.state }));
  const current = one.current_evaluations ?? [];
  const bar = one.bar_summary;
  const expiryAudit = one.contract_window?.universe_expiry_audit;
  const workerState = String(one.worker?.state ?? "UNKNOWN");
  const workerLabel: Record<string, string> = {
    WAIT_PREWARM_WINDOW: c("等待08:30 ET预热", "Prewarm begins 08:30 ET"),
    PREWARM: c("正在补一分钟历史", "Loading one-minute history"),
    PREMARKET_CHECK: c("开盘前核对", "Pre-open check"),
    SHADOW_MONITORING: c("盘中影子计算", "Intraday shadow calculation"),
    EXIT_MONITORING: c("入场截止，继续退出监控", "Entry closed; exit monitoring continues"),
    MARKET_CLOSED: c("市场已收盘", "Market closed"),
    WAIT_MARKET: c("休市，保留未退出持仓监控", "Market closed; unclosed positions remain monitored"),
    STOPPED: c("研究线程已停止", "Research worker stopped"),
    STALLED: c("研究线程未推进", "Research worker stalled"),
    TIME_CONFLICT: c("运行时钟冲突", "Runtime clock conflict"),
  };
  return <section className="ops-one-minute" aria-label={c("一分钟日内研究", "One-minute intraday research")}>
    {!streamConnected ? <p className="ops-warning" role="status">{c("网页实时连接尚未就绪，当前信号资格不可确认；历史记录保留。", "Live page connection is unavailable; current eligibility is unverified. History is retained.")}</p> : null}
    <div className="ops-run"><div><strong>{c("一分钟日内研究", "One-minute intraday research")}</strong><small>{one.policy?.policy_id ?? "—"} · {one.session ?? "—"} · {c("影子观察，不是下单许可", "Shadow observation, not order permission")}</small></div>
      <span>{one.enabled ? workerLabel[workerState] ?? optionStateText(workerState, language) : c("尚未部署启动", "Not started")}</span></div>
    {one.snapshot?.state === "STALE" ? <p className="ops-warning" role="alert">{c("当前显示旧快照，最新计算状态待核验", "Showing a stale snapshot; latest calculation status is unverified")} · {formatUiTime(one.snapshot.as_of, language)}</p> : null}
    {["STOPPED", "STALLED", "TIME_CONFLICT"].includes(workerState) ? <p className="ops-warning" role="alert">{workerLabel[workerState]} · {c("网页可访问不代表研究计算正常", "A reachable page does not imply healthy research computation")}</p> : null}
    {["BAR_PROGRESS_STALE", "NO_COMPLETE_BAR"].includes(one.worker?.research_progress) ? <p className="ops-warning" role="alert">{c("研究循环仍在响应，但未收到近期完整分钟评价；不能判断为没有机会。", "The worker responds but has no recent complete bar evaluation; this is not a no-opportunity result.")}</p> : null}
    {!one.initialized || !s ? <p className="ops-warning">{c("尚无这版当日运行数据。旧两小时结果不能代替一分钟计算。", "No current run for this version. The older two-hour run is not a one-minute calculation.")}</p> : <>
      <dl className="ops-metrics">{[
        [c("登记自选", "Registered"), s.registered_symbols], [c("历史全齐", "Full history"), s.history_ready],
        [c("同分钟已评价方向", "Directions at this bar"), bar?.evaluated_directions], [c("同分钟数值完整", "Numeric checks at this bar"), bar?.numeric_complete_directions],
        [c("同分钟应检查方向", "Expected directions at this bar"), bar?.expected_directions], [c("合格信号", "Qualified signals"), s.qualified_candidates],
      ].map(([name, value]) => <div key={name}><dt>{name}</dt><dd>{value ?? "—"}</dd></div>)}</dl>
      <div className="ops-status-line"><span>{c("最新闭合bar", "Latest closed bar")}: {formatUiTime(s.last_bar_end, language)}</span><span>{c("最近评价", "Last evaluation")}: {formatUiTime(s.last_evaluation_at, language)}</span><span>{c("已订阅标的", "Subscribed symbols")}: {one.worker?.subscribed_symbols ?? "—"}</span><span>{c("边界后补证排队", "Boundary recovery pending")}: {one.worker?.pending_boundary_recovery ?? "—"}</span></div>
      <div className="ops-signal-banner" role="status"><strong>{active.length ? `${c("合格信号", "Qualified signals")} ${active.length}` : !bar?.numeric_complete_directions ? c("等待完整一分钟计算", "Waiting for complete one-minute checks") : c("当前没有可确认的一分钟买入信号", "No currently verified one-minute entry signal")}</strong>
        <span>{!one.approvals?.qualified_signal_pipeline_enabled ? c("新策略与事件合同待O-SETUP确认；数值通过只列为待核验，不发送买入提醒。", "New strategy and event contract await O-SETUP. Numeric passes remain pending and send no entry alert.") : c("检查逐项证据与资格状态", "Inspect each factor and eligibility state")}</span></div>
      {active.length ? <Records rows={active} title={c("合格信号 · 参考报价仍需核对", "Qualified signals · verify reference quotes")} actions={(row: Json) => <><strong>{Math.max(0, Math.ceil((Date.parse(row.deadline_at) - clock) / 1000))}s</strong><button className="quiet-button" onClick={() => onReason(row)}><FileText size={16} />{c("查看原因", "Why")}</button><button className="quiet-button" onClick={() => onChain(displaySymbol(row))}><Layers size={16} />{c("期权链", "Option chain")}</button><button className="quiet-button" onClick={() => onReport(row)}>{c("登记自报交易", "Report own trade")}</button></>} /> : null}
      {candidates.length ? <details><summary>{c("历史合格记录／当前需重新核验", "Qualified history / current eligibility needs rechecking")} ({candidates.length})</summary><Records rows={candidates} title={c("原始资格保留，不延长有效期", "Original evidence retained; validity not extended")} actions={(row: Json) => <button className="quiet-button" onClick={() => onReason(row)}><FileText size={16} />{c("证据", "Evidence")}</button>} /></details> : null}
      {expiryAudit?.status !== "NOT_VERIFIED" && expiryAudit ? <div className="ops-warning" role="note">
        <strong>{c("全自选到期日核查", "Full-watchlist expiry check")}: {expiryAudit.matched} {c("只匹配目标到期日", "symbols match the target expiries")}</strong>
        <p>{c("已核验身份并查询", "Verified identities queried")} {expiryAudit.verified_identity_queried} · {c("无匹配", "No matching expiry")} {expiryAudit.no_matching_expiry} · {c("身份未确认", "Identity unconfirmed")} {expiryAudit.identity_unconfirmed} · {c("查询失败", "Query failed")} {expiryAudit.query_failed}</p>
        <p>{c("目标日期", "Target dates")}: {one.contract_window.dates?.join(" / ")} · {c("核查时间", "Checked")}: {formatUiTime(expiryAudit.checked_at, language)}. {c("到期日匹配仍不等于合约或买入资格；本版不会自动改选1日或4日合约。", "Matching expiry does not establish contract or entry eligibility; this version will not substitute 1- or 4-day contracts.")}</p>
        <details><summary>{c("查看匹配标的与逐项核查", "Matched symbols and per-symbol checks")}</summary>
          <p>{(expiryAudit.matched_symbols ?? []).map((row: Json) => `${row.symbol} (${row.dates.join(", ")})`).join(" · ") || c("没有匹配标的", "No matching symbols")}</p>
          <button className="quiet-button" onClick={() => jsonExport(expiryAudit.items ?? [], `expiry-audit-${one.session}`)}><Download size={16} />{c("导出111只逐项状态", "Export per-symbol status")}</button>
        </details>
      </div> : one.contract_window?.weekend_only ? <p className="ops-warning" role="note">{c("本交易日的2–3自然日DTE为", "This session's 2–3 calendar-day DTE falls on")} {one.contract_window.dates?.join(" / ")} {c("（周末）。须逐项核验实际到期日；本版不会自动改选1日或4日合约。", "(weekend). Verify actual expiries; this version will not substitute 1- or 4-day contracts.")}</p> : null}
      <p className="ops-status-line">{c("历史交易日页", "Historical session pages")}: {s.history_days_fetched ?? "—"} / {s.history_days_required ?? "—"} · {c("空页", "Empty pages")}: {s.history_days_empty ?? "—"} · {c("历史待补", "History pending")}: {s.history_pending ?? "—"} · {c("历史延期或不足", "History deferred or incomplete")}: {s.history_deferred ?? "—"} · {c("身份待确认", "Identity unresolved")}: {s.identity_unresolved ?? "—"} · {c("已存评价", "Saved evaluations")}: {s.saved_evaluations ?? "—"} · {c("数值触发记录", "Numeric trigger records")}: {s.saved_numeric_triggers ?? "—"}</p>
      {observations.length ? <><p className="ops-warning">{c("以下仅是数值研究观察，不是买入信号；超过30秒期限的记录标为已过期。", "These are numeric research observations, not entry signals; records past the 30-second deadline are marked expired.")}</p><Records rows={observations} title={c("当日数值触发记录 · 待资格核验", "Today's numeric trigger records · eligibility pending")} actions={(row: Json) => <><button className="quiet-button" onClick={() => onReason(row)}><FileText size={16} />{c("查看原因", "Why")}</button><button className="icon-button" title={c("打开期权链", "Open option chain")} onClick={() => onChain(displaySymbol(row))}><Layers size={16} /></button><button className="quiet-button" onClick={() => onReport(row)}>{c("登记自报交易", "Report own trade")}</button></>} /></> : <p className="ops-empty">{s.numeric_directions ? c("当日尚无数值触发；详情中可区分条件未满足与数据缺口。", "No numeric trigger today; details distinguish failed conditions from data gaps.") : c("尚无完整数值计算，不能说市场没有机会。", "No complete numeric check yet; cannot conclude there is no opportunity.")}</p>}
      <details><summary>{c("覆盖与逐项诊断", "Coverage and per-symbol diagnostics")}</summary>
        <button className="quiet-button" onClick={() => jsonExport(one.bar_coverage ?? [], `bar-coverage-${one.session}`)}><Download size={16} />{c("导出同分钟逐项覆盖", "Export per-symbol coverage at this bar")}</button>
        <Records rows={current} title={c("各方向最近评价（可能不同分钟）", "Latest per-direction evaluations (may span bars)")} actions={(row: Json) => <><button className="quiet-button" onClick={() => onReason(row)}><FileText size={16} />{c("证据", "Evidence")}</button><button className="quiet-button" onClick={() => onReport(row)}>{c("自报交易", "Report own trade")}</button></>} />
        <Records rows={one.prewarm ?? []} title={c("111标的历史进度", "History progress across watchlist")} actions={() => null} />
        <pre>{JSON.stringify({ worker: one.worker, policy_hash: one.policy?.policy_hash, mode: one.status }, null, 2)}</pre>
      </details>
    </>}
  </section>;
}

function localTimeInput(date = new Date()) {
  return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
}

export function ManualReportProblem({ error, check }: { error: ManualReportError | null; check: () => void }) {
  const c = useCopy();
  if (!error) return null;
  const conflict = error.code === "IDEMPOTENCY_KEY_CONFLICT";
  return <div className="ops-warning" role="alert"><p>{error.uncertain
    ? c("提交结果尚未确认，可能已经记录。重试将使用原编号和原参数；请先核对现有登记，不要重新登记同一笔。", "The outcome is unknown and may already be recorded. Retrying uses the original ID and values; check existing records before creating another report.")
    : conflict ? c("此提交编号已经用于另一组参数，未记录本次修改。请核对现有登记。", "This submission ID was used with different values. This change was not recorded; check existing records.")
    : error.code === "SIGN_IN_REQUIRED" ? c("请先在本机设置并登录工作台账号。", "Set up and sign in to the local workspace first.")
    : c("本次登记未通过校验，请检查合约、数量、价格和时间。", "This report did not pass validation. Check the contract, quantity, price and time.")}</p>
    {error.uncertain || conflict ? <button type="button" className="quiet-button" onClick={check}><Eye size={16} />{c("核对现有登记", "Check existing records")}</button> : null}
    <details><summary>{c("诊断详情", "Diagnostic details")}</summary><code>{error.code}</code></details>
  </div>;
}

function ManualReportRecords({ operationKey, positionId, refresh }: { operationKey?: string; positionId?: string; refresh: number }) {
  const c = useCopy();
  const result = useOperationalResource(operationKey ? `/api/options/one-minute/manual?operation_key=${encodeURIComponent(operationKey)}` : "/api/options/one-minute/manual", refresh);
  const rows = (operationKey ? (result.data?.report ? [result.data.report] : []) : result.data?.positions ?? []).filter((row: Json) => positionId
    ? row.position_id === positionId : row.operation_key === operationKey);
  return <section aria-label={c("现有登记核对", "Existing report check")}>
    <Boundary resource={result}>{result.data ? <>
      {result.data.operation_status === "NOT_FOUND" ? <p>{c("尚未查到该提交记录；这不代表券商交易状态。", "No record found for this submission; this does not establish broker trade status.")}</p> : null}
      {rows.map((row: Json) => {
        const current = operationKey ? result.data?.position_snapshot_state === "AVAILABLE"
          && result.data?.current_position?.position_id === row.position_id ? result.data?.current_position : null : row;
        const remaining = current?.open_quantity;
        return <p key={row.position_id} className="ops-status-line">{row.contract_id} · {c("当前剩余张数", "Current open contracts")}: {Number.isSafeInteger(remaining) && remaining >= 0 ? remaining : c("未确认", "Unconfirmed")}</p>;
      })}
      <Records rows={rows} title={c("用户自报记录，非券商成交核对", "Reported records, not broker reconciliation")} actions={() => null} />
    </> : null}</Boundary>
  </section>;
}

function OneMinuteEntryForm({ evaluation, close, saved }: { evaluation: Json; close: () => void; saved: () => void }) {
  const c = useCopy();
  const [key] = useState(() => crypto.randomUUID());
  const [contract, setContract] = useState("");
  const [quantity, setQuantity] = useState("");
  const [multiplier, setMultiplier] = useState("");
  const [price, setPrice] = useState("");
  const [underlying, setUnderlying] = useState("");
  const [entryFees, setEntryFees] = useState("");
  const [exitFees, setExitFees] = useState("");
  const [at, setAt] = useState(localTimeInput);
  const [error, setError] = useState<ManualReportError | null>(null);
  const [pending, setPending] = useState<ManualReportPayload | null>(null);
  const [recordsVersion, setRecordsVersion] = useState(0);
  const [busy, setBusy] = useState(false);
  const submitting = useRef(false);
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (submitting.current) return;
    submitting.current = true; setBusy(true); setError(null);
    try {
      const payload = pending ?? { operation_key: key, evaluation_id: evaluation.evaluation_id,
        contract_id: contract.trim().toUpperCase(), quantity: Number(quantity), multiplier: Number(multiplier),
        entry_price: Number(price), underlying_entry_price: underlying ? Number(underlying) : null,
        entry_fees: entryFees ? Number(entryFees) : null, exit_fee_estimate: exitFees ? Number(exitFees) : null,
        executed_at: new Date(at).toISOString() };
      setPending(payload);
      const recorded = pending ? await reconcileManualReport(payload) : null;
      if (!recorded) await sendManualReport("/api/options/one-minute/manual/entries", payload);
      saved(); close();
    } catch (cause) {
      const problem = cause instanceof ManualReportError ? cause : cause instanceof RangeError
        ? new ManualReportError("REPORTED_TIME_INVALID", false) : new ManualReportError("REPORT_OUTCOME_UNKNOWN", true);
      setError(problem);
      if (!pending && !problem.uncertain && problem.code !== "IDEMPOTENCY_KEY_CONFLICT") setPending(null);
    } finally { submitting.current = false; setBusy(false); }
  };
  const locked = busy || pending !== null;
  return <Drawer title={`${displaySymbol(evaluation)} ${evaluation.right} · ${c("自报交易", "Reported trade")}`} close={close}>
    <p className="ops-warning">{c("用户自报、未与券商核对；登记不会下单或写入Paper成交。", "User-reported, not broker verified; this creates no order or Paper fill.")}</p>
    <form className="ops-confirm" onSubmit={event => void submit(event)}>
      <label>{c("实际合约代码", "Actual option contract")}<input required disabled={locked} value={contract} onChange={event => setContract(event.target.value)} /></label>
      <label>{c("张数", "Contracts")}<input required disabled={locked} type="number" min="1" step="1" value={quantity} onChange={event => setQuantity(event.target.value)} /></label>
      <label>{c("实际合约乘数", "Actual multiplier")}<input required disabled={locked} type="number" min="1" step="1" value={multiplier} onChange={event => setMultiplier(event.target.value)} /></label>
      <label>{c("自报入场权利金（每股）", "Reported entry premium per share")}<input required disabled={locked} type="number" min="0.0001" step="any" value={price} onChange={event => setPrice(event.target.value)} /></label>
      <label>{c("入场时正股参考价（可空）", "Underlying reference at entry (optional)")}<input disabled={locked} type="number" min="0.0001" step="any" value={underlying} onChange={event => setUnderlying(event.target.value)} /></label>
      <label>{c("已付入场费用（可空）", "Entry fees paid (optional)")}<input disabled={locked} type="number" min="0" step="any" value={entryFees} onChange={event => setEntryFees(event.target.value)} /></label>
      <label>{c("预计退出费用（可空）", "Estimated exit fees (optional)")}<input disabled={locked} type="number" min="0" step="any" value={exitFees} onChange={event => setExitFees(event.target.value)} /></label>
      <label>{c("实际入场时间（本机时间）", "Actual entry time (local)")}<input required disabled={locked} type="datetime-local" value={at} onChange={event => setAt(event.target.value)} /></label>
      <ManualReportProblem error={error} check={() => { saved(); setRecordsVersion(value => value + 1); }} />
      <button className="quiet-button" disabled={busy || error?.code === "IDEMPOTENCY_KEY_CONFLICT"} type="submit">{pending && error ? c("按原参数重试", "Retry original report") : c("记录自报入场", "Record reported entry")}</button>
    </form>
    {recordsVersion > 0 ? <ManualReportRecords operationKey={key} refresh={recordsVersion} /> : null}
  </Drawer>;
}

function OneMinuteExitForm({ position, close, saved }: { position: Json; close: () => void; saved: () => void }) {
  const c = useCopy();
  const [key] = useState(() => crypto.randomUUID());
  const [quantity, setQuantity] = useState("");
  const [price, setPrice] = useState("");
  const [fees, setFees] = useState("");
  const [at, setAt] = useState(localTimeInput);
  const [error, setError] = useState<ManualReportError | null>(null);
  const [pending, setPending] = useState<ManualReportPayload | null>(null);
  const [recordsVersion, setRecordsVersion] = useState(0);
  const [busy, setBusy] = useState(false);
  const submitting = useRef(false);
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    if (submitting.current) return;
    submitting.current = true; setBusy(true); setError(null);
    try {
      const payload = pending ?? { operation_key: key, position_id: position.position_id,
        quantity: Number(quantity), exit_price: Number(price), exit_fees: fees ? Number(fees) : null,
        executed_at: new Date(at).toISOString() };
      setPending(payload);
      const recorded = pending ? await reconcileManualReport(payload) : null;
      if (!recorded) await sendManualReport("/api/options/one-minute/manual/exits", payload);
      saved(); close();
    } catch (cause) {
      const problem = cause instanceof ManualReportError ? cause : cause instanceof RangeError
        ? new ManualReportError("REPORTED_TIME_INVALID", false) : new ManualReportError("REPORT_OUTCOME_UNKNOWN", true);
      setError(problem);
      if (!pending && !problem.uncertain && problem.code !== "IDEMPOTENCY_KEY_CONFLICT") setPending(null);
    } finally { submitting.current = false; setBusy(false); }
  };
  const locked = busy || pending !== null;
  return <Drawer title={`${displaySymbol(position)} · ${c("自报退出", "Reported exit")}`} close={close}>
    <p className="ops-status-line">{position.contract_id} · {c("打开表单时剩余", "Open when form opened")}: {position.open_quantity}</p>
    <form className="ops-confirm" onSubmit={event => void submit(event)}>
      <label>{c("本次退出张数", "Quantity exited")}<input required disabled={locked} type="number" min="1" max={position.open_quantity} step="1" value={quantity} onChange={event => setQuantity(event.target.value)} /></label>
      <label>{c("自报退出权利金（每股）", "Reported exit premium per share")}<input required disabled={locked} type="number" min="0" step="any" value={price} onChange={event => setPrice(event.target.value)} /></label>
      <label>{c("实际退出费用（可空）", "Exit fees paid (optional)")}<input disabled={locked} type="number" min="0" step="any" value={fees} onChange={event => setFees(event.target.value)} /></label>
      <label>{c("实际退出时间（本机时间）", "Actual exit time (local)")}<input required disabled={locked} type="datetime-local" value={at} onChange={event => setAt(event.target.value)} /></label>
      <ManualReportProblem error={error} check={() => { saved(); setRecordsVersion(value => value + 1); }} />
      <button className="quiet-button" disabled={busy || error?.code === "IDEMPOTENCY_KEY_CONFLICT"} type="submit">{pending && error ? c("按原参数重试", "Retry original report") : c("记录自报退出", "Record reported exit")}</button>
    </form>
    {recordsVersion > 0 ? <ManualReportRecords operationKey={key} positionId={position.position_id} refresh={recordsVersion} /> : null}
  </Drawer>;
}

export function ManualContinuityNotice({ data }: { data: Json }) {
  const c = useCopy();
  if (data.old_position_continuity !== "UNKNOWN" && data.position_records_complete !== false) return null;
  return <div className="ops-warning" role="alert">
    <strong>{c("旧持仓状态未确认", "Prior positions are unconfirmed")}</strong>
    <p>{c("旧分钟业务记录未完整恢复。以下只列当前可读取的自报记录，空列表不代表没有持仓或已经平仓。请先核对券商持仓。", "Prior minute-business records have not been fully restored. Only readable self-reported records are listed below. An empty list does not establish no positions or confirmed exits. Reconcile your broker positions first.")}</p>
    {data.data_epoch?.session ? <span>{c("新数据起点", "New data begins")} · {data.data_epoch.session}</span> : null}
  </div>;
}

function OneMinuteManualPanel({ refresh, saved }: { refresh: number; saved: () => void }) {
  const c = useCopy();
  const { language } = useI18n();
  const resource = useOperationalResource("/api/options/one-minute/manual", refresh, true);
  const [exiting, setExiting] = useState<Json | null>(null);
  const positions = resource.data?.positions ?? [];
  const alerts = resource.data?.alerts ?? [];
  return <section className="ops-one-minute" aria-label={c("自报持仓与退出", "Reported positions and exits")}>
    <h3>{c("自报持仓与退出", "Reported positions and exits")}</h3>
    <Boundary resource={resource}>{resource.data ? <>
      <ManualContinuityNotice data={resource.data} />
      {alerts.filter((row: Json) => positions.some((position: Json) => position.position_id === row.position_id && position.open_quantity > 0)).length ?
        <div className="ops-warning" role="alert"><strong>{c("待核查退出", "Exit review pending")}</strong><p>{alerts.filter((row: Json) => positions.some((position: Json) => position.position_id === row.position_id && position.open_quantity > 0)).map((row: Json) => `${row.symbol} ${row.right} · ${optionReasonText(row.reason, language)}`).join(" · ")}</p></div> : null}
      <Records rows={positions} title={c("用户自报 · 未与券商核对", "User-reported · not broker verified")} actions={(row: Json) => row.open_quantity > 0 ? <button className="quiet-button" onClick={() => setExiting(row)}>{c("登记部分/全部退出", "Report partial/full exit")}</button> : null} />
    </> : null}</Boundary>
    {exiting ? <OneMinuteExitForm position={exiting} close={() => setExiting(null)} saved={saved} /> : null}
  </section>;
}

function RunLine({ two }: { two: Json }) {
  const c = useCopy();
  const { language } = useI18n();
  const summary = two.summary ?? {};
  return <div className="ops-run-line" role="status">
    <span><strong>{two.policy?.policy_id === "STRAT-SHORT-ATM-RANGE-EXPANSION-2H-V1" ? c("开盘两小时研究", "Opening two-hour research") : two.policy?.policy_id ?? c("研究运行", "Research run")}</strong> · {summary.session ?? "—"}</span>
    <span>{optionStateText(two.worker?.state ?? two.status, language)} · {c("最近计算", "Last calculation")} {formatUiTime(summary.last_evaluation_at, language)}</span>
    <span>{c("完整计算", "Complete checks")} {summary.complete_directions ?? "—"} · {c("待核验", "Pending review")} {two.pending_triggers?.length ?? "—"}</span>
  </div>;
}

export function SignalList({ rows, onReason, onChain, limit }: { rows: Json[]; onReason: (row: Json) => void; onChain: (symbol: string) => void; limit?: number }) {
  const c = useCopy();
  const { language } = useI18n();
  return <div className="ops-signal-list">{(limit ? rows.slice(0, limit) : rows).map((row: Json) => {
    const contract = row.contract_qualification?.selected ?? {};
    const compression = row.rule_evidence?.compression?.actual;
    const participation = row.rule_evidence?.participation?.actual;
    const metric = (value: unknown) => typeof value === "number" && Number.isFinite(value) ? value.toFixed(2) : "—";
    return <article key={row.evaluation_id ?? row.event_id} className="ops-signal-item">
      <div className="ops-signal-identity"><strong>{displaySymbol(row)} · {row.right === "CALL" ? c("看涨 Call", "Call") : c("看跌 Put", "Put")}</strong><span>{row.contract_id ?? c("合约待确认", "Contract pending")}{contract.expiry_date ? ` · ${contract.expiry_date}` : ""}{contract.strike != null ? ` · ${contract.strike}` : ""}</span></div>
      <div className="ops-signal-when"><span>{formatUiTime(row.bar_end ?? row.evaluated_at, language)}</span><small>{c("有效至", "Valid until")} {formatUiTime(row.deadline_at, language)}</small></div>
      <div className="ops-signal-why">{c("两根5分钟突破", "Two 5-minute bars broke out")} · {c("收缩", "Compression")} {metric(compression)} · {c("量能", "Participation")} {metric(participation)} · SPY</div>
      <div className="ops-row-actions"><button className="quiet-button" onClick={() => onReason(row)}><FileText size={16} />{c("查看原因", "View reason")}</button><button className="icon-button" title={c("打开期权链", "Open option chain")} onClick={() => onChain(displaySymbol(row))}><Layers size={16} /></button><a className="icon-button" title={c("打开图表", "Open chart")} href={`/?workspace=options&view=chart&symbol=${encodeURIComponent(displaySymbol(row))}`}><BarChart3 size={16} /></a></div>
    </article>;
  })}</div>;
}

export function EventSourcesPanel({ symbol, refresh, minute = false, strategy }: { symbol: string; refresh: number; minute?: boolean; strategy?: "opening_trend" | "opening_momentum" }) {
  const c = useCopy();
  const { language } = useI18n();
  const [category, setCategory] = useState<string | null>(null);
  const [review, setReview] = useState<string | null>(null);
  const [automaticEvidence, setAutomaticEvidence] = useState<string | null>(null);
  const [reviewRefresh, setReviewRefresh] = useState(0);
  const research = strategy ?? (minute ? "one_minute" : "two_hour");
  const sameDay = research !== "two_hour";
  const status = useOperationalResource(`/api/options/event-sources?symbol=${encodeURIComponent(symbol)}&research_strategy=${research}`, refresh + reviewRefresh);
  const source = useOperationalResource(category ? `/api/options/event-sources/${category}/events?symbol=${encodeURIComponent(symbol)}` : null, refresh + reviewRefresh);
  const categories = Object.entries(status.data?.calendar_sources?.categories ?? {}) as [string, Json][];
  const missingReasons = Object.entries(status.data?.reviewed_coverage?.missing_reasons ?? {}) as [string, string[]][];
  const names: Record<string, string> = { earnings: c("财报", "Earnings"), dividends: c("分红", "Dividends"), corporate: c("公司行动", "Corporate actions"),
    splits: c("拆并股", "Splits"), mergers: c("并购", "Mergers"), meetings: c("会议", "Meetings"), macro: c("宏观", "Macro") };
  return <section className="ops-source-section" aria-label={c("事件资料来源", "Event evidence sources")}>
    <h3>{displaySymbol({ symbol })} · {c("事件资料来源", "Event evidence sources")}</h3>
    <Boundary resource={status}><>
      <p className="ops-status-line">{c("审核状态", "Review status")}: {optionStateText(status.data?.reviewed_coverage?.status ?? "UNKNOWN", language)} · {c("缺少", "Missing")}: {(status.data?.reviewed_coverage?.missing_categories ?? []).join(", ") || "—"}</p>
      {missingReasons.length ? <p className="ops-warning">{missingReasons.map(([key, value]) => `${key}: ${value.join(", ")}`).join(" · ")}</p> : null}
      <p className="ops-status-line">{c("采集状态", "Collection status")}: {status.data?.calendar_sources?.status ?? "NOT_CHECKED"} · {c("采集资料不自动放行入场", "Collected data does not authorize entry")}</p>
      {sameDay ? <p className="ops-status-line">{research === "opening_momentum" ? c("早盘顺势政策", "Opening momentum policy") : research === "opening_trend" ? c("趋势回踩政策", "Trend pullback policy") : c("一分钟政策", "One-minute policy")}: {status.data?.review_context?.policy_id ?? "—"} · {status.data?.review_context?.can_submit ? c("当日审核窗口", "Same-day review window") : c("等待交易日窗口或准确政策批准", "Awaiting session window or exact policy acceptance")}</p> : null}
      {strategy ? <AutomaticEventCoverage data={status.data?.automatic_coverage} onEvidence={setAutomaticEvidence} /> : null}
      <div className="ops-row-actions">{["earnings", "dividends", "corporate", "macro"].map(key => <button type="button" className="quiet-button" key={key} disabled={sameDay && !status.data?.review_context?.can_submit} onClick={() => setReview(key)}>{names[key] ?? key} · {c("补证审核", "Review evidence")}</button>)}</div>
      <div className="ops-table-scroll"><table><thead><tr><th>{c("资料", "Source")}</th><th>{c("分页与缺口", "Pages and issues")}</th><th>{c("取得时间", "Obtained at")}</th><th>{c("操作", "Actions")}</th></tr></thead><tbody>
        {categories.map(([key, row]) => <tr key={key}><td>{names[key] ?? key}<small>{row.event_count ?? "—"} {c("相关条目", "matching entries")}</small></td>
          <td>{row.pages_complete ? c("分页完成", "Pages complete") : c("部分资料", "Partial data")} · {row.freshness ?? "UNKNOWN"}<small>{(row.issues ?? []).join(", ") || "—"}</small></td>
          <td>{formatUiTime(row.knowledge_as_of, language)}</td><td><button className="icon-button" title={c("查看来源及原始条目", "Inspect source and raw entries")} onClick={() => setCategory(key)}><FileText size={16} /></button></td></tr>)}
      </tbody></table>{!categories.length ? <div className="ops-empty">{c("尚无归档资料", "No archived sources")}</div> : null}</div>
    </></Boundary>
    {category ? <Drawer title={`${names[category] ?? category} · ${c("来源证据", "Source evidence")}`} close={() => setCategory(null)}>
      <Boundary resource={source}>{source.data ? <><p className="ops-status-line">{source.data.source_url ?? "—"} · {formatUiTime(source.data.knowledge_as_of, language)}</p>
        <p>{c("来源哈希", "Source hash")}: <code>{source.data.source_hash ?? "—"}</code></p>
        <p>{c("审核结论", "Review conclusion")}: {c("待核验，不放行信号", "Unreviewed; signal blocked")}</p>
        <button className="quiet-button" onClick={() => jsonExport(source.data, `event-source-${symbol}-${category}`)}><Download size={16} />{c("导出来源", "Export source")}</button>
        <pre>{JSON.stringify(source.data.events ?? [], null, 2)}</pre></> : null}</Boundary>
    </Drawer> : null}
    {review ? <Drawer title={`${names[review] ?? review} · ${c("人工补证", "Manual evidence review")}`} close={() => setReview(null)}>
      <EventReviewForm symbol={symbol} category={review} sources={status.data?.calendar_sources?.categories ?? {}} context={sameDay ? status.data?.review_context : undefined}
        onSaved={() => { setReview(null); setReviewRefresh(value => value + 1); }} />
    </Drawer> : null}
    {automaticEvidence ? <Drawer title={`${names[automaticEvidence]} · ${c("程序核验证据", "Programmatic evidence")}`} close={() => setAutomaticEvidence(null)}>
      <button className="quiet-button" onClick={() => jsonExport(status.data?.automatic_coverage, `automatic-event-${symbol}`)}><Download size={16} />{c("导出依据", "Export evidence")}</button>
      <pre>{JSON.stringify(status.data?.automatic_coverage?.category_states?.[automaticEvidence] ?? {}, null, 2)}</pre>
    </Drawer> : null}
  </section>;
}

export function AutomaticEventCoverage({ data, onEvidence }: { data?: Json; onEvidence: (category: string) => void }) {
  const c = useCopy();
  const { language } = useI18n();
  const names: Record<string, string> = { earnings: c("财报", "Earnings"), dividends: c("分红", "Dividends"), corporate: c("公司行动", "Corporate actions"), macro: c("宏观", "Macro") };
  return <div className="ops-table-scroll" aria-label={c("程序核验", "Programmatic checks")}><table><thead><tr><th>{c("类别", "Category")}</th><th>{c("程序核验", "Programmatic check")}</th><th>{c("判定时间", "Assessed at")}</th><th>{c("证据", "Evidence")}</th></tr></thead><tbody>
    {Object.entries(names).map(([key, name]) => { const row = data?.category_states?.[key]; return <tr key={key}><td>{name}</td>
      <td>{!row ? c("不可用", "Unavailable") : row.known_risk_state === "KNOWN_BLOCKER" ? c("已知风险", "Known risk") : row.trade_eligible ? row.applicability === "NOT_APPLICABLE_UNDER_POLICY" ? c("不适用，已核实", "Not applicable, verified") : c("资料核验通过", "Evidence verified") : c("待核验", "Pending verification")}</td>
      <td>{formatUiTime(data?.as_of, language)}</td><td><button className="icon-button" disabled={!row} title={c("查看程序判定依据", "View programmatic evidence")} onClick={() => onEvidence(key)}><FileText size={16} /></button></td></tr>; })}
  </tbody></table></div>;
}

function EventReviewForm({ symbol, category, sources, context, onSaved }: { symbol: string; category: string; sources: Record<string, Json>; context?: Json; onSaved: () => void }) {
  const c = useCopy();
  const now = new Date();
  const [assetClass, setAssetClass] = useState("COMMON_STOCK");
  const [url, setUrl] = useState("");
  const [content, setContent] = useState("");
  const [risk, setRisk] = useState("");
  const [summary, setSummary] = useState("");
  const [exception, setException] = useState("");
  const [start, setStart] = useState(context?.coverage_start ?? now.toISOString());
  const [end, setEnd] = useState(context?.coverage_end ?? new Date(now.getTime() + 8 * 86400000).toISOString());
  const [events, setEvents] = useState("[]");
  const [pending, setPending] = useState(false);
  const [error, setError] = useState("");
  const [recorded, setRecorded] = useState("");
  const names = category === "corporate" ? ["splits", "mergers", "meetings"] : [category];
  const sourceRows = names.map(name => ({ name, row: sources[name] })).filter(source => source.row);
  async function submit(event: FormEvent) {
    event.preventDefault(); setError(""); setRecorded("");
    let parsedEvents: unknown;
    try { parsedEvents = parseReviewedEvents(events, start, end, risk); }
    catch (failure) {
      const code = failure instanceof Error ? failure.message : "EVENTS_MUST_BE_ARRAY";
      setError(code === "KNOWN_BLOCKER_NEEDS_BLOCKING_EVENT" ? c("明确风险必须填写至少一个具体阻断事件", "Known risk requires at least one specific blocking event")
        : code === "CLEAR_CANNOT_CONTAIN_BLOCKER" ? c("无已知阻断结论不能包含阻断事件", "A clear conclusion cannot contain blocking events")
        : code === "EVENT_TIME_INVALID_OR_TIMEZONE_MISSING" ? c("事件时间必须有效并包含时区", "Event times must be valid and include a timezone")
        : code === "EVENT_OUTSIDE_COVERAGE_WINDOW" ? c("事件必须位于有效覆盖区间内", "Events must fit within the valid coverage window")
        : c("事件必须是数组，逐项填写名称、阻断标记及起止时间", "Use an event array with a name, blocking flag, start and end for every item"));
      return;
    }
    setPending(true);
    try {
      const response = await fetch("/api/options/event-sources/reviews", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({
        symbol: category === "macro" ? "*" : symbol, category, asset_class: assetClass,
        official_source_url: url, official_source_content: content, coverage_start: start,
        coverage_end: end, valid_until: context?.valid_until ?? new Date(now.getTime() + 12 * 3600000).toISOString(),
        research_strategy: context?.research_strategy ?? "two_hour", policy_hash: context?.policy_hash, scope_hash: context?.scope_hash, session: context?.session,
        risk_state: risk, risk_summary: summary, exception_reason: exception, events: parsedEvents,
      }) });
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail ?? String(response.status));
      setRecorded(result.coverage_id);
      onSaved();
    } catch (failure) { setError(failure instanceof Error ? failure.message : "Review failed"); }
    finally { setPending(false); }
  }
  return <form className="ops-event-review" onSubmit={submit}>
    <p className="ops-warning">{c("仅记录你实际核对过的官方资料；空日历、缺页或未知事件不能写成无风险。记录将绑定当前供应商资料，资料变更后失效。", "Record only official material you actually reviewed. Empty calendars and incomplete pages are not clearance. The review is invalidated when provider content changes.")}</p>
    <div className="ops-source-refs">{sourceRows.map(({ name, row }) => <p key={name}>{name} · {row.freshness ?? "UNKNOWN"} · {row.pages_complete ? "PAGES_COMPLETE" : "PAGES_INCOMPLETE"} · {row.semantic_hash ?? "HASH_PENDING"}</p>)}</div>
    <label>{c("证券类型", "Asset class")}<select value={assetClass} onChange={event => setAssetClass(event.target.value)} disabled={category === "macro"}>{["COMMON_STOCK", "ADR", "REIT", "ETF", "ETN", "FUND"].map(value => <option key={value}>{value}</option>)}</select></label>
    <label>{c("官方来源 HTTPS 链接", "Official HTTPS source URL")}<input required type="url" value={url} onChange={event => setUrl(event.target.value)} /></label>
    <label>{c("已阅读的原文摘录", "Reviewed original excerpt")}<textarea required minLength={40} maxLength={32768} rows={5} value={content} onChange={event => setContent(event.target.value)} /></label>
    <div className="ops-review-times"><label>{c("覆盖开始 ISO 时间", "Coverage start ISO time")}<input required value={start} onChange={event => setStart(event.target.value)} /></label><label>{c("覆盖结束 ISO 时间", "Coverage end ISO time")}<input required value={end} onChange={event => setEnd(event.target.value)} /></label></div>
    <label>{c("风险结论", "Risk conclusion")}<select required value={risk} onChange={event => setRisk(event.target.value)}><option value="" disabled>{c("选择实际审核结论", "Select the reviewed conclusion")}</option><option value="CLEAR">{c("核验范围内无已知阻断", "No known blocker in reviewed sources")}</option><option value="KNOWN_BLOCKER">{c("有明确阻断事件", "Known blocking event")}</option></select></label>
    <label>{c("判断依据", "Reasoning")}<textarea required rows={3} value={summary} onChange={event => setSummary(event.target.value)} /></label>
    <label>{c("分页或来源缺口的人工例外依据", "Human exception for incomplete source")}<textarea rows={2} value={exception} onChange={event => setException(event.target.value)} /></label>
    <label>{c("具体事件 JSON 数组", "Specific events JSON array")}<textarea rows={3} value={events} onChange={event => setEvents(event.target.value)} /></label>
    {error ? <p role="alert" className="ops-warning">{error}</p> : null}{recorded ? <p role="status">{recorded}</p> : null}
    <button type="submit" className="quiet-button" disabled={pending}>{pending ? c("正在记录", "Recording") : c("提交署名审核", "Record named review")}</button>
  </form>;
}

export default function OptionsOperations({ view, symbol, refreshNonce, onOpenChain }: {
  view: string; symbol: string; refreshNonce: number; onOpenChain: (symbol: string) => void;
}) {
  const c = useCopy();
  const { language } = useI18n();
  const [localRefresh, setLocalRefresh] = useState(0);
  const refresh = refreshNonce + localRefresh;
  const [tab, setTab] = useState(view === "plans" ? "watch" : view === "review" ? "daily" : "candidates");
  const [detail, setDetail] = useState<Json | null>(null);
  const [entryReport, setEntryReport] = useState<Json | null>(null);
  const [review, setReview] = useState<string | null>(null);
  const [message, setMessage] = useState("");
  const [pending, setPending] = useState(false);
  const [confirm, setConfirm] = useState<Json | null>(null);
  const [notificationPanel, setNotificationPanel] = useState(false);
  const [legacyOpen, setLegacyOpen] = useState(false);
  const [researchOpen, setResearchOpen] = useState(false);
  const [eventSourcesOpen, setEventSourcesOpen] = useState(false);
  const openedLink = useRef(false);
  const oneMinute = useOperationalResource(view === "review" || view === "signals" && tab === "diagnostics" ? "/api/options/one-minute/status" : null, refresh, true);
  const legacyNeeded = view === "plans" || view === "signals" && tab !== "candidates" ||
    oneMinute.data?.enabled === false && (view === "today" || view === "signals" || view === "review" && tab === "daily");
  const full = useOperationalResource(legacyNeeded ? "/api/options/full-watch/status?scope=full&operations_only=true" : null, refresh, true);
  const paper = useOperationalResource(view === "plans" || view === "review" && tab === "paper" ||
    view === "today" && oneMinute.data?.enabled === false ? "/api/options/copilot/paper" : null, refresh, true);
  const copilot = useOperationalResource(view === "plans" || tab === "diagnostics" ? "/api/options/copilot/status" : null, refresh);
  const notifications = useOperationalResource(tab === "diagnostics" || view === "review" && tab === "daily" ||
    notificationPanel ? "/api/stocks/notifications/status" : null, refresh);
  const signals = useOperationalResource(view === "plans" && tab === "pending" ? "/api/options/copilot/signals?limit=100" : null, refresh, true);
  const two = full.data?.two_hour;
  const oneMinuteFocused = oneMinute.data?.enabled !== false;
  const completeDirections = (two?.current_evaluations ?? []).filter((row: Json) => row.data_complete === true && !(row.blockers ?? []).length).length;
  const assessedCompletely = Boolean(two?.summary && two.summary.ready_symbols > 0 &&
    two.summary.unassessed_ready_symbols === 0 && completeDirections >= two.summary.ready_symbols * 2 &&
    two.summary.unknown_directions === 0);
  const pendingTriggerIds = new Set((two?.pending_triggers ?? []).map((row: Json) => row.evaluation_id));
  const pastTriggers = (two?.trigger_history ?? []).filter((row: Json) => !pendingTriggerIds.has(row.evaluation_id));
  useEffect(() => {
    const id = new URLSearchParams(window.location.search).get("evaluation");
    if (!id || openedLink.current) return;
    setDetail({ evaluation_id: id }); openedLink.current = true;
  }, [two]);
  const onSaved = () => setLocalRefresh(n => n + 1);
  const watch = async (row: Json, active: boolean) => {
    setPending(true); setMessage("");
    try {
      const response = await fetch("/api/options/full-watch/observations", { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ evaluation_id: row.evaluation_id, active }) });
      if (!response.ok) throw new Error(`HTTP_${response.status}`);
      onSaved(); setMessage(c("观察记录已更新，未创建Paper意图", "Observation updated; no Paper intent created"));
    } catch { setMessage(c("更新失败，请重试", "Update failed; retry")); }
    finally { setPending(false); }
  };
  const actions = (row: Json) => <>
    <a className="icon-button" title={c("打开图表", "Open chart")} href={`/?workspace=options&view=chart&symbol=${encodeURIComponent(displaySymbol(row))}`}><BarChart3 size={16} /></a>
    <button className="icon-button" title={c("打开期权链", "Open option chain")} onClick={() => onOpenChain(displaySymbol(row))}><Layers size={16} /></button>
    <button className="icon-button" title={c("查看证据", "View evidence")} onClick={() => setDetail(row)}><FileText size={16} /></button>
    {row.evaluation_id ? <button className="icon-button" disabled={pending} title={row.active ? c("移除观察", "Remove observation") : c("加入观察", "Watch")} onClick={() => void watch(row, !row.active)}>{row.active ? <EyeOff size={16} /> : <Eye size={16} />}</button> : null}
    {row.signal_id && (row.source_kind === "POSITION" && row.state === "OPEN" || row.source_kind === "SIGNAL") ? (() => {
      const allowed = copilotPaperAllowed(row, copilot.data);
      return <button className="icon-button" title={allowed ? c("人工Paper确认", "Manual Paper confirmation") : c("Paper审批未通过", "Paper approval required")} disabled={!allowed} onClick={() => setConfirm(row)}><Check size={16} /></button>;
    })() : null}
  </>;
  const triggerActions = (row: Json) => <>
    <button className="quiet-button" onClick={() => setDetail(row)}><FileText size={16} />{c("查看原因", "View reason")}</button>
    <a className="icon-button" title={c("打开图表", "Open chart")} href={`/?workspace=options&view=chart&symbol=${encodeURIComponent(displaySymbol(row))}`}><BarChart3 size={16} /></a>
  </>;
  const watches = (two?.observations ?? []).map((row: Json) => ({ ...row, source_kind: "WATCH" }));
  const plans = [...watches, ...paperRows(paper.data ?? {})];
  const tabs: [string, string][] = view === "signals" ? [["candidates", c("当前信号", "Current signals")], ["pending", c("旧两小时待核验", "Legacy two-hour pending")], ["history", c("旧两小时历史", "Legacy two-hour history")], ["diagnostics", c("扫描详情", "Scan details")]] : view === "plans" ? [["watch", c("观察中", "Watching")], ["pending", c("待人工确认", "Pending confirmation")], ["positions", c("Paper持仓", "Paper positions")], ["exit", c("待退出", "Exit pending")], ["ended", c("已结束", "Ended")], ["history", c("旧研究记录", "Legacy research")]] : [["daily", c("当日复盘", "Daily review")], ["paper", c("Paper记录", "Paper records")], ["research", c("研究证据", "Research evidence")], ["history", c("历史审核", "Review archive")]];
  return <div className="ops-workspace">
    <PolicyAvailabilityNotice data={copilot.data ?? {}} />
    {view === "signals" ? <details><summary>{c("旧策略查询", "Legacy strategy queries")}</summary><Tabs items={tabs} value={tab} change={setTab} /></details> : view !== "today" ? <Tabs items={tabs} value={tab} change={setTab} /> : null}
    {message ? <p role="status">{message}</p> : null}
    {(view === "today" || view === "signals" && tab === "candidates") ? <OpeningTrendPanel refresh={refresh} onReason={setDetail} onChain={onOpenChain} onReport={setEntryReport} onSaved={onSaved} /> : null}
    {(view === "review" && tab === "daily" || view === "signals" && tab === "diagnostics") ? <details><summary>{c("旧一分钟研究记录", "Legacy one-minute research")}</summary><Boundary resource={oneMinute}>{oneMinute.data ? <OneMinutePanel one={oneMinute.data} snapshotRequestedAt={oneMinute.requestedAt} snapshotFailed={!!oneMinute.error} onReason={setDetail} onChain={onOpenChain} onReport={setEntryReport} /> : null}</Boundary></details> : null}
    {!oneMinuteFocused && (view === "today" || view === "signals" || tab === "daily") ? <Boundary resource={full}>{two?.summary ? view === "review" ? <Summary two={two} /> : <RunLine two={two} /> : <p role="alert">{c("当前运行汇总不可用，不能判断为零候选", "Current run summary unavailable; candidate count is unknown")}</p>}</Boundary> : null}
    {!oneMinuteFocused && (view === "today" || view === "signals" && tab === "candidates") && two?.summary ? <>
      {view === "today" && paper.data && paperRows(paper.data).some((row: Json) => ["exit", "positions"].includes(planCategory(row))) ? <Records rows={paperRows(paper.data).filter((row: Json) => ["exit", "positions"].includes(planCategory(row)))} actions={actions} title={c("持仓与待退出", "Positions and exits")} /> : null}
      {view === "today" && paper.error ? <p className="ops-warning" role="alert">{c("持仓信息暂不可用；信号状态独立显示。", "Position data unavailable; signal status is shown independently.")}</p> : null}
      <div className={`ops-signal-banner ${two.qualified_signals?.length ? "qualified" : ""}`} role="status"><strong>{two.qualified_signals?.length ? `${c("当前有效信号", "Active signals")} · ${two.qualified_signals.length}` : assessedCompletely ? c("当前没有符合规则的机会", "No opportunity after complete checks") : c("当前没有合格信号", "No qualified signal now")}</strong><span>{two.worker?.state === "ENTRY_WINDOW_CLOSED" ? c("本版本今日入场时段已结束", "Entry window closed for this version") : two.pending_triggers?.length ? `${c("另有待核验", "Pending review")} ${two.pending_triggers.length}` : two.summary.unassessed_ready_symbols ? `${c("尚未评价标的", "Symbols not yet evaluated")} ${two.summary.unassessed_ready_symbols}` : c("查看扫描详情了解覆盖与缺口", "See scan details for coverage and gaps")}</span></div>
      {two.qualified_signals?.length ? <SignalList rows={two.qualified_signals} limit={view === "today" ? 5 : undefined} onReason={setDetail} onChain={onOpenChain} /> : null}
      {view === "today" ? <a className="quiet-button ops-all-signals" href="/?workspace=options&view=signals">{c("查看全部信号", "View all signals")}</a> : null}
    </> : null}
    {view === "signals" && tab === "pending" && two?.summary ? <div className="ops-pending-signals"><Records rows={(two.pending_triggers ?? []).map((row: Json) => ({ ...row, state: c("数学条件触发 · 待核验", "Math triggered · verification pending") }))} actions={triggerActions} title={c("待核验观察 · 不发送买入提醒", "Pending review · no entry alert")} /></div> : null}
    {view === "signals" && tab === "history" && two?.summary ? <div className="ops-trigger-list"><Records rows={pastTriggers.map((row: Json) => ({ ...row, state: row.display_state ?? row.state }))} actions={triggerActions} title={c("今日触发 · 已过期或未获资格", "Today's triggers · expired or unqualified")} /></div> : null}
    {view === "signals" && tab === "diagnostics" ? <div className="ops-diagnostic-list">
      {oneMinuteFocused ? <details><summary>{c("旧两小时策略运行（独立版本）", "Legacy two-hour run (separate version)")}</summary><Boundary resource={full}>{two?.summary ? <Summary two={two} /> : null}</Boundary></details> : null}
      {!oneMinuteFocused && two?.summary ? <Summary two={two} /> : null}
      {two?.summary ? <Records rows={currentCoverage(two)} actions={actions} title={c("旧两小时全量覆盖 · Call / Put分别评价", "Legacy two-hour coverage · Call and Put")} /> : null}
      {two?.summary ? <Records rows={Object.entries(two.summary.blockers).map(([reason, count]) => ({ symbol: String(count), state: "UNKNOWN", blockers: [reason] }))} actions={actions} title={c("旧两小时阻断分布", "Legacy two-hour blockers")} /> : null}
      <details onToggle={event => setEventSourcesOpen(event.currentTarget.open)}><summary>{c("事件资料与审核缺口", "Event sources and review gaps")}</summary>{eventSourcesOpen ? <EventSourcesPanel symbol={symbol} refresh={refresh} minute={oneMinuteFocused} /> : null}</details>
      <details><summary>{c("运行、恢复与版本证据", "Runtime, recovery and version evidence")}</summary><pre>{JSON.stringify(two, null, 2)}</pre></details>
      <details onToggle={event => setLegacyOpen(event.currentTarget.open)}><summary>{c("旧Full Watch运行（不同版本）", "Legacy Full Watch run (different version)")}</summary>{legacyOpen ? <ReadPanel path="/api/options/full-watch/status?scope=full" refresh={refresh} symbol={symbol} /> : null}</details>
      <details onToggle={event => setResearchOpen(event.currentTarget.open)}><summary>{c("CBRM与AI独立状态", "Independent CBRM and AI status")}</summary>{researchOpen ? <LazyResearch symbol={symbol} refresh={refresh} /> : null}</details>
      <Boundary resource={copilot}><pre>{JSON.stringify(copilot.data?.state_dimensions, null, 2)}</pre></Boundary>
      <Boundary resource={notifications}>{notifications.data ? <OptionRuntimeStatus status={{}} notifications={notifications.data} reload={onSaved} notificationsOnly /> : null}</Boundary>
    </div> : null}
    {view === "plans" && tab !== "history" ? <>
      <OneMinuteManualPanel refresh={refresh} saved={onSaved} />
      <p className="ops-status-line">{c("观察不是建仓；Paper入退场均需人工确认。新版Paper待O-SETUP批准，真实订单关闭。", "Watching is not a position. Paper entry and exit require manual confirmation. New Paper awaits O-SETUP; live orders disabled.")}</p>
      <Boundary resource={tab === "watch" ? full : paper}><Records rows={plans.filter(row => planCategory(row) === tab)} actions={actions} title={tabs.find(item => item[0] === tab)?.[1] ?? ""} /></Boundary>
      {tab === "pending" ? <Boundary resource={signals}><Records rows={(signals.data?.signals ?? []).filter((row: Json) => row.state === "REVIEW_READY").map((row: Json) => ({ ...row, source_kind: "SIGNAL" }))} actions={actions} title={c("待确认信号（原审批范围）", "Signals pending confirmation (original approved scope)")} /></Boundary> : null}
    </> : null}
    {view === "plans" && tab === "history" ? <LegacyPlans refresh={refresh} actions={actions} /> : null}
    {view === "review" && tab === "daily" ? <>
      <Boundary resource={notifications}><p className="ops-status-line">{c("设备订阅", "Device subscriptions")}: {notifications.data?.active_subscriptions ?? "—"} · {c("设备显示待验收；通知不等于成交", "Device display unverified; notification is not a fill")}<button className="quiet-button" onClick={() => setNotificationPanel(true)}>{c("通知设置与测试", "Notification settings and test")}</button></p></Boundary>
      {!oneMinuteFocused && two?.summary ? <Records rows={two.current_evaluations ?? []} actions={actions} title={c("当日最新评价与阻断", "Today's latest evaluations and blockers")} /> : null}
    </> : null}
    {view === "review" && tab === "paper" ? <Boundary resource={paper}><Records rows={paperRows(paper.data ?? {})} actions={actions} title={c("人工Paper意图与持仓（独立记录）", "Manual Paper intents and positions (separate records)")} /></Boundary> : null}
    {view === "review" && tab === "research" ? <LazyResearch symbol={symbol} refresh={refresh} /> : null}
    {view === "review" && tab === "history" ? <div className="ops-archive">{[1, 2, 3, 4, 5, 6].map(n => <button className="quiet-button" key={n} onClick={() => setReview(`r${n}`)}><FileText size={16} />R{n} {c("审核记录", "review")}</button>)}<p>{c("R6结论：实盘未启用，不代表停止研究。", "R6: live trading is not enabled; research is not disabled.")}</p></div> : null}
    {detail ? <Detail item={detail} close={() => setDetail(null)} /> : null}
    {entryReport ? <OneMinuteEntryForm evaluation={entryReport} close={() => setEntryReport(null)} saved={onSaved} /> : null}
    {review ? <Drawer title={`${review.toUpperCase()} ${c("历史审核", "Review archive")}`} close={() => setReview(null)}><ReadPanel path={`/api/options/research/reviews/${review}`} review={review} symbol={symbol} refresh={refresh} /></Drawer> : null}
    {confirm ? <PaperConfirmation item={confirm} close={() => setConfirm(null)} saved={onSaved} /> : null}
    {notificationPanel ? <Drawer title={c("通知设置与测试", "Notification settings and test")} close={() => setNotificationPanel(false)}><Boundary resource={notifications}><OptionRuntimeStatus status={{}} notifications={notifications.data ?? {}} reload={onSaved} notificationsOnly /></Boundary></Drawer> : null}
  </div>;
}

function LazyResearch({ symbol, refresh }: { symbol: string; refresh: number }) {
  const c = useCopy();
  const [part, setPart] = useState("cbrm");
  return <><Tabs value={part} change={setPart} items={[["cbrm", "CBRM · DEV_ONLY"], ["intraday", c("全日研究提案", "Intraday proposal")], ["forward", c("旧前向研究", "Legacy forward research")], ["workbench", c("三组研究与实验", "Profiles and experiments")], ["router", c("AI独立状态", "Independent AI status")]]} /><div className="ops-research-scroll">{part === "intraday" ? <IntradayProposalPanel refresh={refresh} /> : <ReadPanel symbol={symbol} refresh={refresh} path={part === "router" ? "/api/options/model-router/status" : part === "cbrm" ? `/api/options/research/cbrm?symbol=${encodeURIComponent(symbol)}&limit=20` : part === "forward" ? "/api/options/research/forward/status" : "/api/options/research/workbench"} />}</div></>;
}

function IntradayProposalPanel({ refresh }: { refresh: number }) {
  const c = useCopy();
  const resource = useOperationalResource("/api/options/intraday/proposal/status", refresh);
  const policy = resource.data?.policy;
  return <Boundary resource={resource}>{policy ? <section className="ops-proposal">
    <h3>{c("全日内期权研究 · 尚未启用", "Intraday options research · not enabled")}</h3>
    <p>{c("仅为独立提案；未替换当前两小时策略，不生成正式候选或设备提醒。", "Independent proposal only; it has not replaced the current two-hour strategy or enabled signals and alerts.")}</p>
    <dl className="settings-lines"><div><dt>{c("策略", "Policy")}</dt><dd>{policy.policy_id}</dd></div>
      <div><dt>{c("入场窗口", "Entry window")}</dt><dd>09:40–14:30 ET · {c("提前收市另算", "adjusted for early close")}</dd></div>
      <div><dt>{c("合约到期", "Expiry")}</dt><dd>0DTE / 2–3DTE · {c("不含1DTE", "excludes 1DTE")}</dd></div>
      <div><dt>{c("退出提醒", "Exit reminder")}</dt><dd>{c("收市前45分钟；计划收市前30分钟退出，实际成交需确认", "45 minutes before close; planned exit 30 minutes before close, fill requires confirmation")}</dd></div>
      <div><dt>{c("审批状态", "Approval")}</dt><dd>{resource.data?.status} · {c("O-SETUP待确认", "O-SETUP pending")}</dd></div></dl>
    <details><summary>{c("政策哈希与完整原文", "Policy hash and complete definition")}</summary><pre>{JSON.stringify(policy, null, 2)}</pre></details>
  </section> : null}</Boundary>;
}

function LegacyPlans({ refresh, actions }: { refresh: number; actions: (row: Json) => ReactNode }) {
  const c = useCopy();
  const [source, setSource] = useState("forward");
  const paths: Record<string, string> = { radar: "signals/history?limit=200", forward: "research/forward/status", watch: "watchlist?active_only=false", simulations: "simulations?limit=200", manual: "manual-outcomes?limit=200" };
  const result = useOperationalResource(`/api/options/${paths[source]}`, refresh);
  const rows = result.data?.opportunities ?? result.data?.paper_records ?? result.data?.items ?? result.data?.outcomes ?? [];
  return <><Tabs value={source} change={setSource} items={[["radar", c("旧雷达查询", "Legacy radar")], ["forward", c("旧前向研究", "Legacy forward research")], ["watch", c("原计划观察", "Legacy plan watches")], ["simulations", c("旧模拟", "Legacy simulations")], ["manual", c("人工结果", "Manual outcomes")]]} /><Boundary resource={result}><Records rows={rows} actions={actions} title={c("历史记录", "History")} /></Boundary></>;
}

function PaperConfirmation({ item, close, saved }: { item: Json; close: () => void; saved: () => void }) {
  const c = useCopy();
  const [price, setPrice] = useState("");
  const [quantity, setQuantity] = useState("1");
  const [result, setResult] = useState<Json | null>(null);
  const [busy, setBusy] = useState(false);
  const identity = useRef(crypto.randomUUID());
  const action = item.source_kind === "POSITION" ? "EXIT" : "ENTRY";
  const contract = item.payload?.contract ?? item;
  const contractId = item.contract_id ?? contract.contract_id;
  const multiplier = item.multiplier ?? item.contract_multiplier ?? contract.multiplier;
  const submit = async (event: FormEvent) => {
    event.preventDefault(); if (busy || !contractId || !multiplier) return;
    setBusy(true);
    try {
      const response = await fetch("/api/options/copilot/paper/confirm", { method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" }, body: JSON.stringify({
        signal_id: item.signal_id, action, confirmation_id: identity.current, confirmation_text: `CONFIRM PAPER ${action}`,
        contract_id: contractId, contract_multiplier: multiplier, underlying: displaySymbol(item), theme_id: contract.theme_id ?? "UNCLASSIFIED", limit_price: Number(price), requested_quantity: Number(quantity),
      }) });
      setResult(await response.json()); saved();
    } catch { setResult({ status: "UNKNOWN_REQUEST_OUTCOME", message: c("请求结果未知，使用相同确认标识重试", "Request outcome unknown; retry with the same confirmation ID") }); }
    finally { setBusy(false); }
  };
  return <Drawer title={c("人工Paper确认", "Manual Paper confirmation")} close={close}><form onSubmit={submit} className="ops-confirm"><strong>{contractId ?? "-"} · {action}</strong><label>{c("限价", "Limit price")}<input type="number" min="0.01" step="0.01" required value={price} onChange={e => setPrice(e.target.value)} /></label><label>{c("数量", "Quantity")}<input type="number" min="1" step="1" max={action === "EXIT" ? item.quantity : undefined} required value={quantity} onChange={e => setQuantity(e.target.value)} /></label><button type="submit" disabled={busy || !contractId || !multiplier || result?.intent_id}>{c("确认Paper意图", "Confirm Paper intent")}</button>{!multiplier ? <p>{c("缺少合约乘数，禁止提交", "Contract multiplier missing; submission blocked")}</p> : null}{result ? <pre>{JSON.stringify(result, null, 2)}</pre> : null}</form></Drawer>;
}
