import AiConnectionSettings from "./AiConnectionSettings";
import WorkspaceAccessSettings from "./WorkspaceAccessSettings";
import {
  AlertTriangle,
  BellRing,
  CalendarClock,
  Check,
  ChevronRight,
  CircleSlash,
  Clock3,
  Eye,
  EyeOff,
  FileClock,
  FlaskConical,
  Languages,
  Moon,
  RefreshCw,
  ScanSearch,
  ShieldAlert,
  ShieldCheck,
  Sun,
  TrendingDown,
  TrendingUp,
} from "lucide-react";
import { FormEvent, ReactNode, useCallback, useEffect, useMemo, useState } from "react";
import {
  formatUiNumber,
  formatUiTime,
  optionGroupText,
  optionReasonText,
  optionStateText,
  statusText,
  useI18n,
} from "./i18n";
import type { ViewName } from "./workspace";
import "./options-workspace.css";
import OptionRuntimeStatus from "./OptionRuntimeStatus";
import OptionsResearchWorkbench from "./OptionsResearchWorkbench";
import OptionReferenceChain from "./OptionReferenceChain";
import OptionsOperations, { PolicyAvailabilityNotice } from "./OptionsOperations";

type Json = Record<string, any>;

type OptionPlan = {
  plan_id: string;
  opportunity_id: string;
  horizon_group: string;
  contract_symbol: string;
  expiry_date: string;
  dte: number;
  strike_price: number;
  direction: string;
  state: string;
  earliest_confirm_at?: string | null;
  entry_cutoff_at?: string | null;
  exit_reminder_at?: string | null;
  expires_at: string;
  blockers?: string[];
  reference_quote?: Json;
  scenario?: Json;
};

type OptionOpportunity = {
  opportunity_id: string;
  symbol: string;
  hypothesis: string;
  direction: string;
  horizon_class: string;
  rank_value: number;
  evidence_score: number;
  status: string;
  signal_time: string;
  market_data_time?: string | null;
  evidence_grade: string;
  blockers?: string[];
  warnings?: string[];
  evidence?: Json;
  plans?: OptionPlan[];
  watchlist?: Json[];
  simulation_outcomes?: Json[];
  manual_outcomes?: Json[];
};

type Props = {
  view: ViewName;
  symbol: string;
  refreshNonce: number;
  chart: ReactNode;
  onSymbolChange: (symbol: string) => void;
  onOpenChain: (symbol: string) => void;
  language: "zh" | "en";
  theme: "dark" | "light";
  onLanguageChange: (language: "zh" | "en") => void;
  onThemeChange: (theme: "dark" | "light") => void;
};

const ACTIVE_STATES = new Set(["PREMARKET_WATCH", "WAIT_OPEN_CONFIRMATION", "WAITING_CONFIRMATION", "QUOTE_BLOCKED", "REFERENCE_ONLY", "CONFIRMED", "EXIT_REVIEW"]);

function stateTone(value: unknown): string {
  const raw = String(value ?? "").toUpperCase();
  if (["CONFIRMED", "COMPLETED", "AVAILABLE", "PASSED"].includes(raw)) return "positive";
  if (["CANCELLED", "INVALIDATED", "REJECTED", "FAILED", "EXPIRED"].includes(raw)) return "negative";
  if (["QUOTE_BLOCKED", "REFERENCE_ONLY", "EXIT_REVIEW", "CENSORED"].includes(raw)) return "caution";
  return "info";
}

function useOptionI18n() {
  const { language, t } = useI18n();
  return {
    language,
    t,
    stateLabel: (value: unknown) => optionStateText(value, language),
    statusLabel: (value: unknown) => statusText(value, language),
    groupLabel: (value: unknown) => optionGroupText(value, language),
    explain: (value: unknown) => optionReasonText(value, language),
    formatNumber: (value: unknown, digits = 2) => formatUiNumber(value, language, digits),
    formatTime: (value: unknown) => formatUiTime(value, language),
  };
}

async function requestJson(path: string, init?: RequestInit, signal?: AbortSignal): Promise<Json> {
  const response = await fetch(path, { credentials: "same-origin", cache: "no-store", ...init, signal });
  const body = await response.json();
  if (!response.ok) throw new Error(String(body.detail ?? `Request failed (${response.status})`));
  return body;
}

function Status({ value }: { value: unknown }) {
  const { stateLabel } = useOptionI18n();
  return <span className={`option-status ${stateTone(value)}`}><i />{stateLabel(value)}</span>;
}

function Direction({ value }: { value: string }) {
  const call = value.toUpperCase() === "CALL";
  return <span className={`option-direction ${call ? "call" : "put"}`}>{call ? <TrendingUp size={14} /> : <TrendingDown size={14} />}{call ? "Call" : "Put"}</span>;
}

function DailyScopeSummary({ payload }: { payload: Json }) {
  const { language, formatTime } = useOptionI18n();
  const zh = language === "zh";
  const counts = payload.counts ?? {};
  const reasons: Record<string, [string, string]> = {
    market_closed: ["休市：今天没有盘中确认窗口", "Market closed: there is no intraday confirmation window"],
    before_0830_et: ["尚未到08:30 ET盘前报告时间", "Before the 08:30 ET premarket report"],
    before_0940_et: ["已完成盘前摘要，等待09:40 ET后的闭合5分钟确认", "Premarket summary recorded; waiting for closed 5-minute confirmation after 09:40 ET"],
    frozen_forward_read_failed: ["冻结前向任务读取失败，不能解释为市场没有机会", "Frozen forward task read failed; this is not a no-opportunity market conclusion"],
    frozen_forward_task_not_run: ["冻结前向任务尚未运行，不能解释为市场没有机会", "The frozen forward task has not run; this is not a no-opportunity market conclusion"],
    frozen_evidence_or_market_data_blocked: ["行情、事件或证据不完整，相关方向保持阻断", "Market, event, or evidence data is incomplete; affected directions remain blocked"],
    frozen_conditions_not_met: ["任务已完成，冻结条件未满足", "The task completed and the frozen conditions were not met"],
    frozen_scope_candidates_present: ["冻结范围内已有研究候选", "Research candidates exist in the frozen scope"],
    frozen_scope_candidate_recorded: ["已记录冻结范围研究候选", "Frozen-scope research candidate recorded"],
  };
  const reason = reasons[String(payload.reason)]?.[zh ? 0 : 1] ?? String(payload.reason ?? "—");
  const checks = Array.isArray(payload.checks) ? payload.checks : [];
  const candidates = Array.isArray(payload.candidates) ? payload.candidates : [];
  return <section className="option-section daily-scope-report"><div className="section-title"><div><h2>{zh ? "已批准 Paper 每日范围" : "Approved Paper daily scope"}</h2><span>{zh ? "这里仅展示旧 Core12 的已批准前向 Paper；111只完整自选的研究扫描与证据在 Signals 页面，尚未获得新增 Paper 审批。" : "This section shows only the previously approved Core12 forward Paper scope. Research scans and evidence for all 111 watchlist symbols are available in Signals and are not approved for additional Paper activity."}</span></div><Status value={payload.status ?? "NOT_RUN"} /></div><div className="daily-scope-counts"><div><span>{zh ? "自选代码" : "Watchlist symbols"}</span><strong>{counts.watchlist_distinct_symbols ?? 0}</strong></div><div><span>{zh ? "Paper范围检查" : "Paper-scope checks"}</span><strong>{counts.frozen_scope_checked ?? 0}</strong></div><div><span>{zh ? "仅研究覆盖" : "Research only"}</span><strong>{counts.watchlist_not_strategy_covered ?? 0}</strong></div><div><span>{zh ? "Paper候选" : "Paper candidates"}</span><strong>{counts.candidates ?? 0}</strong></div></div><div className="daily-scope-reason"><strong>{reason}</strong><span>{formatTime(payload.generated_at)} · {payload.market_date ?? "—"} ET</span></div>{candidates.length ? <div className="daily-candidate-list">{candidates.map((item: Json) => <a key={item.opportunity_id} href={`?workspace=options&view=opportunities&symbol=${encodeURIComponent(String(item.symbol ?? ""))}`}><div><strong>{item.symbol} · {item.right}</strong><span>{item.contract_symbol || (zh ? "合约选择待定" : "Contract selection pending")}</span></div><div><small>{zh ? "形成" : "Formed"} {formatTime(item.formed_at)}</small><span>{zh ? "打开期权链" : "Open option chain"} ›</span></div></a>)}</div> : null}<details><summary>{zh ? "查看旧 Core12 已批准范围的逐项状态" : "View the approved legacy Core12 checks"}</summary><div className="daily-check-grid">{checks.map((item: Json) => <div key={item.symbol}><strong>{item.symbol}</strong><span>{item.status === "candidate" ? (zh ? `研究候选 · ${(item.rights ?? []).join(" / ")}` : `Research candidate · ${(item.rights ?? []).join(" / ")}`) : item.status === "blocked" ? (zh ? "数据阻断" : "Data blocked") : (zh ? "无候选" : "No candidate")}</span><small>{reasons[String(item.reason)]?.[zh ? 0 : 1] ?? String(item.reason ?? "—")}</small></div>)}</div></details></section>;
}

function Empty({ title, detail }: { title: string; detail: string }) {
  return <div className="option-empty"><CircleSlash size={19} /><strong>{title}</strong><span>{detail}</span></div>;
}

function ResearchProfiles({ payload }: { payload: Json }) {
  const { t, stateLabel, formatTime } = useOptionI18n();
  const profiles = Array.isArray(payload?.profiles?.profiles) ? payload.profiles.profiles : [];
  const evidence = payload?.capability_evidence ?? {};
  const label = (id: string) => id === "SHORT_ATM_DAYS_WEEK" ? t("Short-term ATM") : id === "MEDIUM_ATM_WEEKS_MONTHS" ? t("Medium-term ATM") : t("Long-term OTM");
  const holding = (id: string) => id === "SHORT_ATM_DAYS_WEEK" ? t("Days to one week") : id === "MEDIUM_ATM_WEEKS_MONTHS" ? t("Weeks to months") : t("Months to one year");
  if (payload.profiles?.current_policy_available === false) return <PolicyAvailabilityNotice data={payload.profiles} />;
  return <section className="option-section option-profile-section">
    <div className="section-title"><div><span className="eyebrow">{t("Foundation mode")}</span><h2>{t("Research profiles")}</h2><span>{t("Three observation profiles are registered. Strategy rules remain intentionally undefined.")}</span></div><Status value="PENDING" /></div>
    <div className="option-profile-grid">{profiles.map((profile: Json) => <article key={profile.profile_id}>
      <div><strong>{label(String(profile.profile_id))}</strong><span>{holding(String(profile.profile_id))}</span></div>
      <dl><div><dt>{profile.moneyness_target}</dt><dd>{t("Call and Put tracked separately")}</dd></div><div><dt>{t("Strategy definition pending")}</dt><dd>{profile.profile_version}</dd></div></dl>
      <span className="profile-boundary"><CircleSlash size={13} />{t("Signal generation disabled")}</span>
    </article>)}</div>
    <div className="capability-strip">
      <div><span>{t("Capability evidence")}</span><strong>{formatTime(evidence.generated_at)}</strong></div>
      <div><span>OPRA</span><strong>{evidence.entitlement_status === "VERIFIED" ? t("OPRA entitlement verified") : stateLabel(evidence.entitlement_status)}</strong></div>
      <div><span>BBO</span><strong>{evidence.quote_capability_status === "AVAILABLE" ? t("Reference bid and ask available") : stateLabel(evidence.quote_capability_status)}</strong></div>
      <div><span>{t("Market validation status")}</span><strong>{evidence.market_day_validation_status === "WAIT_MARKET" ? t("Market-session push validation pending") : stateLabel(evidence.market_day_validation_status)}</strong></div>
    </div>
  </section>;
}

function ForwardResearchStatus({ payload }: { payload: Json }) {
  const { language, formatTime } = useOptionI18n();
  if (!payload?.run) return null;
  const zh = language === "zh";
  const groups = Array.isArray(payload.groups) ? payload.groups : [];
  return <section className="option-section option-forward-section">
    <div className="section-title"><div><span className="eyebrow">P4 · FORWARD PAPER</span><h2>{zh ? "冻结前向研究" : "Frozen forward research"}</h2><span>{zh ? "仅 SHORT_ATM_DAYS_WEEK 的 Call/Put 使用获批接收时间报价代理；不是交易所成交。" : "Only SHORT_ATM_DAYS_WEEK Call/Put uses the approved receipt-time quote proxy; these are not exchange fills."}</span></div><Status value={payload.status} /></div>
    <div className="option-profile-grid">{groups.map((group: Json) => <article key={group.profile_id}><div><strong>{group.profile_id}</strong><span>{group.reason}</span></div><dl><div><dt>{zh ? "候选" : "Candidates"}</dt><dd>{group.candidate_count ?? 0}</dd></div><div><dt>{zh ? "完成" : "Completed"}</dt><dd>{group.completed_count ?? 0}</dd></div></dl><span className="profile-boundary"><Clock3 size={13} />{group.state}</span></article>)}</div>
    <div className="capability-strip"><div><span>{zh ? "运行 ID" : "Run ID"}</span><strong>{payload.run.run_id}</strong></div><div><span>{zh ? "下次检查" : "Next check"}</span><strong>{formatTime(payload.run.next_check_at)}</strong></div><div><span>{zh ? "报价证据" : "Quote evidence"}</span><strong>RECEIPT_TIME_PROXY</strong></div><div><span>{zh ? "实盘订单" : "Real orders"}</span><strong>{zh ? "关闭" : "Disabled"}</strong></div></div>
  </section>;
}

function OptionSummaryStrip({ status, opportunities, watchCount, outcomeCount }: { status: Json; opportunities: OptionOpportunity[]; watchCount: number; outcomeCount: number }) {
  const { t, formatTime } = useOptionI18n();
  return <div className="option-summary-strip">
    <div><span>{t("Premarket report")}</span><strong>{formatTime(status.latest_premarket?.generated_at)}</strong></div>
    <div><span>{t("Current opportunities")}</span><strong>{opportunities.filter((item) => ACTIVE_STATES.has(item.status)).length} / 5</strong></div>
    <div><span>{t("Option market data")}</span><strong>{status.opra_status === "available" ? t("OPRA available") : t("Strict quotes not ready")}</strong></div>
    <div><span>{t("Watch / completed")}</span><strong>{watchCount} / {outcomeCount}</strong></div>
  </div>;
}

function OpportunityRows({ items, selectedId, onSelect }: { items: OptionOpportunity[]; selectedId: string; onSelect: (item: OptionOpportunity) => void }) {
  const { t, stateLabel, groupLabel, formatNumber } = useOptionI18n();
  if (!items.length) return <Empty title={t("No qualified opportunities")} detail={t("The radar does not manufacture candidates to fill a quota.")} />;
  return <div className="option-list" role="list">
    {items.map((item) => {
      const next = item.status === "PREMARKET_WATCH" ? t("Wait for 09:40 ET confirmation") : item.status === "EXIT_REVIEW" ? t("Confirm whether the position has exited") : item.status === "QUOTE_BLOCKED" ? t("Wait for data conditions to recover") : stateLabel(item.status);
      const group = item.plans?.[0]?.horizon_group;
      return <button type="button" className={`option-list-row ${selectedId === item.opportunity_id ? "selected" : ""}`} key={item.opportunity_id} onClick={() => onSelect(item)}>
        <span className="option-rank">{String(item.rank_value ?? 0).padStart(2, "0")}</span>
        <span className="option-symbol-cell"><strong>{item.symbol}</strong><small>{group ? groupLabel(group) : item.horizon_class === "INTRADAY" ? t("Intraday") : t("Short swing")}</small></span>
        <Direction value={item.direction} />
        <span className="option-reason">{item.hypothesis.includes("short_swing") ? t("Residual strength continuation") : t("Premarket idiosyncratic move")}<small>{formatNumber(item.evidence?.residual_z)}σ · {item.evidence_grade === "limited" ? t("Limited evidence") : t("Observation evidence")}</small></span>
        <Status value={item.status} />
        <span className="option-next">{next}<ChevronRight size={15} /></span>
      </button>;
    })}
  </div>;
}

function ContractComparison({ opportunity, watched, strictQuoteReady, onWatch, onUnwatch, onTimeline, onManual }: {
  opportunity: OptionOpportunity;
  watched: Set<string>;
  strictQuoteReady: boolean;
  onWatch: (planId: string) => void;
  onUnwatch: (planId: string) => void;
  onTimeline: (planId: string) => void;
  onManual: (planId: string) => void;
}) {
  const { t, stateLabel, groupLabel, formatNumber } = useOptionI18n();
  const plans = opportunity.plans ?? [];
  if (!plans.length) return <Empty title={t("No comparable contracts")} detail={t("The option chain or expiries do not qualify for this horizon.")} />;
  return <div className="contract-comparison">
    <div className="contract-head" aria-hidden="true"><span>{t("Contract")}</span><span>{t("Expiry / strike")}</span><span>{t("Bid / ask")}</span><span>{t("Cost / maximum premium loss")}</span><span>Greeks</span><span>{t("Actions")}</span></div>
    {plans.slice(0, 6).map((plan) => {
      const quote = plan.reference_quote ?? {};
      const multiplier = quote.contract_multiplier == null ? null : Number(quote.contract_multiplier);
      const cost = quote.ask != null && multiplier != null && multiplier > 0 && Number.isFinite(Number(quote.ask)) ? Number(quote.ask) * multiplier : null;
      const isWatched = watched.has(plan.plan_id);
      return <div className="contract-row" key={plan.plan_id}>
        <div><strong>{plan.contract_symbol}</strong><small>{groupLabel(plan.horizon_group)}</small></div>
        <div><strong>{plan.expiry_date}</strong><small>{formatNumber(plan.strike_price)} · {plan.dte} DTE</small></div>
        <div><strong>{`${formatNumber(quote.bid)} / ${formatNumber(quote.ask)}`}</strong><small>{stateLabel("REFERENCE_ONLY")} · {quote.bbo_received_at ?? "-"}</small></div>
        <div><strong>{cost == null ? "-" : `$${formatNumber(cost)}`}</strong><small>{strictQuoteReady ? t("One contract; no sizing advice") : stateLabel("REFERENCE_ONLY")}</small></div>
        <div><strong>{`Δ ${formatNumber(quote.delta)} · Θ ${formatNumber(quote.theta, 3)}`}</strong><small>{`IV ${quote.implied_volatility == null ? "-" : `${formatNumber(Number(quote.implied_volatility) * 100, 1)}%`} · Vega ${formatNumber(quote.vega, 3)}`}</small></div>
        <div className="contract-actions">
          <button type="button" className="icon-button" onClick={() => isWatched ? onUnwatch(plan.plan_id) : onWatch(plan.plan_id)} title={isWatched ? t("Remove from watchlist") : t("Add to watchlist")}>{isWatched ? <EyeOff size={15} /> : <Eye size={15} />}</button>
          <button type="button" className="icon-button" onClick={() => onTimeline(plan.plan_id)} title={t("View plan timeline")}><FileClock size={15} /></button>
          <button type="button" className="icon-button" onClick={() => onManual(plan.plan_id)} title={t("Record manual outcome")}><Check size={15} /></button>
        </div>
      </div>;
    })}
  </div>;
}

function Timeline({ payload }: { payload: Json | null }) {
  const { t, stateLabel, explain, formatTime } = useOptionI18n();
  if (!payload) return null;
  const events = Array.isArray(payload.events) ? payload.events : [];
  return <section className="option-detail-section timeline-section">
    <div className="section-title"><div><h3>{t("Plan timeline")}</h3><span>{payload.plan?.contract_symbol}</span></div><Status value={payload.plan?.state} /></div>
    {events.length ? <ol className="option-timeline">{events.map((event: Json) => <li key={event.event_id}><i /><div><strong>{stateLabel(event.next_state)}</strong><span>{event.event_type.split("_").join(" ")} · {formatTime(event.recorded_at)}</span>{Array.isArray(event.reasons) && event.reasons.length ? <small>{event.reasons.map(explain).join(" ")}</small> : null}</div></li>)}</ol> : <Empty title={t("No appended events")} detail={t("Later state changes are appended here without overwriting the original decision.")} />}
  </section>;
}

function ManualOutcomeForm({ planId, onSaved, onCancel }: { planId: string; onSaved: () => void; onCancel: () => void }) {
  const { t } = useOptionI18n();
  const [status, setStatus] = useState("observing");
  const [entryPrice, setEntryPrice] = useState("");
  const [exitPrice, setExitPrice] = useState("");
  const [fees, setFees] = useState("");
  const [notes, setNotes] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      await requestJson("/api/options/manual-outcomes", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          plan_id: planId,
          status,
          entry_time: entryPrice ? new Date().toISOString() : null,
          entry_price: entryPrice ? Number(entryPrice) : null,
          exit_time: exitPrice ? new Date().toISOString() : null,
          exit_price: exitPrice ? Number(exitPrice) : null,
          contracts: entryPrice ? 1 : null,
          fees: fees ? Number(fees) : null,
          reason: "user_reported",
          notes,
        }),
      });
      onSaved();
    } catch {
      setError(t("Save failed"));
    } finally {
      setBusy(false);
    }
  };
  return <form className="manual-outcome-form" onSubmit={submit}>
    <div className="section-title"><div><h3>{t("Record manual outcome")}</h3><span>{t("Manual outcomes are separate from simulations; blank fees exclude net performance.")}</span></div></div>
    <div className="manual-fields">
      <label>{t("Status")}<select value={status} onChange={(event) => setStatus(event.target.value)}><option value="observing">{t("Observing")}</option><option value="not_entered">{t("Not entered")}</option><option value="open">{t("Manually entered")}</option><option value="completed">{t("Completed")}</option><option value="censored">{t("Incomplete path")}</option></select></label>
      <label>{t("Entry premium")}<input type="number" min="0" step="0.01" value={entryPrice} onChange={(event) => setEntryPrice(event.target.value)} /></label>
      <label>{t("Exit premium")}<input type="number" min="0" step="0.01" value={exitPrice} onChange={(event) => setExitPrice(event.target.value)} /></label>
      <label>{t("Total fees")}<input type="number" min="0" step="0.01" value={fees} onChange={(event) => setFees(event.target.value)} placeholder={t("Leave blank if unknown")} /></label>
    </div>
    <label className="manual-notes">{t("Notes")}<textarea rows={2} value={notes} onChange={(event) => setNotes(event.target.value)} /></label>
    {error ? <p className="form-error">{error}</p> : null}
    <div className="form-actions"><button type="button" className="quiet-button" onClick={onCancel}>{t("Cancel")}</button><button type="submit" className="primary-button" disabled={busy}>{busy ? t("Saving") : t("Save outcome")}</button></div>
  </form>;
}

function OpportunityDetail({ opportunity, watched, strictQuoteReady, timeline, manualPlanId, onWatch, onUnwatch, onTimeline, onManual, onSaved }: {
  opportunity: OptionOpportunity | null;
  watched: Set<string>;
  strictQuoteReady: boolean;
  timeline: Json | null;
  manualPlanId: string;
  onWatch: (planId: string) => void;
  onUnwatch: (planId: string) => void;
  onTimeline: (planId: string) => void;
  onManual: (planId: string) => void;
  onSaved: () => void;
}) {
  const { t, explain, formatNumber, formatTime } = useOptionI18n();
  if (!opportunity) return <aside className="option-detail"><Empty title={t("Select an opportunity")} detail={t("Details, contract comparison, and diagnostics load on demand.")} /></aside>;
  const blockers = opportunity.blockers ?? [];
  const warnings = opportunity.warnings ?? [];
  const supporting = Array.isArray(opportunity.evidence?.supporting_factors) ? opportunity.evidence?.supporting_factors : [];
  return <aside className="option-detail" aria-label={`${opportunity.symbol} ${t("Option opportunity details")}`}>
    <div className="option-detail-head">
      <div><div className="symbol-line"><h2>{opportunity.symbol}</h2><Direction value={opportunity.direction} /><Status value={opportunity.status} /></div><p>{opportunity.hypothesis.includes("short_swing") ? t("Short-swing residual continuation") : t("Intraday idiosyncratic-move continuation")} · {t("Data time")} {formatTime(opportunity.market_data_time ?? opportunity.signal_time)}</p></div>
      <div className="option-score"><span>{t("Residual strength")}</span><strong>{formatNumber(opportunity.evidence?.residual_z)}σ</strong></div>
    </div>
    <section className="option-detail-section">
      <div className="section-title"><div><h3>{t("What to confirm now")}</h3><span>{t("Observation is not a fill, and a reminder is not an exit confirmation.")}</span></div></div>
      <div className="decision-columns">
        <div><span>{t("Supporting")}</span>{supporting.length ? supporting.slice(0, 3).map((item: Json, index: number) => <p key={index}><Check size={14} />{String(item.factor_id ?? t("Registered evidence")).split("_").join(" ")} {formatNumber(item.value)}</p>) : <p><Check size={14} />{t("The underlying idiosyncratic move reached the watch threshold")}</p>}</div>
        <div><span>{t("Blocks / opposing")}</span>{blockers.length ? blockers.slice(0, 3).map((item) => <p key={item}><AlertTriangle size={14} />{explain(item)}</p>) : <p><ShieldCheck size={14} />{t("No new blockers; manual review is still required")}</p>}</div>
      </div>
    </section>
    <section className="option-detail-section">
      <div className="section-title"><div><h3>{t("Contract comparison")}</h3><span>{t("Compare up to three contracts in one horizon; compare risk, not the most profitable contract.")}</span></div></div>
      <ContractComparison opportunity={opportunity} watched={watched} strictQuoteReady={strictQuoteReady} onWatch={onWatch} onUnwatch={onUnwatch} onTimeline={onTimeline} onManual={onManual} />
    </section>
    {manualPlanId ? <ManualOutcomeForm planId={manualPlanId} onSaved={onSaved} onCancel={() => onManual("")} /> : null}
    <Timeline payload={timeline} />
    <details className="option-audit-details"><summary>{t("Audit and full diagnostics")}</summary><dl><div><dt>{t("Opportunity ID")}</dt><dd>{opportunity.opportunity_id}</dd></div><div><dt>{t("Policy")}</dt><dd>{opportunity.evidence?.policy_version ?? "option_radar_v1.1.0"}</dd></div><div><dt>{t("Sector benchmark")}</dt><dd>{opportunity.evidence?.sector_benchmark ?? "-"}</dd></div><div><dt>{t("Evidence grade")}</dt><dd>{opportunity.evidence_grade}</dd></div></dl>{[...blockers, ...warnings].length ? <ul>{[...blockers, ...warnings].map((item, index) => <li key={`${item}-${index}`}>{explain(item)}</li>)}</ul> : null}</details>
  </aside>;
}

function FullWatchResearch({ payload, onOpenChain, onSaved }: { payload: Json; onOpenChain: (symbol: string) => void; onSaved: () => void }) {
  const { language, formatNumber, formatTime } = useOptionI18n();
  const [scope, setScope] = useState<"FULL" | "CORE">("FULL");
  const [state, setState] = useState("ALL");
  const [query, setQuery] = useState("");
  const [visibleLimit, setVisibleLimit] = useState(30);
  const [checking, setChecking] = useState("");
  const [checkResult, setCheckResult] = useState<Json | null>(null);
  const evaluations = Array.isArray(payload.evaluations) ? payload.evaluations : [];
  const counts = payload.run?.counts ?? {};
  const twoHour = payload.two_hour ?? {};
  const prewarm = Array.isArray(twoHour.prewarm) ? twoHour.prewarm : [];
  const grouped = useMemo(() => {
    const result = new Map<string, Json>();
    for (const item of evaluations) {
      const symbol = String(item.symbol ?? "");
      const current = result.get(symbol) ?? { symbol, is_core12: Boolean(item.is_core12), quote: item.quote ?? {}, snapshot: item.snapshot ?? {}, rights: {} };
      current.rights[String(item.option_right ?? "")] = item;
      if (!current.snapshot?.reference_session && item.snapshot?.reference_session) current.snapshot = item.snapshot;
      result.set(symbol, current);
    }
    return [...result.values()];
  }, [evaluations]);
  const visible = grouped.filter((item) => {
    if (scope === "CORE" && !item.is_core12) return false;
    if (query && !String(item.symbol).includes(query.trim().toUpperCase())) return false;
    if (state !== "ALL" && !Object.values(item.rights as Json).some((right: any) => String(right.coverage_state) === state)) return false;
    return true;
  });
  const displayed = visible.slice(0, visibleLimit);
  useEffect(() => setVisibleLimit(30), [scope, state, query]);
  const checkOptions = async (symbol: string) => {
    setChecking(symbol);
    setCheckResult(null);
    try {
      const result = await requestJson(`/api/options/full-watch/options/${encodeURIComponent(symbol)}`, { method: "POST" });
      setCheckResult(result);
      onSaved();
    } catch (error) {
      setCheckResult({ symbol, status: "ERROR", error_type: error instanceof Error ? error.message : String(error) });
    } finally { setChecking(""); }
  };
  const zh = language === "zh";
  if (payload.current_policy_available === false) return <PolicyAvailabilityNotice data={payload} />;
  return <section className="option-section full-watch-research">
    <div className="section-title"><div><span className="eyebrow">2H V1</span><h3>{zh ? "开盘两小时研究" : "First two hours research"}</h3><span>09:40–11:30 ET · {zh ? "连续两根完整5分钟K线" : "Two consecutive closed 5-minute bars"}</span></div><Status value={twoHour.worker?.state ?? "NOT_STARTED"} /></div>
    <div className="full-watch-kpis">
      <div><span>{zh ? "已登记预热" : "Prewarm registered"}</span><strong>{prewarm.length}</strong></div>
      <div><span>{zh ? "预热齐全" : "Prewarm ready"}</span><strong>{prewarm.filter((item: Json) => item.state === "READY").length}</strong></div>
      <div><span>{zh ? "完整规则计算（累计方向数）" : "Complete calculations (all recorded directions)"}</span><strong>{(twoHour.evaluations?.RESEARCH_CANDIDATE ?? 0) + (twoHour.evaluations?.CONDITION_NOT_MET ?? 0) + (twoHour.evaluations?.DUPLICATE_CANDIDATE ?? 0)}</strong></div>
      <div><span>{zh ? "未知（累计）" : "Unknown (all recorded)"}</span><strong>{twoHour.evaluations?.UNKNOWN ?? 0}</strong></div>
      <div><span>{zh ? "新版Paper" : "New-version Paper"}</span><strong>{zh ? "待O-SETUP批准" : "O-SETUP approval pending"}</strong></div>
      <div><span>{zh ? "设备投递" : "Device delivery"}</span><strong>{zh ? "未验收" : "Not verified"}</strong></div>
    </div>
    <details><summary>{zh ? "预热缺口与版本" : "Prewarm gaps and version"}</summary><p>{twoHour.policy?.policy_id ?? "STRAT-SHORT-ATM-RANGE-EXPANSION-2H-V1"}</p><p>{twoHour.policy?.policy_hash ?? "—"}</p>{prewarm.map((item: Json) => <div key={item.symbol}><strong>{item.symbol}</strong> · {item.state} · {item.reason ?? "—"}</div>)}</details>
    <div className="section-title"><div><span className="eyebrow">FULL WATCH · DETERMINISTIC</span><h3>{zh ? "全自选研究覆盖" : "Full watchlist research coverage"}</h3><span>{zh ? "扫描分母来自服务端自选库；Core12仅保留为历史基准。此处不使用CBRM，也不生成Paper持仓。" : "The server watchlist is the scan denominator; Core12 remains a historical benchmark only. CBRM is not consumed and no Paper position is created."}</span></div><Status value={payload.status ?? "NOT_STARTED"} /></div>
    <div className="full-watch-kpis">
      <div><span>{zh ? "自选代码" : "Watchlist"}</span><strong>{counts.symbols_total ?? 0}</strong></div>
      <div><span>{zh ? "有报价" : "Quotes available"}</span><strong>{counts.quote_available_symbols ?? 0}</strong></div>
      <div><span>PASS / FAIL</span><strong>{counts.pass ?? 0} / {counts.fail ?? 0}</strong></div>
      <div><span>{zh ? "未知" : "Unknown"}</span><strong>{counts.unknown ?? 0}</strong></div>
      <div><span>{zh ? "配额延期" : "Quota deferred"}</span><strong>{counts.quota_deferred ?? 0}</strong></div>
      <div><span>Core12</span><strong>{counts.core12_symbols ?? 0}</strong></div>
    </div>
    <div className="full-watch-toolbar">
      <select value={scope} onChange={event => setScope(event.target.value as "FULL" | "CORE")} aria-label={zh ? "研究范围" : "Research scope"}><option value="FULL">{zh ? "完整自选" : "Full watchlist"}</option><option value="CORE">Core12 {zh ? "历史基准" : "benchmark"}</option></select>
      <select value={state} onChange={event => setState(event.target.value)} aria-label={zh ? "覆盖状态" : "Coverage state"}><option value="ALL">{zh ? "全部状态" : "All states"}</option><option value="PASS">PASS</option><option value="FAIL">FAIL</option><option value="UNKNOWN">UNKNOWN</option><option value="QUOTA_DEFERRED">QUOTA_DEFERRED</option><option value="UNKNOWN_IDENTITY">UNKNOWN_IDENTITY</option></select>
      <label><ScanSearch size={15} /><input value={query} onChange={event => setQuery(event.target.value)} placeholder={zh ? "搜索代码" : "Search symbol"} /></label>
      <span>{zh ? `扫描 ${grouped.length}，筛选 ${visible.length}，当前显示 ${displayed.length}` : `${grouped.length} scanned, ${visible.length} filtered, ${displayed.length} shown`}</span>
    </div>
    {visible.length ? <div className="full-watch-table"><div className="full-watch-head"><span>{zh ? "代码 / 报价" : "Symbol / quote"}</span><span>CALL</span><span>PUT</span><span>{zh ? "规则证据" : "Rule evidence"}</span><span>{zh ? "操作" : "Actions"}</span></div>{displayed.map((item: Json) => {
      const call = item.rights.CALL ?? {};
      const put = item.rights.PUT ?? {};
      const snapshot = call.snapshot ?? put.snapshot ?? item.snapshot ?? {};
      const quote = call.quote ?? put.quote ?? item.quote ?? {};
      const components = call.evaluation?.rule_components ?? put.evaluation?.rule_components ?? {};
      return <div className="full-watch-row" key={item.symbol}>
        <div><strong>{item.symbol}</strong><span>{quote.provider_status ?? "unavailable"} · {formatNumber(quote.display_last ?? quote.last ?? quote.last_done ?? quote.last_price)}</span><small>{quote.display_session ?? quote.session ?? quote.market_session ?? "—"} · {formatTime(quote.display_quote_time ?? quote.quote_time ?? quote.data_time ?? quote.timestamp)}</small></div>
        <div><Status value={call.coverage_state ?? "UNKNOWN"} /><small>{(call.reasons ?? []).slice(0, 2).join(" · ") || "—"}</small></div>
        <div><Status value={put.coverage_state ?? "UNKNOWN"} /><small>{(put.reasons ?? []).slice(0, 2).join(" · ") || "—"}</small></div>
        <div><span>C {formatNumber(snapshot.compression_ratio)} · V {formatNumber(snapshot.opening_participation)}</span><small>{zh ? "区间" : "Range"} {String(components.range_confirmation_pass ?? "—")} · {zh ? "市场" : "Market"} {String(components.market_confirmation_pass ?? "—")}</small><small>{snapshot.reference_session ?? "—"} · {item.is_core12 ? "CORE12" : "FULL_WATCH"}</small></div>
        <div className="full-watch-actions"><button className="icon-button" type="button" title={zh ? "按需检查期权能力" : "Check options on demand"} disabled={checking === item.symbol} onClick={() => void checkOptions(item.symbol)}><RefreshCw className={checking === item.symbol ? "spin" : ""} size={15} /></button><button className="icon-button" type="button" title={zh ? "打开期权链" : "Open option chain"} onClick={() => onOpenChain(item.symbol)}><Eye size={15} /></button></div>
      </div>;
    })}</div> : <Empty title={zh ? "没有匹配的覆盖记录" : "No matching coverage records"} detail={zh ? "更改范围、状态或搜索条件。" : "Change the scope, state, or search filter."} />}
    {displayed.length < visible.length ? <button className="quiet-button full-watch-more" type="button" onClick={() => setVisibleLimit(value => value + 30)}>{zh ? `再显示 ${Math.min(30, visible.length - displayed.length)} 个` : `Show ${Math.min(30, visible.length - displayed.length)} more`}</button> : null}
    {checkResult ? <div className="copilot-boundary"><ShieldCheck size={17} /><div><strong>{checkResult.symbol} · {checkResult.status}</strong><span>{zh ? `到期日 ${checkResult.expiry_count ?? 0}，最近 ${checkResult.nearest_expiry ?? "—"}；仅完成按需能力检查，未选合约、未生成信号。` : `${checkResult.expiry_count ?? 0} expiries, nearest ${checkResult.nearest_expiry ?? "—"}; this was an on-demand capability check only, with no contract selection or signal.`}</span></div></div> : null}
    <footer>{zh ? `运行 ${payload.run?.run_id ?? "—"} · ${formatTime(payload.run?.as_of)} · Full Watch收益状态 NOT_EVALUATED` : `Run ${payload.run?.run_id ?? "—"} · ${formatTime(payload.run?.as_of)} · Full Watch performance NOT_EVALUATED`}</footer>
  </section>;
}

function SignalCopilotView({ status, signalPayload, cbrm, paper, fullWatch, onOpenChain, onSaved }: { status: Json; signalPayload: Json; cbrm: Json; paper: Json; fullWatch: Json; onOpenChain: (symbol: string) => void; onSaved: () => void }) {
  const { t, formatTime, formatNumber, language } = useOptionI18n();
  const [selectedSignal, setSelectedSignal] = useState<Json | null>(null);
  const [action, setAction] = useState<"ENTRY" | "EXIT">("ENTRY");
  const [limitPrice, setLimitPrice] = useState("");
  const [quantity, setQuantity] = useState("1");
  const [paperResult, setPaperResult] = useState<Json | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const signals = Array.isArray(signalPayload.signals) ? signalPayload.signals : [];
  const dimensions = status.state_dimensions ?? {};
  const strategy = status.strategy ?? {};
  const execution = status.paper_execution ?? {};
  const router = status.model_router ?? {};
  const sol = router.roles?.SOL ?? {};
  const astra = router.roles?.ASTRA ?? status.astra_runtime ?? status.llm ?? {};
  const notifications = status.desktop_notifications ?? {};
  const research = cbrm.research_result ?? {};
  const evidenceAudit = cbrm.evidence_audit ?? {};
  const callAudit = evidenceAudit.statistics?.CALL?.revised ?? {};
  const putAudit = evidenceAudit.statistics?.PUT?.revised ?? {};
  const callAblation = research.ablation?.CALL ?? {};
  const putAblation = research.ablation?.PUT ?? {};
  const callValidation = research.models?.CALL?.partitions?.VALIDATION ?? {};
  const putValidation = research.models?.PUT?.partitions?.VALIDATION ?? {};
  const submitPaper = async (event: FormEvent) => {
    event.preventDefault();
    if (!selectedSignal) return;
    setSubmitting(true);
    setPaperResult(null);
    try {
      const contractId = String(selectedSignal.contract_id ?? "");
      const result = await requestJson("/api/options/copilot/paper/confirm", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          signal_id: selectedSignal.signal_id, action,
          confirmation_id: `${selectedSignal.signal_id}-${action}-${Date.now()}`,
          confirmation_text: `CONFIRM PAPER ${action}`, contract_id: contractId,
          contract_multiplier: Number(selectedSignal.contract_multiplier ?? 100),
          underlying: selectedSignal.symbol, theme_id: String(selectedSignal.theme_id ?? "UNCLASSIFIED"),
          limit_price: Number(limitPrice), requested_quantity: Number(quantity),
        }),
      });
      setPaperResult(result);
      onSaved();
    } catch (error) {
      setPaperResult({ status: "ERROR", reason: error instanceof Error ? error.message : String(error) });
    } finally { setSubmitting(false); }
  };
  if (status.current_policy_available === false) return <div className="option-page"><PolicyAvailabilityNotice data={status} /><FullWatchResearch payload={fullWatch} onOpenChain={onOpenChain} onSaved={onSaved} /></div>;
  return <div className="option-page signal-copilot-page">
    <section className="option-section signal-copilot-hero">
      <div className="section-title"><div><span className="eyebrow">SC · PAPER RESEARCH</span><h2>{t("Signal Copilot")}</h2><span>{t("Frozen rules create reviewable signals; notifications and Paper intents remain separate.")}</span></div><Status value={status.status ?? "WAIT_REVIEW"} /></div>
      <div className="copilot-boundary"><ShieldCheck size={17} /><div><strong>{t("Signals do not equal notifications or positions")}</strong><span>{t("Every Paper entry and exit requires owner confirmation before a new quote request.")}</span></div></div>
      <div className="copilot-status-grid">
        <div><span>{t("Strategy baseline")}</span><strong>{strategy.strategy_id ?? "STRAT-SHORT-ATM-RANGE-EXPANSION-V1"}</strong><small>{strategy.scope?.profile_id ?? "SHORT_ATM_DAYS_WEEK"} · Call / Put</small></div>
        <div><span>{t("Manual Paper overlay")}</span><strong>{execution.mode ?? "PAPER_MANUAL_CONFIRM"}</strong><small>{execution.enabled ? t("Engineering ready") : t("Waiting for SC-R1")}</small></div>
        <div><span>{language === "zh" ? "Sol 主研究" : "Sol primary research"}</span><strong>{sol.requested_model_id ?? "gpt-5.6-sol"}</strong><small>{t("Model access")} · {sol.capability?.status ?? "NOT_CHECKED"}</small></div>
        <div><span>{language === "zh" ? "Astra 复杂升级" : "Astra complex escalation"}</span><strong>{astra.requested_model_id ?? astra.requested_model ?? "gpt-6-astra"}</strong><small>{t("Model access")} · {astra.capability?.status ?? astra.model_access_status ?? "NOT_CHECKED"}</small></div>
        <div><span>{language === "zh" ? "共享模型预算" : "Shared model budget"}</span><strong>{router.budget?.status ?? t("Not approved")}</strong><small>{router.status ?? "READY_NO_PAID_INFERENCE"}</small></div>
        <div><span>{t("Desktop alerts")}</span><strong>{notifications.active_subscriptions ?? 0}</strong><small>{notifications.active_subscriptions ? t("Subscribed devices") : t("No subscribed device")}</small></div>
      </div>
    </section>
    <FullWatchResearch payload={fullWatch} onOpenChain={onOpenChain} onSaved={onSaved} />
    <section className="option-section">
      <div className="section-title"><div><span className="eyebrow">CBRM · DEV_ONLY</span><h3>{language === "zh" ? "条件突破研究" : "Conditional breakout research"}</h3><span>{language === "zh" ? "真实历史事件与正股代理标签；未加载到活动策略。" : "Real historical events and underlying-proxy labels; not loaded by the active strategy."}</span></div><Status value={research.status ?? cbrm.status ?? "NOT_BUILT"} /></div>
      <div className="cbrm-summary-grid">
        <div><span>BASE</span><strong>{research.event_count ?? 0}</strong><small>{language === "zh" ? "经济事件" : "economic events"}</small></div>
        <div><span>Call F0 / F1 / F2</span><strong>{callAblation.F0?.mature ?? 0} / {callAblation.F1?.mature ?? 0} / {callAblation.F2?.mature ?? 0}</strong><small>{language === "zh" ? "成熟标签" : "mature labels"}</small></div>
        <div><span>Put F0 / F1 / F2</span><strong>{putAblation.F0?.mature ?? 0} / {putAblation.F1?.mature ?? 0} / {putAblation.F2?.mature ?? 0}</strong><small>{language === "zh" ? "成熟标签" : "mature labels"}</small></div>
        <div><span>Call model</span><strong>{callValidation.model_status ?? "NOT_TRAINED"}</strong><small>{callValidation.training_events ?? 0} train · {callValidation.evaluation_events ?? 0} validation</small></div>
        <div><span>Put model</span><strong>{putValidation.model_status ?? "NOT_TRAINED"}</strong><small>{putValidation.training_events ?? 0} train · {putValidation.evaluation_events ?? 0} validation</small></div>
      </div>
      {evidenceAudit.audit_id ? <div className="copilot-boundary"><ShieldCheck size={17} /><div><strong>{language === "zh" ? "统计与时间口径已审计" : "Statistical and timing semantics audited"}</strong><span>{language === "zh" ? `Call Y差 ${formatNumber(callAudit.mean_Y?.point_estimate)}（bootstrap复制均值 ${formatNumber(callAudit.mean_Y?.bootstrap_replicate_mean)}）；Put Y差 ${formatNumber(putAudit.mean_Y?.point_estimate)}（bootstrap复制均值 ${formatNumber(putAudit.mean_Y?.bootstrap_replicate_mean)}）。36条记录是09:45入场资格取消，不是30分钟标签失效。` : `Call Y difference ${formatNumber(callAudit.mean_Y?.point_estimate)} (bootstrap replicate mean ${formatNumber(callAudit.mean_Y?.bootstrap_replicate_mean)}); Put ${formatNumber(putAudit.mean_Y?.point_estimate)} (bootstrap replicate mean ${formatNumber(putAudit.mean_Y?.bootstrap_replicate_mean)}). The 36 records are 09:45 entry-eligibility cancellations, not 30-minute label failures.`}</span></div></div> : null}
      {Array.isArray(cbrm.latest_events) && cbrm.latest_events.length ? <details className="option-audit-details"><summary>{language === "zh" ? "查看最新真实规则计算" : "View latest real rule calculations"}</summary><div className="signal-record-list">{cbrm.latest_events.slice(0, 8).map((item: Json) => <div className="signal-record" key={item.economic_event_id}><div><strong>{item.symbol} · {item.right}</strong><span>{item.session} · C {formatNumber(item.features?.C)} · log(V) {formatNumber(item.features?.V_log)}</span></div><Status value={item.group_states?.F2} /><span>{item.label?.state === "INVALID_BEFORE_T0" ? "CANCELLED_AT_T0" : item.label?.state}</span><time>{formatTime(item.signal_at)}</time></div>)}</div></details> : null}
    </section>
    <section className="option-section">
      <div className="section-title"><div><h3>{t("Signal records")}</h3><span>{t("Market observation")} · {dimensions.LIVE_SESSION_OBSERVATION ?? "WAIT_MARKET"}</span></div><Status value={dimensions.SIGNALS ?? "ENGINEERING_READY_NOT_ACTIVATED"} /></div>
      {signals.length ? <div className="signal-record-list">{signals.map((item: Json) => <div className="signal-record" key={item.signal_id}><div><strong>{item.symbol} · {item.right}</strong><span>{item.contract_id ?? "-"}</span></div><Status value={item.state} /><span>{item.source}</span><time>{formatTime(item.updated_at ?? item.observed_at)}</time><button className="icon-button" type="button" title={language === "zh" ? "人工 Paper 确认" : "Manual Paper confirmation"} onClick={() => setSelectedSignal(item)}><Check size={15} /></button></div>)}</div> : <Empty title={t("No Signal Copilot records yet")} detail={t("The strategy is frozen, but activation waits for SC-R1 and the next eligible market session.")} />}
      {selectedSignal ? <form className="paper-confirm-form" onSubmit={submitPaper}>
        <div><strong>{selectedSignal.symbol} · {selectedSignal.contract_id ?? "-"}</strong><span>{language === "zh" ? "每次入场和退出都会在确认后重新请求报价。" : "Every entry and exit requests a new quote after confirmation."}</span></div>
        <label>{language === "zh" ? "动作" : "Action"}<select value={action} onChange={event => setAction(event.target.value as "ENTRY" | "EXIT")}><option value="ENTRY">ENTRY</option><option value="EXIT">EXIT</option></select></label>
        <label>{language === "zh" ? "限价" : "Limit"}<input inputMode="decimal" value={limitPrice} onChange={event => setLimitPrice(event.target.value)} required /></label>
        <label>{language === "zh" ? "数量" : "Quantity"}<input inputMode="numeric" value={quantity} onChange={event => setQuantity(event.target.value)} required /></label>
        <button type="submit" disabled={!execution.enabled || submitting || !limitPrice}>{submitting ? (language === "zh" ? "提交中" : "Submitting") : (language === "zh" ? "确认 Paper 意图" : "Confirm Paper intent")}</button>
        {!execution.enabled ? <small>{language === "zh" ? "当前审批门保持关闭，不会请求报价或建仓。" : "The current approval gate is closed; no quote or position will be requested."}</small> : null}
        {paperResult ? <Status value={paperResult.status} /> : null}
      </form> : null}
    </section>
    <section className="option-section compact-boundaries"><div><span>{t("Real orders enabled")}</span><strong>{String(status.orders_enabled ?? false)}</strong></div><div><span>{t("Paper engine")}</span><strong>{dimensions.PAPER_ENGINE ?? "SYNTHETIC_ONLY_WAIT_SC_R1"}</strong></div><div><span>{language === "zh" ? "Paper 持仓" : "Paper positions"}</span><strong>{Array.isArray(paper.positions) ? paper.positions.filter((item: Json) => item.state === "OPEN").length : 0}</strong></div><div><span>{t("Performance")}</span><strong>{dimensions.PERFORMANCE ?? "INCONCLUSIVE"}</strong></div></section>
  </div>;
}

export default function OptionsWorkspace(props: Props) {
  if (!props.symbol && ["opportunities", "chart"].includes(props.view)) return <div className="option-page"><Empty title={props.language === "zh" ? "未选择标的" : "No symbol selected"} detail="" /></div>;
  if (props.view === "settings") return <><LegacyOptionsWorkspace {...props} /><WorkspaceAccessSettings language={props.language} /><AiConnectionSettings language={props.language} /></>;
  if (["today", "signals", "plans", "review"].includes(props.view)) return <OptionsOperations key={props.view} view={props.view} symbol={props.symbol} refreshNonce={props.refreshNonce} onOpenChain={props.onOpenChain} />;
  if (props.view === "opportunities") return <div className="option-page"><OptionReferenceChain key={props.symbol} symbol={props.symbol} language={props.language} refreshNonce={props.refreshNonce} /></div>;
  return <LegacyOptionsWorkspace {...props} />;
}

function LegacyOptionsWorkspace({ view, symbol, refreshNonce, chart, onSymbolChange, onOpenChain, language, theme, onLanguageChange, onThemeChange }: Props) {
  const { t, stateLabel, explain, formatNumber, formatTime } = useOptionI18n();
  const [payloads, setPayloads] = useState<Record<string, Json>>({});
  const [errors, setErrors] = useState<Record<string, string>>({});
  const [loading, setLoading] = useState(false);
  const [localNonce, setLocalNonce] = useState(0);
  const [selectedId, setSelectedId] = useState(() => new URLSearchParams(window.location.search).get("opportunity") ?? "");
  const [timeline, setTimeline] = useState<Json | null>(null);
  const [manualPlanId, setManualPlanId] = useState("");
  const [groupFilter, setGroupFilter] = useState("ALL");
  const [directionFilter, setDirectionFilter] = useState("ALL");
  const [stateFilter, setStateFilter] = useState("ACTIVE");
  const [scanJob, setScanJob] = useState<Json | null>(null);
  const linkedPlanId = new URLSearchParams(window.location.search).get("plan");

  useEffect(() => {
    if (view !== "plans" || !linkedPlanId) return;
    const controller = new AbortController();
    void requestJson(`/api/options/plans/${encodeURIComponent(linkedPlanId)}/timeline`, undefined, controller.signal)
      .then(result => { if (!controller.signal.aborted) setTimeline(result); })
      .catch(() => { if (!controller.signal.aborted) setErrors(current => ({ ...current, timeline: t("Some data could not be loaded. See full diagnostics.") })); });
    return () => controller.abort();
  }, [view, linkedPlanId, t]);

  const endpoints = useMemo(() => {
    const common: Record<string, string> = {
      status: "/api/options/radar/status",
      foundation: "/api/options/foundation/status",
      profiles: "/api/options/profiles",
      forward: "/api/options/research/forward/status",
    };
    if (view === "today") return { ...common, daily: "/api/options/daily-summary", signals: "/api/options/signals/current?limit=5", watchlist: "/api/options/watchlist", simulations: "/api/options/simulations?limit=50", manual: "/api/options/manual-outcomes?limit=50" };
    if (view === "signals") return { ...common, copilot: "/api/options/copilot/status", copilotSignals: "/api/options/copilot/signals?limit=100", cbrm: `/api/options/research/cbrm?symbol=${encodeURIComponent(symbol)}&limit=20`, copilotPaper: "/api/options/copilot/paper", fullWatch: "/api/options/full-watch/status?scope=full", notifications: "/api/stocks/notifications/status" };
    if (view === "opportunities") return { ...common, signals: "/api/options/signals/current?limit=100", premarket: "/api/options/radar/premarket", audit: "/api/options/data-audit", watchlist: "/api/options/watchlist" };
    if (view === "plans") return { ...common, signals: "/api/options/signals/current?limit=100", watchlist: "/api/options/watchlist?active_only=false", simulations: "/api/options/simulations?limit=200", manual: "/api/options/manual-outcomes?limit=200" };
    if (view === "review") return { ...common, research: "/api/options/research-report", workbench: "/api/options/research/workbench", reviewR1: "/api/options/research/reviews/r1", reviewR2: "/api/options/research/reviews/r2", reviewR3: "/api/options/research/reviews/r3", reviewR4: "/api/options/research/reviews/r4", reviewR5: "/api/options/research/reviews/r5", reviewR6: "/api/options/research/reviews/r6", simulations: "/api/options/simulations?limit=200", manual: "/api/options/manual-outcomes?limit=200", signals: "/api/options/signals/current?limit=100" };
    if (view === "settings") return { ...common, audit: "/api/options/data-audit", notifications: "/api/stocks/notifications/status" };
    return common;
  }, [view, symbol]);

  const load = useCallback(async (signal?: AbortSignal) => {
    setLoading(true);
    const entries = await Promise.all(Object.entries(endpoints).map(async ([key, path]) => {
      try { return [key, await requestJson(path, undefined, signal), ""] as const; }
      catch { return [key, {}, t("Some data could not be loaded. See full diagnostics.")] as const; }
    }));
    if (signal?.aborted) return;
    setPayloads(Object.fromEntries(entries.map(([key, value]) => [key, value])));
    setErrors(Object.fromEntries(entries.filter(([, , error]) => error).map(([key, , error]) => [key, error])));
    setLoading(false);
  }, [endpoints, t]);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load, refreshNonce, localNonce]);

  useEffect(() => {
    if (!scanJob?.job_id || !["queued", "running"].includes(String(scanJob.status))) return;
    const timer = window.setInterval(async () => {
      try {
        const next = await requestJson(`/api/options/radar/jobs/${encodeURIComponent(scanJob.job_id)}`);
        setScanJob(next);
        if (["completed", "failed"].includes(String(next.status))) setLocalNonce((value) => value + 1);
      } catch {
        window.clearInterval(timer);
      }
    }, 1500);
    return () => window.clearInterval(timer);
  }, [scanJob?.job_id, scanJob?.status]);

  const opportunities = (Array.isArray(payloads.signals?.opportunities) ? payloads.signals.opportunities : Array.isArray(payloads.premarket?.opportunities) ? payloads.premarket.opportunities : []) as OptionOpportunity[];
  const watchRows = (Array.isArray(payloads.watchlist?.items) ? payloads.watchlist.items : []) as Json[];
  const watched = useMemo(() => new Set(watchRows.filter((item) => item.status === "active").map((item) => String(item.plan_id))), [watchRows]);
  const simulations = (Array.isArray(payloads.simulations?.outcomes) ? payloads.simulations.outcomes : []) as Json[];
  const manualRows = (Array.isArray(payloads.manual?.items) ? payloads.manual.items : []) as Json[];
  const selected = opportunities.find((item) => item.opportunity_id === selectedId) ?? opportunities.find((item) => item.symbol === symbol) ?? opportunities[0] ?? null;

  useEffect(() => {
    if (!selected || selected.opportunity_id === selectedId) return;
    setSelectedId(selected.opportunity_id);
  }, [selected, selectedId]);

  const filtered = opportunities.filter((item) => {
    const groupMatch = groupFilter === "ALL" || (item.plans ?? []).some((plan) => plan.horizon_group === groupFilter);
    const directionMatch = directionFilter === "ALL" || item.direction === directionFilter;
    const stateMatch = stateFilter === "ALL" || (stateFilter === "ACTIVE" ? ACTIVE_STATES.has(item.status) : !ACTIVE_STATES.has(item.status));
    return groupMatch && directionMatch && stateMatch;
  });

  const selectOpportunity = (item: OptionOpportunity) => {
    setSelectedId(item.opportunity_id);
    setTimeline(null);
    setManualPlanId("");
    onSymbolChange(item.symbol);
    const url = new URL(window.location.href);
    url.searchParams.set("opportunity", item.opportunity_id);
    url.searchParams.set("symbol", item.symbol);
    window.history.replaceState({}, "", `${url.pathname}${url.search}${url.hash}`);
  };

  const startScan = async () => {
    try {
      setScanJob(await requestJson("/api/options/radar/runs", { method: "POST" }));
    } catch (error) {
      setErrors((current) => ({ ...current, scan: error instanceof Error ? error.message : t("Some data could not be loaded. See full diagnostics.") }));
    }
  };

  const addWatch = async (planId: string) => {
    await requestJson("/api/options/watchlist", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ plan_id: planId, notes: "unified_workspace_watch" }) });
    setLocalNonce((value) => value + 1);
  };
  const removeWatch = async (planId: string) => {
    await requestJson(`/api/options/watchlist/${encodeURIComponent(planId)}`, { method: "DELETE" });
    setLocalNonce((value) => value + 1);
  };
  const openTimeline = async (planId: string) => {
    setTimeline(await requestJson(`/api/options/plans/${encodeURIComponent(planId)}/timeline`));
    setManualPlanId("");
  };

  const outcomeCount = [...simulations, ...manualRows].filter((item) => String(item.status).toLowerCase() === "completed").length;
  const status = payloads.status ?? {};
  const foundation = payloads.foundation ?? {};
  const foundationMode = String(status.supervisor?.mode ?? "") === "foundation";
  const currentOpportunities = foundationMode ? [] : opportunities;
  const urgent = currentOpportunities.filter((item) => ["CONFIRMED", "EXIT_REVIEW"].includes(item.status));
  const anyError = Object.values(errors)[0];

  if (view === "chart") return <div className="option-page">{chart}</div>;

  if (view === "signals") return <SignalCopilotView status={payloads.copilot ?? {}} signalPayload={payloads.copilotSignals ?? {}} cbrm={payloads.cbrm ?? {}} paper={payloads.copilotPaper ?? {}} fullWatch={payloads.fullWatch ?? {}} onOpenChain={onOpenChain} onSaved={() => setLocalNonce(value => value + 1)} />;

  if (view === "today") return <div className="option-page">
    {foundationMode ? <ResearchProfiles payload={foundation} /> : <OptionSummaryStrip status={status} opportunities={currentOpportunities} watchCount={watched.size} outcomeCount={outcomeCount} />}
    {foundationMode ? <ForwardResearchStatus payload={payloads.forward ?? {}} /> : null}
    <DailyScopeSummary payload={payloads.daily ?? {}} />
    <section className="option-section"><div className="section-title"><div><h2>{t("Today")}</h2><span>{t("Handle exits and confirmed opportunities first; keep everything else under observation.")}</span></div><button type="button" className="quiet-button" onClick={() => setLocalNonce((value) => value + 1)}><RefreshCw size={15} />{t("Refresh")}</button></div>{urgent.length ? <OpportunityRows items={urgent} selectedId={selectedId} onSelect={selectOpportunity} /> : <Empty title={t("No plans require immediate action")} detail={foundationMode ? t("No new signals are generated in foundation mode.") : t("Current candidates remain under observation or are blocked by data requirements.")} />}</section>
    {!foundationMode ? <section className="option-section"><div className="section-title"><div><h2>{t("Latest opportunities")}</h2><span>{t("Up to five premarket candidates; there is no daily recommendation quota.")}</span></div></div><OpportunityRows items={currentOpportunities.slice(0, 5)} selectedId={selectedId} onSelect={selectOpportunity} /></section> : null}
    {foundationMode || status.opra_status !== "available" ? <div className="option-warning"><ShieldAlert size={17} /><div><strong>{foundationMode ? t("Native BBO event time unavailable") : t("Option chain reference only")}</strong><span>{foundationMode ? t("OPRA is verified, but native BBO event time is unavailable; strict simulated fills remain blocked.") : t("Longbridge provides the option chain. OPRA permission and timestamped BBO evidence are not available, so bid, ask, cost, and Greeks stay hidden.")}</span></div></div> : null}
  </div>;

  if (view === "opportunities") return <div className="option-page">
    <OptionReferenceChain key={symbol} symbol={symbol} language={language} refreshNonce={refreshNonce} />
    {foundationMode ? <ResearchProfiles payload={foundation} /> : null}
    <section className="option-toolbar"><div className="option-filters" aria-label={t("Option opportunity filters")}><select value={groupFilter} onChange={(event) => setGroupFilter(event.target.value)}><option value="ALL">{t("All horizons")}</option><option value="INTRADAY_0DTE">{t("0DTE intraday")}</option><option value="INTRADAY_7_14DTE">{t("Non-0DTE intraday")}</option><option value="SWING_14_35DTE">{t("Short swing")}</option></select><select value={directionFilter} onChange={(event) => setDirectionFilter(event.target.value)}><option value="ALL">Call + Put</option><option value="CALL">Call</option><option value="PUT">Put</option></select><select value={stateFilter} onChange={(event) => setStateFilter(event.target.value)}><option value="ACTIVE">{t("Active opportunities")}</option><option value="HISTORY">{t("Cancelled / history")}</option><option value="ALL">{t("All states")}</option></select></div>{!foundationMode ? <div className="option-toolbar-actions"><span>{formatTime(payloads.premarket?.generated_at ?? status.latest_premarket?.generated_at)}</span><button type="button" className="quiet-button" onClick={() => void startScan()} disabled={Boolean(scanJob && ["queued", "running"].includes(String(scanJob.status)))}><ScanSearch size={15} />{scanJob && ["queued", "running"].includes(String(scanJob.status)) ? t("Scanning") : t("Rescan")}</button></div> : null}</section>
    {anyError ? <div className="option-inline-error"><AlertTriangle size={15} />{t("Some data could not be loaded. See full diagnostics.")}</div> : null}
    {foundationMode ? <div className="section-title legacy-record-title"><div><h3>{t("Legacy radar records")}</h3><span>{t("These records are preserved for audit and are not generated by the new profiles.")}</span></div></div> : null}
    <div className="option-master-detail"><section className="option-master"><OpportunityRows items={filtered} selectedId={selected?.opportunity_id ?? ""} onSelect={selectOpportunity} /></section><OpportunityDetail opportunity={selected} watched={watched} strictQuoteReady={Boolean(payloads.audit?.strict_simulated_fill_ready)} timeline={timeline} manualPlanId={manualPlanId} onWatch={(id) => void addWatch(id)} onUnwatch={(id) => void removeWatch(id)} onTimeline={(id) => void openTimeline(id)} onManual={setManualPlanId} onSaved={() => { setManualPlanId(""); setLocalNonce((value) => value + 1); }} /></div>
    {loading ? <div className="option-loading"><RefreshCw className="spin" size={15} />{t("Updating option opportunities")}</div> : null}
  </div>;

  if (view === "plans") {
    const forwardPaper = (Array.isArray(payloads.forward?.paper_records) ? payloads.forward.paper_records : []) as Json[];
    const rows: Json[] = [...forwardPaper.map((item) => ({ ...item, source_kind: t("Forward Paper"), timeline_available: false })), ...watchRows.map((item) => ({ ...item, source_kind: t("Watchlist"), timeline_available: true })), ...simulations.map((item) => ({ ...item, source_kind: t("System simulation"), timeline_available: true })), ...manualRows.map((item) => ({ ...item, source_kind: t("Manual record"), timeline_available: true }))];
    return <div className="option-page"><ForwardResearchStatus payload={payloads.forward ?? {}} /><section className="option-section"><div className="section-title"><div><h2>{t("Plans and tracking")}</h2><span>{t("Watchlists, simulations, and manual outcomes are stored separately; cross-day plans remain visible.")}</span></div><BellRing size={18} /></div>{rows.length ? <div className="tracking-list">{rows.map((item, index) => <div className="tracking-row" key={`${item.source_kind}-${item.plan_id}-${index}`}><div><strong>{item.symbol ?? item.contract_symbol ?? item.plan_id}</strong><span>{item.contract_symbol ?? t("Waiting for contract selection")}</span></div><span>{item.source_kind}</span><Status value={item.plan_state ?? item.status} /><time>{formatTime(item.updated_at)}</time>{item.plan_id && item.timeline_available ? <button className="icon-button" type="button" onClick={() => void openTimeline(String(item.plan_id))} title={t("View plan timeline")}><FileClock size={15} /></button> : null}</div>)}</div> : <Empty title={t("No tracked plans")} detail={t("Add a contract to the watchlist, or wait for strict quotes before simulation.")} />}</section><Timeline payload={timeline} /></div>;
  }

  if (view === "review") {
    const metrics = Object.entries(payloads.research?.metrics_by_horizon_and_direction ?? {});
    return <div className="option-page"><OptionsResearchWorkbench payload={payloads.workbench ?? {}} reviewR1={payloads.reviewR1 ?? {}} reviewR2={payloads.reviewR2 ?? {}} reviewR3={payloads.reviewR3 ?? {}} reviewR4={payloads.reviewR4 ?? {}} reviewR5={payloads.reviewR5 ?? {}} reviewR6={payloads.reviewR6 ?? {}} symbol={symbol} /><section className="option-section"><div className="section-title"><div><h2>{t("Options review")}</h2><span>{t("Simulation and manual outcomes are separate and do not borrow stock backtests or legacy Paper results.")}</span></div><FlaskConical size={18} /></div><div className="review-status"><Status value={payloads.research?.performance_status ?? "PERFORMANCE_UNPROVEN"} /><span>{t("Completed outcomes")} {outcomeCount}</span><span>{t("Minimum independent sample gate")} 200 / {t("Horizon / direction")}</span></div>{metrics.length ? <div className="metrics-table"><div className="metrics-head"><span>{t("Horizon / direction")}</span><span>{t("Samples")}</span><span>{t("Win rate")}</span><span>Payoff</span><span>PF</span><span>{t("Evidence status")}</span></div>{metrics.map(([key, value]: [string, any]) => <div className="metrics-row" key={key}><strong>{key.replace("|", " · ")}</strong><span>{value.completed ?? 0}</span><span>{value.win_rate_pct == null ? "-" : `${formatNumber(value.win_rate_pct, 1)}%`}</span><span>{formatNumber(value.payoff)}</span><span>{formatNumber(value.profit_factor)}</span><Status value={value.evidence_status} /></div>)}</div> : <Empty title={t("Performance evidence is not established")} detail={t("Strict-quote outcomes are unavailable, so an option strategy win rate cannot be reported.")} />}</section><section className="option-section"><div className="section-title"><div><h3>{t("Outcome records")}</h3><span>{t("Records with unknown fees are not presented as net performance.")}</span></div></div>{[...manualRows, ...simulations].length ? <div className="tracking-list">{[...manualRows, ...simulations].map((item, index) => <div className="tracking-row" key={`${item.outcome_id ?? item.manual_outcome_id}-${index}`}><div><strong>{item.symbol ?? item.plan_id}</strong><span>{item.contract_symbol ?? (item.source === "user_reported" ? t("Manual record") : t("System simulation"))}</span></div><span>{item.source === "user_reported" ? t("Manual") : t("Simulation")}</span><Status value={item.status} /><time>{formatTime(item.updated_at)}</time><span className="mono">{item.net_pnl == null ? t("Net performance pending fees") : `$${formatNumber(item.net_pnl)}`}</span></div>)}</div> : null}</section></div>;
  }

  const provider = payloads.audit?.provider ?? status;
  const capability = foundation?.capability_evidence ?? {};
  const providerAvailable = capability.entitlement_status === "VERIFIED" || (String(provider?.provider ?? status.provider).toLowerCase() === "longbridge" && String(provider?.status ?? status.status).toLowerCase() === "available");
  const quotePackages = Array.isArray(provider?.quote_packages) ? provider.quote_packages.map((item: unknown) => typeof item === "string" ? item : String((item as Json)?.key ?? "")).join(" ") : "";
  const underlyingRealtime = providerAvailable && quotePackages.includes("US_QBBO_OpenAPI");
  const opraAvailable = capability.entitlement_status === "VERIFIED" || String(provider?.opra_status ?? status.opra_status).toLowerCase() === "available";
  const strictBboReady = Boolean(payloads.audit?.strict_simulated_fill_ready);
  const notificationStatus = Number(payloads.notifications?.active_subscriptions ?? 0) > 0
    ? t("Device registered; display unverified") : t("Waiting for device permission");
  return <div className="option-page"><PolicyAvailabilityNotice data={foundation.profiles ?? {}} /><OptionRuntimeStatus status={status} notifications={payloads.notifications ?? {}} reload={() => setLocalNonce(value => value + 1)} notificationsOnly /><section className="option-section"><div className="section-title"><div><span className="eyebrow">{t("Display preferences")}</span><h2>{t("Appearance")}</h2><span>{t("Preferences stay in this browser and do not affect option data, screening, or risk controls.")}</span></div></div><div className="settings-lines preference-lines"><div><div><span>{t("Language")}</span><small>{t("Navigation and unified workspace")}</small></div><div className="preference-control" role="group" aria-label={t("Language")}><button type="button" className={language === "zh" ? "active" : ""} onClick={() => onLanguageChange("zh")}><Languages size={14} />中文</button><button type="button" className={language === "en" ? "active" : ""} onClick={() => onLanguageChange("en")}>English</button></div></div><div><div><span>{t("Appearance")}</span><small>{t("Dark and light themes")}</small></div><div className="preference-control" role="group" aria-label={t("Appearance")}><button type="button" className={theme === "dark" ? "active" : ""} onClick={() => onThemeChange("dark")}><Moon size={14} />{t("Dark")}</button><button type="button" className={theme === "light" ? "active" : ""} onClick={() => onThemeChange("light")}><Sun size={14} />{t("Light")}</button></div></div></div><div className="section-title"><div><span className="eyebrow">{t("Option runtime")}</span><h2>{t("Option data and notifications")}</h2><span>{t("Technical diagnostics stay here instead of occupying the opportunity list.")}</span></div></div><div className="settings-lines option-source-layers"><div><span>{t("Data platform")}</span><strong>Longbridge</strong></div><div><span>{t("Underlying real-time quotes")}</span><strong>{underlyingRealtime ? t("Available") : t("Not available")}</strong></div><div><span>{t("Option chain")}</span><strong>{providerAvailable ? t("Reference data available") : t("Not available")}</strong></div><div><span>{t("OPRA real-time options")}</span><strong>{opraAvailable ? t("Available") : t("Permission not detected")}</strong></div><div><span>{t("Strict BBO")}</span><strong>{strictBboReady ? t("Verifiable") : t("Not verifiable")}</strong></div><div><span>{t("Simulated fills")}</span><strong>{strictBboReady ? t("Available") : t("Blocked by quote evidence")}</strong></div><div><span>{t("Web alerts")}</span><strong>{notificationStatus}</strong></div><div><span>{t("Operating boundary")}</span><strong>{t("Manual review; no order submission")}</strong></div></div><div className="option-warning source-disclosure"><ShieldAlert size={17} /><div><strong>{opraAvailable ? t("Native BBO event time unavailable") : t("Option chain reference only")}</strong><span>{opraAvailable ? t("OPRA is verified, but native BBO event time is unavailable; strict simulated fills remain blocked.") : t("Longbridge provides the option chain. OPRA permission and timestamped BBO evidence are not available, so bid, ask, cost, and Greeks stay hidden.")}</span></div></div><details className="option-audit-details" open><summary>{t("Data blockers")}</summary>{Array.isArray(payloads.audit?.blockers) && payloads.audit.blockers.length ? <ul>{payloads.audit.blockers.map((item: string) => <li key={item}>{explain(item)}</li>)}</ul> : <p>{t("No registered blockers")}</p>}</details><details className="option-audit-details"><summary>{t("Versions and counts")}</summary><pre>{JSON.stringify({ provider, capability, profiles: foundation?.profiles, policy: status.policy_version, counts: payloads.audit?.counts, supervisor: status.supervisor }, null, 2)}</pre></details></section></div>;
}
