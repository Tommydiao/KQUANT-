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
  const body = await response.json().catch(() => ({}));
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

function Empty({ title, detail }: { title: string; detail: string }) {
  return <div className="option-empty"><CircleSlash size={19} /><strong>{title}</strong><span>{detail}</span></div>;
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
      const multiplier = Number(quote.contract_multiplier ?? 100);
      const cost = strictQuoteReady && Number.isFinite(Number(quote.ask)) ? Number(quote.ask) * multiplier : null;
      const isWatched = watched.has(plan.plan_id);
      return <div className="contract-row" key={plan.plan_id}>
        <div><strong>{plan.contract_symbol}</strong><small>{groupLabel(plan.horizon_group)}</small></div>
        <div><strong>{plan.expiry_date}</strong><small>{formatNumber(plan.strike_price)} · {plan.dte} DTE</small></div>
        <div><strong>{strictQuoteReady ? `${formatNumber(quote.bid)} / ${formatNumber(quote.ask)}` : "-"}</strong><small>{strictQuoteReady && quote.spread_pct != null ? `${t("Spread")} ${formatNumber(quote.spread_pct, 1)}%` : stateLabel("REFERENCE_ONLY")}</small></div>
        <div><strong>{cost == null ? "-" : `$${formatNumber(cost)}`}</strong><small>{strictQuoteReady ? t("One contract; no sizing advice") : stateLabel("REFERENCE_ONLY")}</small></div>
        <div><strong>{strictQuoteReady ? `Δ ${formatNumber(quote.delta)} · Θ ${formatNumber(quote.theta, 3)}` : "-"}</strong><small>{strictQuoteReady ? `IV ${quote.implied_volatility == null ? "-" : `${formatNumber(Number(quote.implied_volatility) * 100, 1)}%`} · Vega ${formatNumber(quote.vega, 3)}` : stateLabel("REFERENCE_ONLY")}</small></div>
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

export default function OptionsWorkspace({ view, symbol, refreshNonce, chart, onSymbolChange, language, theme, onLanguageChange, onThemeChange }: Props) {
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
    const common: Record<string, string> = { status: "/api/options/radar/status" };
    if (view === "today") return { ...common, signals: "/api/options/signals/current?limit=5", watchlist: "/api/options/watchlist", simulations: "/api/options/simulations?limit=50", manual: "/api/options/manual-outcomes?limit=50" };
    if (view === "opportunities") return { ...common, signals: "/api/options/signals/current?limit=100", premarket: "/api/options/radar/premarket", audit: "/api/options/data-audit", watchlist: "/api/options/watchlist" };
    if (view === "plans") return { ...common, signals: "/api/options/signals/current?limit=100", watchlist: "/api/options/watchlist?active_only=false", simulations: "/api/options/simulations?limit=200", manual: "/api/options/manual-outcomes?limit=200" };
    if (view === "review") return { ...common, research: "/api/options/research-report", simulations: "/api/options/simulations?limit=200", manual: "/api/options/manual-outcomes?limit=200", signals: "/api/options/signals/current?limit=100" };
    if (view === "settings") return { ...common, audit: "/api/options/data-audit", notifications: "/api/stocks/notifications/status" };
    return common;
  }, [view]);

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
  const urgent = opportunities.filter((item) => ["CONFIRMED", "EXIT_REVIEW"].includes(item.status));
  const status = payloads.status ?? {};
  const anyError = Object.values(errors)[0];

  if (view === "chart") return <div className="option-page"><section className="option-page-head"><div><h2>{symbol} {t("Underlying chart")}</h2><p>{t("Option opportunities begin with underlying evidence; charts only use closed market data.")}</p></div></section>{chart}</div>;

  if (view === "today") return <div className="option-page">
    <OptionSummaryStrip status={status} opportunities={opportunities} watchCount={watched.size} outcomeCount={outcomeCount} />
    <section className="option-section"><div className="section-title"><div><h2>{t("Today")}</h2><span>{t("Handle exits and confirmed opportunities first; keep everything else under observation.")}</span></div><button type="button" className="quiet-button" onClick={() => setLocalNonce((value) => value + 1)}><RefreshCw size={15} />{t("Refresh")}</button></div>{urgent.length ? <OpportunityRows items={urgent} selectedId={selectedId} onSelect={selectOpportunity} /> : <Empty title={t("No plans require immediate action")} detail={t("Current candidates remain under observation or are blocked by data requirements.")} />}</section>
    <section className="option-section"><div className="section-title"><div><h2>{t("Latest opportunities")}</h2><span>{t("Up to five premarket candidates; there is no daily recommendation quota.")}</span></div></div><OpportunityRows items={opportunities.slice(0, 5)} selectedId={selectedId} onSelect={selectOpportunity} /></section>
    {status.opra_status !== "available" ? <div className="option-warning"><ShieldAlert size={17} /><div><strong>{t("Option chain reference only")}</strong><span>{t("Longbridge provides the option chain. OPRA permission and timestamped BBO evidence are not available, so bid, ask, cost, and Greeks stay hidden.")}</span></div></div> : null}
  </div>;

  if (view === "opportunities") return <div className="option-page">
    <section className="option-toolbar"><div className="option-filters" aria-label={t("Option opportunity filters")}><select value={groupFilter} onChange={(event) => setGroupFilter(event.target.value)}><option value="ALL">{t("All horizons")}</option><option value="INTRADAY_0DTE">{t("0DTE intraday")}</option><option value="INTRADAY_7_14DTE">{t("Non-0DTE intraday")}</option><option value="SWING_14_35DTE">{t("Short swing")}</option></select><select value={directionFilter} onChange={(event) => setDirectionFilter(event.target.value)}><option value="ALL">Call + Put</option><option value="CALL">Call</option><option value="PUT">Put</option></select><select value={stateFilter} onChange={(event) => setStateFilter(event.target.value)}><option value="ACTIVE">{t("Active opportunities")}</option><option value="HISTORY">{t("Cancelled / history")}</option><option value="ALL">{t("All states")}</option></select></div><div className="option-toolbar-actions"><span>{formatTime(payloads.premarket?.generated_at ?? status.latest_premarket?.generated_at)}</span><button type="button" className="quiet-button" onClick={() => void startScan()} disabled={Boolean(scanJob && ["queued", "running"].includes(String(scanJob.status)))}><ScanSearch size={15} />{scanJob && ["queued", "running"].includes(String(scanJob.status)) ? t("Scanning") : t("Rescan")}</button></div></section>
    {anyError ? <div className="option-inline-error"><AlertTriangle size={15} />{t("Some data could not be loaded. See full diagnostics.")}</div> : null}
    <div className="option-master-detail"><section className="option-master"><OpportunityRows items={filtered} selectedId={selected?.opportunity_id ?? ""} onSelect={selectOpportunity} /></section><OpportunityDetail opportunity={selected} watched={watched} strictQuoteReady={Boolean(payloads.audit?.strict_simulated_fill_ready)} timeline={timeline} manualPlanId={manualPlanId} onWatch={(id) => void addWatch(id)} onUnwatch={(id) => void removeWatch(id)} onTimeline={(id) => void openTimeline(id)} onManual={setManualPlanId} onSaved={() => { setManualPlanId(""); setLocalNonce((value) => value + 1); }} /></div>
    {loading ? <div className="option-loading"><RefreshCw className="spin" size={15} />{t("Updating option opportunities")}</div> : null}
  </div>;

  if (view === "plans") {
    const rows: Json[] = [...watchRows.map((item) => ({ ...item, source_kind: t("Watchlist") })), ...simulations.map((item) => ({ ...item, source_kind: t("System simulation") })), ...manualRows.map((item) => ({ ...item, source_kind: t("Manual record") }))];
    return <div className="option-page"><section className="option-section"><div className="section-title"><div><h2>{t("Plans and tracking")}</h2><span>{t("Watchlists, simulations, and manual outcomes are stored separately; cross-day plans remain visible.")}</span></div><BellRing size={18} /></div>{rows.length ? <div className="tracking-list">{rows.map((item, index) => <div className="tracking-row" key={`${item.source_kind}-${item.plan_id}-${index}`}><div><strong>{item.symbol ?? item.contract_symbol ?? item.plan_id}</strong><span>{item.contract_symbol ?? t("Waiting for contract selection")}</span></div><span>{item.source_kind}</span><Status value={item.plan_state ?? item.status} /><time>{formatTime(item.updated_at)}</time>{item.plan_id ? <button className="icon-button" type="button" onClick={() => void openTimeline(String(item.plan_id))} title={t("View plan timeline")}><FileClock size={15} /></button> : null}</div>)}</div> : <Empty title={t("No tracked plans")} detail={t("Add a contract to the watchlist, or wait for strict quotes before simulation.")} />}</section><Timeline payload={timeline} /></div>;
  }

  if (view === "review") {
    const metrics = Object.entries(payloads.research?.metrics_by_horizon_and_direction ?? {});
    return <div className="option-page"><section className="option-section"><div className="section-title"><div><h2>{t("Options review")}</h2><span>{t("Simulation and manual outcomes are separate and do not borrow stock backtests or legacy Paper results.")}</span></div><FlaskConical size={18} /></div><div className="review-status"><Status value={payloads.research?.performance_status ?? "PERFORMANCE_UNPROVEN"} /><span>{t("Completed outcomes")} {outcomeCount}</span><span>{t("Minimum independent sample gate")} 200 / {t("Horizon / direction")}</span></div>{metrics.length ? <div className="metrics-table"><div className="metrics-head"><span>{t("Horizon / direction")}</span><span>{t("Samples")}</span><span>{t("Win rate")}</span><span>Payoff</span><span>PF</span><span>{t("Evidence status")}</span></div>{metrics.map(([key, value]: [string, any]) => <div className="metrics-row" key={key}><strong>{key.replace("|", " · ")}</strong><span>{value.completed ?? 0}</span><span>{value.win_rate_pct == null ? "-" : `${formatNumber(value.win_rate_pct, 1)}%`}</span><span>{formatNumber(value.payoff)}</span><span>{formatNumber(value.profit_factor)}</span><Status value={value.evidence_status} /></div>)}</div> : <Empty title={t("Performance evidence is not established")} detail={t("Strict-quote outcomes are unavailable, so an option strategy win rate cannot be reported.")} />}</section><section className="option-section"><div className="section-title"><div><h3>{t("Outcome records")}</h3><span>{t("Records with unknown fees are not presented as net performance.")}</span></div></div>{[...manualRows, ...simulations].length ? <div className="tracking-list">{[...manualRows, ...simulations].map((item, index) => <div className="tracking-row" key={`${item.outcome_id ?? item.manual_outcome_id}-${index}`}><div><strong>{item.symbol ?? item.plan_id}</strong><span>{item.contract_symbol ?? (item.source === "user_reported" ? t("Manual record") : t("System simulation"))}</span></div><span>{item.source === "user_reported" ? t("Manual") : t("Simulation")}</span><Status value={item.status} /><time>{formatTime(item.updated_at)}</time><span className="mono">{item.net_pnl == null ? t("Net performance pending fees") : `$${formatNumber(item.net_pnl)}`}</span></div>)}</div> : null}</section></div>;
  }

  const provider = payloads.audit?.provider ?? status;
  const providerAvailable = String(provider?.provider ?? status.provider).toLowerCase() === "longbridge" && String(provider?.status ?? status.status).toLowerCase() === "available";
  const quotePackages = Array.isArray(provider?.quote_packages) ? provider.quote_packages.join(" ") : "";
  const underlyingRealtime = providerAvailable && quotePackages.includes("US_QBBO_OpenAPI");
  const opraAvailable = String(provider?.opra_status ?? status.opra_status).toLowerCase() === "available";
  const strictBboReady = Boolean(payloads.audit?.strict_simulated_fill_ready);
  const notificationStatus = stateLabel(payloads.notifications?.enabled ? "AVAILABLE" : "DISABLED");
  return <div className="option-page"><OptionRuntimeStatus status={status} notifications={payloads.notifications ?? {}} reload={() => setLocalNonce(value => value + 1)} /><section className="option-section"><div className="section-title"><div><span className="eyebrow">{t("Display preferences")}</span><h2>{t("Appearance")}</h2><span>{t("Preferences stay in this browser and do not affect option data, screening, or risk controls.")}</span></div></div><div className="settings-lines preference-lines"><div><div><span>{t("Language")}</span><small>{t("Navigation and unified workspace")}</small></div><div className="preference-control" role="group" aria-label={t("Language")}><button type="button" className={language === "zh" ? "active" : ""} onClick={() => onLanguageChange("zh")}><Languages size={14} />中文</button><button type="button" className={language === "en" ? "active" : ""} onClick={() => onLanguageChange("en")}>English</button></div></div><div><div><span>{t("Appearance")}</span><small>{t("Dark and light themes")}</small></div><div className="preference-control" role="group" aria-label={t("Appearance")}><button type="button" className={theme === "dark" ? "active" : ""} onClick={() => onThemeChange("dark")}><Moon size={14} />{t("Dark")}</button><button type="button" className={theme === "light" ? "active" : ""} onClick={() => onThemeChange("light")}><Sun size={14} />{t("Light")}</button></div></div></div><div className="section-title"><div><span className="eyebrow">{t("Option runtime")}</span><h2>{t("Option data and notifications")}</h2><span>{t("Technical diagnostics stay here instead of occupying the opportunity list.")}</span></div></div><div className="settings-lines option-source-layers"><div><span>{t("Data platform")}</span><strong>Longbridge</strong></div><div><span>{t("Underlying real-time quotes")}</span><strong>{underlyingRealtime ? t("Available") : t("Not available")}</strong></div><div><span>{t("Option chain")}</span><strong>{providerAvailable ? t("Reference data available") : t("Not available")}</strong></div><div><span>{t("OPRA real-time options")}</span><strong>{opraAvailable ? t("Available") : t("Permission not detected")}</strong></div><div><span>{t("Strict BBO")}</span><strong>{strictBboReady ? t("Verifiable") : t("Not verifiable")}</strong></div><div><span>{t("Simulated fills")}</span><strong>{strictBboReady ? t("Available") : t("Blocked by quote evidence")}</strong></div><div><span>{t("Web alerts")}</span><strong>{notificationStatus}</strong></div><div><span>{t("Operating boundary")}</span><strong>{t("Manual review; no order submission")}</strong></div></div><div className="option-warning source-disclosure"><ShieldAlert size={17} /><div><strong>{t("Option chain reference only")}</strong><span>{t("Longbridge provides the option chain. OPRA permission and timestamped BBO evidence are not available, so bid, ask, cost, and Greeks stay hidden.")}</span></div></div><details className="option-audit-details" open><summary>{t("Data blockers")}</summary>{Array.isArray(payloads.audit?.blockers) && payloads.audit.blockers.length ? <ul>{payloads.audit.blockers.map((item: string) => <li key={item}>{explain(item)}</li>)}</ul> : <p>{t("No registered blockers")}</p>}</details><details className="option-audit-details"><summary>{t("Versions and counts")}</summary><pre>{JSON.stringify({ provider, policy: status.policy_version, counts: payloads.audit?.counts, supervisor: status.supervisor }, null, 2)}</pre></details></section></div>;
}
