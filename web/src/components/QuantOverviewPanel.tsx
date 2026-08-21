import { Activity, ArrowUpRight, Database, ShieldCheck } from "lucide-react";

export type QuantOverviewPayload = {
  status: string;
  contract_version: string;
  as_of: string;
  read_only_research: boolean;
  automatic_execution_allowed: boolean;
  order_submission_enabled: boolean;
  evidence_chain: Array<{
    status: string;
    run_id: string | null;
    as_of: string | null;
    source: string | null;
  }>;
  versions: Record<string, string | null | undefined>;
  data_trust: {
    primary_provider: string;
    universe_symbols: number;
    canonical_validation_eligible_symbols: number;
    legacy_reference_observations: number;
    intervals: Record<string, { coverage_pct?: number; longbridge_eligible_symbols?: number; target_met?: boolean }>;
    event_calendar?: { status?: string; trade_eligible?: boolean };
    market_breadth?: { status?: string; participation_score?: number };
    coverage_gate: string;
    source_policy: string;
  };
  capital_rotation: {
    status: string;
    as_of: string | null;
    ranked_theme_count: number;
    stress_unreasonable_flips: number;
    top_themes: Array<{ definition_id: string; score?: number | null; data_quality?: string; eligible_member_count: number }>;
  };
  leadership: {
    status: string;
    as_of: string | null;
    unique_symbol_count: number;
    state_counts: Record<string, number>;
    future_prediction_used: boolean;
    top_leaders: Array<{ symbol: string; definition_id: string; state: string; score?: number | null; data_quality?: string }>;
  };
  stock_quant: {
    status: string;
    model_version?: string | null;
    dataset_id?: string | null;
    validation_gate: string;
    research_candidate?: string | null;
    deployment_model?: string | null;
    deployment_status?: string;
    deployment_blockers?: string[];
    test_trade_count: number;
    readiness: string;
  };
  theme_prediction: { status: string; gate_status?: string | null; display_probability: boolean; oos_fold_count: number };
  shadow_observation: {
    status: string;
    observed_trading_days: number;
    target_trading_days: number;
    instruction_events: number;
    completed_forward_outcomes: number;
    go_no_go: string;
    start_allowed?: boolean;
    strategy_freeze_status?: string;
    next_action?: string;
    data_incident_count?: number;
  };
};

type Lang = "en" | "zh";

function number(value: number | null | undefined): string {
  return value == null || !Number.isFinite(value) ? "-" : value.toLocaleString("en-US", { maximumFractionDigits: 2 });
}

function date(value: string | null | undefined): string {
  if (!value) return "-";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString(undefined, { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" });
}

function statusLabel(value: string | undefined, lang: Lang): string {
  if (lang === "en") return value ?? "Not available";
  const labels: Record<string, string> = {
    materialized: "已生成",
    not_available: "暂无快照",
    available: "可用",
    PASS: "通过",
    REVIEW: "待复核",
    pass: "通过",
    no_go: "暂不通过",
    collecting: "收集中",
    not_started: "未开始",
  };
  return labels[value ?? ""] ?? value ?? "暂无数据";
}

function deploymentBlockerLabel(value: string, lang: Lang): string {
  const labels: Record<string, [string, string]> = {
    minimum_test_trades: ["Need at least 100 independent test trades", "独立测试交易不足 100 笔"],
    walk_forward_stability: ["Rolling OOS evidence is not stable", "多折 OOS 证据尚不稳定"],
    average_r_bootstrap_lower_gt_zero: ["Mean R lower confidence bound is not positive", "平均 R 的置信下限未转正"],
    profit_factor_at_least_1_25: ["Profit Factor is below 1.25", "Profit Factor 未达到 1.25"],
    max_drawdown_at_most_8_r: ["Maximum drawdown exceeds 8R", "最大回撤超过 8R"],
    no_validation_candidate: ["No validation candidate is available", "暂无可验证的研究候选"],
  };
  const label = labels[value] ?? additionalDeploymentBlockerLabels[value];
  return label ? label[lang === "zh" ? 1 : 0] : value;
}

const additionalDeploymentBlockerLabels: Record<string, [string, string]> = {
  conservative_profit_factor_at_least_1_05: ["Conservative-cost Profit Factor is below 1.05", "保守成本 Profit Factor 未达到 1.05"],
  leave_best_five_symbols_positive: ["Expectancy is not positive after removing the best five symbols", "剔除表现最好的五只股票后期望值未转正"],
  single_symbol_profit_contribution_at_most_15pct: ["One symbol contributes more than 15% of profit", "单一股票利润贡献超过 15%"],
};

export function QuantOverviewPanel({ overview, lang, onPick }: { overview: QuantOverviewPayload | null; lang: Lang; onPick: (symbol: string) => void }) {
  const zh = lang === "zh";
  if (!overview) {
    return (
      <section className="panel v2-overview-panel v2-overview-loading">
        <div className="v2-overview-head"><span className="eyebrow">KQUANT v2</span><strong>{zh ? "正在加载研究证据" : "Loading research evidence"}</strong></div>
      </section>
    );
  }
  const daily = overview.data_trust.intervals["1d"];
  const hourly = overview.data_trust.intervals["1h"];
  const chainLabels = zh ? ["主题轮动", "主题分类", "领导力", "股票量化"] : ["Capital Rotation", "Theme Taxonomy", "Leadership", "Stock Quant"];
  return (
    <section className="panel v2-overview-panel" aria-label={zh ? "研究证据总览" : "Research evidence overview"}>
      <div className="v2-overview-head">
        <div>
          <span className="eyebrow">KQUANT v2 / {zh ? "只读证据链" : "Read-only evidence chain"}</span>
          <h2>{zh ? "从主题到个股的研究总览" : "Theme-to-stock research overview"}</h2>
          <p>{zh ? "所有层级都来自已保存的时间截面；它们是研究证据，不是自动交易许可。" : "Every layer is a saved point-in-time artifact. It is research evidence, not an execution permission."}</p>
        </div>
        <div className="v2-overview-safety"><ShieldCheck size={16} /><strong>{zh ? "只读 / NO_GO" : "Read-only / NO_GO"}</strong><span>{date(overview.as_of)}</span></div>
      </div>

      <div className="v2-chain-grid">
        {overview.evidence_chain.map((stage, index) => (
          <div className={`v2-chain-step ${stage.status === "materialized" ? "ready" : "pending"}`} key={`${stage.run_id ?? index}`}>
            <span>{String(index + 1).padStart(2, "0")}</span>
            <div><strong>{chainLabels[index]}</strong><small>{statusLabel(stage.status, lang)} · {date(stage.as_of)}</small></div>
          </div>
        ))}
      </div>

      <div className="v2-overview-grid">
        <div className="v2-overview-card trust-card">
          <div className="v2-card-title"><Database size={15} /><strong>{zh ? "数据可信度" : "Data trust"}</strong><b className={overview.data_trust.coverage_gate === "PASS" ? "good" : "warn"}>{statusLabel(overview.data_trust.coverage_gate, lang)}</b></div>
          <div className="v2-fact-row"><span>{zh ? "主数据源" : "Primary source"}</span><strong>{overview.data_trust.primary_provider} / {overview.data_trust.canonical_validation_eligible_symbols}/{overview.data_trust.universe_symbols}</strong></div>
          <div className="v2-fact-row"><span>{zh ? "日线 / 1H 覆盖" : "Daily / 1H coverage"}</span><strong>{number(daily?.coverage_pct)}% / {number(hourly?.coverage_pct)}%</strong></div>
          <div className="v2-fact-row"><span>{zh ? "市场宽度" : "Market breadth"}</span><strong>{number(overview.data_trust.market_breadth?.participation_score)}</strong></div>
          <small className="v2-muted">{overview.data_trust.source_policy}</small>
        </div>

        <div className="v2-overview-card rotation-card">
          <div className="v2-card-title"><Activity size={15} /><strong>{zh ? "主题轮动" : "Capital rotation"}</strong><b>{number(overview.capital_rotation.ranked_theme_count)}</b></div>
          <div className="v2-tag-row">{overview.capital_rotation.top_themes.slice(0, 5).map((theme) => <span className="v2-theme-tag" key={theme.definition_id}>{theme.definition_id} <b>{number(theme.score)}</b></span>)}</div>
          <small className="v2-muted">{zh ? `压力测试异常翻转 ${overview.capital_rotation.stress_unreasonable_flips} 次` : `${overview.capital_rotation.stress_unreasonable_flips} unreasonable stress flips`} · {date(overview.capital_rotation.as_of)}</small>
        </div>

        <div className="v2-overview-card leadership-card">
          <div className="v2-card-title"><ArrowUpRight size={15} /><strong>{zh ? "领导力" : "Leadership"}</strong><b>{number(overview.leadership.unique_symbol_count)}</b></div>
          <div className="v2-state-row">{Object.entries(overview.leadership.state_counts).map(([state, count]) => <span key={state}><b>{count}</b>{state}</span>)}</div>
          <div className="v2-leader-list">{overview.leadership.top_leaders.slice(0, 6).map((leader) => <button type="button" key={`${leader.symbol}-${leader.definition_id}`} onClick={() => onPick(leader.symbol)}><strong>{leader.symbol}</strong><span>{leader.state}</span><b>{number(leader.score)}</b></button>)}</div>
          {overview.leadership.future_prediction_used ? <small className="v2-warning">{zh ? "检测到未来预测依赖，当前链路不应进入模型。" : "Future prediction dependency detected; keep this chain blocked."}</small> : null}
        </div>

        <div className="v2-overview-card validation-card">
          <div className="v2-card-title"><ShieldCheck size={15} /><strong>{zh ? "股票量化验证" : "Stock Quant validation"}</strong><b className="warn">{statusLabel(overview.stock_quant.validation_gate, lang)}</b></div>
          <div className="v2-validation-score"><strong>{overview.stock_quant.deployment_model ?? (zh ? "暂无可用模型" : "No deployable model")}</strong><span>{number(overview.stock_quant.test_trade_count)} {zh ? "测试交易" : "test trades"}</span></div>
          <div className="v2-fact-row"><span>{zh ? "研究候选" : "Research candidate"}</span><strong>{overview.stock_quant.research_candidate ?? "-"}</strong></div>
          <div className="v2-fact-row"><span>{zh ? "模型版本" : "Model"}</span><strong>{overview.stock_quant.model_version ?? "-"}</strong></div>
          {overview.stock_quant.deployment_blockers?.length ? <small className="v2-warning">{zh ? `尚未通过：${overview.stock_quant.deployment_blockers.map((item) => deploymentBlockerLabel(item, lang)).join("、")}` : `Blocked by: ${overview.stock_quant.deployment_blockers.map((item) => deploymentBlockerLabel(item, lang)).join(", ")}`}</small> : null}
          <div className="v2-fact-row"><span>{zh ? "主题预测概率" : "Theme probability"}</span><strong>{overview.theme_prediction.display_probability ? (zh ? "已开放" : "enabled") : (zh ? "校准不足" : "blocked")}</strong></div>
          <small className="v2-muted">{zh ? "测试集不可用于调参；未通过 Gate 前只保留研究与 Shadow。" : "The test partition is never used for tuning; keep research and shadow only until the Gate passes."}</small>
        </div>
      </div>

      <div className="v2-shadow-strip">
        <div><strong>{zh ? "Shadow Observation" : "Shadow Observation"}</strong><span>{statusLabel(overview.shadow_observation.status, lang)} · {overview.shadow_observation.observed_trading_days}/{overview.shadow_observation.target_trading_days} {zh ? "交易日" : "trading days"}</span></div>
        <div><span>{zh ? "指令事件" : "Instruction events"}</span><b>{number(overview.shadow_observation.instruction_events)}</b></div>
        <div><span>{zh ? "已完成前瞻结果" : "Completed outcomes"}</span><b>{number(overview.shadow_observation.completed_forward_outcomes)}</b></div>
        <div className="v2-shadow-next"><span>{zh ? "人工启动" : "Manual start"}</span><b className={overview.shadow_observation.start_allowed ? "good" : "warn"}>{overview.shadow_observation.start_allowed ? (zh ? "已满足冻结条件" : "Freeze ready") : (zh ? "尚未满足" : "Not ready")}</b><small>{overview.shadow_observation.next_action || (zh ? "等待观察条件" : "Waiting for observation prerequisites")}</small></div>
        <strong className="warn">{overview.shadow_observation.go_no_go}</strong>
      </div>
    </section>
  );
}
