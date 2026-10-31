import { AlertTriangle, Clock3, RefreshCw, ShieldCheck, TrendingDown, TrendingUp } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

type RadarPlan = {
  plan_id: string;
  horizon_group: string;
  contract_symbol: string;
  expiry_date: string;
  dte: number;
  strike_price: number;
  direction: "CALL" | "PUT" | string;
  state: string;
  earliest_confirm_at?: string | null;
  entry_cutoff_at?: string | null;
  exit_reminder_at?: string | null;
  expires_at: string;
  blockers: string[];
  reference_quote?: {
    ask?: number | null;
    bid?: number | null;
    delta?: number | null;
    theta?: number | null;
    implied_volatility?: number | null;
    spread_pct?: number | null;
    contract_multiplier?: number | null;
  };
};

type RadarOpportunity = {
  opportunity_id: string;
  symbol: string;
  hypothesis: string;
  direction: "CALL" | "PUT" | string;
  horizon_class: string;
  rank_value: number;
  evidence_score: number;
  status: string;
  signal_time: string;
  evidence_grade: string;
  blockers: string[];
  warnings: string[];
  evidence: {
    residual_z?: number;
    sector_benchmark?: string;
    supporting_factors?: Array<{ factor_id: string; value?: number; direction?: string }>;
    opposing_factors?: Array<{ factor_id: string; status?: string }>;
  };
  plans: RadarPlan[];
};

type PremarketReport = {
  status: string;
  market_date?: string;
  generated_at?: string;
  data_status?: string;
  summary?: {
    opportunity_count?: number;
    eligible_for_intraday_confirmation?: number;
    opra_status?: string;
  };
  opportunities: RadarOpportunity[];
};

type DataAudit = {
  provider?: { opra_status?: string; message?: string };
  counts?: Record<string, number>;
  strict_simulated_fill_ready?: boolean;
  blockers?: string[];
  no_purchase_performed?: boolean;
};

type ResearchReport = {
  performance_status?: string;
  state_counts?: Record<string, number>;
  metrics_by_horizon_and_direction?: Record<string, { completed?: number; win_rate_pct?: number | null; payoff?: number | null; profit_factor?: number | null; evidence_status?: string }>;
};

type Props = {
  lang: "en" | "zh";
  fetcher: (path: string, init?: RequestInit) => Promise<Response>;
  onPickSymbol: (symbol: string) => void;
};

const groupLabel: Record<string, { zh: string; en: string }> = {
  INTRADAY_0DTE: { zh: "0DTE 日内", en: "0DTE intraday" },
  INTRADAY_7_14DTE: { zh: "7–14DTE 日内", en: "7–14DTE intraday" },
  SWING_14_35DTE: { zh: "14–35DTE 短波段", en: "14–35DTE short swing" },
};

const stateLabel: Record<string, { zh: string; en: string }> = {
  PREMARKET_WATCH: { zh: "盘前观察", en: "Premarket watch" },
  WAIT_OPEN_CONFIRMATION: { zh: "等待 09:40 确认", en: "Waiting for 09:40 confirmation" },
  QUOTE_BLOCKED: { zh: "报价未通过", en: "Quote blocked" },
  CONFIRMED: { zh: "待人工复核", en: "Manual review" },
  CANCELLED: { zh: "已取消", en: "Cancelled" },
  INVALIDATED: { zh: "已失效", en: "Invalidated" },
  EXIT_REVIEW: { zh: "退出待复核", en: "Exit review" },
  REFERENCE_ONLY: { zh: "仅参考", en: "Reference only" },
  WAITING_CONFIRMATION: { zh: "等待确认", en: "Waiting" },
};

function label(value: string, lang: "en" | "zh"): string {
  return stateLabel[value]?.[lang] ?? value.replace(/_/g, " ");
}

function formatTime(value: string | null | undefined, lang: "en" | "zh"): string {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return new Intl.DateTimeFormat(lang === "zh" ? "zh-CN" : "en-US", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZone: "America/New_York",
  }).format(date) + " ET";
}

function metric(value: number | null | undefined, digits = 2): string {
  return value == null || !Number.isFinite(value) ? "—" : value.toFixed(digits);
}

export function OptionRadarPanel({ lang, fetcher, onPickSymbol }: Props) {
  const [report, setReport] = useState<PremarketReport | null>(null);
  const [audit, setAudit] = useState<DataAudit | null>(null);
  const [research, setResearch] = useState<ResearchReport | null>(null);
  const [state, setState] = useState<"loading" | "ready" | "error">("loading");

  const load = useCallback(async () => {
    setState("loading");
    try {
      const responses = await Promise.all([
        fetcher("/api/options/radar/premarket"),
        fetcher("/api/options/data-audit"),
        fetcher("/api/options/research-report"),
      ]);
      if (responses.some((response) => !response.ok)) throw new Error("options radar unavailable");
      const [nextReport, nextAudit, nextResearch] = await Promise.all(responses.map((response) => response.json()));
      setReport(nextReport as PremarketReport);
      setAudit(nextAudit as DataAudit);
      setResearch(nextResearch as ResearchReport);
      setState("ready");
    } catch {
      setState("error");
    }
  }, [fetcher]);

  useEffect(() => {
    void load();
  }, [load]);

  const opportunities = report?.opportunities ?? [];
  const completed = Object.values(research?.metrics_by_horizon_and_direction ?? {}).reduce((sum, item) => sum + Number(item.completed ?? 0), 0);
  const opraReady = audit?.provider?.opra_status === "available";

  return (
    <section className="option-radar-workspace" aria-label={lang === "zh" ? "期权机会" : "Options opportunities"}>
      <div className="option-radar-heading">
        <div>
          <span className="eyebrow">{lang === "zh" ? "美股期权研究" : "US options research"}</span>
          <h2>{lang === "zh" ? "期权机会" : "Options opportunities"}</h2>
          <p>{lang === "zh" ? "08:30 ET 盘前筛选 · 09:40 ET 后闭合 5 分钟确认" : "08:30 ET premarket screen · closed 5-minute confirmation after 09:40 ET"}</p>
        </div>
        <button type="button" className="icon-action" onClick={() => void load()} title={lang === "zh" ? "刷新" : "Refresh"} aria-label={lang === "zh" ? "刷新期权机会" : "Refresh options radar"}>
          <RefreshCw size={17} className={state === "loading" ? "spin" : ""} />
        </button>
      </div>

      <div className="option-radar-status-strip">
        <div><span>{lang === "zh" ? "盘前报告" : "Premarket report"}</span><strong>{report?.status === "not_run" ? (lang === "zh" ? "尚未生成" : "Not generated") : formatTime(report?.generated_at, lang)}</strong></div>
        <div><span>{lang === "zh" ? "候选" : "Candidates"}</span><strong>{opportunities.length} / 5</strong></div>
        <div><span>{lang === "zh" ? "期权实时行情" : "Realtime options"}</span><strong className={opraReady ? "tone-good-text" : "tone-warn-text"}>{opraReady ? (lang === "zh" ? "可用" : "Available") : (lang === "zh" ? "未开通" : "Unavailable")}</strong></div>
        <div><span>{lang === "zh" ? "完整结果" : "Completed outcomes"}</span><strong>{completed}</strong></div>
      </div>

      {!opraReady ? (
        <div className="option-radar-blocker" role="status">
          <AlertTriangle size={17} />
          <div>
            <strong>{lang === "zh" ? "当前仅显示观察级候选" : "Observation candidates only"}</strong>
            <span>{lang === "zh" ? "未检测到 OPRA 实时期权权限，系统不会确认模拟成交。" : "OPRA realtime permission was not detected, so simulated fills cannot be confirmed."}</span>
          </div>
        </div>
      ) : null}

      {state === "error" ? <div className="option-radar-empty">{lang === "zh" ? "期权研究服务暂时不可用。" : "Options research is temporarily unavailable."}</div> : null}
      {state === "ready" && !opportunities.length ? (
        <div className="option-radar-empty">
          <ShieldCheck size={20} />
          <strong>{lang === "zh" ? "当前没有达到预登记阈值的机会" : "No opportunity meets the registered threshold"}</strong>
          <span>{lang === "zh" ? "系统不会为了凑数生成推荐。" : "The radar does not force a daily recommendation."}</span>
        </div>
      ) : null}

      <div className="option-opportunity-list">
        {opportunities.map((opportunity) => (
          <article className="option-opportunity-row" key={opportunity.opportunity_id}>
            <div className="option-opportunity-summary">
              <button type="button" className="option-symbol" onClick={() => onPickSymbol(opportunity.symbol)}>{opportunity.symbol}</button>
              <span className={`option-direction ${opportunity.direction === "CALL" ? "call" : "put"}`}>
                {opportunity.direction === "CALL" ? <TrendingUp size={15} /> : <TrendingDown size={15} />}
                {opportunity.direction}
              </span>
              <span>{opportunity.horizon_class === "INTRADAY" ? (lang === "zh" ? "日内独立异动" : "Intraday residual") : (lang === "zh" ? "短波段残差延续" : "Short-swing residual")}</span>
              <strong>{metric(opportunity.evidence?.residual_z)}σ</strong>
              <span className={`option-state state-${opportunity.status.toLowerCase()}`}>{label(opportunity.status, lang)}</span>
            </div>

            <div className="option-contract-table" role="table" aria-label={`${opportunity.symbol} contracts`}>
              {opportunity.plans.map((plan) => {
                const quote = plan.reference_quote ?? {};
                const multiplier = quote.contract_multiplier ?? 100;
                const maxLoss = quote.ask == null ? null : quote.ask * multiplier;
                return (
                  <div className="option-contract-row" role="row" key={plan.plan_id}>
                    <div><span>{lang === "zh" ? "期限" : "Horizon"}</span><strong>{groupLabel[plan.horizon_group]?.[lang] ?? plan.horizon_group}</strong></div>
                    <div><span>{lang === "zh" ? "合约" : "Contract"}</span><strong>{plan.contract_symbol}</strong></div>
                    <div><span>{lang === "zh" ? "到期 / 行权价" : "Expiry / strike"}</span><strong>{plan.expiry_date} / {plan.strike_price}</strong></div>
                    <div><span>{lang === "zh" ? "一张成本 / 全损" : "One-contract cost / max loss"}</span><strong>{maxLoss == null ? "—" : `$${metric(maxLoss)}`}</strong></div>
                    <div><span>{lang === "zh" ? "报价" : "Quote"}</span><strong>{quote.bid == null || quote.ask == null ? "—" : `${quote.bid} / ${quote.ask}`}</strong></div>
                    <div><span>{lang === "zh" ? "状态" : "State"}</span><strong>{label(plan.state, lang)}</strong></div>
                  </div>
                );
              })}
            </div>

            <div className="option-evidence-line">
              <Clock3 size={14} />
              <span>{lang === "zh" ? "数据" : "Data"}: {formatTime(opportunity.signal_time, lang)}</span>
              <span>{lang === "zh" ? "行业基准" : "Sector benchmark"}: {opportunity.evidence?.sector_benchmark ?? "—"}</span>
              <span>{lang === "zh" ? "证据" : "Evidence"}: {opportunity.evidence_grade}</span>
            </div>
            {opportunity.blockers.length ? (
              <details className="option-blocker-details">
                <summary>{lang === "zh" ? `${opportunity.blockers.length} 项等待条件` : `${opportunity.blockers.length} blockers`}</summary>
                <ul>{opportunity.blockers.map((item) => <li key={item}>{item}</li>)}</ul>
              </details>
            ) : null}
          </article>
        ))}
      </div>

      <footer className="option-radar-footer">
        <span>{lang === "zh" ? "人工执行 · 一张合约研究 · 不建议张数" : "Manual execution · one-contract research · no sizing advice"}</span>
        <span>{research?.performance_status ?? "PERFORMANCE_UNPROVEN"}</span>
      </footer>
    </section>
  );
}
