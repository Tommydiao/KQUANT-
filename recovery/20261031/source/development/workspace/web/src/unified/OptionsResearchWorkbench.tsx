/* Hallmark · pre-emit critique: P6 H5 E4 S5 R5 V4 */
import { Activity, Beaker, CalendarClock, Database, ShieldAlert, Target, WalletCards } from "lucide-react";
import { useMemo } from "react";
import { formatUiNumber, useI18n } from "./i18n";
import type { MessageKey } from "./i18n";

type Json = Record<string, any>;

type Props = {
  payload: Json;
  reviewR1?: Json;
  reviewR2?: Json;
  reviewR3?: Json;
  reviewR4?: Json;
  reviewR5?: Json;
  reviewR6?: Json;
  symbol: string;
};

const PROFILE_LABELS: Record<string, MessageKey> = {
  SHORT_ATM_DAYS_WEEK: "Short-term ATM",
  MEDIUM_ATM_WEEKS_MONTHS: "Medium-term ATM",
  LONG_OTM_MONTHS_YEAR: "Long-term OTM",
};

const HYPOTHESIS_COPY: Record<string, { mechanism: MessageKey; target: MessageKey }> = {
  "H-S-01": {
    mechanism: "Test whether sector-relative underlying strength contains information about the next five sessions.",
    target: "Forward five-session underlying excess return",
  },
  "H-M-01": {
    mechanism: "Observe whether trend persistence can survive several weeks of option carry.",
    target: "Coverage and deterministic carry sensitivity",
  },
  "H-L-01": {
    mechanism: "Measure whether a sourced catalyst could justify long-dated OTM premium under volatility and time decay.",
    target: "Catalyst evidence and deterministic sensitivity",
  },
};

function ResearchBadge({ children, tone = "info" }: { children: React.ReactNode; tone?: "info" | "caution" | "positive" }) {
  return <span className={`research-badge ${tone}`}>{children}</span>;
}

function shortenedHash(value: unknown): string {
  const raw = String(value ?? "");
  return raw ? `${raw.slice(0, 8)}…${raw.slice(-6)}` : "-";
}

function R1ReviewPanel({ payload, symbol }: { payload: Json; symbol: string }) {
  const { language, t } = useI18n();
  if (payload.status !== "AVAILABLE") return null;
  const validation = payload.validation ?? {};
  const experiment = payload.experiment ?? {};
  const manifest = payload.manifest ?? {};
  const symbolAudit = (Array.isArray(validation.symbols) ? validation.symbols : []).find((item: Json) => item.symbol === symbol)
    ?? (Array.isArray(validation.symbols) ? validation.symbols[0] : null);
  const partitions = Object.entries(experiment.partitions ?? {}) as [string, Json][];
  const action = validation.corporate_action_test ?? {};

  return <section className="option-section r1-review" aria-labelledby="r1-review-title">
    <div className="section-title r1-review-head">
      <div>
        <span className="eyebrow">R1 · {t("Adjusted data review")}</span>
        <h2 id="r1-review-title">{t("Data and research review package")}</h2>
        <span>{t("The adjusted-data repair and original E-S-001 result are frozen for owner review.")}</span>
      </div>
      <div className="research-boundaries">
        <ResearchBadge tone="caution">WAIT_REVIEW</ResearchBadge>
        <ResearchBadge tone={validation.gate_status === "PASS" ? "positive" : "caution"}>D_ADJUSTED_DATA · {validation.gate_status ?? "-"}</ResearchBadge>
        <ResearchBadge>{experiment.exposure_status ?? "EXPOSED_RESEARCH"}</ResearchBadge>
      </div>
    </div>

    <div className="r1-summary-grid">
      <div><span>{t("Bundle")}</span><strong className="mono">{payload.bundle_id ?? "-"}</strong></div>
      <div><span>{t("E-S-001 result")}</span><strong>{experiment.conclusion ?? experiment.status ?? "-"}</strong></div>
      <div><span>{t("Unique dates")}</span><strong>{experiment.dataset_manifest?.unique_dates ?? payload.dataset?.unique_dates ?? 0}</strong></div>
      <div><span>{t("Production use")}</span><strong>{t("Disabled")}</strong></div>
    </div>

    <div className="research-split r1-detail-grid">
      <article className="research-panel">
        <header><div><span className="eyebrow">{symbolAudit?.symbol ?? symbol}</span><h3>{t("Raw and adjusted lineage")}</h3></div><ResearchBadge tone={symbolAudit?.lineage_complete ? "positive" : "caution"}>{symbolAudit?.lineage_complete ? t("Complete") : t("Limited")}</ResearchBadge></header>
        {symbolAudit ? <dl>
          <div><dt>{t("Date range")}</dt><dd>{symbolAudit.start ?? "-"} → {symbolAudit.end ?? "-"}</dd></div>
          <div><dt>NO_ADJUST</dt><dd>{formatUiNumber(symbolAudit.raw_dates, language, 0)} {t("dates")}</dd></div>
          <div><dt>FORWARD_ADJUST</dt><dd>{formatUiNumber(symbolAudit.adjusted_dates, language, 0)} {t("dates")}</dd></div>
          <div><dt>{t("Changed closes")}</dt><dd>{formatUiNumber(symbolAudit.close_difference_dates, language, 0)}</dd></div>
          <div><dt>{t("Adjustment anchor")}</dt><dd>{validation.adjustment_as_of_policy ?? "-"}</dd></div>
        </dl> : <p>{t("No lineage record is available for this symbol.")}</p>}
        <footer>{t("Current provider-adjusted history is not historical point-in-time evidence.")}</footer>
      </article>

      <article className="research-panel">
        <header><div><span className="eyebrow">NVDA · 2024-06-10</span><h3>{t("Corporate action verification")}</h3></div><ResearchBadge tone={action.status === "PASS" ? "positive" : "caution"}>{action.status ?? "-"}</ResearchBadge></header>
        <dl>
          <div><dt>{t("Official event")}</dt><dd>{action.official_event ?? "-"}</dd></div>
          <div><dt>{t("Raw price ratio")}</dt><dd>{formatUiNumber(action.raw_close_to_post_split_open_ratio, language, 3)}</dd></div>
          <div><dt>{t("Adjusted price ratio")}</dt><dd>{formatUiNumber(action.adjusted_close_to_post_split_open_ratio, language, 3)}</dd></div>
          <div><dt>{t("Adjusted volume ratio")}</dt><dd>{formatUiNumber(action.pre_split_adjusted_to_raw_volume_ratio, language, 3)}</dd></div>
          <div><dt>{t("Turnover preserved")}</dt><dd>{action.turnover_preserved === true ? t("Yes") : action.turnover_preserved === false ? t("No") : "-"}</dd></div>
        </dl>
        <footer>{t("Longbridge NoAdjust and ForwardAdjust are stored separately; old rows are not relabeled.")}</footer>
      </article>
    </div>

    <article className="research-panel r1-experiment">
      <header><div><span className="eyebrow">E-S-001</span><h3>{t("Original preregistered experiment")}</h3></div><ResearchBadge tone={experiment.fit_performed ? "positive" : "caution"}>{experiment.status ?? "-"}</ResearchBadge></header>
      <div className="r1-experiment-contract">
        <span><small>{t("Factor")}</small><strong>excess_log_return_20_sector</strong></span>
        <span><small>{t("Target")}</small><strong>forward_5_session_excess_log_return</strong></span>
        <span><small>{t("Model")}</small><strong>Ridge α=1 · DEV_ONLY</strong></span>
        <span><small>{t("Split")}</small><strong>60 / 20 / 20</strong></span>
      </div>
      {partitions.length ? <div className="r1-partitions">
        <div className="r1-partition-head"><span>{t("Partition")}</span><span>{t("Rows")}</span><span>{t("Ridge MAE")}</span><span>{t("Baseline MAE")}</span><span>{t("Improvement")}</span></div>
        {partitions.map(([name, item]) => <div key={name}><strong>{name}</strong><span>{item.rows ?? 0}</span><span>{formatUiNumber(item.ridge_mae, language, 6)}</span><span>{formatUiNumber(item.training_mean_baseline_mae, language, 6)}</span><span>{formatUiNumber(item.mae_improvement, language, 6)}</span></div>)}
      </div> : <p>{experiment.reason ?? t("No fitted partition result is available.")}</p>}
      <footer>{t("This is exposed underlying research, not independent OOS evidence, option profit, or a trading signal.")}</footer>
    </article>

    <details className="option-audit-details"><summary>{t("R1 full audit")}</summary><pre>{JSON.stringify({ manifest, validation, experiment, tasks: payload.tasks }, null, 2)}</pre></details>
  </section>;
}

function textForLanguage(item: Json, language: "zh" | "en", base: string): string {
  return String(item[`${base}_${language}`] ?? item[base] ?? "-");
}

function dataAvailabilityText(key: string, value: unknown, language: "zh" | "en"): string {
  if (language === "en") return `${key}=${String(value)}`;
  const labels: Record<string, string> = {
    underlying_bars: "正股K线",
    option_reference_fields: "期权参考字段",
    native_bbo_event_time: "原生BBO事件时间",
    event_coverage: "事件覆盖",
    current_iv: "当前IV",
    comparable_iv_history: "可比IV历史",
    catalyst_dataset: "催化剂数据集",
    long_horizon_outcomes: "长期结果",
  };
  const states: Record<string, string> = {
    AVAILABLE: "可用",
    PARTIAL: "部分可用",
    UNAVAILABLE: "不可用",
    BLOCKED: "阻断",
    BLOCKED_UNTIL_SOURCE_COMPLETE: "等待来源完整",
    IMMATURE: "尚未成熟",
  };
  return `${labels[key] ?? key}=${states[String(value)] ?? String(value)}`;
}

function R2ReviewPanel({ payload }: { payload: Json }) {
  const { language, t } = useI18n();
  if (payload.status !== "AVAILABLE") return null;
  const proposals = Array.isArray(payload.strategies?.proposals) ? payload.strategies.proposals : [];
  const executionPolicies = Array.isArray(payload.paper?.execution_policies) ? payload.paper.execution_policies : [];
  const metric = payload.metric ?? {};
  const thresholds = metric.legacy_thresholds_preserved ?? {};
  const primary = proposals.filter((item: Json) => item.variant === "PRIMARY");
  const alternative = proposals.filter((item: Json) => item.variant === "ALTERNATIVE");

  return <section className="option-section r2-review" aria-labelledby="r2-review-title">
    <div className="section-title r2-review-head">
      <div>
        <span className="eyebrow">R2 · {t("Strategy and Paper policy review")}</span>
        <h2 id="r2-review-title">{t("Choose the research contract, not a trade")}</h2>
        <span>{t("Every proposal is frozen for review. Nothing on this page creates a signal, position, or order.")}</span>
      </div>
      <div className="research-boundaries">
        <ResearchBadge tone="caution">WAIT_REVIEW</ResearchBadge>
        <ResearchBadge tone={payload.validation?.status === "PASS" ? "positive" : "caution"}>{t("Proposal validation")} · {payload.validation?.status ?? "-"}</ResearchBadge>
        <ResearchBadge tone="caution">{t("Activation blocked")}</ResearchBadge>
      </div>
    </div>

    <div className="r2-summary-grid">
      <div><Target size={16} /><span>{t("Primary proposals")}</span><strong>{primary.length}</strong></div>
      <div><Beaker size={16} /><span>{t("Material alternatives")}</span><strong>{alternative.length}</strong></div>
      <div><WalletCards size={16} /><span>{t("Quote policies")}</span><strong>{executionPolicies.length}</strong></div>
      <div><ShieldAlert size={16} /><span>{t("Activation")}</span><strong>{t("Blocked pending owner selection")}</strong></div>
    </div>

    <div className="r2-recommendation">
      <div>
        <span className="eyebrow">{t("Recommended first engineering scope")}</span>
        <strong>STRAT-SHORT-ATM-RANGE-EXPANSION-V1</strong>
        <p>{t("Use the receipt-time quote proxy for offline engineering only, with Call and Put measured separately. This is not a profitability claim.")}</p>
      </div>
      <ResearchBadge tone="caution">PROPOSAL_ONLY</ResearchBadge>
    </div>

    <div className="r2-proposal-list">
      {primary.map((proposal: Json) => {
        const contract = proposal.contract_selection ?? {};
        const call = proposal.right_policies?.CALL ?? {};
        const put = proposal.right_policies?.PUT ?? {};
        const examples = Array.isArray(proposal.examples) ? proposal.examples : [];
        const dataStatuses = Object.entries(proposal.data_availability ?? {}) as [string, unknown][];
        return <article className="research-panel r2-proposal" key={proposal.proposal_id}>
          <header>
            <div><span className="eyebrow">{t(PROFILE_LABELS[proposal.profile_id] ?? "Research profiles")}</span><h3>{textForLanguage(proposal, language, "summary")}</h3></div>
            <ResearchBadge tone={proposal.status === "PROPOSAL_ONLY" ? "info" : "caution"}>{proposal.status}</ResearchBadge>
          </header>
          <div className="r2-mechanism"><span>{t("Profit mechanism")}</span><p>{textForLanguage(proposal, language, "profit_mechanism")}</p></div>
          <div className="r2-contract-grid">
            <div><span>{t("Contract intent")}</span><strong>{contract.position} · {contract.moneyness}</strong><small>{contract.dte_min}–{contract.dte_max} DTE · Δ {contract.absolute_delta_min}–{contract.absolute_delta_max}</small></div>
            <div><span>Call</span><strong>{call.maximum_holding_sessions ?? "-"} {t("sessions max")}</strong><small>{textForLanguage(call, language, "confirmation")}</small></div>
            <div><span>Put</span><strong>{put.maximum_holding_sessions ?? "-"} {t("sessions max")}</strong><small>{textForLanguage(put, language, "confirmation")}</small></div>
          </div>
          <div className="r2-policy-grid">
            <div><span>{t("Entry")}</span><p>{textForLanguage(proposal.entry_policy ?? {}, language, "decision_time")}</p></div>
            <div><span>{t("Invalidation and exit")}</span><p>{proposal.exit_policy?.underlying_invalidation ? textForLanguage(proposal.exit_policy, language, "underlying_invalidation") : textForLanguage(proposal.exit_policy ?? {}, language, "catalyst_invalidation")}</p><small>{textForLanguage(proposal.exit_policy ?? {}, language, "time_exit")}</small></div>
            <div><span>{t("Event handling")}</span><p>{proposal.event_policy?.unknown_event_calendar ? textForLanguage(proposal.event_policy, language, "unknown_event_calendar") : textForLanguage(proposal.event_policy ?? {}, language, "unknown")}</p></div>
            <div><span>{t("Validation target")}</span><p>{textForLanguage(proposal.validation_policy ?? {}, language, "primary_unit")}</p><small>{textForLanguage(proposal.validation_policy ?? {}, language, "benchmark")}</small></div>
          </div>
          <div className="r2-examples">
            {examples.map((example: Json, index: number) => <div key={`${proposal.proposal_id}-example-${index}`}><ResearchBadge tone={example.kind === "SYNTHETIC_ACCEPT" ? "positive" : "caution"}>{example.kind}</ResearchBadge><span>{textForLanguage(example, language, "case")}</span><strong>{example.result}</strong></div>)}
          </div>
          <footer><span>{t("Data status")}: {dataStatuses.map(([key, value]) => dataAvailabilityText(key, value, language)).join(" · ")}</span></footer>
        </article>;
      })}
    </div>

    {alternative.length ? <details className="option-audit-details r2-alternative"><summary>{t("Material alternative and why it is blocked")}</summary>{alternative.map((proposal: Json) => <div key={proposal.proposal_id}><strong>{proposal.proposal_id}</strong><p>{textForLanguage(proposal, language, "summary")}</p><span>{Object.entries(proposal.data_availability ?? {}).map(([key, value]) => `${key}=${String(value)}`).join(" · ")}</span></div>)}</details> : null}

    <div className="research-split r2-policy-panels">
      <article className="research-panel">
        <header><div><span className="eyebrow">{t("Paper execution")}</span><h3>{t("Two quote evidence contracts")}</h3></div><ResearchBadge tone="caution">{t("Not active")}</ResearchBadge></header>
        <div className="r2-execution-list">{executionPolicies.map((policy: Json) => <div key={policy.policy_id}><strong>{policy.policy_id}</strong><span>{policy.evidence_class}</span><p>{t("Entry")}: {textForLanguage(policy, language, "entry")}</p><p>{t("Exit")}: {textForLanguage(policy, language, "exit")}</p><ResearchBadge tone={policy.current_eligibility === "BLOCKED" ? "caution" : "info"}>{policy.current_eligibility}</ResearchBadge></div>)}</div>
        <footer>{t("A receipt-time proxy can never be relabeled as native BBO or an exchange fill.")}</footer>
      </article>
      <article className="research-panel">
        <header><div><span className="eyebrow">{t("Capital and costs")}</span><h3>{payload.paper?.capital_policy?.policy_id ?? "-"}</h3></div><ResearchBadge>DEV_ONLY</ResearchBadge></header>
        <dl>
          <div><dt>{t("Reference capital")}</dt><dd>${formatUiNumber(payload.paper?.capital_policy?.reference_capital_usd, language, 0)}</dd></div>
          <div><dt>{t("Open premium cap")}</dt><dd>{formatUiNumber((payload.paper?.capital_policy?.total_open_premium_fraction ?? 0) * 100, language, 2)}%</dd></div>
          <div><dt>{t("Maximum positions")}</dt><dd>{payload.paper?.capital_policy?.maximum_open_positions ?? "-"}</dd></div>
          <div><dt>{t("Commission")}</dt><dd>${formatUiNumber(payload.paper?.cost_policy?.base_commission_usd_per_contract_per_side, language, 2)} / {t("contract per side")}</dd></div>
          <div><dt>{t("Spread accounting")}</dt><dd>{textForLanguage(payload.paper?.cost_policy ?? {}, language, "spread_accounting")}</dd></div>
        </dl>
      </article>
    </div>

    <article className="research-panel r2-metric-panel">
      <header><div><span className="eyebrow">{metric.policy_id}</span><h3>{t("Frozen validation gate")}</h3></div><ResearchBadge>{metric.unknown_policy}</ResearchBadge></header>
      <div className="r2-metrics">
        <span><small>{t("Observation days")}</small><strong>{thresholds.minimum_observation_trading_days ?? "-"}</strong></span>
        <span><small>{t("Completed per profile and right")}</small><strong>{thresholds.minimum_completed_per_claimed_profile_right ?? "-"}</strong></span>
        <span><small>PF</small><strong>≥ {thresholds.net_profit_factor_min ?? "-"}</strong></span>
        <span><small>Payoff</small><strong>≥ {thresholds.net_payoff_min ?? "-"}</strong></span>
        <span><small>{t("Double-cost PF")}</small><strong>≥ {thresholds.double_cost_profit_factor_min ?? "-"}</strong></span>
        <span><small>{t("Net expectancy interval")}</small><strong>{thresholds.net_expectancy_ci95_lower ?? "-"}</strong></span>
      </div>
      <footer>{t("Unknown values never pass. Scenarios, checkpoints, and counterfactuals are not additional trades.")}</footer>
    </article>

    <details className="option-audit-details"><summary>{t("R2 full audit")}</summary><pre>{JSON.stringify({ manifest: payload.manifest, validation: payload.validation, preflight: payload.preflight, strategies: payload.strategies, paper: payload.paper, metric: payload.metric, tasks: payload.tasks }, null, 2)}</pre></details>
  </section>;
}

function R3ReviewPanel({ payload, approved }: { payload: Json; approved: boolean }) {
  const { language } = useI18n();
  if (payload.status !== "AVAILABLE") return null;
  const zh = language === "zh";
  const replay = payload.replay ?? {};
  const ledger = payload.ledger ?? replay.ledger ?? {};
  const counts = ledger.counts ?? {};
  const lifecycles = Array.isArray(replay.lifecycle) ? replay.lifecycle : [];
  const tasks = Array.isArray(payload.tasks?.tasks) ? payload.tasks.tasks : [];
  const preflight = payload.preflight ?? {};
  const policy = payload.policy ?? {};
  const selected = policy.selected_policy_ids ?? {};

  return <section className="option-section r2-review r3-review" aria-labelledby="r3-review-title">
    <div className="section-title r2-review-head">
      <div>
        <span className="eyebrow">R3 · {zh ? "离线策略模拟工程" : "OFFLINE STRATEGY SIMULATION ENGINEERING"}</span>
        <h2 id="r3-review-title">{zh ? "从候选到退出的可恢复链路" : "A recoverable candidate-to-exit lifecycle"}</h2>
        <span>{zh ? "本页验证工程时序、账本和恢复，不代表策略盈利，也不会启动前向 Paper。" : "This page verifies engineering chronology, ledger behavior, and recovery. It is not performance evidence and does not start forward Paper."}</span>
      </div>
      <div className="research-boundaries">
        <ResearchBadge tone={approved ? "positive" : "caution"}>{approved ? "R3_APPROVED" : "WAIT_REVIEW"}</ResearchBadge>
        <ResearchBadge tone={payload.validation?.status === "PASS" ? "positive" : "caution"}>{zh ? "冻结政策" : "Frozen policy"} · {payload.validation?.status ?? "-"}</ResearchBadge>
        <ResearchBadge tone={approved ? "positive" : "caution"}>{approved ? (zh ? "指定范围已批准" : "Approved scope only") : (zh ? "前向 Paper 已阻断" : "Forward Paper blocked")}</ResearchBadge>
      </div>
    </div>

    <div className="r2-summary-grid">
      <div><Target size={16} /><span>{zh ? "研究范围" : "Research scope"}</span><strong>SHORT ATM · Call/Put</strong></div>
      <div><Beaker size={16} /><span>{zh ? "计划" : "Plans"}</span><strong>{counts.plans ?? 0}</strong></div>
      <div><WalletCards size={16} /><span>{zh ? "工程成交事件" : "Engineering fill events"}</span><strong>{counts.paper_fills ?? 0}</strong></div>
      <div><ShieldAlert size={16} /><span>{zh ? "前向资格" : "Forward eligibility"}</span><strong>{preflight.status ?? "BLOCKED"}</strong></div>
    </div>

    <article className="research-panel r3-policy-card">
      <header><div><span className="eyebrow">{policy.policy_id}</span><h3>{selected.strategy ?? "-"}</h3></div><ResearchBadge tone="info">FROZEN_FOR_OFFLINE_ENGINEERING</ResearchBadge></header>
      <div className="r2-contract-grid">
        <div><span>{zh ? "报价政策" : "Quote policy"}</span><strong>{selected.paper_execution ?? "-"}</strong><small>{zh ? "仅接收时间代理，不是交易所成交" : "Receipt-time proxy only; not an exchange fill"}</small></div>
        <div><span>{zh ? "资金与成本" : "Capital and cost"}</span><strong>{selected.capital ?? "-"}</strong><small>{selected.cost ?? "-"}</small></div>
        <div><span>{zh ? "评价门槛" : "Metric gate"}</span><strong>{selected.metric ?? "-"}</strong><small>{zh ? "工程夹具不计入收益样本" : "Engineering fixtures never count as performance samples"}</small></div>
      </div>
    </article>

    <div className="r3-lifecycle-list">
      {lifecycles.map((item: Json) => {
        const exitResult = item.right === "CALL" ? replay.exit_results?.call : replay.exit_results?.put_recovered;
        return <article className="research-panel" key={item.right}>
          <header><div><span className="eyebrow">{item.right}</span><h3>{item.candidate?.symbol ?? "-"} · {item.selection?.selected?.contract_id ?? "-"}</h3></div><ResearchBadge tone="positive">{exitResult?.status ?? "-"}</ResearchBadge></header>
          <div className="r3-state-line">
            <span>ELIGIBLE_RESEARCH_CANDIDATE</span><span>PLAN_FROZEN</span><span>PAPER_ENTRY_PENDING</span><span>PAPER_OPEN</span><span>PAPER_EXIT_PENDING</span><span>PAPER_CLOSED</span>
          </div>
          <dl>
            <div><dt>{zh ? "决定前报价" : "Pre-decision quote"}</dt><dd>{item.predecision_quote?.reason ?? "-"}</dd></div>
            <div><dt>{zh ? "入场代理" : "Entry proxy"}</dt><dd>{item.entry?.status ?? "-"} · ask + {zh ? "冻结滑点" : "frozen slippage"}</dd></div>
            <div><dt>{zh ? "退出代理" : "Exit proxy"}</dt><dd>{exitResult?.status ?? "-"} · bid - {zh ? "冻结滑点" : "frozen slippage"}</dd></div>
            <div><dt>{zh ? "重复机会" : "Duplicate opportunity"}</dt><dd>{item.duplicate?.reasons?.includes("DUPLICATE_ECONOMIC_OPPORTUNITY") ? (zh ? "已拒绝" : "Rejected") : "-"}</dd></div>
          </dl>
        </article>;
      })}
    </div>

    <div className="research-split r2-policy-panels">
      <article className="research-panel">
        <header><div><span className="eyebrow">{zh ? "恢复证据" : "RECOVERY EVIDENCE"}</span><h3>{zh ? "账本与重启" : "Ledger and restart"}</h3></div><ResearchBadge tone={ledger.integrity_check === "ok" ? "positive" : "caution"}>{ledger.integrity_check ?? "-"}</ResearchBadge></header>
        <dl>
          <div><dt>{zh ? "重启恢复未结束持仓" : "Open positions recovered after restart"}</dt><dd>{replay.restart_recovered_open_positions ?? 0}</dd></div>
          <div><dt>{zh ? "事务回滚探针" : "Transaction rollback probe"}</dt><dd>{replay.rollback_probe?.status ?? "-"}</dd></div>
          <div><dt>{zh ? "最终计划状态" : "Final plan states"}</dt><dd>{JSON.stringify(ledger.plan_states ?? {})}</dd></div>
        </dl>
      </article>
      <article className="research-panel">
        <header><div><span className="eyebrow">{zh ? "权限边界" : "PERMISSION BOUNDARY"}</span><h3>{approved ? (zh ? "仅批准冻结范围的前向 Paper" : "Frozen-scope forward Paper only") : (zh ? "仍需 R3 批准" : "R3 approval still required")}</h3></div><ResearchBadge tone={approved ? "positive" : "caution"}>{approved ? "SCOPED_APPROVAL" : "BLOCKED"}</ResearchBadge></header>
        {approved ? <ul className="r3-blockers"><li>SHORT_ATM_DAYS_WEEK · CALL / PUT</li><li>PAPER-RECEIPT-TIME-PROXY-V1</li><li>{zh ? "实盘、自动增资、策略修改均未批准" : "Live trading, capital expansion, and policy changes are not approved"}</li></ul> : <ul className="r3-blockers">{(preflight.blockers ?? []).map((blocker: string) => <li key={blocker}>{blocker}</li>)}</ul>}
        <footer>{approved ? (zh ? "该批准不把工程夹具变成收益证据。" : "This approval does not convert engineering fixtures into performance evidence.") : (zh ? "信号、自动 Paper、实盘订单均为关闭状态。" : "Signals, automatic Paper entries, and real orders remain disabled.")}</footer>
      </article>
    </div>

    <div className="r3-fixture-warning"><ShieldAlert size={18} /><span>{zh ? "这些记录是合成工程夹具，不得计算为历史交易、胜率、PF、Payoff或盈利证据。" : "These records are synthetic engineering fixtures and must not be counted as historical trades, win rate, PF, payoff, or profitability evidence."}</span></div>
    <details className="option-audit-details"><summary>{zh ? "R3 完整审计" : "R3 full audit"}</summary><pre>{JSON.stringify({ manifest: payload.manifest, acceptance: payload.acceptance, validation: payload.validation, policy, replay, preflight, tasks }, null, 2)}</pre></details>
  </section>;
}

function R4ReviewPanel({ payload }: { payload: Json }) {
  const { language } = useI18n();
  if (payload.status !== "AVAILABLE") return null;
  const zh = language === "zh";
  const manifest = payload.manifest ?? {};
  const forward = payload.forward ?? {};
  const run = forward.run ?? {};
  const ledger = forward.ledger ?? {};
  const deficiency = payload.deficiency ?? {};
  const groups = Array.isArray(forward.groups) ? forward.groups : [];
  return <section className="option-section r2-review r3-review r4-review" aria-labelledby="r4-review-title">
    <div className="section-title r2-review-head">
      <div><span className="eyebrow">R4 · {zh ? "冻结前向 Paper" : "FROZEN FORWARD PAPER"}</span><h2 id="r4-review-title">{zh ? "真实运行已启动，收益结论仍未形成" : "The real run is active; performance is still unresolved"}</h2><span>{zh ? "周末与证据缺口只阻塞对应观察，不会制造自然机会、成交或概率。" : "Market closure and evidence gaps block only their dependent paths; no natural opportunity, fill, or probability is fabricated."}</span></div>
      <div className="research-boundaries"><ResearchBadge tone="caution">WAIT_REVIEW</ResearchBadge><ResearchBadge tone="caution">{manifest.performance_status ?? "INCONCLUSIVE"}</ResearchBadge><ResearchBadge>{manifest.result_class ?? "INTERIM_ENGINEERING_REVIEW_ONLY"}</ResearchBadge></div>
    </div>
    <div className="r2-summary-grid">
      <div><Activity size={16} /><span>{zh ? "前向运行" : "Forward run"}</span><strong className="mono">{run.run_id ?? "-"}</strong></div>
      <div><CalendarClock size={16} /><span>{zh ? "当前状态" : "Current state"}</span><strong>{forward.status ?? "-"}</strong></div>
      <div><WalletCards size={16} /><span>{zh ? "完成交易" : "Completed trades"}</span><strong>{ledger.completed ?? 0}</strong></div>
      <div><ShieldAlert size={16} /><span>{zh ? "真实订单" : "Real orders"}</span><strong>{zh ? "关闭" : "Disabled"}</strong></div>
    </div>
    <div className="r3-lifecycle-list">{groups.map((group: Json) => <article className="research-panel" key={group.profile_id}><header><div><span className="eyebrow">{group.profile_id}</span><h3>{group.state}</h3></div><ResearchBadge tone={group.state === "OPEN_TRACKING" ? "positive" : "caution"}>{group.state}</ResearchBadge></header><dl><div><dt>{zh ? "候选" : "Candidates"}</dt><dd>{group.candidate_count ?? 0}</dd></div><div><dt>{zh ? "完成" : "Completed"}</dt><dd>{group.completed_count ?? 0}</dd></div><div><dt>{zh ? "原因" : "Reason"}</dt><dd>{group.reason ?? "-"}</dd></div></dl></article>)}</div>
    <div className="research-split r2-policy-panels">
      <article className="research-panel"><header><div><span className="eyebrow">{zh ? "确定性风险" : "DETERMINISTIC RISK"}</span><h3>{zh ? "不使用虚构概率" : "No fabricated probability"}</h3></div><ResearchBadge>{forward.risk_research?.method ?? "-"}</ResearchBadge></header><dl><div><dt>{zh ? "参考本金" : "Reference capital"}</dt><dd>${forward.risk_research?.reference_capital_usd ?? "-"}</dd></div><div><dt>{zh ? "单仓权利金上限" : "Per-position premium cap"}</dt><dd>${forward.risk_research?.per_position_premium_cap_usd ?? "-"}</dd></div><div><dt>Monte Carlo</dt><dd>{forward.risk_research?.monte_carlo_status ?? "-"}</dd></div></dl></article>
      <article className="research-panel"><header><div><span className="eyebrow">{zh ? "当前缺口" : "CURRENT DEFICIENCIES"}</span><h3>{zh ? "只阻塞依赖路径" : "Scoped blockers only"}</h3></div><ResearchBadge tone="caution">INCONCLUSIVE</ResearchBadge></header><ul className="r3-blockers">{(deficiency.blocking_only ?? []).map((item: string) => <li key={item}>{item}</li>)}</ul></article>
    </div>
    <div className="r3-fixture-warning"><ShieldAlert size={18} /><span>{zh ? "0 笔完成交易显示 N/A；当前不报告胜率、PF、Payoff或策略通过。" : "With zero completed trades, metrics are N/A; no win rate, PF, payoff, or strategy pass is reported."}</span></div>
    <details className="option-audit-details"><summary>{zh ? "R4 完整审计" : "R4 full audit"}</summary><pre>{JSON.stringify(payload, null, 2)}</pre></details>
  </section>;
}

function R5ReviewPanel({ payload }: { payload: Json }) {
  const { language } = useI18n();
  if (payload.status !== "AVAILABLE") return null;
  const zh = language === "zh";
  const manifest = payload.manifest ?? {};
  const notification = payload.notification ?? {};
  const records = payload.records ?? {};
  const forward = payload.forward ?? {};
  const groups = Array.isArray(forward.groups) ? forward.groups : [];
  const tasks = Array.isArray(payload.tasks) ? payload.tasks : [];
  return <section className="option-section r2-review r3-review r4-review r5-review" aria-labelledby="r5-review-title">
    <div className="section-title r2-review-head">
      <div><span className="eyebrow">R5 · {zh ? "个人研究版本" : "PERSONAL RESEARCH RELEASE"}</span><h2 id="r5-review-title">{zh ? "工程可用，收益仍未证明" : "Engineering ready; performance remains unproven"}</h2><span>{zh ? "前向 Paper、人工记录和旧模拟已分层；这个版本不授予交易权限。" : "Forward Paper, manual records, and legacy simulations are separated. This release grants no trading permission."}</span></div>
      <div className="research-boundaries"><ResearchBadge tone="caution">WAIT_REVIEW</ResearchBadge><ResearchBadge>{manifest.release_class ?? "PERSONAL_RESEARCH_READY_WITH_LIMITATIONS"}</ResearchBadge><ResearchBadge tone="caution">{manifest.performance_status ?? "INCONCLUSIVE"}</ResearchBadge></div>
    </div>
    <div className="r2-summary-grid">
      <div><Activity size={16} /><span>{zh ? "前向状态" : "Forward state"}</span><strong>{forward.status ?? "-"}</strong></div>
      <div><WalletCards size={16} /><span>{zh ? "前向 Paper" : "Forward Paper"}</span><strong>{records.counts?.forward_paper ?? 0}</strong></div>
      <div><CalendarClock size={16} /><span>{zh ? "手机投递" : "Phone delivery"}</span><strong>{notification.state ?? "WAIT_PERMISSION"}</strong></div>
      <div><ShieldAlert size={16} /><span>{zh ? "交易权限" : "Trading permission"}</span><strong>{zh ? "未授予" : "Not granted"}</strong></div>
    </div>
    <div className="r3-lifecycle-list">{groups.map((group: Json) => <article className="research-panel" key={group.profile_id}><header><div><span className="eyebrow">{group.profile_id}</span><h3>{group.state}</h3></div><ResearchBadge tone={group.state === "OPEN_TRACKING" ? "positive" : "caution"}>{group.state}</ResearchBadge></header><dl><div><dt>{zh ? "候选" : "Candidates"}</dt><dd>{group.candidate_count ?? 0}</dd></div><div><dt>{zh ? "完成" : "Completed"}</dt><dd>{group.completed_count ?? 0}</dd></div><div><dt>{zh ? "原因" : "Reason"}</dt><dd>{group.reason ?? "-"}</dd></div></dl></article>)}</div>
    <div className="research-split r2-policy-panels">
      <article className="research-panel"><header><div><span className="eyebrow">{zh ? "记录分层" : "RECORD LAYERS"}</span><h3>{zh ? "不混算样本" : "No borrowed samples"}</h3></div><ResearchBadge tone="positive">SEPARATE</ResearchBadge></header><dl><div><dt>{zh ? "观察清单" : "Watchlist"}</dt><dd>{records.counts?.watchlist ?? 0}</dd></div><div><dt>{zh ? "旧模拟" : "Legacy simulations"}</dt><dd>{records.counts?.legacy_simulation ?? 0}</dd></div><div><dt>{zh ? "人工记录" : "Manual records"}</dt><dd>{records.counts?.manual ?? 0}</dd></div></dl><footer>{zh ? "重复扫描不会增加独立样本。" : "Repeated scans do not add independent samples."}</footer></article>
      <article className="research-panel"><header><div><span className="eyebrow">{zh ? "通知权限" : "NOTIFICATION PERMISSION"}</span><h3>{notification.state ?? "WAIT_PERMISSION"}</h3></div><ResearchBadge tone="caution">{notification.active_subscriptions ?? 0} {zh ? "台设备" : "devices"}</ResearchBadge></header><p>{notification.reason === "NO_AUTHORIZED_PUSH_RECIPIENT" ? (zh ? "尚无用户主动授权的接收设备；本地测试不能冒充真实手机送达。" : "No owner-authorized receiver exists; a local test cannot be claimed as real phone delivery.") : (zh ? "投递状态已保存。" : "Delivery status is persisted.")}</p></article>
    </div>
    <div className="r3-fixture-warning"><ShieldAlert size={18} /><span>{zh ? "策略、成本、风险和门槛保持冻结。R5 不开启实盘、自动增资或策略替换。" : "Strategy, cost, risk, and gates remain frozen. R5 enables no live trading, capital expansion, or strategy substitution."}</span></div>
    <details className="option-audit-details"><summary>{zh ? "R5 完整审计" : "R5 full audit"}</summary><pre>{JSON.stringify({ manifest, notification, records, tasks, backups: payload.backups, services: payload.services }, null, 2)}</pre></details>
  </section>;
}

function R6ReviewPanel({ payload }: { payload: Json }) {
  const { language } = useI18n();
  if (payload.status !== "AVAILABLE") return null;
  const zh = language === "zh";
  const manifest = payload.manifest ?? {};
  const readiness = payload.readiness ?? {};
  const scopes = Array.isArray(readiness.scopes) ? readiness.scopes : [];
  const gates = Object.entries(readiness.gates ?? {}) as [string, Json][];
  const approval = payload.manual_approval ?? {};
  return <section className="option-section r2-review r3-review r4-review r5-review r6-review" aria-labelledby="r6-review-title">
    <div className="section-title r2-review-head">
      <div><span className="eyebrow">R6 · {zh ? "人工使用准备审计" : "MANUAL-USE READINESS AUDIT"}</span><h2 id="r6-review-title">{zh ? "当前没有合格的真实资金使用范围" : "No scope currently qualifies for real-capital use"}</h2><span>{zh ? "工程版本继续可用于研究；收益证据不足，因此不签发人工交易授权。" : "The engineering release remains usable for research. Evidence is insufficient, so no manual trading authorization is issued."}</span></div>
      <div className="research-boundaries"><ResearchBadge tone={payload.state === "ACCEPTED_LIVE_NOT_ENABLED" ? "positive" : "caution"}>{payload.state ?? "WAIT_REVIEW"}</ResearchBadge><ResearchBadge tone="caution">{manifest.readiness_status ?? "NO_GO_WAIT_EVIDENCE"}</ResearchBadge><ResearchBadge tone="caution">{manifest.live_status ?? "LIVE_NOT_ENABLED"}</ResearchBadge><ResearchBadge tone="caution">{manifest.performance_status ?? "INCONCLUSIVE"}</ResearchBadge></div>
    </div>
    <div className="r2-summary-grid">
      <div><Target size={16} /><span>{zh ? "合格范围" : "Qualified scopes"}</span><strong>{manifest.eligible_scope_count ?? 0}</strong></div>
      <div><Activity size={16} /><span>{zh ? "短周期状态" : "Short-term state"}</span><strong>{scopes.find((item: Json) => item.profile_id === "SHORT_ATM_DAYS_WEEK")?.status ?? "WAIT_EVIDENCE"}</strong></div>
      <div><WalletCards size={16} /><span>{zh ? "真实资金" : "Real capital"}</span><strong>{zh ? "未启用" : "Not enabled"}</strong></div>
      <div><ShieldAlert size={16} /><span>{zh ? "订单能力" : "Order capability"}</span><strong>{zh ? "关闭" : "Disabled"}</strong></div>
    </div>
    <div className="r3-lifecycle-list">{scopes.map((scope: Json) => <article className="research-panel" key={scope.profile_id}><header><div><span className="eyebrow">{scope.profile_id}</span><h3>{scope.status}</h3></div><ResearchBadge tone="caution">{scope.forward_state ?? scope.status}</ResearchBadge></header>{Array.isArray(scope.rights) && scope.rights.length ? <dl>{scope.rights.map((right: Json) => <div key={right.right}><dt>{right.right}</dt><dd>{right.completed ?? 0} / {right.minimum_completed ?? 200} · {right.evidence_gate ?? "INCONCLUSIVE"}</dd></div>)}</dl> : <p>{scope.reason ?? (zh ? "继续研究" : "Research continues")}</p>}</article>)}</div>
    <div className="research-split r2-policy-panels">
      <article className="research-panel"><header><div><span className="eyebrow">{zh ? "准入门槛" : "ADMISSION GATES"}</span><h3>{zh ? "按原标准逐项核验" : "Checked against frozen thresholds"}</h3></div><ResearchBadge tone="caution">NO_GO</ResearchBadge></header><dl>{gates.map(([gate, result]) => <div key={gate}><dt>{gate}</dt><dd>{result.status}</dd></div>)}</dl></article>
      <article className="research-panel"><header><div><span className="eyebrow">{zh ? "人工授权" : "MANUAL AUTHORIZATION"}</span><h3>{approval.status ?? "NOT_ISSUABLE_NO_QUALIFIED_SCOPE"}</h3></div><ResearchBadge tone="caution">NULL</ResearchBadge></header><p>{zh ? "账户、本金、损失上限、范围、有效期和所有者确认均保持为空。" : "Account, capital, loss limits, scope, validity, and owner confirmation all remain null."}</p></article>
    </div>
    <div className="r3-fixture-warning"><ShieldAlert size={18} /><span>{zh ? "R6 接受的是 LIVE_NOT_ENABLED 结论。冻结前向观察继续，中长期组继续研究；不放宽门槛、不替换策略。" : "R6 records a LIVE_NOT_ENABLED conclusion. Frozen observation and research continue without lower gates or strategy substitution."}</span></div>
    <details className="option-audit-details"><summary>{zh ? "R6 完整审计" : "R6 full audit"}</summary><pre>{JSON.stringify(payload, null, 2)}</pre></details>
  </section>;
}

export default function OptionsResearchWorkbench({ payload, reviewR1 = {}, reviewR2 = {}, reviewR3 = {}, reviewR4 = {}, reviewR5 = {}, reviewR6 = {}, symbol }: Props) {
  const { language, t } = useI18n();
  const hypotheses = Array.isArray(payload.hypotheses) ? payload.hypotheses : [];
  const equitySnapshots = Array.isArray(payload.equity_feature_snapshots) ? payload.equity_feature_snapshots : [];
  const optionSnapshots = Array.isArray(payload.option_feature_snapshots) ? payload.option_feature_snapshots : [];
  const scenarios = Array.isArray(payload.scenarios) ? payload.scenarios : [];
  const checkpoints = Array.isArray(payload.cohort?.checkpoints) ? payload.cohort.checkpoints : [];
  const tasks = Array.isArray(payload.tasks) ? payload.tasks : [];
  const experiment = payload.experiment ?? {};
  const counts = payload.counts ?? {};

  const currentEquity = equitySnapshots.find((item: Json) => item.entity_id === symbol) ?? equitySnapshots[0] ?? null;
  const currentOption = optionSnapshots.find((item: Json) => String(item.underlying_symbol ?? item.symbol ?? "").startsWith(symbol)) ?? optionSnapshots[0] ?? null;
  const currentScenario = scenarios.find((item: Json) => item.contract_id === currentOption?.entity_id) ?? scenarios[0] ?? null;
  const oneDayCases = (Array.isArray(currentScenario?.cases) ? currentScenario.cases : []).filter((item: Json) => item.elapsed_calendar_days === 1);
  const scenarioMatrix = [-0.05, 0, 0.05].map((spotShock) => ({
    spotShock,
    values: [-5, 0, 5].map((ivShock) => oneDayCases.find((item: Json) => item.underlying_return_shock === spotShock && item.iv_shock_percentage_points === ivShock)?.local_approximation_value),
  }));
  const checkpointSummary = useMemo(() => {
    const summary = new Map<number, { count: number; waiting: number }>();
    checkpoints.forEach((item: Json) => {
      const sessions = Number(item.checkpoint_sessions);
      const current = summary.get(sessions) ?? { count: 0, waiting: 0 };
      current.count += 1;
      if (item.outcome_status !== "PENDING") current.waiting += 1;
      summary.set(sessions, current);
    });
    return [...summary.entries()].sort(([left], [right]) => left - right);
  }, [checkpoints]);
  const completedTasks = tasks.filter((item: Json) => ["VERIFIED", "DELIVERED_WITH_LIMITATIONS"].includes(item.state)).length;
  const r1Experiment = reviewR1.status === "AVAILABLE" ? reviewR1.experiment ?? {} : null;
  const displayedExperiment = r1Experiment ?? experiment;

  if (!payload.status) {
    return <><R6ReviewPanel payload={reviewR6} /><R5ReviewPanel payload={reviewR5} /><R4ReviewPanel payload={reviewR4} /><R3ReviewPanel payload={reviewR3} approved={reviewR4.status === "AVAILABLE"} /><R2ReviewPanel payload={reviewR2} /><R1ReviewPanel payload={reviewR1} symbol={symbol} /><section className="option-section research-workbench"><div className="option-empty"><strong>{t("Research workbench unavailable")}</strong><span>{t("The independent research store has not produced a readable artifact yet.")}</span></div></section></>;
  }

  return <><R6ReviewPanel payload={reviewR6} /><R5ReviewPanel payload={reviewR5} /><R4ReviewPanel payload={reviewR4} /><R3ReviewPanel payload={reviewR3} approved={reviewR4.status === "AVAILABLE"} /><R2ReviewPanel payload={reviewR2} /><R1ReviewPanel payload={reviewR1} symbol={symbol} /><section className="option-section research-workbench" aria-labelledby="options-research-title">
    <div className="section-title research-workbench-head">
      <div>
        <span className="eyebrow">{t("Options research V0.1")}</span>
        <h2 id="options-research-title">{t("Research workbench")}</h2>
        <span>{t("Descriptive evidence, fixed experiments, and no-position observations remain isolated from signals and execution.")}</span>
      </div>
      <div className="research-boundaries" aria-label={t("Research boundaries")}>
        <ResearchBadge tone="caution">{t("Strategy pending")}</ResearchBadge>
        <ResearchBadge>{t("Performance not evaluated")}</ResearchBadge>
        <ResearchBadge>{t("Orders disabled")}</ResearchBadge>
      </div>
    </div>

    <div className="research-kpis">
      <div><Database size={15} /><span>{t("Feature definitions")}</span><strong>{counts.research_feature_definitions ?? 0}</strong></div>
      <div><Activity size={15} /><span>{t("Feature snapshots")}</span><strong>{counts.research_feature_snapshots ?? 0}</strong></div>
      <div><Beaker size={15} /><span>{t("Registered hypotheses")}</span><strong>{hypotheses.length}</strong></div>
      <div><CalendarClock size={15} /><span>{t("Future checkpoints")}</span><strong>{checkpoints.length}</strong></div>
      <div><ShieldAlert size={15} /><span>{t("Task evidence")}</span><strong>{completedTasks}/{tasks.length || 18}</strong></div>
    </div>

    <div className="research-hypothesis-grid">
      {hypotheses.map((item: Json) => {
        const copy = HYPOTHESIS_COPY[item.hypothesis_id];
        return <article key={item.hypothesis_id}>
          <header><div><span>{item.hypothesis_id}</span><h3>{t(PROFILE_LABELS[item.profile_id] ?? "Research profiles")}</h3></div><ResearchBadge tone="positive">{t("Registered")}</ResearchBadge></header>
          <p>{copy ? t(copy.mechanism) : String(item.mechanism ?? "-")}</p>
          <dl>
            <div><dt>{t("Measurement target")}</dt><dd>{copy ? t(copy.target) : String(item.target ?? "-")}</dd></div>
            <div><dt>{t("Observable factors")}</dt><dd>{(item.observable_information ?? []).join(" · ")}</dd></div>
          </dl>
          <footer>{t("DTE, Delta, entry, exit, and sizing remain null.")}</footer>
        </article>;
      })}
    </div>

    <div className="research-split">
      <article className="research-panel experiment-panel">
        <header><div><span className="eyebrow">E-S-001</span><h3>{t("Preregistered underlying experiment")}</h3></div><ResearchBadge tone={displayedExperiment.fit_performed ? "positive" : "caution"}>{displayedExperiment.status ?? "DATA_INSUFFICIENT"}</ResearchBadge></header>
        <p>{displayedExperiment.fit_performed ? t("The original frozen experiment ran on the separately stored adjusted dataset; its result remains DEV_ONLY.") : t("The only development experiment is frozen. It did not fit a model because the required adjusted daily price basis is not verified.")}</p>
        <dl>
          <div><dt>{t("Single factor")}</dt><dd>excess_log_return_20_sector</dd></div>
          <div><dt>{t("Model")}</dt><dd>Ridge α=1 · DEV_ONLY</dd></div>
          <div><dt>{t("Fit performed")}</dt><dd>{displayedExperiment.fit_performed || displayedExperiment.fit_artifact ? t("Yes") : t("No")}</dd></div>
          <div><dt>{t("Result")}</dt><dd>{displayedExperiment.conclusion ?? displayedExperiment.preflight?.blockers?.[0] ?? "-"}</dd></div>
          <div><dt>{t("Dataset hash")}</dt><dd className="mono">{shortenedHash(displayedExperiment.dataset_manifest?.dataset_hash ?? displayedExperiment.dataset_hash)}</dd></div>
        </dl>
        <footer>{t("This experiment studies the underlying, not option P&L or a Call/Put signal.")}</footer>
      </article>

      <article className="research-panel factor-panel">
        <header><div><span className="eyebrow">{currentEquity?.entity_id ?? symbol}</span><h3>{t("Latest descriptive factors")}</h3></div><ResearchBadge>{t("Unadjusted basis")}</ResearchBadge></header>
        {currentEquity ? <dl className="factor-values">
          {Object.entries(currentEquity.values ?? {}).slice(0, 6).map(([key, value]) => <div key={key}><dt>{key}</dt><dd>{formatUiNumber(value, language, 4)}</dd></div>)}
        </dl> : <p>{t("No descriptive factor snapshot is available for this symbol.")}</p>}
        <footer>{t("As of")} {currentEquity?.as_of_market_time ?? "-"} · {t("Lineage")} <span className="mono">{shortenedHash(currentEquity?.lineage_hash)}</span></footer>
      </article>
    </div>

    <div className="research-split">
      <article className="research-panel scenario-panel">
        <header><div><span className="eyebrow">{currentScenario?.contract_id ?? "-"}</span><h3>{t("Deterministic Greeks comparison")}</h3></div><ResearchBadge>{t("Not a forecast")}</ResearchBadge></header>
        <div className="scenario-matrix" role="table" aria-label={t("One-day local Greeks approximation")}>
          <div className="scenario-row scenario-head" role="row"><span>{t("Spot shock")}</span><span>IV -5pt</span><span>IV 0pt</span><span>IV +5pt</span></div>
          {scenarioMatrix.map((row) => <div className="scenario-row" role="row" key={row.spotShock}><strong>{row.spotShock > 0 ? "+" : ""}{formatUiNumber(row.spotShock * 100, language, 0)}%</strong>{row.values.map((value, index) => <span key={index}>{formatUiNumber(value, language, 2)}</span>)}</div>)}
        </div>
        <footer>{t("Local Greeks values are explanatory approximations, not executable prices, probabilities, or expected profit.")}</footer>
      </article>

      <article className="research-panel cohort-panel">
        <header><div><span className="eyebrow">{t("No-position cohort")}</span><h3>{t("Fixed future checkpoints")}</h3></div><ResearchBadge tone="positive">{t("No positions created")}</ResearchBadge></header>
        <div className="checkpoint-list">
          {checkpointSummary.map(([sessions, item]) => <div key={sessions}><strong>{sessions}</strong><span>{t("sessions")}</span><small>{item.count - item.waiting} {t("scheduled")} · {item.waiting} {t("calendar pending")}</small></div>)}
        </div>
        <footer>{t("Quote and IV changes are observations only; no entry, exit, ledger, or option P&L is created.")}</footer>
      </article>
    </div>
  </section></>;
}
