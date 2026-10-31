import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import OptionsResearchWorkbench from "./OptionsResearchWorkbench";
import { I18nProvider } from "./i18n";

const payload = {
  status: "ENGINEERING_READY_WAIT_MARKET",
  counts: { research_feature_definitions: 13, research_feature_snapshots: 24 },
  hypotheses: [{
    hypothesis_id: "H-S-01",
    profile_id: "SHORT_ATM_DAYS_WEEK",
    observable_information: ["excess_log_return_20_sector"],
  }],
  experiment: {
    status: "DATA_INSUFFICIENT",
    fit_artifact: null,
    dataset_hash: "0123456789abcdef",
    preflight: { blockers: ["NO_VERIFIED_ADJUSTED_DAILY_PRICE_BASIS"] },
  },
  cohort: { checkpoints: [{ checkpoint_sessions: 5, outcome_status: "PENDING" }] },
  tasks: [{ state: "VERIFIED" }],
  equity_feature_snapshots: [{
    entity_id: "NVDA",
    as_of_market_time: "2026-09-18",
    lineage_hash: "abcdef0123456789",
    values: { excess_log_return_20_sector: 0.01 },
  }],
  option_feature_snapshots: [],
  scenarios: [],
};

const reviewR1 = {
  status: "AVAILABLE",
  state: "WAIT_REVIEW",
  bundle_id: "options-r1-test",
  manifest: { permissions: { signals: false, paper_entries: false, orders: false } },
  validation: {
    gate_status: "PASS",
    adjustment_as_of_policy: "PULL_COMPLETION_TIME; NOT HISTORICAL_POINT_IN_TIME",
    corporate_action_test: {
      status: "PASS",
      official_event: "10-for-1 forward split",
      raw_close_to_post_split_open_ratio: 9.98,
      adjusted_close_to_post_split_open_ratio: 0.998,
      pre_split_adjusted_to_raw_volume_ratio: 10,
      turnover_preserved: true,
    },
    symbols: [{ symbol: "NVDA", start: "2021-01-01", end: "2026-09-18", raw_dates: 1400, adjusted_dates: 1400, close_difference_dates: 1200, lineage_complete: true }],
  },
  experiment: {
    status: "DEV_FIT_COMPLETE",
    conclusion: "INCONCLUSIVE",
    fit_performed: true,
    exposure_status: "EXPOSED_RESEARCH",
    dataset_manifest: { unique_dates: 1300, dataset_hash: "r1-dataset-hash" },
    partitions: { TEST: { rows: 200, ridge_mae: 0.02, training_mean_baseline_mae: 0.021, mae_improvement: 0.001 } },
  },
  tasks: { tasks: [{ task_id: "T06", state: "WAIT_REVIEW" }] },
};

const reviewR2 = {
  status: "AVAILABLE",
  state: "WAIT_REVIEW",
  bundle_id: "options-r2-test",
  validation: { status: "PASS" },
  preflight: { status: "BLOCKED", activation_allowed: false },
  strategies: {
    proposals: [{
      proposal_id: "STRAT-SHORT-ATM-RANGE-EXPANSION-V1",
      variant: "PRIMARY",
      profile_id: "SHORT_ATM_DAYS_WEEK",
      status: "PROPOSAL_ONLY",
      summary_zh: "研究整理后的方向扩张。",
      summary_en: "Study directional expansion after compression.",
      profit_mechanism: "Capture convex premium repricing.",
      contract_selection: { position: "LONG_SINGLE_LEG", moneyness: "ATM_BY_DELTA", dte_min: 14, dte_max: 35, absolute_delta_min: 0.45, absolute_delta_max: 0.60 },
      right_policies: { CALL: { maximum_holding_sessions: 5, confirmation: "Call confirmation" }, PUT: { maximum_holding_sessions: 3, confirmation: "Put confirmation" } },
      entry_policy: { decision_time: "09:40_ET" },
      exit_policy: { underlying_invalidation: "30m close crosses level", time_exit: "MAX_HOLD" },
      event_policy: { unknown_event_calendar: "ABSTAIN" },
      validation_policy: { primary_unit: "completed_option_paper_trade", benchmark: "random" },
      data_availability: { native_bbo_event_time: "UNAVAILABLE" },
      examples: [{ kind: "SYNTHETIC_ACCEPT", case: "Frozen example", result: "CANDIDATE_PENDING_QUOTE_POLICY" }],
    }],
  },
  paper: {
    execution_policies: [{ policy_id: "PAPER-RECEIPT-TIME-PROXY-V1", evidence_class: "RECEIPT_TIME_QUOTE_PROXY", current_eligibility: "RESEARCH_PROXY_ONLY", entry: "ask after decision", exit: "bid after trigger" }],
    capital_policy: { policy_id: "PAPER-RISK-10000-V1", reference_capital_usd: 10000, total_open_premium_fraction: 0.015, maximum_open_positions: 3 },
    cost_policy: { base_commission_usd_per_contract_per_side: 1, spread_accounting: "never deduct spread twice" },
  },
  metric: {
    policy_id: "METRIC-OPTIONS-RESEARCH-GATE-V1",
    unknown_policy: "UNKNOWN_NEVER_PASSES",
    legacy_thresholds_preserved: { minimum_observation_trading_days: 20, minimum_completed_per_claimed_profile_right: 200, net_profit_factor_min: 1.3, net_payoff_min: 1.8, double_cost_profit_factor_min: 1.05, net_expectancy_ci95_lower: ">0" },
  },
};

const reviewR3 = {
  status: "AVAILABLE",
  state: "WAIT_REVIEW",
  bundle_id: "options-r3-test",
  validation: { status: "PASS" },
  policy: {
    policy_id: "OPTIONS-SHORT-ATM-OFFLINE-V1",
    selected_policy_ids: {
      strategy: "STRAT-SHORT-ATM-RANGE-EXPANSION-V1",
      paper_execution: "PAPER-RECEIPT-TIME-PROXY-V1",
      capital: "PAPER-RISK-10000-V1",
      cost: "COST-OPTIONS-CONSERVATIVE-V1",
      metric: "METRIC-OPTIONS-RESEARCH-GATE-V1",
    },
  },
  replay: {
    classification: "SYNTHETIC_ENGINEERING_REPLAY_NOT_PERFORMANCE",
    lifecycle: [
      { right: "CALL", candidate: { symbol: "NVDA" }, selection: { selected: { contract_id: "NVDA-CALL" } }, predecision_quote: { reason: "QUOTE_PRECEDES_DECISION_OR_REQUEST" }, entry: { status: "PAPER_OPEN" } },
      { right: "PUT", candidate: { symbol: "NVDA" }, selection: { selected: { contract_id: "NVDA-PUT" } }, predecision_quote: { reason: "QUOTE_PRECEDES_DECISION_OR_REQUEST" }, entry: { status: "PAPER_OPEN" } },
    ],
    exit_results: { call: { status: "PAPER_CLOSED" }, put_recovered: { status: "PAPER_CLOSED" } },
    restart_recovered_open_positions: 1,
    rollback_probe: { status: "PASS" },
  },
  ledger: { integrity_check: "ok", counts: { plans: 2, paper_fills: 4 }, plan_states: { PAPER_CLOSED: 2 } },
  preflight: { status: "BLOCKED", blockers: ["R3_OWNER_REVIEW_REQUIRED"], forward_paper_allowed: false },
  tasks: { tasks: [{ task_id: "T18", state: "WAIT_REVIEW" }] },
};

const reviewR6 = {
  status: "AVAILABLE",
  state: "ACCEPTED_LIVE_NOT_ENABLED",
  bundle_id: "options-r6-test",
  manifest: { readiness_status: "NO_GO_WAIT_EVIDENCE", live_status: "LIVE_NOT_ENABLED", performance_status: "INCONCLUSIVE", eligible_scope_count: 0 },
  readiness: {
    gates: {
      D_PAPER_DATA: { status: "WAIT_EVIDENCE" },
      V_STRATEGY_EVIDENCE: { status: "INCONCLUSIVE" },
      R_RELEASE_SAFE: { status: "PASS_WITH_LIMITATIONS" },
      H_EXACT_MANUAL_AUTH: { status: "NOT_REQUESTED" },
    },
    scopes: [
      { profile_id: "SHORT_ATM_DAYS_WEEK", status: "WAIT_EVIDENCE", forward_state: "WAIT_MARKET", rights: [{ right: "CALL", completed: 0, minimum_completed: 200, evidence_gate: "INCONCLUSIVE" }, { right: "PUT", completed: 0, minimum_completed: 200, evidence_gate: "INCONCLUSIVE" }] },
      { profile_id: "MEDIUM_ATM_WEEKS_MONTHS", status: "NOT_EVALUATED", reason: "RESEARCH_CONTINUES" },
      { profile_id: "LONG_OTM_MONTHS_YEAR", status: "NOT_EVALUATED", reason: "RESEARCH_CONTINUES" },
    ],
  },
  manual_approval: { status: "NOT_ISSUABLE_NO_QUALIFIED_SCOPE", capital_usd: null, owner_confirmation: null },
  trading_permission: false,
  orders_enabled: false,
};

describe("options research workbench", () => {
  it("shows honest boundaries and no-position evidence in English", () => {
    const markup = renderToStaticMarkup(<I18nProvider language="en"><OptionsResearchWorkbench payload={payload} symbol="NVDA" /></I18nProvider>);
    expect(markup).toContain("Research workbench");
    expect(markup).toContain("DATA_INSUFFICIENT");
    expect(markup).toContain("Orders disabled");
    expect(markup).toContain("No positions created");
    expect(markup).toContain("not executable prices, probabilities, or expected profit");
    expect(markup).not.toContain("Win probability");
  });

  it("keeps the same boundary visible in Chinese", () => {
    const markup = renderToStaticMarkup(<I18nProvider language="zh"><OptionsResearchWorkbench payload={payload} symbol="NVDA" /></I18nProvider>);
    expect(markup).toContain("研究工作台");
    expect(markup).toContain("未创建持仓");
    expect(markup).toContain("该实验研究正股，不代表期权盈亏");
  });

  it("renders the R1 adjusted-data and experiment evidence without enabling trading", () => {
    const markup = renderToStaticMarkup(<I18nProvider language="en"><OptionsResearchWorkbench payload={payload} reviewR1={reviewR1} symbol="NVDA" /></I18nProvider>);
    expect(markup).toContain("Data and research review package");
    expect(markup).toContain("D_ADJUSTED_DATA · PASS");
    expect(markup).toContain("NO_ADJUST");
    expect(markup).toContain("FORWARD_ADJUST");
    expect(markup).toContain("10-for-1 forward split");
    expect(markup).toContain("DEV_FIT_COMPLETE");
    expect(markup).toContain("Production use");
    expect(markup).toContain("Disabled");
  });

  it("renders the R2 proposal contract while keeping activation blocked", () => {
    const markup = renderToStaticMarkup(<I18nProvider language="en"><OptionsResearchWorkbench payload={payload} reviewR2={reviewR2} symbol="NVDA" /></I18nProvider>);
    expect(markup).toContain("Choose the research contract, not a trade");
    expect(markup).toContain("STRAT-SHORT-ATM-RANGE-EXPANSION-V1");
    expect(markup).toContain("PAPER-RECEIPT-TIME-PROXY-V1");
    expect(markup).toContain("UNKNOWN_NEVER_PASSES");
    expect(markup).toContain("Activation blocked");
    expect(markup).not.toContain("Order submission enabled");
  });

  it("renders the R3 offline lifecycle without presenting fixtures as performance", () => {
    const markup = renderToStaticMarkup(<I18nProvider language="en"><OptionsResearchWorkbench payload={payload} reviewR3={reviewR3} symbol="NVDA" /></I18nProvider>);
    expect(markup).toContain("A recoverable candidate-to-exit lifecycle");
    expect(markup).toContain("QUOTE_PRECEDES_DECISION_OR_REQUEST");
    expect(markup).toContain("PAPER_EXIT_PENDING");
    expect(markup).toContain("R3_OWNER_REVIEW_REQUIRED");
    expect(markup).toContain("synthetic engineering fixtures");
    expect(markup).not.toContain("Forward Paper enabled");
  });

  it("renders the R6 no-live branch without issuing manual authorization", () => {
    const markup = renderToStaticMarkup(<I18nProvider language="en"><OptionsResearchWorkbench payload={payload} reviewR6={reviewR6} symbol="NVDA" /></I18nProvider>);
    expect(markup).toContain("No scope currently qualifies for real-capital use");
    expect(markup).toContain("NO_GO_WAIT_EVIDENCE");
    expect(markup).toContain("ACCEPTED_LIVE_NOT_ENABLED");
    expect(markup).toContain("LIVE_NOT_ENABLED");
    expect(markup).toContain("CALL");
    expect(markup).toContain("0 / 200 · INCONCLUSIVE");
    expect(markup).toContain("NOT_ISSUABLE_NO_QUALIFIED_SCOPE");
    expect(markup).not.toContain("Trading authorized");
  });
});
