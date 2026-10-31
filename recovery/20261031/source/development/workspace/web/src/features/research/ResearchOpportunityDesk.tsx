import { Activity, RefreshCw } from "lucide-react";

type Lang = "en" | "zh";
type ResearchText = Record<string, string>;
type OpportunityItem = {
  symbol: string;
  action: string;
  confidence: string;
  best_profile: string;
  entry_zone: string;
  risk_reward: string;
  why_now: string[];
  hard_veto_applied?: boolean;
  ai_action_validation?: { expected_value_r?: number; win_rate?: number };
  money_pilot_eligibility?: { eligible_for_review?: boolean };
  probe_eligibility?: { eligible_for_probe_review?: boolean };
  probe_risk_policy?: { default_risk_pct_of_account?: number; max_risk_pct_of_account?: number };
};
type DailyReport = {
  status?: string;
  reason?: string;
  is_stale?: boolean;
  age_seconds?: number | null;
  ai_context_candidate_count?: number;
  last_error?: string | null;
  broker_order_wiring_enabled?: boolean;
  ai_report?: {
    top_buy_candidates?: OpportunityItem[];
    probe_candidates?: OpportunityItem[];
    watch_for_pullback?: OpportunityItem[];
    data_quality_warnings?: string[];
    daily_summary?: string;
  };
};

function number(value: number | undefined): string {
  return value == null || !Number.isFinite(value) ? "-" : value.toFixed(2);
}

function actionClass(action: string): string {
  const value = action.toUpperCase();
  if (value.includes("BUY")) return "buy";
  if (value.includes("WATCH") || value.includes("WAIT")) return "watch";
  return "pass";
}

function displayAction(action: string, lang: Lang): string {
  if (lang === "en") return action;
  const labels: Record<string, string> = { AI_BUY_CANDIDATE: "买入候选", AI_PULLBACK_BUY: "回踩候选", AI_PROBE_BUY: "小仓观察", AI_BREAKOUT_WATCH: "突破观察", AI_REVERSAL_WATCH: "反转观察", AI_WAIT: "等待", AI_AVOID: "暂不参与" };
  return labels[action] || action;
}

function Fact({ label, value }: { label: string; value: string }) {
  return <div className="fact"><span>{label}</span><strong>{value}</strong></div>;
}

function OpportunityColumn({ lang, title, empty, items, onPick, passive = false }: { lang: Lang; title: string; empty: string; items: OpportunityItem[]; onPick: (symbol: string) => void; passive?: boolean }) {
  return <div className="ai-opportunity-column"><strong>{title}</strong>{items.length ? items.map((item) => (
    <button type="button" className={`ai-opportunity-card ${actionClass(item.action)}`} key={`${title}-${item.symbol}-${item.best_profile}`} onClick={() => (!passive && item.symbol ? onPick(item.symbol) : undefined)} disabled={passive}>
      <div><b>{item.symbol}</b><span>{displayAction(item.action, lang)} / {item.confidence}</span></div>
      <small>{item.best_profile || (lang === "zh" ? "交易计划" : "Trade plan")} / R:R {item.risk_reward || "-"}</small>
      <div className="opportunity-quality"><span>EV {number(item.ai_action_validation?.expected_value_r)}R</span><span>Win {number(item.ai_action_validation?.win_rate)}%</span><span>{item.money_pilot_eligibility?.eligible_for_review ? (lang === "zh" ? "可人工复核" : "Manual review") : item.probe_eligibility?.eligible_for_probe_review ? (lang === "zh" ? "小仓观察" : "Small-size review") : (lang === "zh" ? "暂不满足条件" : "Not ready")}</span></div>
      {item.action === "AI_PROBE_BUY" ? <small>{lang === "zh" ? "小仓风险" : "Small-size risk"} {number(item.probe_risk_policy?.default_risk_pct_of_account ?? 0.15)}% / max {number(item.probe_risk_policy?.max_risk_pct_of_account ?? 0.2)}%</small> : null}
      <p>{item.entry_zone || item.why_now?.[0] || "Open for details."}</p>
      {item.hard_veto_applied ? <em>{lang === "zh" ? "当前风险条件未通过" : "Current risk conditions are not cleared"}</em> : null}
    </button>
  )) : <p className="probability-note">{empty}</p>}</div>;
}

export function ResearchOpportunityDesk({ report, state, autoRunState, aiStatus, selectedUniverseLabel, lang, text, onRun, onPick }: { report: DailyReport | null; state: "idle" | "loading" | "ready" | "error"; autoRunState: string; aiStatus: { status: string } | null; selectedUniverseLabel: string; lang: Lang; text: ResearchText; onRun: () => void; onPick: (symbol: string) => void }) {
  const aiConnected = aiStatus?.status === "available";
  const aiReport = report?.ai_report;
  const top = aiReport?.top_buy_candidates ?? [];
  const probe = aiReport?.probe_candidates ?? [];
  const watch = aiReport?.watch_for_pullback ?? [];
  const warnings = aiReport?.data_quality_warnings ?? [];
  const label = (zh: string, en: string) => lang === "zh" ? zh : en;
  return <section className="panel ai-trade-desk">
    <div className="ai-trade-desk-head"><div><span>{label("今日复核", "Today")}</span><h2>{label("研究机会", "Research opportunities")}</h2><p>{label(`为 ${selectedUniverseLabel} 整理入场、止损、目标与风险收益，并由数据与风控条件决定是否可复核。`, `Prepare entry, stop, target, and risk/reward for ${selectedUniverseLabel}, subject to data and risk controls.`)}</p></div><div className="ai-trade-desk-actions"><span className={`pill ${aiConnected ? "good" : "warn"}`}><Activity size={14} />{aiConnected ? label("研究服务已连接", "Research ready") : label("研究服务不可用", "Research unavailable")}</span><button className="primary-action" type="button" onClick={onRun} disabled={state === "loading"}><RefreshCw size={15} />{state === "loading" ? label("更新中", "Updating") : label("刷新机会", "Refresh opportunities")}</button></div></div>
    <div className="ai-trade-summary"><Fact label={text.status} value={report?.status ?? "not_scanned"} /><Fact label={text.autoAgent} value={autoRunState} /><Fact label={text.freshness} value={report?.is_stale ? `stale ${report.age_seconds ?? "-"}s` : "fresh"} /><Fact label={label("研究服务", "Research service")} value={aiConnected ? label("已连接", "Connected") : label("不可用", "Unavailable")} /><Fact label={text.candidates} value={String(report?.ai_context_candidate_count ?? 0)} /><Fact label={text.readOnlyShort} value={report?.broker_order_wiring_enabled === false ? text.noBrokerNoOrder : text.guarded} /></div>
    <div className="ai-opportunity-grid"><OpportunityColumn lang={lang} title={label("优先复核", "Priority review")} empty={label("暂无满足条件的买入候选。", "No clean buy candidate yet.")} items={top} onPick={onPick} /><OpportunityColumn lang={lang} title={label("小仓观察", "Small-size observation")} empty={label("暂无小仓试错候选。", "No small-size probe candidate yet.")} items={probe.slice(0, 6)} onPick={onPick} /><OpportunityColumn lang={lang} title={text.watchForPullback} empty={label("暂无观察项目。", "No watchlist items yet.")} items={watch.slice(0, 5)} onPick={onPick} /><OpportunityColumn lang={lang} title={text.dataRiskWarnings} empty={text.noWarnings} items={warnings.slice(0, 5).map((warning, index) => ({ symbol: `WARN${index + 1}`, action: "AI_AVOID", confidence: "LOW", best_profile: "data_quality", entry_zone: warning, risk_reward: "", why_now: [warning] }))} onPick={() => undefined} passive /></div>
    <p className="secondary-note">{aiReport?.daily_summary ?? report?.last_error ?? report?.reason ?? text.aiDailyFallback}</p>
  </section>;
}
