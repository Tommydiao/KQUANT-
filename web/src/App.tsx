import {
  Activity,
  AlertTriangle,
  BarChart3,
  CheckCircle2,
  Languages,
  Lock,
  MessageCircle,
  Moon,
  RefreshCw,
  Search,
  Send,
  ShieldCheck,
  Sun,
} from "lucide-react";
import {
  CandlestickSeries,
  createChart,
  HistogramSeries,
  LineSeries,
  type CandlestickData,
  type HistogramData,
  type IChartApi,
  type LineData,
  type Time,
} from "lightweight-charts";
import { type FormEvent, useEffect, useMemo, useRef, useState } from "react";

type Lang = "en" | "zh";
type Theme = "light" | "dark";
type Source = "fixture" | "live";
type Level = "BUY SETUP" | "WATCH" | "PASS";
type TradeAction = "BUY" | "WAIT" | "DO_NOT_BUY" | "HOLD_TRAIL" | "EXIT_REVIEW";
type AiAction = "AI_BUY_CANDIDATE" | "AI_WAIT" | "AI_AVOID" | "AI_HOLD_TRAIL" | "AI_EXIT_REVIEW";
type UniverseName = "default" | "ai_five_layer" | "physical_ai" | "all";
type AppView = "stocks" | "mstr";
type WorkspaceName =
  | "today"
  | "search"
  | "watchlist"
  | "stock"
  | "charts"
  | "aiPlan"
  | "chat"
  | "mstr"
  | "journal"
  | "settings";
type StrategyProfileName =
  | "tactical_1w_v1"
  | "swing_1_2m_v1"
  | "position_6m_v1"
  | "cycle_1_3y_v1"
  | "high_beta_growth_v1";
type RangeValue = "5d" | "1y" | "5y" | "10y";
type IntervalValue = "1h" | "1d" | "1wk" | "1mo";
type ChartPresetKey = "1h" | "1d" | "1w" | "1m";
type ApiConnectionState = "checking" | "connected" | "offline";

type Candle = {
  time: Time;
  open_time?: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
};

type ChartPreset = {
  key: ChartPresetKey;
  label: string;
  range: RangeValue;
  interval: IntervalValue;
};

type CandleMeta = {
  symbol: string;
  range: string;
  interval: string;
  sourceType: string;
  providerStatus: string;
  freshness: string;
  staleAge: string;
  count: number;
  first: string;
  last: string;
  errors: string[];
};

type ApiHealthPayload = {
  status: string;
  backend?: string;
  live_data_enabled?: boolean;
  ai_review_status?: string;
  read_only_research?: boolean;
  fixture_user_visible?: boolean;
  broker_order_wiring_enabled?: boolean;
  account_access_enabled?: boolean;
  order_submission_enabled?: boolean;
};

type AiReviewStatusPayload = {
  status: "available" | "missing_key" | string;
  reason: string;
  setup_hint?: string;
  models: {
    review?: string;
    batch?: string;
    deep?: string;
    research?: string;
  };
  read_only_research: boolean;
  llm_signal_core_enabled: boolean;
  ai_decision_engine_enabled?: boolean;
  daily_opportunity_agent_enabled?: boolean;
  deep_research_chat_enabled?: boolean;
  hard_rule_veto_enabled?: boolean;
  ai_can_lead_decisions?: boolean;
  ai_can_place_orders?: boolean;
  broker_order_wiring_enabled: boolean;
};

type StockSignal = {
  symbol: string;
  score: number;
  level: Level;
  profile_name?: string;
  strategy_label?: string;
  holding_period?: string;
  primary_timeframe?: string;
  confirmation_timeframe?: string;
  review_bucket?: "high_priority" | "watch" | "pass";
  downgraded_reasons?: string[];
  direction: "LONG";
  trend_summary: string;
  trigger_summary: string;
  risk_warnings: string[];
  manual_checklist: string[];
  data_status: {
    daily_provider_status: string;
    hourly_provider_status: string;
    daily_candles: number;
    hourly_candles: number;
    source: string;
    freshness: string;
    data_quality?: string;
    live_does_not_fallback_to_fixture?: boolean;
  };
  features: Record<string, number>;
  score_breakdown?: {
    trend_score: number;
    trigger_score: number;
    volume_score: number;
    risk_score: number;
    total_score: number;
    buy_setup_threshold: number;
    watch_threshold: number;
    formula: string;
  };
  exit_risk?: {
    status: string;
    level: string;
    reasons: string[];
    checklist: string[];
  };
  exit_plan?: {
    status: string;
    holding_period: string;
    profile_name: string;
    rules: string[];
    current_close?: number;
    read_only_research: boolean;
  };
  trade_conclusion?: {
    action: TradeAction;
    confidence: "HIGH" | "MEDIUM" | "LOW" | string;
    risk_bucket: "standard_risk" | "light_risk" | "avoid" | string;
    decision_summary: string;
    why: string[];
    blockers: string[];
    invalidation: string[];
    profile_name: string;
    holding_period: string;
    position_context: string;
    read_only_research: boolean;
    llm_signal_core_enabled: boolean;
    broker_order_wiring_enabled: boolean;
  };
  readiness_gate?: TradeReadinessGate;
  primary_layer?: string;
  tags?: string[];
  liquidity_tier?: string;
  historical_edge: {
    sample_count: number;
    win_rate_5d: number;
    target_hit_rate_5d: number;
    avg_forward_return_3d: number;
    avg_forward_return_5d: number;
    avg_forward_return_10d: number;
    avg_max_drawdown_5d: number;
    verdict: string;
    focus_window?: string;
    focus_horizon_bars?: number;
    focus_sample_count?: number;
    focus_win_rate?: number;
    focus_target_hit_rate?: number;
    focus_avg_return?: number;
    focus_avg_max_drawdown?: number;
    profile_verdict?: string;
    profile_note?: string;
  };
};

type AiReviewPayload = {
  status: "available" | "ai_review_unavailable" | string;
  reason: string;
  model_name: string;
  generated_at: string;
  input_summary: Record<string, unknown>;
  rule_conclusion: StockSignal["trade_conclusion"] | Record<string, unknown>;
  ai_review: {
    ai_review_verdict: "supports_rule_conclusion" | "caution" | "disagrees" | string;
    quality_filter: "high_quality" | "mixed" | "low_quality" | string;
    rr_improvement_notes: string[];
    risk_questions: string[];
    journal_prompt: string[];
    downgrade_suggestion: string;
    summary: string;
    rule_action: string;
    does_not_override_rule_conclusion: boolean;
    cannot_upgrade_do_not_buy_to_buy: boolean;
  };
  safety_policy: {
    read_only_research: boolean;
    llm_signal_core_enabled: boolean;
    ai_review_only: boolean;
    broker_order_wiring_enabled: boolean;
    account_access_enabled: boolean;
    order_submission_enabled: boolean;
    does_not_override_rule_conclusion: boolean;
  };
};

type AiDecisionPayload = {
  status: "available" | "ai_unavailable" | string;
  reason: string;
  model_name: string;
  generated_at: string;
  input_summary: Record<string, unknown>;
  rule_conclusion: StockSignal["trade_conclusion"] | Record<string, unknown>;
  hard_veto: {
    active: boolean;
    reasons: string[];
    can_ai_buy: boolean;
    policy: string;
  };
  ai_decision: {
    action: AiAction | string;
    confidence: "HIGH" | "MEDIUM" | "LOW" | string;
    risk_bucket: "standard_risk" | "light_risk" | "high_beta_risk" | "avoid" | string;
    entry_zone: string;
    stop_zone: string;
    target_zone: string;
    risk_reward: string;
    position_size_hint: string;
    why_now: string[];
    what_invalidates_this_setup: string[];
    best_profile: string;
    human_checklist: string[];
    summary: string;
    rule_action: string;
    hard_veto_applied: boolean;
    hard_veto_reasons: string[];
    read_only_research: boolean;
    broker_order_wiring_enabled: boolean;
    order_submission_enabled: boolean;
  };
  safety_policy: {
    read_only_research: boolean;
    ai_leads_decision_layer: boolean;
    hard_rule_veto_enabled: boolean;
    hard_veto_active: boolean;
    llm_signal_core_enabled: boolean;
    broker_order_wiring_enabled: boolean;
    account_access_enabled: boolean;
    order_submission_enabled: boolean;
    manual_human_execution_only: boolean;
  };
};

type ResearchChatAnswer = {
  answer: string;
  direct_view: string;
  key_points: string[];
  risk_flags: string[];
  what_to_check_next: string[];
  evidence_used: string[];
  follow_up_questions: string[];
  safety_note: string;
};

type AiResearchChatPayload = {
  product: string;
  status: "available" | "ai_unavailable" | string;
  reason: string;
  model_name: string;
  primary_model_name?: string;
  fallback_model_used?: boolean;
  fallback_reason?: string;
  generated_at: string;
  symbol: string;
  profile: string;
  question: string;
  answer: ResearchChatAnswer;
  safety_policy: {
    read_only_research: boolean;
    ai_research_chat_enabled: boolean;
    ai_can_place_orders: boolean;
    broker_order_wiring_enabled: boolean;
    account_access_enabled: boolean;
    order_submission_enabled: boolean;
    does_not_change_rule_score: boolean;
    does_not_trigger_scans: boolean;
  };
};

type ResearchChatMessage = {
  id: string;
  role: "user" | "assistant";
  content: string;
  payload?: AiResearchChatPayload;
  created_at: string;
};

type AiDailyItem = {
  symbol: string;
  action: AiAction | string;
  confidence: string;
  best_profile: string;
  entry_zone: string;
  stop_zone: string;
  target_zone: string;
  risk_reward: string;
  position_size_hint: string;
  why_now: string[];
  risk_flags: string[];
  hard_veto_applied?: boolean;
};

type AiDailyAgentPayload = {
  status: "available" | "ai_unavailable" | "not_scanned" | string;
  reason: string;
  run_id?: string;
  model_name?: string;
  generated_at?: string;
  market_date?: string;
  is_stale?: boolean;
  age_seconds?: number | null;
  auto_run_recommended?: boolean;
  auto_run_skipped?: boolean;
  auto_run_skip_reason?: string;
  trigger?: "auto" | "manual" | string;
  cooldown_seconds?: number;
  last_error?: string | null;
  universe?: string;
  scanned_candidate_count?: number;
  ai_context_candidate_count?: number;
  ai_report?: {
    top_buy_candidates: AiDailyItem[];
    watch_for_pullback: AiDailyItem[];
    avoid_or_risk_elevated: AiDailyItem[];
    mstr_cycle_update: string;
    data_quality_warnings: string[];
    daily_summary: string;
  };
  read_only_research: boolean;
  broker_order_wiring_enabled: boolean;
};

type TradeReadinessGate = {
  status: "READY_FOR_MANUAL_REVIEW" | "REVIEW_ONLY" | "BLOCKED" | string;
  ready: boolean;
  market_regime: string;
  reasons: string[];
  required_checks: string[];
  risk_controls: string[];
  read_only_research: boolean;
};

type MarketRegimeComponent = {
  symbol: string;
  label: string;
  provider_status: string;
  source_type: string;
  freshness: string;
  candle_count: number;
  close?: number | null;
  ema50?: number | null;
  ema200?: number | null;
  return_20d_pct?: number;
};

type MarketRegimePayload = {
  as_of: string;
  source: string;
  regime: "RISK_ON" | "MIXED" | "RISK_OFF" | "DATA_CAUTION" | string;
  label: string;
  score: number;
  high_confidence_allowed: boolean;
  manual_rule: string;
  components: Record<string, MarketRegimeComponent>;
  provider_status: string;
  provider_error_count: number;
  provider_errors: string[];
  reasons: string[];
};

type MondayReadiness = {
  status: "READY" | "CAUTION" | "NO_TRADE";
  title: string;
  summary: string;
  checks: {
    label: string;
    value: string;
    ok: boolean;
    critical?: boolean;
  }[];
  reasons: string[];
  riskRules: string[];
};

type ManualTradeTicket = {
  status: "cleared_for_review" | "journal_required" | "blocked";
  title: string;
  summary: string;
  checks: {
    label: string;
    value: string;
    ok: boolean;
  }[];
  action: string;
  entryZone: string;
  stopZone: string;
  targetZone: string;
  riskReward: string;
  positionSizeHint: string;
  invalidatedIf: string[];
  reasons: string[];
};

type StockJournalEntry = {
  id: number;
  run_id: string;
  symbol: string;
  strategy_profile?: string;
  rule_conclusion?: string;
  ai_review_verdict?: string;
  status: string;
  notes: string;
  planned_entry?: number | null;
  planned_stop?: number | null;
  planned_target?: number | null;
  outcome: string;
  reviewed_at: string;
  read_only_research: boolean;
};

type StockJournalPayload = {
  product: string;
  symbol: string;
  entries: StockJournalEntry[];
  counts: Record<string, number>;
  summary: Record<string, number>;
  safety: {
    read_only_research: boolean;
    broker_order_wiring_enabled: boolean;
    account_access_enabled: boolean;
    llm_signal_core_enabled?: boolean;
  };
};

type SignalRun = {
  run_id: string;
  source: Source | string;
  universe: string;
  universe_total?: number;
  scanned_count?: number;
  downgraded_by_data_count?: number;
  provider_coverage?: {
    universe_total: number;
    scanned: number;
    available: number;
    stale_or_partial: number;
    failed: number;
    unscanned: number;
    coverage_pct: number;
  };
  profile: {
    name: string;
    label?: string;
    holding_period?: string;
    primary_timeframe?: string;
    confirmation_timeframe?: string;
    focus_window?: string;
    buy_setup_threshold: number;
    watch_threshold: number;
    direction: string;
  };
  provider_status: string;
  provider_error_count: number;
  provider_errors?: string[];
  trade_conclusion_counts?: Record<string, number>;
  market_regime?: MarketRegimePayload;
  review_counts?: { high_priority: number; watch: number; pass: number; downgraded: number };
  historical_validation?: {
    sample_count: number;
    win_rate_5d: number;
    target_hit_rate_5d: number;
    avg_forward_return_5d: number;
    avg_max_drawdown_5d: number;
  };
  counts: { buy_setup: number; watch: number; pass: number; total: number };
  signals: StockSignal[];
  llm_signal_core_enabled: boolean;
  broker_order_wiring_enabled: boolean;
};

type HealthTimeframe = {
  timeframe: string;
  provider_status: string;
  source_type: string;
  candle_count: number;
  expected_bars: number;
  count_ok: boolean;
  first_time: string;
  last_time: string;
  stale_age_seconds: number;
  provider_errors?: string[];
};

type HealthSymbol = {
  symbol: string;
  layer: string;
  provider_status: string;
  timeframes: HealthTimeframe[];
};

type HealthUniverse = {
  universe: string;
  symbol_count: number;
  provider_status: string;
  symbols: HealthSymbol[];
};

type LiveHealthPayload = {
  run_id: string;
  source: string;
  completed_at?: string;
  latest_cache_status?: string;
  fixture_user_visible: boolean;
  daily_usability?: { status: string; label: string; reason: string; failed_ratio: number };
  summary: {
    symbol_count: number;
    timeframe_checks: number;
    available_checks: number;
    stale_cache_checks: number;
    provider_error_checks: number;
    provider_status: string;
  };
  database?: {
    live_candle_count?: number;
    provider_event_count?: number;
    latest_candle_write?: string;
    tables_ready?: boolean;
  };
  universes_detail: HealthUniverse[];
};

type MstrCycleLevel = "CYCLE ACCUMULATION" | "BOTTOM WATCH" | "WAIT" | "DISTRIBUTION RISK";

type MstrComponent = {
  status: string;
  score: number;
  metrics?: Record<string, number>;
  reasons?: string[];
  risk_warnings?: string[];
  premium_to_btc_nav?: number | null;
  reason?: string;
};

type MonteCarloHorizon = {
  weeks: number;
  p10_return_pct: number;
  p50_return_pct: number;
  p90_return_pct: number;
  median_return_pct: number;
  p10_max_drawdown_pct: number;
  median_max_drawdown_pct: number;
  probability_2x_pct: number;
  probability_5x_pct: number;
  probability_10x_pct: number;
};

type MonteCarloPayload = {
  status: string;
  method: string;
  paths: number;
  beta_to_btc?: number;
  regime_adjustment_weekly_pct?: number;
  horizons: Record<string, MonteCarloHorizon>;
  reason?: string;
  limitations?: string[];
};

type BayesianEvidence = {
  name: string;
  likelihood_ratio: number;
  reason: string;
};

type BayesianBottomPayload = {
  status: string;
  method: string;
  prior_probability: number;
  bottom_probability: number;
  confidence: number;
  confidence_band: { low: number; high: number };
  positive_evidence: BayesianEvidence[];
  negative_evidence: BayesianEvidence[];
  does_not_override_level: boolean;
  limitations?: string[];
};

type CycleDashboardItem = {
  label: string;
  current: number | string;
  target: number | string;
  status: string;
  why: string;
};

type CycleUpgradeTrigger = {
  level: string;
  status: string;
  requirements: string[];
};

type TenXPath = {
  status: string;
  current_mstr_price?: number | null;
  target_mstr_price_10x?: number | null;
  current_btc_price?: number | null;
  current_premium_to_nav?: number | null;
  target_market_cap?: number | null;
  required_btc_prices: { premium_to_nav: number; required_btc_price?: number | null; btc_multiple_from_current?: number | null }[];
  monte_carlo_24m_probability_10x_pct?: number | null;
  monte_carlo_24m_p90_return_pct?: number | null;
  assumptions: string[];
};

type CycleDashboardPayload = {
  summary: string;
  wait_reasons: CycleDashboardItem[];
  upgrade_triggers: CycleUpgradeTrigger[];
  ten_x_path: TenXPath;
  review_bias: string;
  read_only: boolean;
  does_not_issue_trade_instruction: boolean;
  score_gaps: Record<string, number>;
};

type TriggerMonitorCondition = {
  level: string;
  name: string;
  current: number | string;
  target: number | string;
  comparator: string;
  met: boolean;
};

type TriggerMonitorPayload = {
  status: string;
  level: string;
  next_state: string;
  gaps: Record<string, number>;
  conditions: TriggerMonitorCondition[];
  read_only: boolean;
};

type PathStressRow = {
  dilution_rate_pct: number;
  premium_to_nav: number;
  required_btc_price?: number | null;
  btc_multiple_from_current?: number | null;
  adjusted_target_market_cap?: number | null;
};

type PathStressPayload = {
  status: string;
  question?: string;
  reason?: string;
  rows: PathStressRow[];
  assumptions?: string[];
  read_only: boolean;
};

type MstrMetricValue = string | number | boolean | null | undefined | string[];

type MstrMetricBlock = {
  status?: string;
  source_type?: string;
  calculation_method?: string;
  [key: string]: MstrMetricValue;
};

type MstrStrategyTrackerMetrics = {
  status: string;
  source_type?: string;
  tracker_provider_status: string;
  tracker_source?: string;
  freshness?: string;
  as_of_date?: string | null;
  calculation_policy?: string;
  availability?: Record<string, boolean>;
  missing_tracker_fields?: string[];
  treasury_snapshot?: MstrMetricBlock;
  premium_nav_metrics?: MstrMetricBlock;
  cost_basis_metrics?: MstrMetricBlock;
  btc_yield_metrics?: MstrMetricBlock;
  share_metrics?: MstrMetricBlock;
  debt_financing_metrics?: MstrMetricBlock;
  liquidity_metrics?: MstrMetricBlock;
  benchmark_metrics?: MstrMetricBlock;
};

type CycleHistorySummary = {
  run_count: number;
  latest_level: string;
  previous_level?: string;
  latest_completed_at?: string | null;
  first_completed_at?: string | null;
  latest_bottom_score?: number;
  score_change: number;
  latest_bottom_probability?: number;
  probability_change: number;
  latest_premium_to_nav?: number | null;
  latest_mc_24m_probability_10x?: number | null;
  trend: string;
};

type MstrJournalEntry = {
  id: number;
  run_id: string;
  status: string;
  notes: string;
  outcome: string;
  reviewed_at: string;
  level: string;
  bottom_score: number;
  bayesian_bottom_probability: number;
  manual_checklist?: TriggerMonitorCondition[];
};

type MstrJournalPayload = {
  status: string;
  limit: number;
  entries: MstrJournalEntry[];
  counts: Record<string, number>;
  read_only_research: boolean;
};

type MstrCyclePayload = {
  run_id: string;
  level: MstrCycleLevel;
  bottom_score: number;
  distribution_risk_score: number;
  provider_status: string;
  provider_error_count: number;
  provider_errors: string[];
  btc_reference_only: boolean;
  fixture_user_visible: boolean;
  llm_signal_core_enabled: boolean;
  broker_order_wiring_enabled: boolean;
  positioning_note: string;
  components: {
    btc_cycle: MstrComponent;
    mstr_bottom: MstrComponent;
    relative_btc: MstrComponent;
    premium_proxy: MstrComponent;
    financing_risk: MstrComponent;
    distribution_risk: MstrComponent;
  };
  monte_carlo: MonteCarloPayload;
  bayesian_bottom: BayesianBottomPayload;
  cycle_dashboard: CycleDashboardPayload;
  trigger_monitor: TriggerMonitorPayload;
  path_stress_test: PathStressPayload;
  strategy_tracker_metrics?: MstrStrategyTrackerMetrics;
  treasury_snapshot?: MstrMetricBlock;
  premium_nav_metrics?: MstrMetricBlock;
  cost_basis_metrics?: MstrMetricBlock;
  btc_yield_metrics?: MstrMetricBlock;
  share_metrics?: MstrMetricBlock;
  debt_financing_metrics?: MstrMetricBlock;
  liquidity_metrics?: MstrMetricBlock;
  benchmark_metrics?: MstrMetricBlock;
  tracker_provider_status?: string;
  cycle_history_summary: CycleHistorySummary;
  manual_journal?: MstrJournalPayload;
  scenario_horizon: string[];
  model_limitations: string[];
  reasons: string[];
  blockers: string[];
  manual_checklist: string[];
  charts: Record<string, Record<string, unknown>>;
};

type UniverseStock = {
  symbol: string;
  name: string;
  sector: string;
  layer: string;
  primary_layer?: string;
  tags: string[];
  aliases?: string[];
  match_score?: number;
  search_text?: string;
  rank: number;
  liquidity_tier?: string;
};

type OhlcState = {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
};

const copy = {
  en: {
    title: "KQUANT US Stock Signal Terminal",
    subtitle: "Long-only stock setups first. Options return later as expression tools.",
    stockView: "Stock Terminal",
    mstrView: "MSTR Cycle Radar",
    source: "Source",
    fixture: "Fixture",
    live: "Live",
    refresh: "Run Stock Scan",
    refreshMstr: "Refresh MSTR Radar",
    readOnly: "Read-only research",
    llmLocked: "AI-led / hard veto",
    db: "New DB",
    buySetups: "BUY SETUP",
    watch: "WATCH",
    pass: "PASS",
    provider: "Provider",
    universe: "Universe",
    historicalValidation: "Historical Validation",
    historicalEdge: "Historical Edge",
    winRate: "5D Win Rate",
    samples: "Samples",
    avgReturn: "Avg 5D Return",
    dataQuality: "Data Quality",
    today: "Today's Stock Setups",
    selected: "Selected Stock Review",
    daily: "Stock K-Line",
    hourly: "Confirmation K-Line",
    reasons: "Signal Reasons",
    risks: "Risk Warnings",
    checklist: "Manual Checklist",
    layers: "Market Layers",
    data: "Data Status",
    optionsLater: "Options module is parked until the stock signal is stable.",
    noBroker: "No broker, no account read, no paper/live/testnet order path.",
    dailyHint: "Daily trend: EMA20 / EMA50 / EMA200",
    hourlyHint: "1h confirmation: momentum and entry timing",
    ohlc: "Move crosshair over chart for OHLC",
    noCandles: "No live candles from the selected source.",
    chartSource: "Source",
    chartStatus: "Status",
    chartRange: "Range",
    candles: "Candles",
    firstLast: "First / Last",
    report: "Report",
    fallback: "API unavailable. No synthetic stock data is displayed.",
    apiReady: "Connected to local KQUANT API.",
    clean: "Clean",
    caution: "Caution",
    chinese: "中文",
    english: "EN",
    light: "Light",
    dark: "Dark",
    mstrCycleTitle: "MSTR Cycle Bottom Radar",
    mstrCycleSubtitle: "Cross-cycle MSTR accumulation research. BTC is reference-only; no BTC trading module is restored.",
    bottomScore: "Bottom Score",
    distributionRisk: "Distribution Risk",
    btcCycle: "BTC Cycle",
    mstrBottom: "MSTR Bottom",
    relativeBtc: "MSTR/BTC Relative",
    premiumProxy: "Premium Proxy",
    financingRisk: "Financing Risk",
    blockers: "Blockers",
    monteCarlo: "Monte Carlo Distribution",
    bayesianBottom: "Bayesian Bottom Probability",
    cycleDashboard: "Cycle Dashboard",
    whyWait: "Why Not Yet",
    upgradeTriggers: "Upgrade Triggers",
    tenXPath: "10x Path Map",
    modelLimitations: "Model Limitations",
    probability: "Probability",
    confidence: "Confidence",
    currentPage: "Current",
    systemStatus: "System",
    navigation: "Navigation",
    tradingSystem: "Trading System",
    universeControl: "Universe",
    actions: "Actions",
    preferences: "Preferences",
    todayNav: "Today",
    todaySub: "AI Signals",
    searchNav: "Search",
    searchSub: "Stocks",
    watchlistNav: "Watchlist",
    watchlistSub: "Universe",
    stockNav: "Stock",
    stockSub: "Detail",
    chartsNav: "Charts",
    chartsSub: "K-Line",
    aiPlanNav: "AI Plan",
    aiPlanSub: "Command",
    chatNav: "Chat",
    chatSub: "Deep Research",
    researchNav: "Research",
    researchSub: "Dossier",
    evidenceNav: "Evidence",
    evidenceSub: "Sources",
    reportsNav: "Reports",
    reportsSub: "Exports",
    mstrNav: "MSTR",
    mstrSub: "Radar",
    journalNav: "Journal",
    journalSub: "Notes",
    settingsNav: "Settings",
    settingsSub: "Safety",
    refreshStock: "Refresh Stock",
    refreshAiToday: "Refresh AI Today",
    searchPlaceholder: "Search NVDA, NVIDIA, robot, robotics, space, semiconductor...",
    analyze: "Analyze",
    loading: "Loading...",
    recent: "Recent",
    commandSearch: "Command Search",
    searchingUniverse: "Searching live universe...",
    close: "Close",
    searchOffline: "Search API offline. Local symbol index is still available.",
    noSearchMatch: "No match yet. Try ticker, company, layer, or Chinese theme.",
    analyzeFeedback: "Analyzing {symbol} with live candles and rule engine...",
    aiTradingCommand: "AI Trading Command",
    regenerateAiCommand: "Regenerate AI Command",
    aiCommandGenerating: "AI Command generating...",
    aiKeyRequired: "AI Key Required",
    aiModelNote: "AI synthesizes K-lines, score, regime, historical edge, research evidence, and hard veto.",
    aiUnavailableHint: "Missing backend OPENAI_API_KEY. Add it to the local server environment, never to frontend or GitHub.",
    aiReviewRequired: "AI Review Required: high-beta setups need smaller size, staged entry, volatility-aware stop, and no chasing.",
    aiSignalPlan: "AI Signal Plan",
    aiAction: "AI Action",
    hardVeto: "Hard Veto",
    entryZone: "Entry Zone",
    stopZone: "Stop Zone",
    targetZone: "Target Zone",
    riskReward: "Risk / Reward",
    sizeHint: "Size Hint",
    bestProfile: "Best Profile",
    whyNow: "Why Now",
    invalidation: "Invalidation",
    humanChecklist: "Human Checklist",
    ruleGuardrails: "Rule Guardrails",
    why: "Why",
    aiRequestFailed: "AI Agent request failed. Check local API and model configuration.",
    aiNotActive: "AI signal layer is not active yet. Configure OPENAI_API_KEY on the local backend, then restart the dashboard.",
    aiToday: "AI Today",
    aiResearchSignals: "AI Research Signals",
    aiTodayDescription: "AI ranks today's research opportunities for {universe} and turns them into entry, stop, target, risk/reward, and position-size plans. Hard guardrails still veto bad data, stale providers, and any order path.",
    aiUnavailableUntilKey: "AI unavailable until backend key is loaded",
    refreshAiSignals: "Refresh AI Signals",
    generating: "Generating...",
    status: "Status",
    autoAgent: "Auto Agent",
    freshness: "Freshness",
    model: "Model",
    candidates: "Candidates",
    readOnlyShort: "Read Only",
    noBrokerNoOrder: "no broker / no order",
    guarded: "guarded",
    topAiSignals: "Top AI Signals",
    noAiCandidate: "No hard-veto-clean AI buy candidate yet.",
    watchForPullback: "Watch for Pullback",
    noAiWatchlist: "No AI watchlist yet.",
    dataRiskWarnings: "Data / Risk Warnings",
    noWarnings: "No warnings loaded.",
    aiDailyFallback: "The dashboard checks the latest AI report on open and auto-runs once when stale and AI is available.",
    deepResearchChat: "Deep Research Chat",
    deepResearchSubtitle: "Ask the strongest configured model about this stock. The chat includes K-lines, AI command, rule guardrails, historical edge, and journal context.",
    researchModel: "Research Model",
    askResearchPlaceholder: "Ask about this setup, risks, better entry, K-line evidence, or what would change the AI view...",
    askResearch: "Ask",
    askingResearch: "Thinking...",
    researchChatUnavailable: "Deep research chat is unavailable until the backend AI key is loaded.",
    researchChatEmpty: "Ask a focused question to start deep research on the selected stock.",
    directView: "Direct View",
    keyPoints: "Key Points",
    whatToCheckNext: "What To Check Next",
    evidenceUsed: "Evidence Used",
    followUps: "Follow-up Questions",
    settingsTitle: "SaaS Readiness and Safety Boundary",
    settingsDescription: "KQUANT is moving toward a consumer AI research signal product. This page keeps the product boundary explicit before login, payments, and hosted infrastructure are added.",
    researchSignalOnly: "Research signal only",
    currentLocalMode: "Current Local Mode",
    futureSaasTarget: "Future SaaS Target",
    futureSaasCopy: "Vercel frontend + hosted Python API + Postgres. A public SaaS cannot depend on this PC's localhost backend.",
    paymentDisabled: "Payment hooks are intentionally not enabled yet.",
    dataSourceTitle: "Data Source",
    dataSourceCopy: "Prototype: Yahoo/public chart with stale real cache. Production must evaluate a formal market-data provider.",
    remoteApi: "Remote API",
    aiStatusTitle: "AI Status",
    aiStatusCopy: "AI can rank research opportunities and produce plans, but hard veto blocks bad data and all order paths.",
    consumerSafetyCopy: "Consumer Safety Copy",
    consumerSafetyText: "KQUANT provides AI research signals for manual review. It does not read brokerage accounts, submit orders, manage portfolios, or promise returns.",
    journalDesign: "Journal Design",
    journalDesignText: "Planned user journal states: watched, skipped, entered manually, exited manually. These are review records, not execution events.",
    mondayReadiness: "Monday Live Readiness",
    realMoneyPilot: "Small-size manual pilot only",
    readinessReady: "READY",
    readinessCaution: "CAUTION",
    readinessNoTrade: "NO TRADE",
    noRealMoneyTrade: "NO REAL-MONEY TRADE",
    manualTradeTicket: "Manual Trade Ticket",
    clearedForReview: "Cleared for manual review",
    journalRequired: "Journal required before any manual entry",
    ticketBlocked: "Blocked for real-money pilot",
    firstDayRiskRules: "First-day risk rules",
    maxRiskPerTrade: "Max risk per trade: 0.25% of account equity",
    maxTradesDay: "Day 1 maximum: 1-2 trades, total daily risk <= 0.5%",
    noOptionsNoLeverage: "Stocks only: no options, no leveraged ETFs, no automatic orders",
    noChasingNoAveraging: "No chasing, no averaging down, no trade during data caution",
    journalBeforeTrade: "Journal must be saved before any manual trade",
    mondayRunbook: "Monday runbook",
    runbookPremarket: "Premarket: start KQUANT, confirm READY, regenerate AI Daily report",
    runbookOpen: "Open: wait 15-30 minutes, inspect top AI candidates and pullback list",
    runbookEntry: "Before entry: confirm daily/1H K-lines, entry, stop, target, R:R, invalidation, journal",
    runbookClose: "After close: update journal and review whether AI/K-line evidence helped",
  },
  zh: {
    title: "KQUANT 美股 AI 交易研究台",
    subtitle: "AI 主动筛选美股机会，系统只读，不接券商，不自动下单。",
    stockView: "美股终端",
    mstrView: "MSTR 周期雷达",
    source: "数据源",
    fixture: "演示数据",
    live: "实时",
    refresh: "运行股票扫描",
    refreshMstr: "刷新 MSTR 雷达",
    readOnly: "只读研究",
    llmLocked: "AI 主导 / 硬风控",
    db: "新数据库",
    buySetups: "买入候选",
    watch: "观察",
    pass: "跳过",
    provider: "数据状态",
    universe: "股票池",
    historicalValidation: "历史验证",
    historicalEdge: "历史优势",
    winRate: "5日胜率",
    samples: "样本数",
    avgReturn: "5日平均收益",
    dataQuality: "数据质量",
    today: "今日股票信号",
    selected: "当前股票分析",
    daily: "股票 K 线",
    hourly: "确认 K 线",
    reasons: "信号理由",
    risks: "风险提示",
    checklist: "人工复核清单",
    layers: "市场分类",
    data: "数据状态",
    optionsLater: "期权模块暂时后置，等正股信号稳定后再接回。",
    noBroker: "无券商、无账户读取、无模拟/实盘/测试网下单路径。",
    dailyHint: "日线趋势：EMA20 / EMA50 / EMA200",
    hourlyHint: "1H 确认：动量与入场节奏",
    ohlc: "移动十字光标查看 OHLC",
    noCandles: "当前公开数据源没有返回实时 K 线。",
    chartSource: "来源",
    chartStatus: "状态",
    chartRange: "周期",
    candles: "K线数",
    firstLast: "首尾时间",
    report: "报告",
    fallback: "本地 API 不可用；不会显示合成假数据。",
    apiReady: "已连接本地 KQUANT API。",
    clean: "干净",
    caution: "谨慎",
    chinese: "中文",
    english: "EN",
    light: "浅色",
    dark: "深色",
    mstrCycleTitle: "MSTR 周期抄底雷达",
    mstrCycleSubtitle: "跨周期 MSTR 建仓研究。BTC 仅作为参考因子，不恢复 BTC 交易模块。",
    bottomScore: "底部评分",
    distributionRisk: "顶部/派发风险",
    btcCycle: "BTC 周期",
    mstrBottom: "MSTR 底部",
    relativeBtc: "MSTR/BTC 相对强弱",
    premiumProxy: "溢价代理",
    financingRisk: "融资风险",
    blockers: "阻断因素",
    monteCarlo: "蒙特卡洛分布",
    bayesianBottom: "贝叶斯底部概率",
    cycleDashboard: "周期仪表盘",
    whyWait: "为什么还不能买",
    upgradeTriggers: "升级触发条件",
    tenXPath: "10倍路径图",
    modelLimitations: "模型限制",
    probability: "概率",
    confidence: "置信度",
    currentPage: "当前",
    systemStatus: "系统状态",
    navigation: "导航",
    tradingSystem: "交易系统",
    universeControl: "股票池",
    actions: "操作",
    preferences: "偏好",
    todayNav: "今日",
    todaySub: "AI信号",
    searchNav: "搜索",
    searchSub: "股票",
    watchlistNav: "自选池",
    watchlistSub: "股票池",
    stockNav: "股票",
    stockSub: "详情",
    chartsNav: "图表",
    chartsSub: "K线",
    aiPlanNav: "AI计划",
    aiPlanSub: "交易指令",
    chatNav: "问答",
    chatSub: "深度研究",
    researchNav: "研究",
    researchSub: "档案",
    evidenceNav: "证据",
    evidenceSub: "材料",
    reportsNav: "报告",
    reportsSub: "导出",
    mstrNav: "MSTR",
    mstrSub: "雷达",
    journalNav: "复盘",
    journalSub: "笔记",
    settingsNav: "设置",
    settingsSub: "安全",
    refreshStock: "刷新当前股票",
    refreshAiToday: "刷新今日AI",
    searchPlaceholder: "搜索 NVDA、英伟达、机器人、太空、半导体...",
    analyze: "分析",
    loading: "加载中...",
    recent: "最近",
    commandSearch: "命令搜索",
    searchingUniverse: "正在搜索股票池...",
    close: "关闭",
    searchOffline: "搜索 API 离线，本地股票索引仍可使用。",
    noSearchMatch: "暂未匹配。可以输入 ticker、公司名、分类或中文主题。",
    analyzeFeedback: "正在用真实K线和规则引擎分析 {symbol}...",
    aiTradingCommand: "AI 交易指令",
    regenerateAiCommand: "重新生成 AI 指令",
    aiCommandGenerating: "AI 指令生成中...",
    aiKeyRequired: "需要 AI Key",
    aiModelNote: "AI 综合 K 线、分数、市场状态、历史优势、研究证据和硬风控。",
    aiUnavailableHint: "后端缺少 OPENAI_API_KEY。请只放在本地后端环境变量，不要放进前端或 GitHub。",
    aiReviewRequired: "需要 AI 复核：高波动交易必须小仓、分批、波动止损，不能追高。",
    aiSignalPlan: "AI 信号计划",
    aiAction: "AI 动作",
    hardVeto: "硬风控",
    entryZone: "入场区",
    stopZone: "止损区",
    targetZone: "目标区",
    riskReward: "盈亏比",
    sizeHint: "仓位提示",
    bestProfile: "最佳系统",
    whyNow: "为什么现在",
    invalidation: "失效条件",
    humanChecklist: "人工检查清单",
    ruleGuardrails: "规则风控",
    why: "原因",
    aiRequestFailed: "AI Agent 请求失败，请检查本地 API 和模型配置。",
    aiNotActive: "AI 信号层尚未启用。请在本地后端配置 OPENAI_API_KEY 后重启仪表盘。",
    aiToday: "今日 AI",
    aiResearchSignals: "AI 研究信号",
    aiTodayDescription: "AI 会为 {universe} 排序今日研究机会，并生成入场、止损、目标、盈亏比和仓位计划。坏数据、过期数据和任何下单路径仍会被硬风控否决。",
    aiUnavailableUntilKey: "后端 Key 加载前 AI 不可用",
    refreshAiSignals: "刷新 AI 信号",
    generating: "生成中...",
    status: "状态",
    autoAgent: "自动 Agent",
    freshness: "新鲜度",
    model: "模型",
    candidates: "候选数",
    readOnlyShort: "只读",
    noBrokerNoOrder: "无券商 / 无下单",
    guarded: "受保护",
    topAiSignals: "AI 顶级信号",
    noAiCandidate: "暂无通过硬风控的 AI 买入候选。",
    watchForPullback: "等待回踩",
    noAiWatchlist: "暂无 AI 观察名单。",
    dataRiskWarnings: "数据 / 风险警告",
    noWarnings: "暂无风险警告。",
    aiDailyFallback: "页面打开时会检查最新 AI 报告；当报告过期且 AI 可用时自动运行一次。",
    deepResearchChat: "深度研究问答",
    deepResearchSubtitle: "围绕当前股票向最强研究模型提问。上下文会自动包含 K线、AI 指令、规则风控、历史优势和复盘上下文。",
    researchModel: "研究模型",
    askResearchPlaceholder: "询问这个形态、风险、更好入场点、K线证据，或者什么条件会改变 AI 判断...",
    askResearch: "提问",
    askingResearch: "思考中...",
    researchChatUnavailable: "后端 AI Key 加载前，深度研究问答不可用。",
    researchChatEmpty: "输入一个具体问题，开始对当前股票做深度研究。",
    directView: "直接观点",
    keyPoints: "关键要点",
    whatToCheckNext: "下一步检查",
    evidenceUsed: "使用的证据",
    followUps: "可继续追问",
    settingsTitle: "SaaS 就绪度与安全边界",
    settingsDescription: "KQUANT 正在向 To C AI 研究信号产品演进。登录、支付和托管基础设施上线前，这里明确产品边界。",
    researchSignalOnly: "仅研究信号",
    currentLocalMode: "当前本地模式",
    futureSaasTarget: "未来 SaaS 目标",
    futureSaasCopy: "Vercel 前端 + 托管 Python API + Postgres。公开 SaaS 不能依赖这台电脑的 localhost 后端。",
    paymentDisabled: "支付入口目前刻意不启用。",
    dataSourceTitle: "数据源",
    dataSourceCopy: "原型阶段使用 Yahoo/public chart + 真实缓存。生产化必须评估正式行情源。",
    remoteApi: "远程 API",
    aiStatusTitle: "AI 状态",
    aiStatusCopy: "AI 可以排序研究机会并生成计划，但硬风控会阻断坏数据和所有下单路径。",
    consumerSafetyCopy: "消费者安全文案",
    consumerSafetyText: "KQUANT 提供用于人工复核的 AI 研究信号；不读取券商账户，不提交订单，不管理组合，也不承诺收益。",
    journalDesign: "复盘设计",
    journalDesignText: "计划中的用户复盘状态：已观察、跳过、手动进入、手动退出。这些是复盘记录，不是执行事件。",
    mondayReadiness: "周一实盘准备度",
    realMoneyPilot: "仅限小仓手工试运行",
    readinessReady: "READY",
    readinessCaution: "CAUTION",
    readinessNoTrade: "NO TRADE",
    noRealMoneyTrade: "禁止真钱交易",
    manualTradeTicket: "手工交易票据",
    clearedForReview: "可进入人工复核",
    journalRequired: "交易前必须写复盘",
    ticketBlocked: "实盘 Pilot 已阻断",
    firstDayRiskRules: "第一天风控规则",
    maxRiskPerTrade: "单笔最大风险：账户净值 0.25%",
    maxTradesDay: "第一天最多 1-2 笔，总日风险不超过 0.5%",
    noOptionsNoLeverage: "只做正股：不做期权、不做杠杆 ETF、不自动下单",
    noChasingNoAveraging: "不追高、不摊平，数据异常时不交易",
    journalBeforeTrade: "任何手工交易前必须保存 Journal",
    mondayRunbook: "周一执行流程",
    runbookPremarket: "开盘前：启动 KQUANT，确认 READY，重新生成 AI Daily 报告",
    runbookOpen: "开盘后：等待 15-30 分钟，只看 Top AI 和回踩观察名单",
    runbookEntry: "入场前：确认日线/1H、入场、止损、目标、盈亏比、失效条件和 Journal",
    runbookClose: "盘后：更新 Journal，复盘 AI 和 K 线证据是否有效",
  },
} as const;
const CHART_PRESETS: ChartPreset[] = [
  { key: "1h", label: "1H", range: "5d", interval: "1h" },
  { key: "1d", label: "1D", range: "1y", interval: "1d" },
  { key: "1w", label: "1W", range: "5y", interval: "1wk" },
  { key: "1m", label: "1M", range: "10y", interval: "1mo" },
];
const STRATEGY_PROFILES: { key: StrategyProfileName; label: string; period: string }[] = [
  { key: "tactical_1w_v1", label: "1W Tactical", period: "3-7D" },
  { key: "swing_1_2m_v1", label: "1-2M Swing", period: "20-40D" },
  { key: "position_6m_v1", label: "6M Position", period: "3-6M" },
  { key: "cycle_1_3y_v1", label: "1-3Y Cycle", period: "1-3Y" },
  { key: "high_beta_growth_v1", label: "High-Beta Growth", period: "3-15D" },
];
const API_BASE_URL = normalizeApiBase(String(import.meta.env.VITE_KQUANT_API_BASE_URL ?? ""));

const STOCKS: UniverseStock[] = [
  "SPY:SPDR S&P 500 ETF:ETF:Index ETFs",
  "QQQ:Invesco QQQ Trust:ETF:Index ETFs",
  "IWM:iShares Russell 2000 ETF:ETF:Index ETFs",
  "DIA:SPDR Dow Jones ETF:ETF:Index ETFs",
  "AAPL:Apple:Technology:Mega Cap Tech",
  "MSFT:Microsoft:Technology:AI Cloud",
  "NVDA:NVIDIA:Technology:AI Compute",
  "TSLA:Tesla:Consumer Discretionary:High Beta Growth",
  "AMZN:Amazon:Consumer Discretionary:AI Cloud",
  "META:Meta Platforms:Communication Services:AI Cloud",
  "GOOGL:Alphabet:Communication Services:AI Cloud",
  "AMD:Advanced Micro Devices:Technology:AI Compute",
  "AVGO:Broadcom:Technology:Semis / Foundry / Tools",
  "NFLX:Netflix:Communication Services:Consumer Internet",
  "COST:Costco:Consumer Staples:Defensive Growth",
  "JPM:JPMorgan Chase:Financials:Financials",
  "BAC:Bank of America:Financials:Financials",
  "WFC:Wells Fargo:Financials:Financials",
  "GS:Goldman Sachs:Financials:Financials",
  "MS:Morgan Stanley:Financials:Financials",
  "XOM:Exxon Mobil:Energy:Energy",
  "CVX:Chevron:Energy:Energy",
  "COP:ConocoPhillips:Energy:Energy",
  "UNH:UnitedHealth:Healthcare:Healthcare",
  "LLY:Eli Lilly:Healthcare:Healthcare",
  "MRK:Merck:Healthcare:Healthcare",
  "JNJ:Johnson & Johnson:Healthcare:Healthcare",
  "ABBV:AbbVie:Healthcare:Healthcare",
  "HD:Home Depot:Consumer Discretionary:Industrials / Consumer",
  "WMT:Walmart:Consumer Staples:Defensive Growth",
  "MCD:McDonald's:Consumer Discretionary:Industrials / Consumer",
  "NKE:Nike:Consumer Discretionary:Industrials / Consumer",
  "BA:Boeing:Industrials:Industrials / Consumer",
  "CAT:Caterpillar:Industrials:Industrials / Consumer",
  "GE:GE Aerospace:Industrials:Industrials / Consumer",
  "DIS:Disney:Communication Services:Consumer Internet",
  "T:AT&T:Communication Services:Defensive Value",
  "V:Visa:Financials:Payments",
  "MA:Mastercard:Financials:Payments",
  "CRM:Salesforce:Technology:AI Software / Data",
  "ORCL:Oracle:Technology:AI Cloud",
  "ADBE:Adobe:Technology:AI Software / Data",
  "INTC:Intel:Technology:Semis / Foundry / Tools",
  "MU:Micron:Technology:Semis / Foundry / Tools",
  "QCOM:Qualcomm:Technology:Semis / Foundry / Tools",
  "SMCI:Super Micro Computer:Technology:AI Compute",
  "PLTR:Palantir:Technology:AI Software / Data",
  "COIN:Coinbase:Financials:Crypto / Fintech Beta",
  "SHOP:Shopify:Technology:AI Software / Data",
  "UBER:Uber:Industrials:AI Software / Data",
  "ARM:Arm Holdings:Technology:AI Compute",
  "MRVL:Marvell:Technology:AI Semis",
  "TSM:Taiwan Semiconductor:Technology:Semis / Foundry / Tools",
  "ASML:ASML:Technology:Semis / Foundry / Tools",
  "ANET:Arista Networks:Technology:AI Infra",
  "DELL:Dell Technologies:Technology:AI Infra",
  "NOW:ServiceNow:Technology:AI Software / Data",
  "SNOW:Snowflake:Technology:AI Software / Data",
  "DDOG:Datadog:Technology:AI Infra",
  "MDB:MongoDB:Technology:AI Software / Data",
  "CRWD:CrowdStrike:Technology:AI Security",
  "PANW:Palo Alto Networks:Technology:AI Security",
  "NET:Cloudflare:Technology:AI Infra",
  "AI:C3.ai:Technology:AI Software / Data",
  "PATH:UiPath:Technology:AI Software / Data",
  "IBM:IBM:Technology:AI Cloud",
  "TXN:Texas Instruments:Technology:Semis / Foundry / Tools",
  "AMAT:Applied Materials:Technology:Semis / Foundry / Tools",
  "LRCX:Lam Research:Technology:Semis / Foundry / Tools",
  "KLAC:KLA:Technology:Semis / Foundry / Tools",
  "ADI:Analog Devices:Technology:Semis / Foundry / Tools",
  "MSTR:MicroStrategy:Technology:Crypto / Fintech Beta",
  "HOOD:Robinhood:Financials:Crypto / Fintech Beta",
  "PYPL:PayPal:Financials:Payments",
  "SQ:Block:Financials:Crypto / Fintech Beta",
  "AXP:American Express:Financials:Financials",
  "BLK:BlackRock:Financials:Financials",
  "SCHW:Charles Schwab:Financials:Financials",
  "C:Citigroup:Financials:Financials",
  "PFE:Pfizer:Healthcare:Healthcare",
  "TMO:Thermo Fisher:Healthcare:Healthcare",
  "ISRG:Intuitive Surgical:Healthcare:Healthcare",
  "ABT:Abbott Laboratories:Healthcare:Healthcare",
  "PEP:PepsiCo:Consumer Staples:Defensive Growth",
  "KO:Coca-Cola:Consumer Staples:Defensive Growth",
  "PG:Procter & Gamble:Consumer Staples:Defensive Growth",
  "LOW:Lowe's:Consumer Discretionary:Industrials / Consumer",
  "SBUX:Starbucks:Consumer Discretionary:Industrials / Consumer",
  "GM:General Motors:Consumer Discretionary:High Beta Growth",
  "F:Ford:Consumer Discretionary:High Beta Growth",
  "RIVN:Rivian:Consumer Discretionary:High Beta Growth",
  "LULU:Lululemon:Consumer Discretionary:Industrials / Consumer",
  "XLE:Energy Select Sector SPDR:ETF:Energy",
  "XLK:Technology Select Sector SPDR:ETF:Index ETFs",
  "SMH:VanEck Semiconductor ETF:ETF:AI Semis",
  "SOXX:iShares Semiconductor ETF:ETF:AI Semis",
  "ARKK:ARK Innovation ETF:ETF:High Beta Growth",
  "TLT:iShares 20+ Year Treasury ETF:ETF:Macro ETFs",
  "GLD:SPDR Gold Shares:ETF:Macro ETFs",
  "USO:United States Oil Fund:ETF:Energy",
  "CEG:Constellation Energy:Utilities:Energy",
  "VST:Vistra:Utilities:Energy",
  "NRG:NRG Energy:Utilities:Energy",
  "NEE:NextEra Energy:Utilities:Energy",
  "SO:Southern Company:Utilities:Energy",
  "DUK:Duke Energy:Utilities:Energy",
  "GEV:GE Vernova:Industrials:Energy",
  "ETN:Eaton:Industrials:Energy",
  "PWR:Quanta Services:Industrials:Energy",
  "VRT:Vertiv:Industrials:Energy",
  "CARR:Carrier Global:Industrials:Energy",
  "CCJ:Cameco:Energy:Energy",
  "CSCO:Cisco:Technology:Infrastructure",
  "HPE:Hewlett Packard Enterprise:Technology:Infrastructure",
  "EQIX:Equinix:Real Estate:Infrastructure",
  "DLR:Digital Realty:Real Estate:Infrastructure",
  "MCHP:Microchip Technology:Technology:Chips",
  "MPWR:Monolithic Power Systems:Technology:Chips",
  "ON:ON Semiconductor:Technology:Chips",
  "APP:AppLovin:Technology:Applications",
  "DUOL:Duolingo:Communication Services:Applications",
  "KKR:KKR:Financials:Financials",
  "BX:Blackstone:Financials:Financials",
  "APO:Apollo Global Management:Financials:Financials",
  "ICE:Intercontinental Exchange:Financials:Financials",
  "CME:CME Group:Financials:Financials",
  "MSCI:MSCI:Financials:Financials",
  "SPGI:S&P Global:Financials:Financials",
  "MCO:Moody's:Financials:Financials",
  "CB:Chubb:Financials:Financials",
  "PGR:Progressive:Financials:Financials",
  "TRV:Travelers:Financials:Financials",
  "AFL:Aflac:Financials:Financials",
  "AMGN:Amgen:Healthcare:Healthcare",
  "GILD:Gilead Sciences:Healthcare:Healthcare",
  "REGN:Regeneron:Healthcare:Healthcare",
  "VRTX:Vertex Pharmaceuticals:Healthcare:Healthcare",
  "DHR:Danaher:Healthcare:Healthcare",
  "SYK:Stryker:Healthcare:Healthcare",
  "BSX:Boston Scientific:Healthcare:Healthcare",
  "MDT:Medtronic:Healthcare:Healthcare",
  "ELV:Elevance Health:Healthcare:Healthcare",
  "CI:Cigna:Healthcare:Healthcare",
  "CVS:CVS Health:Healthcare:Healthcare",
  "MELI:MercadoLibre:Consumer Discretionary:Consumer Internet",
  "ABNB:Airbnb:Consumer Discretionary:Consumer Internet",
  "MAR:Marriott International:Consumer Discretionary:Industrials / Consumer",
  "BKNG:Booking Holdings:Consumer Discretionary:Consumer Internet",
  "DASH:DoorDash:Consumer Discretionary:Consumer Internet",
  "CMG:Chipotle Mexican Grill:Consumer Discretionary:Industrials / Consumer",
  "ORLY:O'Reilly Automotive:Consumer Discretionary:Industrials / Consumer",
  "AZO:AutoZone:Consumer Discretionary:Industrials / Consumer",
  "ROST:Ross Stores:Consumer Discretionary:Industrials / Consumer",
  "TJX:TJX Companies:Consumer Discretionary:Industrials / Consumer",
  "RTX:RTX:Industrials:Industrials / Consumer",
  "LMT:Lockheed Martin:Industrials:Industrials / Consumer",
  "NOC:Northrop Grumman:Industrials:Industrials / Consumer",
  "GD:General Dynamics:Industrials:Industrials / Consumer",
  "HON:Honeywell:Industrials:Industrials / Consumer",
  "MMM:3M:Industrials:Industrials / Consumer",
  "DE:Deere:Industrials:Industrials / Consumer",
  "UPS:UPS:Industrials:Industrials / Consumer",
  "FDX:FedEx:Industrials:Industrials / Consumer",
  "WM:Waste Management:Industrials:Industrials / Consumer",
  "LIN:Linde:Materials:Industrials / Consumer",
  "TEAM:Atlassian:Technology:AI Software / Data",
  "WDAY:Workday:Technology:AI Software / Data",
  "ZS:Zscaler:Technology:AI Security",
  "OKTA:Okta:Technology:AI Security",
  "FTNT:Fortinet:Technology:AI Security",
  "AKAM:Akamai:Technology:AI Infra",
  "CDNS:Cadence Design Systems:Technology:Semis / Foundry / Tools",
  "SNPS:Synopsys:Technology:Semis / Foundry / Tools",
  "ADSK:Autodesk:Technology:AI Software / Data",
  "INTU:Intuit:Technology:AI Software / Data",
  "XLF:Financial Select Sector SPDR:ETF:Financials",
  "XLI:Industrial Select Sector SPDR:ETF:Industrials / Consumer",
  "XLY:Consumer Discretionary Select Sector SPDR:ETF:Industrials / Consumer",
  "XLV:Health Care Select Sector SPDR:ETF:Healthcare",
  "XLU:Utilities Select Sector SPDR:ETF:Energy",
  "XLP:Consumer Staples Select Sector SPDR:ETF:Defensive Growth",
  "XLRE:Real Estate Select Sector SPDR:ETF:Macro ETFs",
  "XLC:Communication Services Select Sector SPDR:ETF:Consumer Internet",
  "XBI:SPDR S&P Biotech ETF:ETF:Healthcare",
  "IBB:iShares Biotechnology ETF:ETF:Healthcare",
  "KRE:SPDR S&P Regional Banking ETF:ETF:Financials",
  "XRT:SPDR S&P Retail ETF:ETF:Industrials / Consumer",
  "FCX:Freeport-McMoRan:Materials:Energy",
  "NUE:Nucor:Materials:Industrials / Consumer",
  "STLD:Steel Dynamics:Materials:Industrials / Consumer",
  "CLF:Cleveland-Cliffs:Materials:High Beta Growth",
  "ALB:Albemarle:Materials:High Beta Growth",
  "FSLR:First Solar:Technology:Energy",
  "ENPH:Enphase Energy:Technology:High Beta Growth",
  "ROK:Rockwell Automation:Industrials:Industrials / Consumer",
  "TTD:The Trade Desk:Technology:AI Software / Data",
  "RDDT:Reddit:Communication Services:Consumer Internet",
  "PINS:Pinterest:Communication Services:Consumer Internet",
  "SE:Sea Limited:Communication Services:Consumer Internet",
  "TGT:Target:Consumer Staples:Defensive Growth",
  "RKLB:Rocket Lab:Industrials:Space / Robotics",
  "ASTS:AST SpaceMobile:Communication Services:Space / Robotics",
  "LUNR:Intuitive Machines:Industrials:Space / Robotics",
  "PL:Planet Labs:Industrials:Space / Robotics",
  "IRDM:Iridium Communications:Communication Services:Space / Robotics",
  "KTOS:Kratos Defense & Security:Industrials:Space / Robotics",
  "LHX:L3Harris Technologies:Industrials:Space / Robotics",
  "LDOS:Leidos:Industrials:Space / Robotics",
  "TDY:Teledyne Technologies:Industrials:Space / Robotics",
  "HEI:HEICO:Industrials:Space / Robotics",
  "ACHR:Archer Aviation:Industrials:Space / Robotics",
  "JOBY:Joby Aviation:Industrials:Space / Robotics",
  "SYM:Symbotic:Industrials:Space / Robotics",
  "SERV:Serve Robotics:Industrials:Space / Robotics",
  "TER:Teradyne:Technology:Space / Robotics",
  "ZBRA:Zebra Technologies:Technology:Space / Robotics",
  "CGNX:Cognex:Technology:Space / Robotics",
  "AMBA:Ambarella:Technology:Space / Robotics",
  "ARBE:Arbe Robotics:Technology:Space / Robotics",
  "OUST:Ouster:Technology:Space / Robotics",
  "MBLY:Mobileye:Technology:Space / Robotics",
  "BOTZ:Global X Robotics & AI ETF:ETF:Space / Robotics",
  "ROBO:ROBO Global Robotics ETF:ETF:Space / Robotics",
  "ARKQ:ARK Autonomous Technology ETF:ETF:Space / Robotics",
  "ITA:iShares U.S. Aerospace & Defense ETF:ETF:Space / Robotics",
  "XAR:SPDR S&P Aerospace & Defense ETF:ETF:Space / Robotics",
  "UFO:Procure Space ETF:ETF:Space / Robotics",
].map(parseStockRow);

const AI_FIVE_LAYER_STOCKS: UniverseStock[] = [
  "CEG:Constellation Energy:Utilities:Energy",
  "VST:Vistra:Utilities:Energy",
  "NRG:NRG Energy:Utilities:Energy",
  "NEE:NextEra Energy:Utilities:Energy",
  "SO:Southern Company:Utilities:Energy",
  "DUK:Duke Energy:Utilities:Energy",
  "GEV:GE Vernova:Industrials:Energy",
  "ETN:Eaton:Industrials:Energy",
  "PWR:Quanta Services:Industrials:Energy",
  "VRT:Vertiv:Industrials:Energy",
  "CARR:Carrier Global:Industrials:Energy",
  "CCJ:Cameco:Energy:Energy",
  "NVDA:NVIDIA:Technology:Chips",
  "AMD:Advanced Micro Devices:Technology:Chips",
  "AVGO:Broadcom:Technology:Chips",
  "QCOM:Qualcomm:Technology:Chips",
  "MRVL:Marvell:Technology:Chips",
  "ARM:Arm Holdings:Technology:Chips",
  "INTC:Intel:Technology:Chips",
  "MU:Micron:Technology:Chips",
  "TSM:Taiwan Semiconductor:Technology:Chips",
  "ASML:ASML:Technology:Chips",
  "AMAT:Applied Materials:Technology:Chips",
  "LRCX:Lam Research:Technology:Chips",
  "KLAC:KLA:Technology:Chips",
  "TXN:Texas Instruments:Technology:Chips",
  "ADI:Analog Devices:Technology:Chips",
  "MCHP:Microchip Technology:Technology:Chips",
  "MPWR:Monolithic Power Systems:Technology:Chips",
  "ON:ON Semiconductor:Technology:Chips",
  "NVTS:Navitas Semiconductor:Technology:Chips",
  "SNDK:SanDisk:Technology:Chips",
  "WDC:Western Digital:Technology:Chips",
  "STX:Seagate Technology:Technology:Chips",
  "AMBA:Ambarella:Technology:Chips",
  "ACLS:Axcelis Technologies:Technology:Chips",
  "SMH:VanEck Semiconductor ETF:ETF:Chips",
  "SOXX:iShares Semiconductor ETF:ETF:Chips",
  "MSFT:Microsoft:Technology:Infrastructure",
  "AMZN:Amazon:Consumer Discretionary:Infrastructure",
  "GOOGL:Alphabet:Communication Services:Infrastructure",
  "META:Meta Platforms:Communication Services:Infrastructure",
  "ORCL:Oracle:Technology:Infrastructure",
  "IBM:IBM:Technology:Infrastructure",
  "ANET:Arista Networks:Technology:Infrastructure",
  "CSCO:Cisco:Technology:Infrastructure",
  "DELL:Dell Technologies:Technology:Infrastructure",
  "HPE:Hewlett Packard Enterprise:Technology:Infrastructure",
  "SMCI:Super Micro Computer:Technology:Infrastructure",
  "EQIX:Equinix:Real Estate:Infrastructure",
  "DLR:Digital Realty:Real Estate:Infrastructure",
  "COHR:Coherent:Technology:Infrastructure",
  "LITE:Lumentum:Technology:Infrastructure",
  "FN:Fabrinet:Technology:Infrastructure",
  "ALAB:Astera Labs:Technology:Infrastructure",
  "CRDO:Credo Technology:Technology:Infrastructure",
  "CLS:Celestica:Technology:Infrastructure",
  "JBL:Jabil:Technology:Infrastructure",
  "FLEX:Flex:Technology:Infrastructure",
  "IREN:IREN:Technology:Infrastructure",
  "NBIS:Nebius Group:Technology:Infrastructure",
  "CORZ:Core Scientific:Technology:Infrastructure",
  "NET:Cloudflare:Technology:Infrastructure",
  "DDOG:Datadog:Technology:Infrastructure",
  "PLTR:Palantir:Technology:Models",
  "SNOW:Snowflake:Technology:Models",
  "MDB:MongoDB:Technology:Models",
  "AI:C3.ai:Technology:Models",
  "CRM:Salesforce:Technology:Applications",
  "NOW:ServiceNow:Technology:Applications",
  "ADBE:Adobe:Technology:Applications",
  "CRWD:CrowdStrike:Technology:Applications",
  "PANW:Palo Alto Networks:Technology:Applications",
  "PATH:UiPath:Technology:Applications",
  "UBER:Uber:Industrials:Applications",
  "TSLA:Tesla:Consumer Discretionary:Applications",
  "ISRG:Intuitive Surgical:Healthcare:Applications",
  "APP:AppLovin:Technology:Applications",
  "DUOL:Duolingo:Communication Services:Applications",
  "SHOP:Shopify:Technology:Applications",
].map(parseStockRow);

const PHYSICAL_AI_STOCKS: UniverseStock[] = [
  "ROK:Rockwell Automation:Industrials:Embodied AI Components",
  "TER:Teradyne:Technology:Embodied AI Components",
  "SYM:Symbotic:Industrials:Embodied AI Components",
  "ISRG:Intuitive Surgical:Healthcare:Embodied AI Components",
  "ZBRA:Zebra Technologies:Technology:Embodied AI Components",
  "CGNX:Cognex:Technology:Embodied AI Components",
  "SERV:Serve Robotics:Industrials:Embodied AI Components",
  "TRMB:Trimble:Technology:Embodied AI Components",
  "KEYS:Keysight Technologies:Technology:Embodied AI Components",
  "ADI:Analog Devices:Technology:Embodied AI Components",
  "ON:ON Semiconductor:Technology:Embodied AI Components",
  "MPWR:Monolithic Power Systems:Technology:Embodied AI Components",
  "BOTZ:Global X Robotics & AI ETF:ETF:Embodied AI Components",
  "ROBO:ROBO Global Robotics ETF:ETF:Embodied AI Components",
  "AVAV:AeroVironment:Industrials:Drones / Low Altitude",
  "KTOS:Kratos Defense & Security:Industrials:Drones / Low Altitude",
  "RCAT:Red Cat Holdings:Technology:Drones / Low Altitude",
  "ONDS:Ondas Holdings:Technology:Drones / Low Altitude",
  "UMAC:Unusual Machines:Technology:Drones / Low Altitude",
  "EH:EHang:Industrials:Drones / Low Altitude",
  "ACHR:Archer Aviation:Industrials:Drones / Low Altitude",
  "JOBY:Joby Aviation:Industrials:Drones / Low Altitude",
  "TXT:Textron:Industrials:Drones / Low Altitude",
  "LHX:L3Harris Technologies:Industrials:Drones / Low Altitude",
  "LDOS:Leidos:Industrials:Drones / Low Altitude",
  "ITA:iShares U.S. Aerospace & Defense ETF:ETF:Drones / Low Altitude",
  "XAR:SPDR S&P Aerospace & Defense ETF:ETF:Drones / Low Altitude",
  "AAPL:Apple:Technology:Spatial Computing",
  "META:Meta Platforms:Communication Services:Spatial Computing",
  "SNAP:Snap:Communication Services:Spatial Computing",
  "VUZI:Vuzix:Technology:Spatial Computing",
  "KOPN:Kopin:Technology:Spatial Computing",
  "MVIS:MicroVision:Technology:Spatial Computing",
  "LAZR:Luminar:Technology:Spatial Computing",
  "OUST:Ouster:Technology:Spatial Computing",
  "HSAI:Hesai Group:Technology:Spatial Computing",
  "AEVA:Aeva Technologies:Technology:Spatial Computing",
  "MBLY:Mobileye:Technology:Spatial Computing",
  "AMBA:Ambarella:Technology:Spatial Computing",
  "COHR:Coherent:Technology:Spatial Computing",
  "LITE:Lumentum:Technology:Spatial Computing",
  "RKLB:Rocket Lab:Industrials:Space Exploration",
  "ASTS:AST SpaceMobile:Communication Services:Space Exploration",
  "LUNR:Intuitive Machines:Industrials:Space Exploration",
  "PL:Planet Labs:Industrials:Space Exploration",
  "IRDM:Iridium Communications:Communication Services:Space Exploration",
  "SPIR:Spire Global:Industrials:Space Exploration",
  "BKSY:BlackSky Technology:Industrials:Space Exploration",
  "RDW:Redwire:Industrials:Space Exploration",
  "GSAT:Globalstar:Communication Services:Space Exploration",
  "SATL:Satellogic:Industrials:Space Exploration",
  "BA:Boeing:Industrials:Space Exploration",
  "LMT:Lockheed Martin:Industrials:Space Exploration",
  "NOC:Northrop Grumman:Industrials:Space Exploration",
  "RTX:RTX:Industrials:Space Exploration",
  "GD:General Dynamics:Industrials:Space Exploration",
  "KTOS:Kratos Defense & Security:Industrials:Space Exploration",
  "UFO:Procure Space ETF:ETF:Space Exploration",
  "ARKX:ARK Space Exploration ETF:ETF:Space Exploration",
].map(parseStockRow);

const ALL_STOCKS = uniqueStocks([...STOCKS, ...AI_FIVE_LAYER_STOCKS, ...PHYSICAL_AI_STOCKS]);

const SEARCH_QUERY_ALIASES: Record<string, string[]> = {
  英伟达: ["nvda", "nvidia", "gpu", "accelerator", "chips"],
  微软: ["msft", "microsoft", "azure", "cloud"],
  谷歌: ["googl", "google", "alphabet", "search"],
  亚马逊: ["amzn", "amazon", "aws", "cloud"],
  特斯拉: ["tsla", "tesla", "robotics", "autonomy"],
  机器人: ["robot", "robotics", "automation", "autonomy", "space robotics"],
  具身智能: ["embodied", "robotics", "automation", "sensors", "machine vision", "motor control"],
  人形机器人: ["humanoid", "robotics", "automation", "embodied", "sensors"],
  减速器: ["robotics", "automation", "motor control", "industrial automation"],
  传感器: ["sensors", "machine vision", "lidar", "3d sensing", "analog semis"],
  无人机: ["drones", "unmanned systems", "low altitude", "defense tech", "evtol"],
  低空经济: ["drones", "evtol", "low altitude", "autonomous aircraft", "aviation"],
  太空: ["space", "rocket", "satellite", "aerospace", "space robotics"],
  航天: ["space", "rocket", "satellite", "aerospace", "space robotics"],
  太空探索: ["space", "space exploration", "launch", "satellite", "lunar"],
  卫星星座: ["satellite", "space", "satellite network", "direct to device", "earth observation"],
  空间计算: ["spatial computing", "ar", "vr", "mixed reality", "lidar", "3d sensing"],
  激光雷达: ["lidar", "3d sensing", "4d sensing", "spatial computing", "autonomy"],
  火箭: ["space", "rocket", "rklb", "aerospace"],
  卫星: ["satellite", "space", "asts", "irdm"],
  芯片: ["chips", "semis", "semiconductor", "ai semis"],
  半导体: ["chips", "semis", "semiconductor", "ai semis"],
  存储: ["storage", "memory", "nand", "hdd", "ai storage", "sndk", "wdc", "stx", "mu"],
  内存: ["memory", "hbm", "storage", "mu", "sndk"],
  光模块: ["optical", "photonics", "datacenter interconnect", "ai networking", "cohr", "fn", "lite", "crdo"],
  光互联: ["optical", "photonics", "datacenter interconnect", "ai networking", "cohr", "fn", "lite", "crdo"],
  硅光: ["optical", "photonics", "cohr", "lite"],
  gpu云: ["neocloud", "gpu cloud", "ai datacenter", "iren", "nbis", "corz"],
  "gpu 云": ["neocloud", "gpu cloud", "ai datacenter", "iren", "nbis", "corz"],
  新云: ["neocloud", "gpu cloud", "ai datacenter", "iren", "nbis", "corz"],
  电源半导体: ["power semis", "gan", "sic", "ai power", "nvts", "mpwr", "on"],
  氮化镓: ["gan", "power semis", "ai power", "nvts"],
  能源: ["energy", "power", "nuclear", "grid"],
  核电: ["nuclear", "uranium", "power", "ai energy"],
  比特币: ["bitcoin", "btc", "crypto", "mstr", "coin"],
};

const STOCK_SEARCH_ALIASES: Record<string, string[]> = {
  NVDA: ["英伟达", "gpu", "accelerator"],
  MSFT: ["微软", "azure"],
  GOOGL: ["谷歌", "google", "gemini"],
  AMZN: ["亚马逊", "aws"],
  TSLA: ["特斯拉", "robotaxi", "autonomy"],
  MSTR: ["microstrategy", "strategy", "比特币", "bitcoin", "btc"],
  RKLB: ["rocket lab", "火箭", "太空", "space"],
  ASTS: ["satellite", "space mobile", "太空", "卫星"],
  LUNR: ["moon", "lunar", "space", "太空"],
  BOTZ: ["robotics etf", "机器人", "automation"],
  ROBO: ["robotics etf", "机器人", "automation"],
  ISRG: ["surgical robot", "机器人", "robotics"],
  SYM: ["warehouse robot", "机器人", "automation"],
  AVAV: ["aerovironment", "无人机", "drones", "unmanned systems"],
  RCAT: ["red cat", "无人机", "drones", "teal drones"],
  ONDS: ["ondas", "无人机", "autonomous systems", "drones"],
  UMAC: ["unusual machines", "无人机", "drone components"],
  EH: ["ehang", "低空经济", "evtol", "autonomous aircraft"],
  TRMB: ["trimble", "传感器", "positioning", "industrial automation"],
  KEYS: ["keysight", "传感器", "test equipment", "robotics"],
  SNAP: ["snap", "空间计算", "ar glasses", "augmented reality"],
  VUZI: ["vuzix", "空间计算", "ar glasses"],
  KOPN: ["kopin", "空间计算", "microdisplays", "ar vr"],
  MVIS: ["microvision", "激光雷达", "lidar", "3d sensing"],
  LAZR: ["luminar", "激光雷达", "lidar", "autonomy"],
  HSAI: ["hesai", "激光雷达", "lidar", "3d sensing"],
  AEVA: ["aeva", "激光雷达", "4d lidar", "sensing"],
  SPIR: ["spire global", "太空探索", "satellite data"],
  BKSY: ["blacksky", "太空探索", "satellite imagery"],
  RDW: ["redwire", "太空探索", "space infrastructure"],
  GSAT: ["globalstar", "卫星星座", "satellite network"],
  SATL: ["satellogic", "太空探索", "earth observation"],
  ARKX: ["space exploration etf", "太空探索", "space etf"],
  SNDK: ["sandisk", "存储", "nand", "ai storage"],
  MU: ["micron", "内存", "存储", "hbm"],
  IREN: ["gpu cloud", "neocloud", "gpu云", "新云", "ai datacenter"],
  NVTS: ["navitas", "电源半导体", "氮化镓", "gan", "sic"],
  COHR: ["coherent", "光模块", "光互联", "silicon photonics", "optical"],
  FN: ["fabrinet", "光模块", "optical manufacturing"],
  LITE: ["lumentum", "光模块", "光互联", "photonics"],
  ALAB: ["astera labs", "ai connectivity", "pcie", "datacenter"],
  CRDO: ["credo", "ai networking", "serdes", "datacenter"],
  NBIS: ["nebius", "gpu cloud", "neocloud", "gpu云"],
  CORZ: ["core scientific", "neocloud", "ai datacenter"],
  SERV: ["serve robotics", "机器人", "delivery robotics", "autonomy"],
  AMBA: ["ambarella", "edge ai", "computer vision", "autonomy"],
};

const SEARCH_SHORTCUTS = [
  { label: "NVDA", query: "NVDA", symbol: "NVDA" },
  { label: "MSTR", query: "MSTR", symbol: "MSTR" },
  { label: "AI Chips", query: "半导体" },
  { label: "AI Infra", query: "gpu云" },
  { label: "Storage", query: "存储" },
  { label: "Optical", query: "光模块" },
  { label: "Physical AI", query: "具身智能" },
  { label: "Drones", query: "无人机" },
  { label: "Spatial", query: "空间计算" },
  { label: "Space", query: "太空" },
  { label: "Robotics", query: "机器人" },
  { label: "Mag 7", query: "mega cap tech" },
  { label: "High Beta", query: "high_beta" },
] as const;

function initialLanguage(): Lang {
  if (typeof navigator !== "undefined" && navigator.language.toLowerCase().startsWith("zh")) {
    return "zh";
  }
  return "en";
}

function aiDecisionCacheKey(signal: StockSignal, profile: StrategyProfileName): string {
  const dataStamp = [
    signal.symbol,
    profile,
    signal.score,
    signal.level,
    signal.features?.close ?? "-",
    signal.data_status?.source ?? "-",
    signal.data_status?.freshness ?? "-",
    signal.data_status?.daily_candles ?? 0,
    signal.data_status?.hourly_candles ?? 0,
  ].join(":");
  return dataStamp;
}

function App() {
  const [lang, setLang] = useStoredState<Lang>("kquant-stock:lang", initialLanguage());
  const [theme, setTheme] = useStoredState<Theme>("kquant-stock:theme", "light");
  const [view, setView] = useStoredState<AppView>("kquant-stock:view:v1", "stocks");
  const source: Source = "live";
  const [selectedUniverse, setSelectedUniverse] = useStoredState<UniverseName>("kquant-stock:universe:v2", "default");
  const [selectedProfile, setSelectedProfile] = useStoredState<StrategyProfileName>("kquant-stock:strategy-profile:v1", "tactical_1w_v1");
  const [primaryPresetKey, setPrimaryPresetKey] = useStoredState<ChartPresetKey>("kquant-stock:primary-preset:v2", "1d");
  const [confirmationPresetKey, setConfirmationPresetKey] = useStoredState<ChartPresetKey>("kquant-stock:confirmation-preset:v2", "1h");
  const [run, setRun] = useState<SignalRun>(() => makeUnavailableSignalRun(selectedUniverse));
  const [universe, setUniverse] = useState<UniverseStock[]>(() => stocksForUniverse(selectedUniverse));
  const [selectedSymbol, setSelectedSymbol] = useStoredState<string>("kquant-stock:selected", "NVDA");
  const [searchText, setSearchText] = useState("");
  const [recentSearches, setRecentSearches] = useStoredState<string>("kquant-stock:recent-searches:v1", "NVDA,MSTR,SPY");
  const primaryPreset = chartPresetByKey(primaryPresetKey);
  const confirmationPreset = chartPresetByKey(confirmationPresetKey);
  const [dailyCandles, setDailyCandles] = useState<Candle[]>([]);
  const [hourlyCandles, setHourlyCandles] = useState<Candle[]>([]);
  const [dailyMeta, setDailyMeta] = useState<CandleMeta>(() => failedMeta("NVDA", chartPresetByKey("1d")));
  const [hourlyMeta, setHourlyMeta] = useState<CandleMeta>(() => failedMeta("NVDA", chartPresetByKey("1h")));
  const [apiState, setApiState] = useState<"api" | "fallback">("fallback");
  const [apiConnection, setApiConnection] = useState<ApiConnectionState>("checking");
  const [apiHealth, setApiHealth] = useState<ApiHealthPayload | null>(null);
  const [aiStatus, setAiStatus] = useState<AiReviewStatusPayload | null>(null);
  const [marketRegime, setMarketRegime] = useState<MarketRegimePayload | null>(null);
  const [stockJournal, setStockJournal] = useState<StockJournalPayload | null>(null);
  const [mstrRadar, setMstrRadar] = useState<MstrCyclePayload | null>(null);
  const [mstrJournal, setMstrJournal] = useState<MstrJournalPayload | null>(null);
  const [mstrState, setMstrState] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const [fixtureBlocked, setFixtureBlocked] = useState(() => urlRequestedFixture());
  const [analysisState, setAnalysisState] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const [profileCompare, setProfileCompare] = useState<StockSignal[]>([]);
  const [compareState, setCompareState] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const [aiReview, setAiReview] = useState<AiReviewPayload | null>(null);
  const [aiReviewState, setAiReviewState] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const [aiDecision, setAiDecision] = useState<AiDecisionPayload | null>(null);
  const [aiDecisionState, setAiDecisionState] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const [researchChatMessages, setResearchChatMessages] = useState<ResearchChatMessage[]>([]);
  const [researchChatInput, setResearchChatInput] = useState("");
  const [researchChatState, setResearchChatState] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const [aiDailyReport, setAiDailyReport] = useState<AiDailyAgentPayload | null>(null);
  const [aiDailyState, setAiDailyState] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const [aiAgentAutoRunState, setAiAgentAutoRunState] = useState<"idle" | "checking" | "generating" | "ready" | "skipped" | "unavailable" | "error">("idle");
  const [activeWorkspace, setActiveWorkspace] = useState<WorkspaceName>("today");
  const [searchResults, setSearchResults] = useState<UniverseStock[]>([]);
  const [searchState, setSearchState] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const [searchOpen, setSearchOpen] = useState(false);
  const analyzeRequestRef = useRef(0);
  const candleRequestRef = useRef(0);
  const aiDecisionRequestRef = useRef(0);
  const researchChatRequestRef = useRef(0);
  const aiDecisionCacheRef = useRef<Record<string, AiDecisionPayload>>({});
  const autoAgentAttemptRef = useRef("");
  const text = copy[lang];

  const selected =
    run.signals.find((signal) => signal.symbol === selectedSymbol) ??
    makeUnavailableSignal(selectedSymbol);
  const selectedMeta = universe.find((stock) => stock.symbol === selected.symbol) ?? ALL_STOCKS.find((stock) => stock.symbol === selected.symbol) ?? STOCKS[0];
  const layerGroups = useMemo(() => groupByLayer(universe, run.signals), [run.signals, universe]);
  const activeMarketRegime = marketRegime ?? run.market_regime ?? null;
  const recentSymbols = useMemo(
    () =>
      recentSearches
        .split(",")
        .map((item) => item.trim().toUpperCase())
        .filter(Boolean)
        .slice(0, 8),
    [recentSearches],
  );
  const localSearchResults = useMemo(() => searchStocks(searchText, ALL_STOCKS, 10), [searchText]);
  const activeSearchResults = searchResults.length ? searchResults : localSearchResults;
  const latestResearchMessage = [...researchChatMessages].reverse().find((message) => message.role === "assistant");
  const latestResearchAnswer = latestResearchMessage?.payload?.answer;
  const showStockWorkspace = ["watchlist", "stock", "charts", "aiPlan", "chat", "journal"].includes(activeWorkspace);
  const showSelectedPanel = ["stock", "aiPlan", "journal"].includes(activeWorkspace);
  const showDeepResearch = activeWorkspace === "stock" || activeWorkspace === "chat";
  const showCharts = activeWorkspace === "stock" || activeWorkspace === "charts";
  const showRuleDetails = activeWorkspace === "aiPlan" || activeWorkspace === "journal";
  const mondayReadiness = deriveMondayReadiness({
    apiConnection,
    apiHealth,
    aiStatus,
    aiDailyReport,
    marketRegime: activeMarketRegime,
    run,
    dailyMeta,
    hourlyMeta,
    text,
  });
  const manualTradeTicket = deriveManualTradeTicket({
    selected,
    selectedSymbol: selected.symbol,
    aiDecision,
    dailyMeta,
    hourlyMeta,
    stockJournal,
    text,
  });

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    document.documentElement.lang = lang === "zh" ? "zh-CN" : "en";
  }, [lang, theme]);

  useEffect(() => {
    void loadApiHealth();
    void loadAiStatus();
    void loadAiDailyReportLatest();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (view !== "stocks") return;
    if (!aiStatus) {
      setAiAgentAutoRunState("checking");
      return;
    }
    if (aiStatus.status !== "available") {
      setAiAgentAutoRunState("unavailable");
      return;
    }
    if (!aiDailyReport) return;
    if (!aiDailyReport.auto_run_recommended) {
      setAiAgentAutoRunState(aiDailyReport.auto_run_skipped ? "skipped" : "ready");
      return;
    }
    const key = `${aiDailyReport.market_date ?? "unknown"}:${selectedUniverse}`;
    if (autoAgentAttemptRef.current === key || aiAgentAutoRunState === "generating") return;
    const lastAutoRun = Number(window.localStorage.getItem("kquant-stock:ai-daily-last-auto") || 0);
    if (Number.isFinite(lastAutoRun) && Date.now() - lastAutoRun < 30 * 60 * 1000) {
      setAiAgentAutoRunState("skipped");
      return;
    }
    autoAgentAttemptRef.current = key;
    window.localStorage.setItem("kquant-stock:ai-daily-last-auto", String(Date.now()));
    void runAiDailyAgent("auto");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [aiStatus?.status, aiDailyReport?.auto_run_recommended, aiDailyReport?.market_date, selectedUniverse, view]);

  useEffect(() => {
    try {
      if (urlRequestedFixture() || window.localStorage.getItem("kquant-stock:source:v2") === "fixture") {
        setFixtureBlocked(true);
      }
      window.localStorage.setItem("kquant-stock:source:v2", "live");
    } catch {
      // localStorage can be unavailable in strict embedded contexts.
    }
    if (!CHART_PRESETS.some((preset) => preset.key === primaryPresetKey)) {
      setPrimaryPresetKey("1d");
    }
    if (!CHART_PRESETS.some((preset) => preset.key === confirmationPresetKey)) {
      setConfirmationPresetKey("1h");
    }
    if (!["default", "ai_five_layer", "physical_ai", "all"].includes(selectedUniverse)) {
      setSelectedUniverse("default");
    }
    if (!STRATEGY_PROFILES.some((profile) => profile.key === selectedProfile)) {
      setSelectedProfile("tactical_1w_v1");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (view === "stocks") {
      void analyzeSymbol(selectedSymbol || "SPY", { keepSearch: true });
      void loadSignals(false);
      void loadMarketRegime();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedUniverse, selectedProfile, view]);

  useEffect(() => {
    const query = searchText.trim();
    if (!query) {
      setSearchResults([]);
      setSearchState("idle");
      return;
    }
    const timer = window.setTimeout(() => {
      void loadSearchResults(query);
    }, 180);
    return () => window.clearTimeout(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchText, selectedUniverse]);

  useEffect(() => {
    if (analysisState !== "loading") void loadCandles(selected.symbol);
    void loadStockJournal(selected.symbol);
    setProfileCompare([]);
    setCompareState("idle");
    setAiReview(null);
    setAiReviewState("idle");
    setResearchChatMessages([]);
    setResearchChatInput("");
    setResearchChatState("idle");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected.symbol, primaryPresetKey, confirmationPresetKey]);

  useEffect(() => {
    if (view === "mstr" && !mstrRadar && mstrState !== "loading") {
      void loadMstrRadar();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [view]);

  async function loadApiHealth() {
    try {
      setApiConnection("checking");
      const response = await apiFetch("/api/health");
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const payload = (await response.json()) as ApiHealthPayload;
      setApiHealth(payload);
      setApiConnection("connected");
      setApiState("api");
    } catch {
      setApiHealth(null);
      setApiConnection("offline");
      setApiState("fallback");
    }
  }

  async function loadAiStatus() {
    try {
      const response = await apiFetch("/api/stocks/ai-review/status");
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      setAiStatus((await response.json()) as AiReviewStatusPayload);
    } catch {
      setAiStatus(null);
    }
  }

  async function loadAiDailyReportLatest() {
    try {
      const response = await apiFetch("/api/stocks/ai-daily-report/latest");
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      setAiDailyReport((await response.json()) as AiDailyAgentPayload);
      setAiDailyState("ready");
    } catch {
      setAiDailyReport(null);
      setAiDailyState("error");
    }
  }

  async function runAiDailyAgent(trigger: "auto" | "manual" = "manual") {
    try {
      setAiDailyState("loading");
      setAiAgentAutoRunState(trigger === "auto" ? "generating" : "checking");
      const response = await apiFetch("/api/stocks/ai-daily-agent", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          trigger,
          cooldown_seconds: 1800,
          universe: selectedUniverse,
          limit: selectedUniverse === "all" ? 50 : 40,
          top_n: 8,
          profiles: STRATEGY_PROFILES.map((profile) => profile.key),
          model_tier: "batch",
        }),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const payload = (await response.json()) as AiDailyAgentPayload;
      setAiDailyReport(payload);
      setAiDailyState("ready");
      setAiAgentAutoRunState(payload.auto_run_skipped ? "skipped" : "ready");
      setApiState("api");
    } catch {
      setAiDailyState("error");
      setAiAgentAutoRunState("error");
      setApiState("fallback");
    }
  }

  async function loadSearchResults(query: string) {
    try {
      setSearchState("loading");
      setSearchResults([]);
      const response = await apiFetch(`/api/stocks/search?q=${encodeURIComponent(query)}&universe=all&limit=12`);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const payload = await response.json();
      setSearchResults((payload.results ?? []) as UniverseStock[]);
      setSearchState("ready");
    } catch {
      setSearchResults([]);
      setSearchState("error");
    }
  }

  async function loadSignals(forceScan: boolean, layer?: string) {
    const nextUniverse = selectedUniverse;
    const scanLimit = nextUniverse === "all" ? 300 : nextUniverse === "ai_five_layer" ? 100 : 200;
    try {
      const endpoint = forceScan || layer ? "/api/stocks/signals" : "/api/stocks/signals/latest";
      const layerQuery = layer ? `&layer=${encodeURIComponent(layer)}` : "";
      const response = await apiFetch(`${endpoint}?source=live&universe=${nextUniverse}&profile=${selectedProfile}&limit=${scanLimit}${layerQuery}`);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const payload = (await response.json()) as SignalRun;
      const universeResponse = await apiFetch(`/api/stocks/universe?universe=${nextUniverse}`);
      if (universeResponse.ok) {
        const universePayload = await universeResponse.json();
        setUniverse(universePayload.stocks ?? stocksForUniverse(nextUniverse));
      }
      setRun((current) => {
        const currentSelected = current.signals.find((signal) => signal.symbol === selectedSymbol);
        if (!currentSelected) return payload;
        const mergedSignals = [
          currentSelected,
          ...payload.signals.filter((signal) => signal.symbol !== currentSelected.symbol),
        ];
        return {
          ...payload,
          signals: mergedSignals,
          counts: {
            buy_setup: mergedSignals.filter((item) => item.level === "BUY SETUP").length,
            watch: mergedSignals.filter((item) => item.level === "WATCH").length,
            pass: mergedSignals.filter((item) => item.level === "PASS").length,
            total: mergedSignals.length,
          },
        };
      });
      setMarketRegime(payload.market_regime ?? null);
      setApiState("api");
    } catch {
      setRun((current) => (current.signals.length ? current : makeUnavailableSignalRun(nextUniverse)));
      setUniverse(stocksForUniverse(nextUniverse));
      setApiState("fallback");
    }
  }

  async function loadMarketRegime() {
    try {
      const response = await apiFetch("/api/stocks/market-regime?source=live");
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      setMarketRegime((await response.json()) as MarketRegimePayload);
    } catch {
      setMarketRegime(null);
    }
  }

  async function loadStockJournal(symbol: string) {
    try {
      const response = await apiFetch(`/api/stocks/signal-journal?symbol=${encodeURIComponent(symbol)}&limit=10`);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      setStockJournal((await response.json()) as StockJournalPayload);
    } catch {
      setStockJournal(null);
    }
  }

  async function saveStockJournal(entry: {
    status: string;
    notes: string;
    planned_entry?: string;
    planned_stop?: string;
    planned_target?: string;
    outcome: string;
  }) {
    const response = await apiFetch("/api/stocks/signal-journal/entry", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        run_id: run.run_id,
        symbol: selected.symbol,
        strategy_profile: selectedProfile,
        rule_conclusion: selected.trade_conclusion?.action ?? "",
        ai_review_verdict: aiReview?.ai_review?.ai_review_verdict ?? "",
        status: entry.status,
        notes: entry.notes,
        planned_entry: entry.planned_entry,
        planned_stop: entry.planned_stop,
        planned_target: entry.planned_target,
        outcome: entry.outcome,
      }),
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = await response.json();
    setStockJournal(payload.journal as StockJournalPayload);
  }

  async function analyzeSymbol(rawSymbol: string, options: { keepSearch?: boolean } = {}) {
    const symbol = rawSymbol.trim().toUpperCase().replace(/[^A-Z0-9.^-]/g, "");
    if (!symbol) return;
    const requestId = ++analyzeRequestRef.current;
    setSelectedSymbol(symbol);
    setAnalysisState("loading");
    setAiDecision(null);
    setAiDecisionState("idle");
    const candlePromise = loadCandles(symbol);
    const journalPromise = loadStockJournal(symbol);
    const aiStatusPromise = loadAiStatus();
    try {
      const response = await apiFetch(`/api/stocks/analyze?symbol=${encodeURIComponent(symbol)}&source=live&profile=${selectedProfile}`);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const payload = await response.json();
      const signal = payload.signal as StockSignal;
      if (requestId !== analyzeRequestRef.current) return;
      setRun((current) => {
        const remaining = current.signals.filter((item) => item.symbol !== signal.symbol);
        const nextSignals = [signal, ...remaining];
        return {
          ...current,
          run_id: `analyze-${signal.symbol}-${selectedProfile}`,
          profile: payload.profile ?? current.profile,
          signals: nextSignals,
          provider_status:
            signal.data_status?.daily_provider_status === "available" || signal.data_status?.hourly_provider_status === "available"
              ? "available"
              : current.provider_status,
          provider_error_count:
            signal.data_status?.daily_provider_status === "available" || signal.data_status?.hourly_provider_status === "available"
              ? 0
              : current.provider_error_count,
          counts: {
            buy_setup: nextSignals.filter((item) => item.level === "BUY SETUP").length,
            watch: nextSignals.filter((item) => item.level === "WATCH").length,
            pass: nextSignals.filter((item) => item.level === "PASS").length,
            total: nextSignals.length,
          },
        };
      });
      setMarketRegime(payload.market_regime ?? null);
      setSelectedSymbol(signal.symbol);
      if (!options.keepSearch) {
        setSearchText("");
        setSearchOpen(false);
      }
      const nextRecent = [signal.symbol, ...recentSymbols.filter((item) => item !== signal.symbol)].slice(0, 8);
      setRecentSearches(nextRecent.join(","));
      await Promise.allSettled([candlePromise, journalPromise, aiStatusPromise]);
      setAnalysisState("ready");
      setApiState("api");
      void requestAiDecision({ trigger: "auto", signalOverride: signal });
    } catch {
      await Promise.allSettled([candlePromise, journalPromise, aiStatusPromise]);
      if (requestId !== analyzeRequestRef.current) return;
      setSelectedSymbol(symbol);
      if (!options.keepSearch) {
        setSearchText("");
        setSearchOpen(false);
      }
      setAnalysisState("error");
      setApiState("fallback");
    }
  }

  async function compareProfiles(symbol: string) {
    const cleanSymbol = symbol.trim().toUpperCase().replace(/[^A-Z0-9.^-]/g, "");
    if (!cleanSymbol) return;
    try {
      setCompareState("loading");
      const results: StockSignal[] = [];
      for (const profile of STRATEGY_PROFILES) {
        const response = await apiFetch(`/api/stocks/analyze?symbol=${encodeURIComponent(cleanSymbol)}&source=live&profile=${profile.key}`);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const payload = await response.json();
        results.push(payload.signal as StockSignal);
      }
      setProfileCompare(results);
      setCompareState("ready");
      setApiState("api");
    } catch {
      setProfileCompare([]);
      setCompareState("error");
      setApiState("fallback");
    }
  }

  async function requestAiReview() {
    try {
      setAiReviewState("loading");
      const response = await apiFetch("/api/stocks/ai-review", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          symbol: selected.symbol,
          profile: selectedProfile,
          model_tier: "review",
          signal_payload: selected,
          profile_comparison: profileCompare,
          research_context: {
            status: "removed",
            note: "External research layer has been removed. Use KQUANT live K-lines, rule guardrails, AI command, historical edge, and journal context.",
          },
          journal_context_limit: 5,
        }),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const payload = (await response.json()) as AiReviewPayload;
      setAiReview(payload);
      setAiReviewState("ready");
      setApiState("api");
    } catch {
      setAiReview(null);
      setAiReviewState("error");
      setApiState("fallback");
    }
  }

  async function requestAiDecision(options: { trigger?: "auto" | "manual"; signalOverride?: StockSignal; force?: boolean } = {}) {
    const signal = options.signalOverride ?? selected;
    const requestId = ++aiDecisionRequestRef.current;
    const cacheKey = aiDecisionCacheKey(signal, selectedProfile);
    if (!options.force && aiDecisionCacheRef.current[cacheKey]) {
      setAiDecision(aiDecisionCacheRef.current[cacheKey]);
      setAiDecisionState("ready");
      return;
    }
    try {
      setAiDecisionState("loading");
      const response = await apiFetch("/api/stocks/ai-decision", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          symbol: signal.symbol,
          profile: selectedProfile,
          model_tier: signal.profile_name === "cycle_1_3y_v1" || signal.symbol === "MSTR" ? "deep" : "review",
          signal_payload: signal,
          profile_comparison: profileCompare,
          trigger: options.trigger ?? "manual",
          research_context: {
            status: "removed",
            note: "External research layer has been removed. Use KQUANT live K-lines, rule guardrails, historical edge, and journal context.",
          },
          journal_context_limit: 5,
        }),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const payload = (await response.json()) as AiDecisionPayload;
      if (requestId !== aiDecisionRequestRef.current) return;
      aiDecisionCacheRef.current[cacheKey] = payload;
      setAiDecision(payload);
      setAiDecisionState("ready");
      setApiState("api");
    } catch {
      if (requestId !== aiDecisionRequestRef.current) return;
      setAiDecision(null);
      setAiDecisionState("error");
      setApiState("fallback");
    }
  }

  async function sendResearchChat(questionOverride?: string) {
    const question = (questionOverride ?? researchChatInput).trim();
    if (!question || researchChatState === "loading") return;
    const requestId = ++researchChatRequestRef.current;
    const userMessage: ResearchChatMessage = {
      id: `user-${Date.now()}`,
      role: "user",
      content: question,
      created_at: new Date().toISOString(),
    };
    const nextMessages = [...researchChatMessages, userMessage].slice(-12);
    setResearchChatMessages(nextMessages);
    setResearchChatInput("");
    setResearchChatState("loading");
    try {
      const response = await apiFetch("/api/stocks/research-chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          symbol: selected.symbol,
          profile: selectedProfile,
          language: lang,
          question,
          messages: nextMessages.map((message) => ({ role: message.role, content: message.content })),
          signal_payload: selected,
          ai_decision: aiDecision,
          research_context: {
            status: "removed",
            note: "External research layer has been removed. Use KQUANT live K-lines, rule guardrails, AI command, historical edge, and journal context.",
          },
        }),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const payload = (await response.json()) as AiResearchChatPayload;
      if (requestId !== researchChatRequestRef.current) return;
      setResearchChatMessages([
        ...nextMessages,
        {
          id: `assistant-${Date.now()}`,
          role: "assistant",
          content: payload.answer.answer,
          payload,
          created_at: payload.generated_at,
        },
      ]);
      setResearchChatState("ready");
      setApiState("api");
    } catch {
      if (requestId !== researchChatRequestRef.current) return;
      setResearchChatMessages([
        ...nextMessages,
        {
          id: `assistant-error-${Date.now()}`,
          role: "assistant",
          content: text.aiRequestFailed,
          created_at: new Date().toISOString(),
        },
      ]);
      setResearchChatState("error");
      setApiState("fallback");
    }
  }

  async function loadCandles(symbol: string) {
    const requestId = ++candleRequestRef.current;
    setDailyCandles([]);
    setHourlyCandles([]);
    setDailyMeta(refreshingMeta(symbol, primaryPreset));
    setHourlyMeta(refreshingMeta(symbol, confirmationPreset));
    try {
      const [dailyResponse, hourlyResponse] = await Promise.all([
        apiFetch(`/api/stocks/candles?symbol=${symbol}&range=${primaryPreset.range}&interval=${primaryPreset.interval}&source=live`),
        apiFetch(`/api/stocks/candles?symbol=${symbol}&range=${confirmationPreset.range}&interval=${confirmationPreset.interval}&source=live`),
      ]);
      if (!dailyResponse.ok || !hourlyResponse.ok) throw new Error("candles unavailable");
      const [dailyPayload, hourlyPayload] = await Promise.all([dailyResponse.json(), hourlyResponse.json()]);
      const normalizedDaily = normalizeCandles(dailyPayload.candles, []);
      const normalizedHourly = normalizeCandles(hourlyPayload.candles, []);
      if (requestId !== candleRequestRef.current) return;
      setDailyCandles(normalizedDaily);
      setHourlyCandles(normalizedHourly);
      setDailyMeta(metaFromPayload(dailyPayload, primaryPreset, normalizedDaily));
      setHourlyMeta(metaFromPayload(hourlyPayload, confirmationPreset, normalizedHourly));
      setApiConnection("connected");
      setApiState("api");
    } catch {
      if (requestId !== candleRequestRef.current) return;
      setDailyCandles([]);
      setHourlyCandles([]);
      setDailyMeta(failedMeta(symbol, primaryPreset));
      setHourlyMeta(failedMeta(symbol, confirmationPreset));
      setApiConnection((current) => (current === "connected" ? current : "offline"));
    }
  }

  async function loadMstrRadar() {
    try {
      setMstrState("loading");
      const response = await apiFetch("/api/mstr/cycle-radar?source=live");
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const payload = (await response.json()) as MstrCyclePayload;
      setMstrRadar(payload);
      setMstrJournal(payload.manual_journal ?? null);
      void loadMstrJournal();
      setMstrState("ready");
      setApiState("api");
    } catch {
      setMstrRadar(null);
      setMstrState("error");
      setApiState("fallback");
    }
  }

  async function loadMstrJournal() {
    try {
      const response = await apiFetch("/api/mstr/cycle-journal?limit=20");
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      setMstrJournal((await response.json()) as MstrJournalPayload);
    } catch {
      // Journal is local review state; keep the latest loaded radar if this read fails.
    }
  }

  async function saveMstrJournal(entry: { status: string; notes: string; outcome: string }) {
    if (!mstrRadar?.run_id) return;
    const response = await apiFetch("/api/mstr/cycle-journal/entry", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ...entry, run_id: mstrRadar.run_id }),
    });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = await response.json();
    setMstrJournal(payload.journal as MstrJournalPayload);
  }

  function openWorkspace(workspace: WorkspaceName) {
    setActiveWorkspace(workspace);
    if (workspace === "mstr") {
      setView("mstr");
      return;
    }
    if (view !== "stocks") setView("stocks");
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <div className="brand">
          <div className="brand-mark">KQ</div>
          <div>
            <h1>{text.title}</h1>
            <p>{text.subtitle}</p>
          </div>
        </div>
        <div className="top-context">
          <span>{text.currentPage}</span>
          <strong>{view === "mstr" ? text.mstrCycleTitle : `${selected.symbol} / ${text.aiTradingCommand}`}</strong>
        </div>
        <div className="top-status-mini" aria-label={text.systemStatus}>
          <Pill
            tone={apiConnection === "connected" ? "good" : "warn"}
            icon={<Activity size={14} />}
            label={apiConnection === "connected" ? "Live" : "Offline"}
          />
          <Pill
            tone={aiStatus?.status === "available" ? "good" : "warn"}
            icon={<Lock size={14} />}
            label={aiStatus?.status === "available" ? "AI" : "AI Key"}
          />
          <Pill
            tone={regimeTone(activeMarketRegime?.regime)}
            icon={<BarChart3 size={14} />}
            label={activeMarketRegime?.regime ?? "Market"}
          />
        </div>
      </header>

      <section className="stock-workspace-shell">
        <aside className="workspace-sidebar" aria-label="Workspace navigation">
          <div className="sidebar-section sidebar-status-stack">
            <Pill
              tone={apiConnection === "connected" ? "good" : "warn"}
              icon={<Activity size={14} />}
              label={apiConnection === "connected" ? `Live: ${apiHealth?.backend ?? "API"}` : "Live API offline"}
            />
            <Pill
              tone={aiStatus?.status === "available" ? "good" : "warn"}
              icon={<Lock size={14} />}
              label={aiStatus?.status === "available" ? `AI: ${aiStatus.models.review ?? "review"}` : "AI key missing"}
            />
            <Pill
              tone={regimeTone(activeMarketRegime?.regime)}
              icon={<BarChart3 size={14} />}
              label={`Market: ${activeMarketRegime?.regime ?? "loading"}`}
            />
            <Pill tone="good" icon={<CheckCircle2 size={14} />} label="No fixture" />
            {fixtureBlocked ? <Pill tone="warn" icon={<AlertTriangle size={14} />} label="Fixture URL ignored" /> : null}
            <Pill tone="neutral" icon={<ShieldCheck size={14} />} label="No broker / no order" />
          </div>

          <div className="sidebar-section primary-nav-section">
            <span className="sidebar-section-title">{text.navigation}</span>
            {[
              ["today", text.todayNav, text.todaySub],
              ["search", text.searchNav, text.searchSub],
              ["watchlist", text.watchlistNav, text.watchlistSub],
              ["stock", text.stockNav, text.stockSub],
              ["charts", text.chartsNav, text.chartsSub],
              ["aiPlan", text.aiPlanNav, text.aiPlanSub],
              ["chat", text.chatNav, text.chatSub],
              ["mstr", text.mstrNav, text.mstrSub],
              ["journal", text.journalNav, text.journalSub],
              ["settings", text.settingsNav, text.settingsSub],
            ].map(([key, short, label]) => (
              <button
                type="button"
                key={key}
                className={`workspace-nav-button ${activeWorkspace === key ? "active" : ""}`}
                onClick={() => openWorkspace(key as WorkspaceName)}
              >
                <strong>{short}</strong>
                <span>{label}</span>
              </button>
            ))}
          </div>

          <div className="sidebar-section">
            <span className="sidebar-section-title">{text.tradingSystem}</span>
            {STRATEGY_PROFILES.map((profile) => (
              <button
                type="button"
                key={profile.key}
                className={`sidebar-option ${selectedProfile === profile.key ? "active" : ""}`}
                onClick={() => setSelectedProfile(profile.key)}
              >
                <strong>{profile.label}</strong>
                <span>{profile.period}</span>
              </button>
            ))}
          </div>

          <div className="sidebar-section">
            <span className="sidebar-section-title">{text.universeControl}</span>
            {(["default", "ai_five_layer", "physical_ai", "all"] as UniverseName[]).map((item) => (
              <button
                type="button"
                key={item}
                className={`sidebar-option ${selectedUniverse === item ? "active" : ""}`}
                onClick={() => setSelectedUniverse(item)}
              >
                <strong>{universeOptionLabel(item, lang)}</strong>
                <span>{item === "default" ? "Core" : item === "ai_five_layer" ? "AI" : item === "physical_ai" ? "Physical" : "Merged"}</span>
              </button>
            ))}
          </div>

          <div className="sidebar-section">
            <span className="sidebar-section-title">{text.actions}</span>
            <button className="sidebar-action-button" type="button" onClick={() => void analyzeSymbol(selected.symbol, { keepSearch: true })}>
              <RefreshCw size={14} />
              {text.refreshStock}
            </button>
            <button className="sidebar-action-button" type="button" onClick={() => void runAiDailyAgent("manual")}>
              <RefreshCw size={14} />
              {text.refreshAiToday}
            </button>
            <button className="sidebar-action-button" type="button" onClick={() => (view === "mstr" ? void loadMstrRadar() : void loadSignals(true))}>
              <RefreshCw size={14} />
              {view === "mstr" ? text.refreshMstr : text.refresh}
            </button>
          </div>

          <div className="sidebar-section sidebar-preferences">
            <span className="sidebar-section-title">{text.preferences}</span>
            <Segmented
              value={lang}
              options={[
                ["en", text.english],
                ["zh", text.chinese],
              ]}
              onChange={(value) => setLang(value as Lang)}
              icon={<Languages size={14} />}
            />
            <Segmented
              value={theme}
              options={[
                ["light", text.light],
                ["dark", text.dark],
              ]}
              onChange={(value) => setTheme(value as Theme)}
              icon={theme === "light" ? <Sun size={14} /> : <Moon size={14} />}
            />
            <Segmented
              value={view}
              options={[
                ["stocks", text.stockView],
                ["mstr", text.mstrView],
              ]}
              onChange={(value) => setView(value as AppView)}
            />
          </div>
        </aside>
        <div className="stock-workspace-main">

      <section className="research-command-panel" id="stock-search-workspace" aria-label="Stock command search">
        <form
          className="symbol-command symbol-command-large"
          onSubmit={(event) => {
            event.preventDefault();
            void analyzeSymbol(resolveSearchSymbol(searchText, activeSearchResults, selected.symbol));
          }}
        >
          <Search size={17} />
          <input
            value={searchText}
            onFocus={() => setSearchOpen(true)}
            onChange={(event) => {
              setSearchText(event.target.value);
              setSearchOpen(true);
            }}
            onKeyDown={(event) => {
              if (event.key === "Escape") setSearchOpen(false);
              if (event.key === "ArrowDown") setSearchOpen(true);
              if (event.key === "Enter" && activeSearchResults[0]) {
                event.preventDefault();
                void analyzeSymbol(resolveSearchSymbol(searchText, activeSearchResults, selected.symbol));
              }
            }}
            placeholder={text.searchPlaceholder}
            aria-label="Search ticker, company, Chinese alias, theme, or layer"
          />
          <button type="submit">
            {analysisState === "loading" ? text.loading : text.analyze}
          </button>
        </form>
        <div className="search-shortcuts">
          {SEARCH_SHORTCUTS.map((shortcut) => (
            <button
              type="button"
              key={shortcut.label}
              onClick={() => {
                setSearchText(shortcut.query);
                setSearchOpen(true);
                if ("symbol" in shortcut) {
                  void analyzeSymbol(shortcut.symbol);
                } else {
                  void loadSearchResults(shortcut.query);
                }
              }}
            >
              {shortcut.label}
            </button>
          ))}
        </div>
        {analysisState === "loading" ? (
          <p className="command-feedback">{text.analyzeFeedback.replace("{symbol}", selectedSymbol)}</p>
        ) : null}
        {searchOpen || searchText.trim() ? (
          <div className="command-results command-results-inline" role="listbox">
            <div className="command-results-head">
              <span>{searchState === "loading" ? text.searchingUniverse : text.commandSearch}</span>
              <button type="button" onClick={() => setSearchOpen(false)}>{text.close}</button>
            </div>
            {(searchText.trim() ? activeSearchResults : quickSearchStocks(ALL_STOCKS)).slice(0, 12).map((stock) => {
              const signal = run.signals.find((item) => item.symbol === stock.symbol);
              return (
                <button
                  type="button"
                  className="command-result"
                  key={stock.symbol}
                  onClick={() => void analyzeSymbol(stock.symbol)}
                >
                  <strong>{stock.symbol}</strong>
                  <span>{stock.name}</span>
                  <small>{stock.layer} / {signal?.trade_conclusion?.action ?? text.analyze} / {signal?.data_status?.data_quality ?? "live check"}</small>
                </button>
              );
            })}
            {searchState === "error" ? <p>{text.searchOffline}</p> : null}
            {searchState === "ready" && searchText.trim() && activeSearchResults.length === 0 ? <p>{text.noSearchMatch}</p> : null}
          </div>
        ) : null}
      </section>

      <section className="quick-search-row" aria-label="Recent symbol searches">
        <span>{text.recent}</span>
        {recentSymbols.map((symbol) => (
          <button key={symbol} type="button" className={symbol === selected.symbol ? "symbol-chip active" : "symbol-chip"} onClick={() => void analyzeSymbol(symbol)}>
            {symbol}
          </button>
        ))}
        <span className="quick-search-note">{run.profile.label ?? selectedProfile} / {run.profile.holding_period ?? ""}</span>
      </section>

      <section className={`metrics-grid market-snapshot-strip ${activeWorkspace === "today" ? "" : "workspace-hidden"}`}>
        <Metric label={text.buySetups} value={String(run.counts.buy_setup)} tone="good" />
        <Metric label={text.watch} value={String(run.counts.watch)} tone="watch" />
        <Metric label={text.pass} value={String(run.counts.pass)} />
        <Metric label={text.provider} value={`${run.provider_status} / ${run.provider_error_count}`} tone={run.provider_error_count ? "warn" : "good"} />
        <Metric
          label="Market Regime"
          value={`${activeMarketRegime?.label ?? "Loading"} / ${activeMarketRegime?.score ?? 0}`}
          tone={regimeTone(activeMarketRegime?.regime) === "good" ? "good" : "watch"}
        />
        <Metric label={text.universe} value={`${universeOptionLabel(selectedUniverse, lang)} / ${run.scanned_count ?? run.counts.total}/${run.universe_total ?? universe.length}`} />
        <Metric
          label="Coverage"
          value={`${run.provider_coverage?.available ?? 0}/${run.provider_coverage?.stale_or_partial ?? 0}/${run.provider_coverage?.failed ?? 0}`}
          tone={run.provider_coverage?.failed ? "warn" : "good"}
        />
        <Metric
          label={text.historicalValidation}
          value={`${run.historical_validation?.sample_count ?? 0} / ${formatNumber(run.historical_validation?.win_rate_5d)}%`}
          tone={(run.historical_validation?.win_rate_5d ?? 0) >= 52 ? "good" : "watch"}
        />
      </section>

      {view === "mstr" ? (
        <div id="mstr-radar-workspace">
        <MstrCycleRadar
          payload={mstrRadar}
          state={mstrState}
          theme={theme}
          lang={lang}
          text={text}
          onRefresh={() => void loadMstrRadar()}
          journal={mstrJournal}
          onSaveJournal={saveMstrJournal}
        />
        </div>
      ) : (
        <>
      <div id="ai-trade-desk-workspace" className={activeWorkspace === "today" ? "" : "workspace-hidden"}>
      <MondayReadinessPanel readiness={mondayReadiness} text={text} />
      <AiTradeDesk
        report={aiDailyReport}
        state={aiDailyState}
        autoRunState={aiAgentAutoRunState}
        aiStatus={aiStatus}
        selectedUniverse={selectedUniverse}
        lang={lang}
        text={text}
        onRun={() => void runAiDailyAgent("manual")}
        onPick={(symbol) => void analyzeSymbol(symbol)}
      />
      <section className="panel deep-research-preview">
        <div>
          <span className="eyebrow">{text.chatSub}</span>
          <h2>{text.deepResearchChat}</h2>
          <p>{latestResearchAnswer?.direct_view ?? text.researchChatEmpty}</p>
        </div>
        <button type="button" className="secondary-action" onClick={() => openWorkspace("chat")}>
          <MessageCircle size={15} />
          {text.chatNav}
        </button>
      </section>
      </div>
      <div className={activeWorkspace === "settings" ? "" : "workspace-hidden"}>
      <DataReliabilityPanel
        apiConnection={apiConnection}
        apiHealth={apiHealth}
        run={run}
        dailyMeta={dailyMeta}
        hourlyMeta={hourlyMeta}
        selectedSymbol={selected.symbol}
        apiBaseUrl={API_BASE_URL}
      />
      </div>
      {showStockWorkspace ? (
      <section className={`main-grid ${activeWorkspace === "watchlist" ? "watchlist-only" : "single-main"}`}>
        {activeWorkspace === "watchlist" ? (
        <aside className="panel queue-panel" id="stock-watchlist-workspace">
          <PanelTitle title={text.today} detail={run.profile.name} />
          <div className="signal-list">
            {run.signals.slice(0, 24).map((signal) => (
              <button
                type="button"
                className={`signal-card ${signal.symbol === selected.symbol ? "active" : ""}`}
                key={signal.symbol}
                onClick={() => void analyzeSymbol(signal.symbol)}
              >
                <div className="signal-card-top">
                  <strong>{signal.symbol}</strong>
                  <span className={`level ${levelClass(signal.level)}`}>{levelLabel(signal.level, lang)}</span>
                </div>
                <div className="score-line">
                  <span>{signal.primary_layer ?? selectedMetaBySymbol(universe, signal.symbol)?.layer ?? "US Stock"}</span>
                  <b>{signal.score}/100</b>
                </div>
                <div className="score-break-mini">
                  T {formatNumber(signal.score_breakdown?.trend_score)} / C {formatNumber(signal.score_breakdown?.trigger_score)} / V{" "}
                  {formatNumber(signal.score_breakdown?.volume_score)} / R {formatNumber(signal.score_breakdown?.risk_score)}
                </div>
                <div className="edge-line">
                  <span>
                    {text.winRate} {formatNumber(signal.historical_edge?.win_rate_5d)}%
                  </span>
                  <span>
                    {text.samples} {signal.historical_edge?.sample_count ?? 0}
                  </span>
                </div>
                <div className={`signal-action ${actionClass(signal.trade_conclusion?.action)}`}>
                  Conclusion: {signal.trade_conclusion?.action ?? "-"}
                </div>
                <p>{signal.trigger_summary}</p>
              </button>
            ))}
          </div>
        </aside>
        ) : null}

        {activeWorkspace !== "watchlist" ? (
        <section className="review-stack">
          {showSelectedPanel ? (
          <section className="panel selected-panel" id="selected-stock-workspace">
            <PanelTitle title={text.selected} detail={`${signalLayer(selected, selectedMeta)} / ${selected.liquidity_tier ?? selectedMeta.liquidity_tier ?? "core"}`} />
            <div className="selected-row">
              <div>
                <span>{selectedMeta.name}</span>
                <h2>{selected.symbol} / {levelLabel(selected.level, lang)}</h2>
              </div>
              <div className="selected-score">{selected.score}/100</div>
            </div>
            <ManualTradingConclusion
              conclusion={selected.trade_conclusion}
              aiReview={aiReview}
              aiReviewState={aiReviewState}
              aiDecision={aiDecision}
              aiDecisionState={aiDecisionState}
              aiStatus={aiStatus}
              text={text}
              onReview={() => void requestAiDecision({ trigger: "manual", force: true })}
            />
            <ManualTradeTicketPanel
              ticket={manualTradeTicket}
              aiDecision={aiDecision}
              text={text}
              onOpenJournal={() => openWorkspace("journal")}
            />
            <div className="fact-grid">
              <Fact label="Close" value={formatNumber(selected.features.close)} />
              <Fact label="EMA20" value={formatNumber(selected.features.ema20)} />
              <Fact label="EMA50" value={formatNumber(selected.features.ema50)} />
              <Fact label="EMA200" value={formatNumber(selected.features.ema200)} />
              <Fact label="ATR" value={`${formatNumber(selected.features.atr_pct)}%`} />
              <Fact label="Volume" value={`${formatNumber(selected.features.volume_ratio)}x`} />
              <Fact label="Trade Readiness" value={selected.readiness_gate?.status ?? "BLOCKED"} />
              <Fact label="System" value={selected.strategy_label ?? run.profile.label ?? selectedProfile} />
              <Fact label="Holding" value={selected.holding_period ?? run.profile.holding_period ?? "-"} />
              <Fact label={text.winRate} value={`${formatNumber(selected.historical_edge?.win_rate_5d)}%`} />
              <Fact label={text.avgReturn} value={`${formatNumber(selected.historical_edge?.avg_forward_return_5d)}%`} />
              <Fact label={text.samples} value={String(selected.historical_edge?.sample_count ?? 0)} />
            </div>
            <div className="score-breakdown-row">
              <Fact label="Trend" value={formatNumber(selected.score_breakdown?.trend_score)} />
              <Fact label="1H Confirm" value={formatNumber(selected.score_breakdown?.trigger_score)} />
              <Fact label="Volume" value={formatNumber(selected.score_breakdown?.volume_score)} />
              <Fact label="Risk Window" value={formatNumber(selected.score_breakdown?.risk_score)} />
              <Fact label="Exit Risk" value={selected.exit_risk?.status ?? "-"} />
            </div>
            <div className="profile-compare-panel" id="strategy-compare-workspace">
              <div className="profile-compare-head">
                <div>
                  <strong>Strategy Comparison</strong>
                  <span>Same stock, different holding periods and risk modes. Use this to avoid mixing conservative and aggressive systems.</span>
                </div>
                <button type="button" onClick={() => void compareProfiles(selected.symbol)} disabled={compareState === "loading"}>
                  {compareState === "loading" ? "Comparing..." : "Compare 5 Systems"}
                </button>
              </div>
              <div className="profile-compare-grid">
                {STRATEGY_PROFILES.map((profile) => {
                  const compared = profileCompare.find((item) => item.profile_name === profile.key);
                  return (
                    <div className="profile-compare-card" key={profile.key}>
                      <span>{profile.label}</span>
                      <strong className={`action-badge ${actionClass(compared?.trade_conclusion?.action)}`}>
                        {compared?.trade_conclusion?.action ?? "-"}
                      </strong>
                      <small>{compared ? `${formatNumber(compared.score)}/100 / ${compared.historical_edge?.focus_window ?? profile.period}` : profile.period}</small>
                      <p>{compared?.exit_plan?.status ?? (compareState === "ready" ? "No result" : "Click compare")}</p>
                    </div>
                  );
                })}
              </div>
              {compareState === "error" ? <p className="compare-error">Profile comparison unavailable. Live provider may be degraded.</p> : null}
            </div>
            <p className="secondary-note">{text.optionsLater}</p>
          </section>
          ) : null}

          {showDeepResearch ? (
          <DeepResearchChatPanel
            text={text}
            selected={selected}
            aiStatus={aiStatus}
            aiDecision={aiDecision}
            state={researchChatState}
            messages={researchChatMessages}
            input={researchChatInput}
            onInputChange={setResearchChatInput}
            onSend={() => void sendResearchChat()}
            onAsk={(question) => void sendResearchChat(question)}
          />
          ) : null}

          {showCharts ? (
          <div className="chart-grid" id="kline-workspace">
            <ChartPanel
              title={text.daily}
              subtitle={`${selected.symbol} / ${primaryPreset.label} / ${text.dailyHint}`}
              candles={dailyCandles}
              theme={theme}
              ohlcHint={text.ohlc}
              emptyText={text.noCandles}
              meta={dailyMeta}
              presets={CHART_PRESETS}
              presetKey={primaryPresetKey}
              onPresetChange={(value) => setPrimaryPresetKey(value as ChartPresetKey)}
              onReload={() => void analyzeSymbol(selected.symbol, { keepSearch: true })}
              labels={{
                source: text.chartSource,
                status: text.chartStatus,
                range: text.chartRange,
                candles: text.candles,
                firstLast: text.firstLast,
              }}
            />
            <ChartPanel
              title={text.hourly}
              subtitle={`${selected.symbol} / ${confirmationPreset.label} / ${text.hourlyHint}`}
              candles={hourlyCandles}
              theme={theme}
              ohlcHint={text.ohlc}
              emptyText={text.noCandles}
              meta={hourlyMeta}
              presets={CHART_PRESETS}
              presetKey={confirmationPresetKey}
              onPresetChange={(value) => setConfirmationPresetKey(value as ChartPresetKey)}
              onReload={() => void analyzeSymbol(selected.symbol, { keepSearch: true })}
              labels={{
                source: text.chartSource,
                status: text.chartStatus,
                range: text.chartRange,
                candles: text.candles,
                firstLast: text.firstLast,
              }}
            />
          </div>
          ) : null}

          {showRuleDetails ? (
          <section className="panel detail-grid">
            <Narrative title={text.reasons} items={[selected.trend_summary, selected.trigger_summary]} />
            <Narrative
              title="Buy Logic"
              items={buyLogicItems(selected, activeMarketRegime)}
            />
            <Narrative
              title="Market Regime"
              items={[
                `${activeMarketRegime?.label ?? "Loading"} / ${activeMarketRegime?.score ?? 0}`,
                ...(activeMarketRegime?.reasons ?? ["Market regime loads from SPY, QQQ, IWM, and VIX."]),
              ]}
            />
            <Narrative
              title="Trade Readiness Gate"
              items={[
                selected.readiness_gate?.status ?? "BLOCKED",
                ...(selected.readiness_gate?.reasons ?? ["Run a stock scan to calculate readiness."]),
              ]}
            />
            <Narrative
              title={text.historicalEdge}
              items={[
                `${text.samples}: ${selected.historical_edge?.sample_count ?? 0}`,
                `${text.winRate}: ${formatNumber(selected.historical_edge?.win_rate_5d)}% / ${text.avgReturn}: ${formatNumber(selected.historical_edge?.avg_forward_return_5d)}%`,
                `Focus ${selected.historical_edge?.focus_window ?? "5D"}: win ${formatNumber(selected.historical_edge?.focus_win_rate)}% / avg ${formatNumber(selected.historical_edge?.focus_avg_return)}%`,
                `Verdict: ${selected.historical_edge?.verdict ?? "missing"}`,
              ]}
            />
            <Narrative title="Exit Risk" items={selected.exit_risk?.reasons ?? ["No exit-risk data."]} />
            <Narrative title="Exit Plan" items={selected.exit_plan?.rules ?? ["No exit plan loaded yet."]} />
            <Narrative title={text.risks} items={selected.risk_warnings} />
            <Narrative title={text.checklist} items={selected.manual_checklist} />
            <Narrative title="Risk Controls" items={selected.readiness_gate?.risk_controls ?? ["No readiness gate loaded yet."]} />
            <div id="journal-workspace">
            <StockJournalPanel
              runId={run.run_id}
              symbol={selected.symbol}
              journal={stockJournal}
              onSave={saveStockJournal}
            />
            </div>
            <div className="data-box">
              <h3>{text.data}</h3>
              <Fact label="Daily" value={`${selected.data_status.daily_provider_status} / ${selected.data_status.daily_candles}`} />
              <Fact label="1H" value={`${selected.data_status.hourly_provider_status} / ${selected.data_status.hourly_candles}`} />
              <Fact label={text.dataQuality} value={selected.data_status.data_quality === "clean" ? text.clean : text.caution} />
              <Fact label={text.source} value={`${selected.data_status.source} / ${selected.data_status.freshness}`} />
              <Fact label={text.report} value={run.run_id} />
            </div>
          </section>
          ) : null}
        </section>
        ) : null}
      </section>
      ) : null}

      {activeWorkspace === "watchlist" ? (
      <section className="panel layers-panel">
        <PanelTitle title="AI Five-Layer Cake" detail={`${universe.length} selected stocks / ${universeOptionLabel(selectedUniverse, lang)}`} />
        <div className="layer-grid">
          {layerGroups.map((layer) => (
            <div className="layer-card" key={layer.name}>
              <div className="layer-head">
                <strong>{layer.name}</strong>
                <span>{layer.stocks.length}</span>
              </div>
              <div className="layer-stats">
                <span>Avg {formatNumber(layer.avgScore)}</span>
                <span>BUY {layer.buySetup} / WATCH {layer.watch}</span>
                <span>{layer.providerCaution ? "Data caution" : "Data clean"}</span>
              </div>
              <button className="layer-scan-button" type="button" onClick={() => void loadSignals(true, layer.name)}>
                <RefreshCw size={13} />
                Scan This Layer
              </button>
              <div className="symbol-wrap">
                {layer.stocks.slice(0, 16).map((stock) => {
                  const signal = run.signals.find((item) => item.symbol === stock.symbol);
                  return (
                    <button
                      className={stock.symbol === selected.symbol ? "symbol-chip active" : "symbol-chip"}
                      type="button"
                      key={stock.symbol}
                      onClick={() => void analyzeSymbol(stock.symbol)}
                    >
                      {stock.symbol}
                      {signal ? <span>{Math.round(signal.score)}</span> : null}
                    </button>
                  );
                })}
              </div>
            </div>
          ))}
        </div>
      </section>
      ) : null}
      {activeWorkspace === "settings" ? (
      <SettingsPanel
        apiConnection={apiConnection}
        aiStatus={aiStatus}
        apiBaseUrl={API_BASE_URL}
        apiHealth={apiHealth}
        text={text}
      />
      ) : null}
        </>
      )}
        </div>
      </section>
    </main>
  );
}

function DeepResearchChatPanel({
  text,
  selected,
  aiStatus,
  aiDecision,
  state,
  messages,
  input,
  onInputChange,
  onSend,
  onAsk,
}: {
  text: (typeof copy)["en"] | (typeof copy)["zh"];
  selected: StockSignal;
  aiStatus: AiReviewStatusPayload | null;
  aiDecision: AiDecisionPayload | null;
  state: "idle" | "loading" | "ready" | "error";
  messages: ResearchChatMessage[];
  input: string;
  onInputChange: (value: string) => void;
  onSend: () => void;
  onAsk: (question: string) => void;
}) {
  const model = aiStatus?.models?.research ?? aiStatus?.models?.deep ?? "gpt-5.5-pro";
  const promptIdeas = [
    `Analyze ${selected.symbol}'s risk/reward and best entry zone.`,
    `What would change the AI view on ${selected.symbol}?`,
    `Compare bullish and bearish evidence for ${selected.symbol}.`,
  ];
  return (
    <section className="panel deep-research-chat" id="deep-research-chat-workspace">
      <div className="deep-chat-head">
        <div>
          <span className="eyebrow">{text.chatSub}</span>
          <h2>{text.deepResearchChat}</h2>
          <p>{text.deepResearchSubtitle}</p>
        </div>
        <div className="deep-chat-model">
          <span>{text.researchModel}</span>
          <strong>{model}</strong>
        </div>
      </div>
      <div className="deep-chat-context">
        <Fact label="Symbol" value={selected.symbol} />
        <Fact label="Rule" value={`${selected.level} / ${formatNumber(selected.score)}`} />
        <Fact label="AI" value={aiDecision?.ai_decision?.action ?? "-"} />
        <Fact label={text.dataQuality} value={selected.data_status?.data_quality ?? "-"} />
      </div>
      <div className="deep-chat-messages">
        {messages.length === 0 ? (
          <div className="deep-chat-empty">
            <MessageCircle size={28} />
            <strong>{text.researchChatEmpty}</strong>
            <div className="deep-chat-prompts">
              {promptIdeas.map((prompt) => (
                <button type="button" key={prompt} onClick={() => onAsk(prompt)} disabled={state === "loading" || aiStatus?.status !== "available"}>
                  {prompt}
                </button>
              ))}
            </div>
          </div>
        ) : (
          messages.map((message) => (
            <article className={`deep-chat-message ${message.role}`} key={message.id}>
              <div className="deep-chat-bubble">
                <strong>{message.role === "user" ? "You" : "KQUANT AI"}</strong>
                <p>{message.content}</p>
              </div>
              {message.payload?.answer ? <ResearchChatAnswerCard payload={message.payload} text={text} /> : null}
            </article>
          ))
        )}
        {state === "loading" ? (
          <div className="deep-chat-message assistant">
            <div className="deep-chat-bubble">
              <strong>KQUANT AI</strong>
              <p>{text.askingResearch}</p>
            </div>
          </div>
        ) : null}
      </div>
      <form
        className="deep-chat-input"
        onSubmit={(event: FormEvent<HTMLFormElement>) => {
          event.preventDefault();
          onSend();
        }}
      >
        <textarea
          value={input}
          onChange={(event) => onInputChange(event.target.value)}
          placeholder={aiStatus?.status === "available" ? text.askResearchPlaceholder : text.researchChatUnavailable}
          disabled={state === "loading" || aiStatus?.status !== "available"}
        />
        <button type="submit" disabled={state === "loading" || aiStatus?.status !== "available" || !input.trim()}>
          <Send size={15} />
          {state === "loading" ? text.askingResearch : text.askResearch}
        </button>
      </form>
      {aiStatus?.status !== "available" ? <p className="secondary-note">{text.aiUnavailableHint}</p> : null}
    </section>
  );
}

function ResearchChatAnswerCard({ payload, text }: { payload: AiResearchChatPayload; text: (typeof copy)["en"] | (typeof copy)["zh"] }) {
  const answer = payload.answer;
  const isDegraded = payload.status !== "available" || Boolean(payload.fallback_model_used);
  return (
    <div className={`deep-chat-answer-card ${isDegraded ? "degraded" : ""}`}>
      <div className="deep-chat-status-row">
        <span>Status: <strong>{payload.status}</strong></span>
        <span>Model: <strong>{payload.model_name}</strong></span>
        {payload.fallback_model_used ? <span>Fallback: <strong>{payload.primary_model_name ?? "primary"} failed</strong></span> : null}
        {payload.reason && payload.reason !== "ok" ? <span>Reason: <strong>{payload.reason}</strong></span> : null}
      </div>
      {payload.fallback_reason ? <p className="secondary-note">Fallback reason: {payload.fallback_reason}</p> : null}
      <Fact label={text.directView} value={answer.direct_view} />
      <Narrative title={text.keyPoints} items={answer.key_points} />
      <Narrative title={text.risks} items={answer.risk_flags} />
      <Narrative title={text.whatToCheckNext} items={answer.what_to_check_next} />
      {answer.evidence_used?.length ? <Narrative title={text.evidenceUsed} items={answer.evidence_used} /> : null}
      <Narrative title={text.followUps} items={answer.follow_up_questions} />
      <p className="secondary-note">{answer.safety_note}</p>
    </div>
  );
}

function MstrCycleRadar({
  payload,
  state,
  theme,
  lang,
  text,
  onRefresh,
  journal,
  onSaveJournal,
}: {
  payload: MstrCyclePayload | null;
  state: "idle" | "loading" | "ready" | "error";
  theme: Theme;
  lang: Lang;
  text: (typeof copy)["en"] | (typeof copy)["zh"];
  onRefresh: () => void;
  journal: MstrJournalPayload | null;
  onSaveJournal: (entry: { status: string; notes: string; outcome: string }) => Promise<void>;
}) {
  const mstrWeeklyPayload = chartPayload(payload, "mstr_weekly");
  const mstrMonthlyPayload = chartPayload(payload, "mstr_monthly");
  const btcWeeklyPayload = chartPayload(payload, "btc_weekly");
  const relativePayload = chartPayload(payload, "mstr_btc_weekly");
  const mstrWeekly = normalizeCandles(mstrWeeklyPayload.candles, []);
  const mstrMonthly = normalizeCandles(mstrMonthlyPayload.candles, []);
  const btcWeekly = normalizeCandles(btcWeeklyPayload.candles, []);
  const relativeWeekly = normalizeCandles(relativePayload.candles, []);
  const level = payload?.level ?? "WAIT";
  const components = payload?.components;

  return (
    <section className="mstr-radar">
      <section className="panel mstr-hero">
        <div>
          <span className="eyebrow">{text.mstrView}</span>
          <h2>{text.mstrCycleTitle}</h2>
          <p>{text.mstrCycleSubtitle}</p>
        </div>
        <div className="mstr-actions">
          <span className={`level ${mstrLevelClass(level)}`}>{level}</span>
          <button className="primary-action" type="button" onClick={onRefresh}>
            <RefreshCw size={15} />
            {text.refreshMstr}
          </button>
        </div>
      </section>

      <section className="metrics-grid">
        <Metric label={text.bottomScore} value={payload ? `${formatNumber(payload.bottom_score)}/100` : stateLabel(state)} tone={payload?.bottom_score && payload.bottom_score >= 72 ? "good" : "watch"} />
        <Metric label={text.distributionRisk} value={payload ? `${formatNumber(payload.distribution_risk_score)}/100` : "-"} tone={payload?.distribution_risk_score && payload.distribution_risk_score >= 55 ? "warn" : "good"} />
        <Metric label={text.provider} value={payload ? `${payload.provider_status} / ${payload.provider_error_count}` : stateLabel(state)} tone={payload?.provider_error_count ? "warn" : "good"} />
        <Metric label={text.premiumProxy} value={formatPremium(components?.premium_proxy)} tone={components?.premium_proxy?.status === "available" ? "good" : "warn"} />
        <Metric label={text.financingRisk} value={components?.financing_risk?.status ?? "-"} tone={components?.financing_risk?.status === "available" ? "good" : "warn"} />
        <Metric label="BTC Ref" value={payload?.btc_reference_only ? "reference-only" : "-"} />
      </section>

      <StrategyTrackerMetricsPanel payload={payload?.strategy_tracker_metrics} />

      <CycleDashboardPanel
        title={text.cycleDashboard}
        whyTitle={text.whyWait}
        triggerTitle={text.upgradeTriggers}
        tenXPathTitle={text.tenXPath}
        payload={payload?.cycle_dashboard}
      />

      <section className="mstr-ops-grid">
        <TriggerMonitorPanel payload={payload?.trigger_monitor} />
        <HistoryTrendPanel payload={payload?.cycle_history_summary} />
        <PathStressPanel payload={payload?.path_stress_test} />
        <MstrJournalPanel runId={payload?.run_id} journal={journal} onSave={onSaveJournal} />
      </section>

      <section className="panel mstr-component-grid">
        <ComponentBox title={text.btcCycle} component={components?.btc_cycle} />
        <ComponentBox title={text.mstrBottom} component={components?.mstr_bottom} />
        <ComponentBox title={text.relativeBtc} component={components?.relative_btc} />
        <ComponentBox title={text.premiumProxy} component={components?.premium_proxy} />
        <ComponentBox title={text.financingRisk} component={components?.financing_risk} />
        <ComponentBox title={text.distributionRisk} component={components?.distribution_risk} />
      </section>

      <section className="probability-grid">
        <MonteCarloPanel title={text.monteCarlo} payload={payload?.monte_carlo} />
        <BayesianPanel title={text.bayesianBottom} probabilityLabel={text.probability} confidenceLabel={text.confidence} payload={payload?.bayesian_bottom} />
      </section>

      <section className="chart-grid mstr-chart-grid">
        <ChartPanel
          title="MSTR Weekly"
          subtitle="MSTR / 5Y / 1W"
          candles={mstrWeekly}
          theme={theme}
          ohlcHint={text.ohlc}
          emptyText={text.noCandles}
          meta={metaFromPayload(mstrWeeklyPayload, chartPresetByKey("1w"), mstrWeekly)}
          presets={[chartPresetByKey("1w")]}
          presetKey="1w"
          onPresetChange={() => undefined}
          labels={chartLabels(text)}
        />
        <ChartPanel
          title="MSTR Monthly"
          subtitle="MSTR / 10Y / 1M"
          candles={mstrMonthly}
          theme={theme}
          ohlcHint={text.ohlc}
          emptyText={text.noCandles}
          meta={metaFromPayload(mstrMonthlyPayload, chartPresetByKey("1m"), mstrMonthly)}
          presets={[chartPresetByKey("1m")]}
          presetKey="1m"
          onPresetChange={() => undefined}
          labels={chartLabels(text)}
        />
        <ChartPanel
          title="BTC Weekly"
          subtitle="BTC-USD / 5Y / 1W / reference only"
          candles={btcWeekly}
          theme={theme}
          ohlcHint={text.ohlc}
          emptyText={text.noCandles}
          meta={metaFromPayload(btcWeeklyPayload, chartPresetByKey("1w"), btcWeekly)}
          presets={[chartPresetByKey("1w")]}
          presetKey="1w"
          onPresetChange={() => undefined}
          labels={chartLabels(text)}
        />
        <ChartPanel
          title="MSTR/BTC Weekly"
          subtitle="Relative strength / derived from live candles"
          candles={relativeWeekly}
          theme={theme}
          ohlcHint={text.ohlc}
          emptyText={text.noCandles}
          meta={metaFromPayload(relativePayload, chartPresetByKey("1w"), relativeWeekly)}
          presets={[chartPresetByKey("1w")]}
          presetKey="1w"
          onPresetChange={() => undefined}
          labels={chartLabels(text)}
        />
      </section>

      <section className="panel detail-grid mstr-detail-grid">
        <Narrative title={text.reasons} items={payload?.reasons ?? [state === "loading" ? "Loading live MSTR cycle data." : "No MSTR cycle report yet."]} />
        <Narrative title={text.blockers} items={payload?.blockers ?? ["Refresh the radar to generate blockers."]} />
        <Narrative title={text.modelLimitations} items={payload?.model_limitations ?? ["Probability layers load after the live MSTR radar refresh."]} />
        <Narrative title={text.checklist} items={payload?.manual_checklist ?? ["Refresh live MSTR/BTC cycle data."]} />
        <div className="data-box">
          <h3>{text.data}</h3>
          <Fact label="Run" value={payload?.run_id ?? stateLabel(state)} />
          <Fact label="Policy" value={payload?.fixture_user_visible === false ? "live-only / no fixture" : "-"} />
          <Fact label="Broker" value={payload?.broker_order_wiring_enabled === false ? "disabled" : "-"} />
          <Fact label="LLM Core" value={payload?.llm_signal_core_enabled === false ? "locked" : "-"} />
        </div>
      </section>
    </section>
  );
}

function StrategyTrackerMetricsPanel({ payload }: { payload?: MstrStrategyTrackerMetrics }) {
  const treasury = payload?.treasury_snapshot;
  const premium = payload?.premium_nav_metrics;
  const yieldMetrics = payload?.btc_yield_metrics;
  const shares = payload?.share_metrics;
  const debt = payload?.debt_financing_metrics;
  const liquidity = payload?.liquidity_metrics;
  const benchmarks = payload?.benchmark_metrics;
  const cost = payload?.cost_basis_metrics;
  const missing = payload?.missing_tracker_fields ?? [];
  return (
    <section className="panel tracker-metrics-panel">
      <PanelTitle title="StrategyTracker Metrics" detail={`${payload?.tracker_provider_status ?? "not loaded"} / ${payload?.freshness ?? "unknown"}`} />
      <div className="tracker-summary">
        <Fact label="BTC Holdings" value={metricValue(treasury?.btc_holdings)} />
        <Fact label="NAV Premium" value={metricPct(premium?.nav_premium)} />
        <Fact label="Basic mNAV" value={metricMultiple(premium?.basic_mnav)} />
        <Fact label="Avg Cost/BTC" value={metricMoney(cost?.avg_cost_per_btc)} />
        <Fact label="Sats/Share" value={metricValue(shares?.sats_per_diluted_share)} />
        <Fact label="Debt/BTC NAV" value={metricPctFromRatio(debt?.debt_to_btc_nav)} />
      </div>
      <p className="tracker-policy">
        {payload?.calculation_policy ?? "SaylorTracker-style metrics load after refreshing MSTR Radar."}
      </p>
      {missing.length ? <p className="tracker-missing">Missing tracker fields: {missing.slice(0, 8).join(", ")}{missing.length > 8 ? "..." : ""}</p> : null}
      <div className="tracker-grid">
        <MetricBlock
          title="Treasury"
          block={treasury}
          rows={[
            ["BTC Holdings Value", "btc_holdings_value", "money"],
            ["Market Cap", "market_cap", "money"],
            ["Enterprise Value", "enterprise_value", "money"],
            ["BTC Price", "btc_price", "money"],
          ]}
        />
        <MetricBlock
          title="Premium / NAV"
          block={premium}
          rows={[
            ["Market Cap / BTC NAV", "market_cap_to_btc_nav", "multiple"],
            ["EV / BTC NAV", "ev_to_btc_nav", "multiple"],
            ["NAV / Basic Share", "nav_per_basic_share", "money"],
            ["NAV / Diluted Share", "nav_per_diluted_share", "money"],
          ]}
        />
        <MetricBlock
          title="BTC Yield / Gain"
          block={yieldMetrics}
          rows={[
            ["BTC Yield YTD", "btc_yield_ytd", "pct"],
            ["BTC Yield QTD", "btc_yield_qtd", "pct"],
            ["BTC Gain YTD", "btc_gain_ytd", "number"],
            ["BTC $ Gain YTD", "btc_dollar_gain_ytd", "money"],
          ]}
        />
        <MetricBlock
          title="Shares"
          block={shares}
          rows={[
            ["Basic Shares", "basic_shares_outstanding", "number"],
            ["Diluted Shares", "assumed_diluted_shares_outstanding", "number"],
            ["BTC / Basic Share", "btc_per_basic_share", "number"],
            ["Share Dilution", "share_dilution_pct", "pct"],
          ]}
        />
        <MetricBlock
          title="Debt / Financing"
          block={debt}
          rows={[
            ["Total Debt", "total_debt", "money"],
            ["Preferred Stock", "preferred_stock", "money"],
            ["Net Obligations / NAV", "net_obligations_to_btc_nav", "ratioPct"],
            ["ATM Raises", "common_equity_raises_atm", "money"],
          ]}
        />
        <MetricBlock
          title="Liquidity"
          block={liquidity}
          rows={[
            ["Latest Volume", "latest_volume", "number"],
            ["20D Avg Volume", "avg_volume_20d", "number"],
            ["Relative Volume", "relative_volume", "multiple"],
            ["Days to Cover mNAV", "days_to_cover_mnav", "number"],
          ]}
        />
        <MetricBlock
          title="Benchmarks"
          block={benchmarks}
          rows={[
            ["MSTR 3M", "mstr_return_3m_pct", "pct"],
            ["MSTR 1Y", "mstr_return_1y_pct", "pct"],
            ["BTC 1Y", "btc_return_1y_pct", "pct"],
            ["MSTR - BTC 1Y", "mstr_minus_btc_1y_pct", "pct"],
          ]}
        />
      </div>
    </section>
  );
}

function MetricBlock({
  title,
  block,
  rows,
}: {
  title: string;
  block?: MstrMetricBlock;
  rows: [string, string, "number" | "money" | "pct" | "ratioPct" | "multiple"][];
}) {
  return (
    <div className="tracker-block">
      <div className="tracker-block-head">
        <strong>{title}</strong>
        <span>{block?.status ?? "not loaded"}</span>
      </div>
      {rows.map(([label, key, kind]) => (
        <div className="tracker-row" key={`${title}-${key}`}>
          <span>{label}</span>
          <b>{formatTrackerMetric(block?.[key], kind)}</b>
        </div>
      ))}
      <small>{String(block?.source_type ?? "unavailable")} / {String(block?.calculation_method ?? "Refresh MSTR Radar.")}</small>
    </div>
  );
}

function ComponentBox({ title, component }: { title: string; component?: MstrComponent }) {
  const reasons = component?.reasons ?? component?.risk_warnings ?? (component?.reason ? [component.reason] : []);
  return (
    <div className="component-box">
      <div className="component-head">
        <strong>{title}</strong>
        <span>{formatNumber(component?.score)}/100</span>
      </div>
      <p>{component?.status ?? "not loaded"}</p>
      {component?.metrics ? (
        <div className="component-metrics">
          {Object.entries(component.metrics)
            .slice(0, 4)
            .map(([key, value]) => (
              <span key={key}>
                {key.replace(/_/g, " ")} <b>{formatNumber(value)}</b>
              </span>
            ))}
        </div>
      ) : null}
      {reasons.slice(0, 2).map((reason) => (
        <small key={reason}>{reason}</small>
      ))}
    </div>
  );
}

function CycleDashboardPanel({
  title,
  whyTitle,
  triggerTitle,
  tenXPathTitle,
  payload,
}: {
  title: string;
  whyTitle: string;
  triggerTitle: string;
  tenXPathTitle: string;
  payload?: CycleDashboardPayload;
}) {
  const tenXPath = payload?.ten_x_path;
  return (
    <section className="panel cycle-dashboard-panel">
      <PanelTitle title={title} detail={payload?.review_bias ?? "not loaded"} />
      <p className="cycle-summary">{payload?.summary ?? "Refresh MSTR Radar to generate cycle dashboard."}</p>
      <div className="cycle-dashboard-grid">
        <div className="cycle-card">
          <h3>{whyTitle}</h3>
          {(payload?.wait_reasons ?? []).slice(0, 5).map((item) => (
            <div className="cycle-row" key={item.label}>
              <span className={`status-dot ${item.status}`}>{item.status}</span>
              <strong>{item.label}</strong>
              <small>
                {`${String(item.current)} -> ${String(item.target)}`}
              </small>
              <p>{item.why}</p>
            </div>
          ))}
        </div>
        <div className="cycle-card">
          <h3>{triggerTitle}</h3>
          {(payload?.upgrade_triggers ?? []).map((trigger) => (
            <div className="trigger-block" key={trigger.level}>
              <div>
                <strong>{trigger.level}</strong>
                <span>{trigger.status}</span>
              </div>
              {trigger.requirements.slice(0, 3).map((requirement) => (
                <p key={requirement}>{requirement}</p>
              ))}
            </div>
          ))}
        </div>
        <div className="cycle-card tenx-card">
          <h3>{tenXPathTitle}</h3>
          <div className="tenx-facts">
            <Fact label="MSTR now" value={money(tenXPath?.current_mstr_price)} />
            <Fact label="10x target" value={money(tenXPath?.target_mstr_price_10x)} />
            <Fact label="P(10x) 24m" value={`${formatNumber(tenXPath?.monte_carlo_24m_probability_10x_pct)}%`} />
          </div>
          <div className="tenx-table">
            <div className="tenx-row head">
              <span>Premium</span>
              <span>BTC needed</span>
              <span>Multiple</span>
            </div>
            {(tenXPath?.required_btc_prices ?? []).map((row) => (
              <div className="tenx-row" key={row.premium_to_nav}>
                <span>{row.premium_to_nav}x</span>
                <span>{money(row.required_btc_price)}</span>
                <span>{formatNumber(row.btc_multiple_from_current)}x</span>
              </div>
            ))}
          </div>
          <p>{tenXPath?.assumptions?.[0] ?? "10x path loads after live radar refresh."}</p>
        </div>
      </div>
    </section>
  );
}

function TriggerMonitorPanel({ payload }: { payload?: TriggerMonitorPayload }) {
  const grouped = ["BOTTOM WATCH", "CYCLE ACCUMULATION", "DISTRIBUTION RISK"].map((level) => ({
    level,
    conditions: (payload?.conditions ?? []).filter((condition) => condition.level === level),
  }));
  return (
    <section className="panel compact-panel">
      <PanelTitle title="MSTR Trigger Monitor" detail={payload?.next_state ?? "not loaded"} />
      <div className="compact-body">
        <div className="mini-fact-grid">
          <Fact label="Bottom Watch Gap" value={formatNumber(payload?.gaps?.bottom_watch_score_gap)} />
          <Fact label="Accumulation Gap" value={formatNumber(payload?.gaps?.cycle_accumulation_score_gap)} />
          <Fact label="Distribution Gap" value={formatNumber(payload?.gaps?.distribution_risk_score_gap)} />
        </div>
        {grouped.map((group) => (
          <div className="condition-group" key={group.level}>
            <strong>{group.level}</strong>
            {(group.conditions.length ? group.conditions : [{ name: "Refresh radar to calculate conditions", met: false, current: "-", target: "-", comparator: "" } as TriggerMonitorCondition]).map(
              (condition) => (
                <div className="condition-row" key={`${group.level}-${condition.name}`}>
                  <span className={condition.met ? "check-dot met" : "check-dot"}>{condition.met ? "OK" : "..."}</span>
                  <p>{condition.name}</p>
                  <small>
                    {String(condition.current)} {condition.comparator} {String(condition.target)}
                  </small>
                </div>
              ),
            )}
          </div>
        ))}
      </div>
    </section>
  );
}

function HistoryTrendPanel({ payload }: { payload?: CycleHistorySummary }) {
  return (
    <section className="panel compact-panel">
      <PanelTitle title="Historical Trend" detail={payload?.trend ?? "not scanned"} />
      <div className="compact-body">
        <div className="mini-fact-grid">
          <Fact label="Runs" value={String(payload?.run_count ?? 0)} />
          <Fact label="Latest Level" value={payload?.latest_level ?? "-"} />
          <Fact label="Score Change" value={formatSigned(payload?.score_change)} />
          <Fact label="Bayes Change" value={`${formatSigned(payload?.probability_change)}%`} />
          <Fact label="Premium" value={`${formatNumber(payload?.latest_premium_to_nav)}x`} />
          <Fact label="P(10x) 24m" value={`${formatNumber(payload?.latest_mc_24m_probability_10x)}%`} />
        </div>
        <p className="probability-note">
          Latest: {payload?.latest_completed_at ?? "-"} / first stored: {payload?.first_completed_at ?? "-"}
        </p>
      </div>
    </section>
  );
}

function PathStressPanel({ payload }: { payload?: PathStressPayload }) {
  const rows = payload?.rows ?? [];
  return (
    <section className="panel compact-panel stress-panel">
      <PanelTitle title="10x Stress Test" detail={payload?.status ?? "not loaded"} />
      <p className="probability-note">{payload?.question ?? payload?.reason ?? "Refresh MSTR Radar to calculate dilution and premium stress."}</p>
      <div className="stress-table">
        <div className="stress-row head">
          <span>Dilution</span>
          <span>Premium</span>
          <span>BTC Needed</span>
          <span>Multiple</span>
        </div>
        {rows.length ? (
          rows.slice(0, 12).map((row) => (
            <div className="stress-row" key={`${row.dilution_rate_pct}-${row.premium_to_nav}`}>
              <span>{formatNumber(row.dilution_rate_pct)}%</span>
              <span>{row.premium_to_nav}x</span>
              <span>{money(row.required_btc_price)}</span>
              <span>{formatNumber(row.btc_multiple_from_current)}x</span>
            </div>
          ))
        ) : (
          <div className="stress-row">
            <span>-</span>
            <span>-</span>
            <span>-</span>
            <span>-</span>
          </div>
        )}
      </div>
      {payload?.assumptions?.length ? <p className="probability-note">{payload.assumptions[0]}</p> : null}
    </section>
  );
}

function StockJournalPanel({
  runId,
  symbol,
  journal,
  onSave,
}: {
  runId: string;
  symbol: string;
  journal: StockJournalPayload | null;
  onSave: (entry: { status: string; notes: string; planned_entry?: string; planned_stop?: string; planned_target?: string; outcome: string }) => Promise<void>;
}) {
  const [status, setStatus] = useState("reviewed");
  const [notes, setNotes] = useState("");
  const [plannedEntry, setPlannedEntry] = useState("");
  const [plannedStop, setPlannedStop] = useState("");
  const [plannedTarget, setPlannedTarget] = useState("");
  const [outcome, setOutcome] = useState("");
  const [saveState, setSaveState] = useState<"idle" | "saving" | "saved" | "error">("idle");

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    try {
      setSaveState("saving");
      await onSave({
        status,
        notes,
        planned_entry: plannedEntry,
        planned_stop: plannedStop,
        planned_target: plannedTarget,
        outcome,
      });
      setNotes("");
      setPlannedEntry("");
      setPlannedStop("");
      setPlannedTarget("");
      setOutcome("");
      setSaveState("saved");
    } catch {
      setSaveState("error");
    }
  }

  return (
    <section className="journal-panel">
      <PanelTitle title="Manual Journal" detail={`${symbol} / ${journal?.entries.length ?? 0} entries`} />
      <form className="journal-form stock-journal-form" onSubmit={handleSubmit}>
        <select value={status} onChange={(event) => setStatus(event.target.value)}>
          <option value="reviewed">reviewed</option>
          <option value="watch">watch</option>
          <option value="skipped">skipped</option>
          <option value="paper-observed">paper-observed</option>
          <option value="manual-traded">manual-traded note</option>
          <option value="entered-manually">entered manually</option>
          <option value="exited-manually">exited manually</option>
          <option value="invalidated">invalidated</option>
        </select>
        <textarea value={notes} onChange={(event) => setNotes(event.target.value)} placeholder="Manual review note: daily, 1H, regime, entry plan..." />
        <div className="journal-price-grid">
          <input value={plannedEntry} onChange={(event) => setPlannedEntry(event.target.value)} placeholder="Planned entry" inputMode="decimal" />
          <input value={plannedStop} onChange={(event) => setPlannedStop(event.target.value)} placeholder="Planned stop" inputMode="decimal" />
          <input value={plannedTarget} onChange={(event) => setPlannedTarget(event.target.value)} placeholder="Planned target" inputMode="decimal" />
        </div>
        <input value={outcome} onChange={(event) => setOutcome(event.target.value)} placeholder="Outcome / follow-up" />
        <button className="primary-action" type="submit" disabled={saveState === "saving"}>
          {saveState === "saving" ? "Saving..." : "Save Journal"}
        </button>
        {saveState === "saved" ? <small>Saved locally. Read-only note only.</small> : null}
        {saveState === "error" ? <small>Save failed. Check local API and try again.</small> : null}
      </form>
      <div className="journal-list">
        {(journal?.entries ?? []).slice(0, 4).map((entry) => (
          <div className="journal-entry" key={entry.id}>
            <strong>{entry.status}</strong>
            <span>{entry.reviewed_at}</span>
            <p>{entry.notes || entry.outcome || "No note"}</p>
            <small>
              {entry.strategy_profile || "profile"} / entry {formatNumber(entry.planned_entry)} / stop {formatNumber(entry.planned_stop)} / target {formatNumber(entry.planned_target)}
            </small>
            <small>
              Rule {entry.rule_conclusion || "-"} / AI {entry.ai_review_verdict || "-"}
            </small>
          </div>
        ))}
        {journal && journal.entries.length === 0 ? <p className="probability-note">No manual stock review entries yet.</p> : null}
      </div>
    </section>
  );
}

function SettingsPanel({
  apiConnection,
  aiStatus,
  apiBaseUrl,
  apiHealth,
  text,
}: {
  apiConnection: ApiConnectionState;
  aiStatus: AiReviewStatusPayload | null;
  apiBaseUrl: string;
  apiHealth: ApiHealthPayload | null;
  text: (typeof copy)["en"] | (typeof copy)["zh"];
}) {
  return (
    <section className="panel settings-panel" id="settings-workspace">
      <div className="settings-head">
        <div>
          <span>{text.settingsNav}</span>
          <h2>{text.settingsTitle}</h2>
          <p>{text.settingsDescription}</p>
        </div>
        <Pill tone="neutral" icon={<ShieldCheck size={14} />} label={text.researchSignalOnly} />
      </div>
      <div className="settings-grid">
        <div className="settings-card">
          <strong>{text.currentLocalMode}</strong>
          <p>Local backend: {apiHealth?.backend ?? "127.0.0.1:8001"} / SQLite: work/kquant_us.sqlite3</p>
          <p>Status: {apiConnection === "connected" ? "live API connected" : "live API offline"}</p>
        </div>
        <div className="settings-card">
          <strong>{text.futureSaasTarget}</strong>
          <p>{text.futureSaasCopy}</p>
          <p>{text.paymentDisabled}</p>
        </div>
        <div className="settings-card">
          <strong>{text.dataSourceTitle}</strong>
          <p>{text.dataSourceCopy}</p>
          <p>{text.remoteApi}: {apiBaseUrl ? apiBaseUrl : "not configured"}</p>
        </div>
        <div className="settings-card">
          <strong>{text.aiStatusTitle}</strong>
          <p>{aiStatus?.status === "available" ? `Connected: ${aiStatus.models.review ?? "review model"}` : "Missing backend OPENAI_API_KEY"}</p>
          <p>{text.aiStatusCopy}</p>
        </div>
        <div className="settings-card wide">
          <strong>{text.consumerSafetyCopy}</strong>
          <p>{text.consumerSafetyText}</p>
        </div>
        <div className="settings-card wide">
          <strong>{text.journalDesign}</strong>
          <p>{text.journalDesignText}</p>
        </div>
      </div>
    </section>
  );
}

function DataReliabilityPanel({
  apiConnection,
  apiHealth,
  run,
  dailyMeta,
  hourlyMeta,
  selectedSymbol,
  apiBaseUrl,
}: {
  apiConnection: ApiConnectionState;
  apiHealth: ApiHealthPayload | null;
  run: SignalRun;
  dailyMeta: CandleMeta;
  hourlyMeta: CandleMeta;
  selectedSymbol: string;
  apiBaseUrl: string;
}) {
  const available = run.provider_coverage?.available ?? 0;
  const stale = run.provider_coverage?.stale_or_partial ?? 0;
  const failed = run.provider_coverage?.failed ?? run.provider_error_count ?? 0;
  const candleTimes = [dailyMeta.last, hourlyMeta.last].filter(Boolean).sort();
  const latestCandle = candleTimes[candleTimes.length - 1] ?? "-";
  const worstStatus =
    apiConnection !== "connected"
      ? "Live API offline"
      : dailyMeta.providerStatus === "available" || hourlyMeta.providerStatus === "available"
        ? "Live data available"
        : run.provider_status === "available"
          ? "Latest scan available"
          : "Provider degraded";
  return (
    <section className="panel data-reliability-panel" id="data-reliability-workspace">
      <div className="data-reliability-head">
        <div>
          <span>Data Reliability</span>
          <h2>{worstStatus}</h2>
          <p>
            User-facing charts stay live-only. If Yahoo/public data fails, KQUANT shows provider failed or stale real cache instead of synthetic candles.
          </p>
        </div>
        <Pill
          tone={apiConnection === "connected" ? "good" : "warn"}
          icon={<Activity size={14} />}
          label={apiConnection === "connected" ? "Live backend connected" : "Live backend offline"}
        />
      </div>
      <div className="data-reliability-grid">
        <Fact label="Provider Status" value={`${run.provider_status} / errors ${run.provider_error_count}`} />
        <Fact label="Coverage" value={`${available} live / ${stale} stale / ${failed} failed`} />
        <Fact label="Scanned Symbols" value={`${run.scanned_count ?? run.counts.total}/${run.universe_total ?? run.counts.total}`} />
        <Fact label="Last Candle" value={`${selectedSymbol} / ${latestCandle}`} />
        <Fact label="Selected Daily" value={`${dailyMeta.providerStatus} / ${dailyMeta.count} candles`} />
        <Fact label="Selected Confirm" value={`${hourlyMeta.providerStatus} / ${hourlyMeta.count} candles`} />
        <Fact label="Stale Age" value={`${dailyMeta.staleAge || "none"} / ${hourlyMeta.staleAge || "none"}`} />
        <Fact label="Environment" value={apiBaseUrl ? `remote API ${apiBaseUrl.replace(/^https?:\/\//, "")}` : `local ${apiHealth?.backend ?? "stdlib_server"}`} />
      </div>
    </section>
  );
}

function AiTradeDesk({
  report,
  state,
  autoRunState,
  aiStatus,
  selectedUniverse,
  lang,
  text,
  onRun,
  onPick,
}: {
  report: AiDailyAgentPayload | null;
  state: "idle" | "loading" | "ready" | "error";
  autoRunState: "idle" | "checking" | "generating" | "ready" | "skipped" | "unavailable" | "error";
  aiStatus: AiReviewStatusPayload | null;
  selectedUniverse: UniverseName;
  lang: Lang;
  text: (typeof copy)["en"] | (typeof copy)["zh"];
  onRun: () => void;
  onPick: (symbol: string) => void;
}) {
  const aiConnected = aiStatus?.status === "available";
  const aiReport = report?.ai_report;
  const top = aiReport?.top_buy_candidates ?? [];
  const watch = aiReport?.watch_for_pullback ?? [];
  const warnings = aiReport?.data_quality_warnings ?? [];
  return (
    <section className="panel ai-trade-desk">
      <div className="ai-trade-desk-head">
        <div>
          <span>{text.aiToday}</span>
          <h2>{text.aiResearchSignals}</h2>
          <p>
            {text.aiTodayDescription.replace("{universe}", universeOptionLabel(selectedUniverse, lang))}
          </p>
        </div>
        <div className="ai-trade-desk-actions">
          <Pill
            tone={aiConnected ? "good" : "warn"}
            icon={<Activity size={14} />}
            label={aiConnected ? `AI: ${aiStatus?.models.batch ?? "batch"}` : text.aiUnavailableUntilKey}
          />
          <button className="primary-action" type="button" onClick={onRun} disabled={state === "loading"}>
            <RefreshCw size={15} />
            {state === "loading" ? text.generating : text.refreshAiSignals}
          </button>
        </div>
      </div>
      <div className="ai-trade-summary">
        <Fact label={text.status} value={report?.status ?? "not_scanned"} />
        <Fact label={text.autoAgent} value={autoRunState} />
        <Fact label={text.freshness} value={report?.is_stale ? `stale ${report.age_seconds ?? "-"}s` : "fresh"} />
        <Fact label={text.model} value={report?.model_name ?? aiStatus?.models.batch ?? "-"} />
        <Fact label={text.candidates} value={String(report?.ai_context_candidate_count ?? 0)} />
        <Fact label={text.readOnlyShort} value={report?.broker_order_wiring_enabled === false ? text.noBrokerNoOrder : text.guarded} />
      </div>
      <div className="ai-opportunity-grid">
        <AiOpportunityColumn title={text.topAiSignals} empty={text.noAiCandidate} items={top} onPick={onPick} />
        <AiOpportunityColumn title={text.watchForPullback} empty={text.noAiWatchlist} items={watch.slice(0, 5)} onPick={onPick} />
        <AiOpportunityColumn
          title={text.dataRiskWarnings}
          empty={text.noWarnings}
          items={warnings.slice(0, 5).map((warning, index) => ({
            symbol: `WARN${index + 1}`,
            action: "AI_AVOID",
            confidence: "LOW",
            best_profile: "data_quality",
            entry_zone: warning,
            stop_zone: "",
            target_zone: "",
            risk_reward: "",
            position_size_hint: "",
            why_now: [warning],
            risk_flags: [warning],
          }))}
          onPick={() => undefined}
          passive
        />
      </div>
      <p className="secondary-note">
        {aiReport?.daily_summary ??
          report?.last_error ??
          report?.reason ??
          text.aiDailyFallback}
      </p>
    </section>
  );
}

function AiOpportunityColumn({
  title,
  empty,
  items,
  onPick,
  passive = false,
}: {
  title: string;
  empty: string;
  items: AiDailyItem[];
  onPick: (symbol: string) => void;
  passive?: boolean;
}) {
  return (
    <div className="ai-opportunity-column">
      <strong>{title}</strong>
      {items.length ? (
        items.map((item) => (
          <button
            type="button"
            className={`ai-opportunity-card ${actionClass(item.action)}`}
            key={`${title}-${item.symbol}-${item.best_profile}`}
            onClick={() => (!passive && item.symbol ? onPick(item.symbol) : undefined)}
            disabled={passive}
          >
            <div>
              <b>{item.symbol}</b>
              <span>{item.action} / {item.confidence}</span>
            </div>
            <small>{item.best_profile || "AI plan"} / R:R {item.risk_reward || "-"}</small>
            <p>{item.entry_zone || item.why_now?.[0] || "Open for details."}</p>
            {item.hard_veto_applied ? <em>Hard veto applied</em> : null}
          </button>
        ))
      ) : (
        <p className="probability-note">{empty}</p>
      )}
    </div>
  );
}

function MondayReadinessPanel({
  readiness,
  text,
}: {
  readiness: MondayReadiness;
  text: (typeof copy)["en"] | (typeof copy)["zh"];
}) {
  const statusLabel =
    readiness.status === "READY"
      ? text.readinessReady
      : readiness.status === "CAUTION"
        ? text.readinessCaution
        : text.readinessNoTrade;
  return (
    <section className={`panel live-readiness-panel ${readiness.status.toLowerCase().replace(/_/g, "-")}`}>
      <div className="readiness-head">
        <div>
          <span className="eyebrow">{text.realMoneyPilot}</span>
          <h2>{text.mondayReadiness}</h2>
          <p>{readiness.summary}</p>
        </div>
        <b>{statusLabel}</b>
      </div>
      {readiness.status === "NO_TRADE" ? <p className="compare-error">{text.noRealMoneyTrade}</p> : null}
      <div className="readiness-check-grid">
        {readiness.checks.map((check) => (
          <div className={`readiness-check ${check.ok ? "ok" : check.critical ? "critical" : "warn"}`} key={check.label}>
            <span>{check.label}</span>
            <strong>{check.value}</strong>
          </div>
        ))}
      </div>
      {readiness.reasons.length ? (
        <div className="readiness-reasons">
          {readiness.reasons.map((reason) => (
            <span key={reason}>{reason}</span>
          ))}
        </div>
      ) : null}
      <div className="pilot-runbook">
        <strong>{text.firstDayRiskRules}</strong>
        {readiness.riskRules.map((rule) => (
          <span key={rule}>{rule}</span>
        ))}
      </div>
      <div className="pilot-runbook compact">
        <strong>{text.mondayRunbook}</strong>
        {[text.runbookPremarket, text.runbookOpen, text.runbookEntry, text.runbookClose].map((step) => (
          <span key={step}>{step}</span>
        ))}
      </div>
    </section>
  );
}

function ManualTradeTicketPanel({
  ticket,
  aiDecision,
  text,
  onOpenJournal,
}: {
  ticket: ManualTradeTicket;
  aiDecision: AiDecisionPayload | null;
  text: (typeof copy)["en"] | (typeof copy)["zh"];
  onOpenJournal: () => void;
}) {
  const title =
    ticket.status === "cleared_for_review"
      ? text.clearedForReview
      : ticket.status === "journal_required"
        ? text.journalRequired
        : text.ticketBlocked;
  return (
    <section className={`manual-ticket ${ticket.status.replace(/_/g, "-")}`}>
      <div className="manual-ticket-head">
        <div>
          <span>{text.manualTradeTicket}</span>
          <strong>{title}</strong>
          <p>{ticket.summary}</p>
        </div>
        <b>{ticket.action}</b>
      </div>
      <div className="manual-ticket-grid">
        <Fact label={text.entryZone} value={ticket.entryZone} />
        <Fact label={text.stopZone} value={ticket.stopZone} />
        <Fact label={text.targetZone} value={ticket.targetZone} />
        <Fact label={text.riskReward} value={ticket.riskReward} />
        <Fact label={text.sizeHint} value={ticket.positionSizeHint} />
        <Fact label={text.hardVeto} value={aiDecision?.hard_veto?.active ? "active" : "clear"} />
      </div>
      <div className="readiness-check-grid compact">
        {ticket.checks.map((check) => (
          <div className={`readiness-check ${check.ok ? "ok" : "critical"}`} key={check.label}>
            <span>{check.label}</span>
            <strong>{check.value}</strong>
          </div>
        ))}
      </div>
      <div className="manual-conclusion-detail">
        <Narrative title={text.invalidation} items={ticket.invalidatedIf.length ? ticket.invalidatedIf : ["No invalidation loaded."]} />
        <Narrative title={text.blockers} items={ticket.reasons.length ? ticket.reasons : ["All ticket checks are clear."]} />
      </div>
      <div className="ticket-actions">
        <button type="button" className="primary-action" onClick={onOpenJournal}>
          {text.journalBeforeTrade}
        </button>
      </div>
    </section>
  );
}

function ManualTradingConclusion({
  conclusion,
  aiReview,
  aiReviewState,
  aiDecision,
  aiDecisionState,
  aiStatus,
  text,
  onReview,
}: {
  conclusion: StockSignal["trade_conclusion"] | undefined;
  aiReview: AiReviewPayload | null;
  aiReviewState: "idle" | "loading" | "ready" | "error";
  aiDecision: AiDecisionPayload | null;
  aiDecisionState: "idle" | "loading" | "ready" | "error";
  aiStatus: AiReviewStatusPayload | null;
  text: (typeof copy)["en"] | (typeof copy)["zh"];
  onReview: () => void;
}) {
  const action = conclusion?.action ?? "DO_NOT_BUY";
  const ai = aiReview?.ai_review;
  const decision = aiDecision?.ai_decision;
  const displayAction = decision?.action ?? action;
  const displaySummary = decision?.summary ?? conclusion?.decision_summary ?? "No rule conclusion loaded yet.";
  const aiConnected = aiStatus?.status === "available";
  const aiReviewRequired =
    conclusion?.profile_name === "high_beta_growth_v1" && (action === "BUY" || action === "WAIT");
  return (
    <section className={`manual-conclusion ${actionClass(displayAction)}`}>
      <div className="manual-conclusion-main">
        <span>{text.aiTradingCommand}</span>
        <strong>{displayAction}</strong>
        <p>{displaySummary}</p>
        {aiReviewRequired ? (
          <p className="compare-error">
            {text.aiReviewRequired}
          </p>
        ) : null}
      </div>
      <div className="manual-conclusion-facts">
        <Fact label="Confidence" value={conclusion?.confidence ?? "-"} />
        <Fact label="Risk Bucket" value={conclusion?.risk_bucket ?? "-"} />
        <Fact label="Position" value={conclusion?.position_context ?? "no_position_assumed"} />
      </div>
      <div className="manual-conclusion-actions">
        <button type="button" onClick={onReview} disabled={aiDecisionState === "loading"}>
          {aiDecisionState === "loading" ? text.aiCommandGenerating : aiConnected ? text.regenerateAiCommand : text.aiKeyRequired}
        </button>
        <small>
          {aiConnected
            ? `Model: ${aiStatus?.models.review ?? "review"} / ${text.aiModelNote}`
            : aiStatus?.setup_hint ?? text.aiUnavailableHint}
        </small>
      </div>
      {aiDecisionState === "ready" && aiDecision ? (
        <div className={`ai-decision-panel ${actionClass(decision?.action)}`}>
          <div className="ai-review-head">
            <strong>{text.aiSignalPlan}</strong>
            <span>{aiDecision.status} / {aiDecision.model_name}</span>
          </div>
          <div className="ai-review-facts">
            <Fact label={text.aiAction} value={decision?.action ?? "-"} />
            <Fact label={text.confidence} value={decision?.confidence ?? "-"} />
            <Fact label={text.hardVeto} value={aiDecision.hard_veto?.active ? "active" : "clear"} />
          </div>
          <div className="ai-plan-grid">
            <Fact label={text.entryZone} value={decision?.entry_zone ?? "-"} />
            <Fact label={text.stopZone} value={decision?.stop_zone ?? "-"} />
            <Fact label={text.targetZone} value={decision?.target_zone ?? "-"} />
            <Fact label={text.riskReward} value={decision?.risk_reward ?? "-"} />
            <Fact label={text.sizeHint} value={decision?.position_size_hint ?? "-"} />
            <Fact label={text.bestProfile} value={decision?.best_profile ?? "-"} />
          </div>
          <Narrative title={text.whyNow} items={decision?.why_now?.length ? decision.why_now : ["No AI decision reasons."]} />
          <Narrative title={text.invalidation} items={decision?.what_invalidates_this_setup?.length ? decision.what_invalidates_this_setup : ["No AI invalidation."]} />
          <Narrative title={text.humanChecklist} items={decision?.human_checklist?.length ? decision.human_checklist : ["Save journal before acting manually."]} />
          {aiDecision.hard_veto?.active ? <p className="compare-error">Hard veto: {aiDecision.hard_veto.reasons.join("; ")}</p> : null}
          <p className="secondary-note">{decision?.summary ?? aiDecision.reason}</p>
        </div>
      ) : null}
      <div className="manual-conclusion-detail">
        <Narrative title={text.why} items={conclusion?.why?.length ? conclusion.why : ["Run analysis to load rule reasons."]} />
        <Narrative title={text.blockers} items={conclusion?.blockers?.length ? conclusion.blockers : ["No hard blocker listed."]} />
        <Narrative title={text.invalidation} items={conclusion?.invalidation?.length ? conclusion.invalidation : ["No invalidation loaded."]} />
      </div>
      {aiReviewState === "ready" && aiReview ? (
        <div className="ai-review-panel">
          <div className="ai-review-head">
            <strong>AI Review</strong>
            <span>{aiReview.status} / {aiReview.model_name}</span>
          </div>
          <div className="ai-review-facts">
            <Fact label="Verdict" value={ai?.ai_review_verdict ?? "-"} />
            <Fact label="Quality" value={ai?.quality_filter ?? "-"} />
            <Fact label="Downgrade" value={ai?.downgrade_suggestion ?? "-"} />
          </div>
          <Narrative title="R/R Improvement" items={ai?.rr_improvement_notes?.length ? ai.rr_improvement_notes : ["No AI review notes."]} />
          <Narrative title="Risk Questions" items={ai?.risk_questions?.length ? ai.risk_questions : ["No AI risk questions."]} />
          <Narrative title="Journal Prompt" items={ai?.journal_prompt?.length ? ai.journal_prompt : ["No AI journal prompt."]} />
          <p className="secondary-note">{ai?.summary ?? aiReview.reason}</p>
        </div>
      ) : null}
      {aiDecisionState === "error" ? <p className="compare-error">{text.aiRequestFailed}</p> : null}
      {!aiConnected && aiDecisionState === "idle" ? (
        <p className="compare-error">{text.aiNotActive}</p>
      ) : null}
    </section>
  );
}

function MstrJournalPanel({
  runId,
  journal,
  onSave,
}: {
  runId?: string;
  journal: MstrJournalPayload | null;
  onSave: (entry: { status: string; notes: string; outcome: string }) => Promise<void>;
}) {
  const [status, setStatus] = useState("reviewed");
  const [notes, setNotes] = useState("");
  const [outcome, setOutcome] = useState("");
  const [saveState, setSaveState] = useState<"idle" | "saving" | "saved" | "error">("idle");

  async function handleSubmit(event: FormEvent) {
    event.preventDefault();
    if (!runId) return;
    try {
      setSaveState("saving");
      await onSave({ status, notes, outcome });
      setNotes("");
      setOutcome("");
      setSaveState("saved");
    } catch {
      setSaveState("error");
    }
  }

  return (
    <section className="panel compact-panel journal-panel">
      <PanelTitle title="MSTR Cycle Journal" detail={`${journal?.entries.length ?? 0} entries`} />
      <form className="journal-form" onSubmit={handleSubmit}>
        <select value={status} onChange={(event) => setStatus(event.target.value)} disabled={!runId}>
          <option value="reviewed">reviewed</option>
          <option value="wait">wait</option>
          <option value="staged-watch">staged-watch</option>
          <option value="invalidated">invalidated</option>
        </select>
        <textarea value={notes} onChange={(event) => setNotes(event.target.value)} placeholder="Manual review note: BTC weekly, MSTR weekly, premium, blockers..." disabled={!runId} />
        <input value={outcome} onChange={(event) => setOutcome(event.target.value)} placeholder="Outcome / follow-up" disabled={!runId} />
        <button className="primary-action" type="submit" disabled={!runId || saveState === "saving"}>
          {saveState === "saving" ? "Saving..." : "Save Journal"}
        </button>
        {saveState === "saved" ? <small>Saved locally.</small> : null}
        {saveState === "error" ? <small>Save failed. Run radar first and try again.</small> : null}
      </form>
      <div className="journal-list">
        {(journal?.entries ?? []).slice(0, 5).map((entry) => (
          <div className="journal-entry" key={entry.id}>
            <strong>{entry.status}</strong>
            <span>{entry.reviewed_at}</span>
            <p>{entry.notes || entry.outcome || "No note"}</p>
            <small>
              {entry.level} / score {formatNumber(entry.bottom_score)} / Bayes {formatNumber(entry.bayesian_bottom_probability)}%
            </small>
          </div>
        ))}
        {journal && journal.entries.length === 0 ? <p className="probability-note">No manual MSTR cycle review entries yet.</p> : null}
      </div>
    </section>
  );
}

function MonteCarloPanel({ title, payload }: { title: string; payload?: MonteCarloPayload }) {
  const horizons = Object.entries(payload?.horizons ?? {});
  return (
    <section className="panel probability-panel">
      <PanelTitle
        title={title}
        detail={payload?.status === "available" ? `${payload.paths} paths / beta ${formatNumber(payload.beta_to_btc)}` : (payload?.status ?? "not loaded")}
      />
      {payload?.status === "available" && horizons.length ? (
        <div className="scenario-table">
          <div className="scenario-row head">
            <span>Horizon</span>
            <span>P10</span>
            <span>Median</span>
            <span>P90</span>
            <span>Max DD</span>
            <span>2x</span>
            <span>5x</span>
            <span>10x</span>
          </div>
          {horizons.map(([label, stats]) => (
            <div className="scenario-row" key={label}>
              <span>{label}</span>
              <span>{formatNumber(stats.p10_return_pct)}%</span>
              <span>{formatNumber(stats.median_return_pct)}%</span>
              <span>{formatNumber(stats.p90_return_pct)}%</span>
              <span>{formatNumber(stats.median_max_drawdown_pct)}%</span>
              <span>{formatNumber(stats.probability_2x_pct)}%</span>
              <span>{formatNumber(stats.probability_5x_pct)}%</span>
              <span>{formatNumber(stats.probability_10x_pct)}%</span>
            </div>
          ))}
        </div>
      ) : (
        <div className="probability-empty">{payload?.reason ?? "Run the radar to generate scenario distribution."}</div>
      )}
      {payload?.limitations?.length ? <p className="probability-note">{payload.limitations[0]}</p> : null}
    </section>
  );
}

function BayesianPanel({
  title,
  probabilityLabel,
  confidenceLabel,
  payload,
}: {
  title: string;
  probabilityLabel: string;
  confidenceLabel: string;
  payload?: BayesianBottomPayload;
}) {
  return (
    <section className="panel probability-panel">
      <PanelTitle title={title} detail={payload?.method ?? "not loaded"} />
      <div className="bayes-summary">
        <Fact label={probabilityLabel} value={`${formatNumber(payload?.bottom_probability)}%`} />
        <Fact label={confidenceLabel} value={`${formatNumber(payload?.confidence)}%`} />
        <Fact
          label="Band"
          value={
            payload?.confidence_band
              ? `${formatNumber(payload.confidence_band.low)}% - ${formatNumber(payload.confidence_band.high)}%`
              : "-"
          }
        />
      </div>
      <div className="evidence-grid">
        <EvidenceList title="Positive Evidence" items={payload?.positive_evidence ?? []} />
        <EvidenceList title="Negative Evidence" items={payload?.negative_evidence ?? []} />
      </div>
      {payload?.limitations?.length ? <p className="probability-note">{payload.limitations[0]}</p> : null}
    </section>
  );
}

function EvidenceList({ title, items }: { title: string; items: BayesianEvidence[] }) {
  return (
    <div className="evidence-list">
      <h3>{title}</h3>
      {items.length ? (
        items.slice(0, 5).map((item) => (
          <p key={`${item.name}-${item.likelihood_ratio}`}>
            <strong>{item.name}</strong>
            <span>LR {item.likelihood_ratio}</span>
            {item.reason}
          </p>
        ))
      ) : (
        <p>No evidence yet.</p>
      )}
    </div>
  );
}

function ChartPanel({
  title,
  subtitle,
  candles,
  theme,
  ohlcHint,
  emptyText,
  meta,
  presets,
  presetKey,
  onPresetChange,
  onReload,
  labels,
}: {
  title: string;
  subtitle: string;
  candles: Candle[];
  theme: Theme;
  ohlcHint: string;
  emptyText: string;
  meta: CandleMeta;
  presets: ChartPreset[];
  presetKey: ChartPresetKey;
  onPresetChange: (value: string) => void;
  onReload?: () => void;
  labels: {
    source: string;
    status: string;
    range: string;
    candles: string;
    firstLast: string;
  };
}) {
  const panelRef = useRef<HTMLElement | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [hover, setHover] = useState<OhlcState | null>(null);
  const indicators = useMemo(
    () => ({ ema20: ema(candles, 20), ema50: ema(candles, 50), ema200: ema(candles, 200), vwap: vwap(candles) }),
    [candles],
  );
  const effectiveEmptyText = meta.providerStatus === "refreshing" ? "Refreshing real data..." : emptyText;
  const openFullscreen = () => {
    const node = panelRef.current;
    if (node?.requestFullscreen) {
      void node.requestFullscreen();
    }
  };

  useEffect(() => {
    if (!containerRef.current) return;
    const container = containerRef.current;
    container.innerHTML = "";
    const dark = theme === "dark";
    const chart = createChart(container, {
      width: container.clientWidth,
      height: container.clientHeight,
      autoSize: true,
      layout: {
        background: { color: dark ? "#0f172a" : "#ffffff" },
        textColor: dark ? "#94a3b8" : "#64748b",
        fontFamily: "Inter, ui-sans-serif, system-ui, sans-serif",
      },
      grid: {
        vertLines: { color: dark ? "#1e293b" : "#eef2f7" },
        horzLines: { color: dark ? "#1e293b" : "#eef2f7" },
      },
      rightPriceScale: { borderColor: dark ? "#263241" : "#e5e7eb" },
      timeScale: { borderColor: dark ? "#263241" : "#e5e7eb", timeVisible: true },
      handleScroll: { mouseWheel: false, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: false },
      handleScale: { mouseWheel: false, pinch: true, axisPressedMouseMove: true },
    });

    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: "#16a34a",
      downColor: "#ef4444",
      wickUpColor: "#16a34a",
      wickDownColor: "#ef4444",
      borderVisible: false,
      priceLineColor: "#2563eb",
    });
    candleSeries.setData(candles as CandlestickData<Time>[]);

    const volumeSeries = chart.addSeries(HistogramSeries, {
      color: "rgba(99, 102, 241, 0.22)",
      priceFormat: { type: "volume" },
      priceScaleId: "",
    });
    volumeSeries.priceScale().applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });
    volumeSeries.setData(
      candles.map((bar) => ({
        time: bar.time,
        value: bar.volume,
        color: bar.close >= bar.open ? "rgba(22, 163, 74, 0.24)" : "rgba(239, 68, 68, 0.22)",
      })) as HistogramData<Time>[],
    );

    addLine(chart, indicators.ema20, "#2563eb");
    addLine(chart, indicators.ema50, "#f59e0b");
    if (indicators.ema200.length) addLine(chart, indicators.ema200, "#0f766e");
    addLine(chart, indicators.vwap, "#7c3aed");
    chart.timeScale().fitContent();
    chart.subscribeCrosshairMove((param) => {
      const point = param.seriesData.get(candleSeries);
      if (!point || !("open" in point)) {
        setHover(null);
        return;
      }
      setHover({
        time: String(point.time),
        open: point.open,
        high: point.high,
        low: point.low,
        close: point.close,
      });
    });
    return () => chart.remove();
  }, [candles, indicators.ema20, indicators.ema50, indicators.ema200, indicators.vwap, theme]);

  return (
    <section className="panel chart-panel" ref={panelRef}>
      <div className="chart-header">
        <div>
          <h3>{title}</h3>
          <p>{subtitle}</p>
        </div>
        <div className="chart-tools">
          <Segmented value={presetKey} options={presets.map((preset) => [preset.key, preset.label])} onChange={onPresetChange} />
          <button className="chart-reload" type="button" onClick={onReload}>
            Reload Real Data
          </button>
          <button className="chart-reload" type="button" onClick={openFullscreen}>
            Fullscreen
          </button>
          <div className="indicator-tags">
            <span>EMA20</span>
            <span>EMA50</span>
            <span>EMA200</span>
            <span>Volume MA20</span>
            <span>ATR14</span>
            <span>RSI14</span>
            <span>VWAP</span>
          </div>
        </div>
      </div>
      <div className="chart-meta">
        <span>
          {labels.source}: <b>{meta.sourceType}</b>
        </span>
        <span>
          {labels.status}: <b>{meta.providerStatus}</b>
        </span>
        <span>
          Freshness: <b>{meta.freshness}</b>
        </span>
        <span>
          Stale Age: <b>{meta.staleAge}</b>
        </span>
        <span>
          {labels.range}: <b>{meta.range} / {meta.interval}</b>
        </span>
        <span>
          {labels.candles}: <b>{meta.count}</b>
        </span>
        <span>
          {labels.firstLast}: <b>{meta.first || "-"} / {meta.last || "-"}</b>
        </span>
        {meta.errors.length ? (
          <span>
            Errors: <b>{meta.errors.join("; ").slice(0, 120)}</b>
          </span>
        ) : null}
      </div>
      <div className="ohlc-row">
        {hover ? (
          <>
            <span>{hover.time}</span>
            <span>O {hover.open.toFixed(2)}</span>
            <span>H {hover.high.toFixed(2)}</span>
            <span>L {hover.low.toFixed(2)}</span>
            <span>C {hover.close.toFixed(2)}</span>
          </>
        ) : (
          <span>{ohlcHint}</span>
        )}
      </div>
      {candles.length ? (
        <div className="chart-canvas" ref={containerRef} />
      ) : (
        <div className="chart-empty">
          <span>{effectiveEmptyText}</span>
          {onReload ? (
            <button type="button" onClick={onReload}>
              Repair Chart With Real Data
            </button>
          ) : null}
        </div>
      )}
    </section>
  );
}

function PanelTitle({ title, detail }: { title: string; detail: string }) {
  return (
    <div className="panel-title">
      <h2>{title}</h2>
      <span>{detail}</span>
    </div>
  );
}

function Segmented({
  value,
  options,
  onChange,
  icon,
}: {
  value: string;
  options: [string, string][];
  onChange: (value: string) => void;
  icon?: React.ReactNode;
}) {
  return (
    <div className="segmented">
      {icon}
      {options.map(([key, label]) => (
        <button className={value === key ? "active" : ""} key={key} type="button" onClick={() => onChange(key)}>
          {label}
        </button>
      ))}
    </div>
  );
}

function Pill({ label, icon, tone }: { label: string; icon: React.ReactNode; tone: "good" | "warn" | "neutral" }) {
  return (
    <span className={`pill ${tone}`}>
      {icon}
      {label}
    </span>
  );
}

function Metric({ label, value, tone }: { label: string; value: string; tone?: "good" | "watch" | "warn" }) {
  return (
    <div className={`metric ${tone ?? ""}`}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div className="fact">
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function Narrative({ title, items }: { title: string; items: string[] }) {
  return (
    <div className="narrative">
      <h3>{title}</h3>
      {items.map((item) => (
        <p key={item}>{item}</p>
      ))}
    </div>
  );
}

function chartPresetByKey(key: ChartPresetKey): ChartPreset {
  return CHART_PRESETS.find((preset) => preset.key === key) ?? CHART_PRESETS[1];
}

function urlRequestedFixture(): boolean {
  try {
    const params = new URLSearchParams(window.location.search);
    const value = params.get("source") ?? params.get("optionsSource");
    return value === "fixture";
  } catch {
    // URL parsing can fail in unusual embedded contexts.
  }
  return false;
}

function metaFromPayload(payload: Record<string, unknown>, preset: ChartPreset, candles: Candle[]): CandleMeta {
  return {
    symbol: String(payload.symbol ?? ""),
    range: String(payload.range ?? preset.range),
    interval: String(payload.interval ?? preset.interval),
    sourceType: String(payload.source_type ?? "unknown"),
    providerStatus: String(payload.provider_status ?? "unknown"),
    freshness: String(payload.freshness ?? "unknown"),
    staleAge: formatStaleAge(payload.freshness_seconds, payload.freshness),
    count: candles.length,
    first: formatCandleTime(candles[0]),
    last: formatCandleTime(candles[candles.length - 1]),
    errors: Array.isArray(payload.provider_errors) ? payload.provider_errors.map(String) : [],
  };
}

function chartPayload(payload: MstrCyclePayload | null, key: string): Record<string, unknown> {
  return ((payload?.charts?.[key] ?? {}) as Record<string, unknown>) || {};
}

function chartLabels(text: (typeof copy)["en"] | (typeof copy)["zh"]) {
  return {
    source: text.chartSource,
    status: text.chartStatus,
    range: text.chartRange,
    candles: text.candles,
    firstLast: text.firstLast,
  };
}

function formatPremium(component: MstrComponent | undefined): string {
  if (!component) return "-";
  if (typeof component.premium_to_btc_nav === "number") return `${component.premium_to_btc_nav.toFixed(2)}x`;
  return component.status ?? "-";
}

function metricNumber(value: MstrMetricValue): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value === "string" && value.trim() !== "" && Number.isFinite(Number(value))) return Number(value);
  return null;
}

function metricValue(value: MstrMetricValue): string {
  const number = metricNumber(value);
  if (number !== null) return formatNumber(number);
  if (typeof value === "boolean") return value ? "yes" : "no";
  if (Array.isArray(value)) return value.join(", ");
  if (typeof value === "string" && value) return value;
  return "-";
}

function metricMoney(value: MstrMetricValue): string {
  return money(metricNumber(value));
}

function metricPct(value: MstrMetricValue): string {
  const number = metricNumber(value);
  return number === null ? "-" : `${formatSigned(number)}%`;
}

function metricPctFromRatio(value: MstrMetricValue): string {
  const number = metricNumber(value);
  return number === null ? "-" : `${formatNumber(number * 100)}%`;
}

function metricMultiple(value: MstrMetricValue): string {
  const number = metricNumber(value);
  return number === null ? "-" : `${formatNumber(number)}x`;
}

function formatTrackerMetric(value: MstrMetricValue, kind: "number" | "money" | "pct" | "ratioPct" | "multiple"): string {
  if (kind === "money") return metricMoney(value);
  if (kind === "pct") return metricPct(value);
  if (kind === "ratioPct") return metricPctFromRatio(value);
  if (kind === "multiple") return metricMultiple(value);
  return metricValue(value);
}

function stateLabel(state: "idle" | "loading" | "ready" | "error"): string {
  if (state === "loading") return "loading";
  if (state === "error") return "unavailable";
  if (state === "ready") return "ready";
  return "not loaded";
}

function mstrLevelClass(level: MstrCycleLevel) {
  if (level === "CYCLE ACCUMULATION") return "buy";
  if (level === "BOTTOM WATCH") return "watch";
  if (level === "DISTRIBUTION RISK") return "pass";
  return "neutral";
}

function fixtureMeta(symbol: string, preset: ChartPreset, candles: Candle[]): CandleMeta {
  return {
    symbol,
    range: preset.range,
    interval: preset.interval,
    sourceType: "fixture_read_only",
    providerStatus: "fixture_read_only",
    freshness: "fixture",
    staleAge: "none",
    count: candles.length,
    first: formatCandleTime(candles[0]),
    last: formatCandleTime(candles[candles.length - 1]),
    errors: [],
  };
}

function failedMeta(symbol: string, preset: ChartPreset): CandleMeta {
  return {
    symbol,
    range: preset.range,
    interval: preset.interval,
    sourceType: "live_yahoo_chart",
    providerStatus: "provider_failed",
    freshness: "missing",
    staleAge: "none",
    count: 0,
    first: "",
    last: "",
    errors: ["Local API or public provider did not return candles."],
  };
}

function refreshingMeta(symbol: string, preset: ChartPreset): CandleMeta {
  return {
    symbol,
    range: preset.range,
    interval: preset.interval,
    sourceType: "live_yahoo_chart",
    providerStatus: "refreshing",
    freshness: "loading",
    staleAge: "none",
    count: 0,
    first: "",
    last: "",
    errors: ["Refreshing real data..."],
  };
}

function normalizeApiBase(value: string): string {
  const trimmed = value.trim();
  if (!trimmed) return "";
  return trimmed.replace(/\/+$/, "");
}

function apiUrl(path: string): string {
  if (!API_BASE_URL) return path;
  return `${API_BASE_URL}${path.startsWith("/") ? path : `/${path}`}`;
}

function apiFetch(path: string, init?: RequestInit): Promise<Response> {
  return fetch(apiUrl(path), {
    ...init,
    credentials: API_BASE_URL ? "include" : init?.credentials ?? "same-origin",
  });
}

function formatStaleAge(rawSeconds: unknown, freshness: unknown): string {
  const direct = Number(rawSeconds ?? 0);
  if (Number.isFinite(direct) && direct > 0) return `${Math.round(direct)}s`;
  const text = String(freshness ?? "");
  if (text.startsWith("stale ")) return text.replace("stale ", "");
  return "none";
}

function parseStockRow(row: string, index: number): UniverseStock {
  const [symbol, name, sector, layer] = row.split(":");
  const isAiLayer = layer === "Energy" || layer === "Chips" || layer === "Infrastructure" || layer === "Models" || layer === "Applications";
  const isSpaceRobotics = layer === "Space / Robotics";
  return {
    symbol,
    name,
    sector,
    layer,
    primary_layer: layer,
    tags: isAiLayer ? [`ai_${layer.toLowerCase()}`] : isSpaceRobotics ? ["space", "robotics", "automation"] : [],
    rank: index + 1,
    liquidity_tier: ["AI", "APP", "DUOL", "PATH", "TSLA", "RKLB", "ASTS", "LUNR", "ACHR", "JOBY", "OUST", "MBLY", "SYM"].includes(symbol)
      ? "high_beta"
      : "core",
  };
}

function uniqueStocks(stocks: UniverseStock[]): UniverseStock[] {
  const seen = new Map<string, UniverseStock>();
  for (const stock of stocks) {
    if (!seen.has(stock.symbol)) seen.set(stock.symbol, stock);
  }
  return [...seen.values()].map((stock, index) => ({ ...stock, rank: index + 1 }));
}

function searchStocks(query: string, stocks: UniverseStock[], limit = 10): UniverseStock[] {
  const terms = expandedSearchTerms(query);
  const normalized = terms[0] ?? "";
  if (!normalized) return quickSearchStocks(stocks).slice(0, limit);
  const scored = stocks
    .map((stock) => {
      const aliases = [...(stock.aliases ?? []), ...(STOCK_SEARCH_ALIASES[stock.symbol] ?? [])].join(" ");
      const haystack = `${stock.symbol} ${stock.name} ${stock.sector} ${stock.layer} ${(stock.tags ?? []).join(" ")} ${aliases}`.toLowerCase();
      let score = 0;
      for (const [index, term] of terms.entries()) {
        const weight = index === 0 ? 1 : 0.72;
        if (stock.symbol.toLowerCase() === term) score += 140 * weight;
        if (stock.symbol.toLowerCase().startsWith(term)) score += 95 * weight;
        if (stock.symbol.toLowerCase().includes(term)) score += 70 * weight;
        if (stock.name.toLowerCase().includes(term)) score += 48 * weight;
        if (aliases.toLowerCase().includes(term)) score += 46 * weight;
        if (stock.layer.toLowerCase().includes(term)) score += 38 * weight;
        if ((stock.tags ?? []).join(" ").toLowerCase().includes(term)) score += 34 * weight;
        if (haystack.includes(term)) score += 12 * weight;
      }
      return { stock, score };
    })
    .filter((item) => item.score > 0)
    .sort((a, b) => b.score - a.score || (a.stock.rank ?? 9999) - (b.stock.rank ?? 9999));
  return scored.slice(0, limit).map((item) => item.stock);
}

function resolveSearchSymbol(query: string, results: UniverseStock[], fallbackSymbol: string): string {
  const raw = query.trim();
  const cleaned = raw.toUpperCase().replace(/[^A-Z0-9.^-]/g, "");
  const exact = results.find((stock) => stock.symbol === cleaned);
  if (exact) return exact.symbol;
  if (results[0]) return results[0].symbol;
  return cleaned || fallbackSymbol;
}

function expandedSearchTerms(query: string): string[] {
  const normalized = query.trim().toLowerCase();
  if (!normalized) return [];
  const terms = [normalized];
  Object.entries(SEARCH_QUERY_ALIASES).forEach(([alias, expansions]) => {
    if (normalized.includes(alias.toLowerCase())) {
      terms.push(...expansions.map((item) => item.toLowerCase()));
    }
  });
  const compact = normalized.replace(/\s+/g, "");
  if (compact !== normalized) terms.push(compact);
  return [...new Set(terms.filter(Boolean))];
}

function quickSearchStocks(stocks: UniverseStock[]): UniverseStock[] {
  const preferred = ["NVDA", "MSTR", "SPY", "QQQ", "RKLB", "ASTS", "TSLA", "ISRG", "BOTZ", "PLTR"];
  const bySymbol = new Map(stocks.map((stock) => [stock.symbol, stock]));
  return preferred.map((symbol) => bySymbol.get(symbol)).filter((stock): stock is UniverseStock => Boolean(stock));
}

function stocksForUniverse(universeName: UniverseName): UniverseStock[] {
  if (universeName === "ai_five_layer") return AI_FIVE_LAYER_STOCKS;
  if (universeName === "physical_ai") return PHYSICAL_AI_STOCKS;
  if (universeName === "all") return ALL_STOCKS;
  return STOCKS;
}

function universeOptionLabel(universeName: UniverseName, lang: Lang): string {
  if (lang === "zh") {
    if (universeName === "ai_five_layer") return "AI Five-Layer";
    if (universeName === "physical_ai") return "Physical AI";
    if (universeName === "all") return "All";
    return "Core 200";
  }
  if (universeName === "ai_five_layer") return "AI Five-Layer";
  if (universeName === "physical_ai") return "Physical AI";
  if (universeName === "all") return "All";
  return "Core 200";
}

function buyLogicItems(signal: StockSignal, regime: MarketRegimePayload | null): string[] {
  const profileName = signal.profile_name ?? "tactical_1w_v1";
  const profileRules: Record<string, string> = {
    tactical_1w_v1: "1W Tactical: daily EMA10/20/50 structure + 1H momentum + volume expansion + ATR, RSI, gap, and extension discipline.",
    swing_1_2m_v1: "1-2M Swing: daily EMA20/50/200 trend, weekly support, relative strength, pullback quality, volume structure, and earnings-window caution.",
    position_6m_v1: "6M Position: weekly EMA20/50 trend stability, daily EMA50/200 support, industry layer leadership, and drawdown tolerance.",
    cycle_1_3y_v1: "1-3Y Cycle: monthly/weekly trend, cycle location, 200D/40W support, long-term relative strength, and narrative or financing risk.",
    high_beta_growth_v1: "High-Beta Growth: live data + price near EMA20/EMA50 support + above EMA200 + 1H momentum turn + looser volume + wider ATR, for small staged entries only.",
  };
  const exitRiskPhrase =
    profileName === "high_beta_growth_v1"
      ? "clear exit risk or accepted high-beta pullback risk"
      : "clear exit risk";
  return [
    `BUY SETUP requires score >= ${signal.score_breakdown?.buy_setup_threshold ?? 88}; WATCH starts at ${signal.score_breakdown?.watch_threshold ?? 65}.`,
    `BUY also requires clean live data, readiness gate ready, positive historical edge, ${exitRiskPhrase}, and market regime not blocking new longs.`,
    profileRules[profileName] ?? (signal.score_breakdown?.formula || "Trend + confirmation + volume + risk window."),
    `Current rule conclusion: ${signal.trade_conclusion?.action ?? "DO_NOT_BUY"} / gate ${signal.readiness_gate?.status ?? "BLOCKED"}.`,
    `Market regime: ${regime?.label ?? "loading"} (${regime?.regime ?? "unknown"}), score ${regime?.score ?? 0}.`,
    `Exit risk: ${signal.exit_risk?.status ?? "not loaded"}; stale or provider-failed data blocks BUY.`,
  ];
}

function signalLayer(signal: StockSignal, stock: UniverseStock): string {
  return signal.primary_layer ?? stock.primary_layer ?? stock.layer;
}

function makeLocalSignalRun(source: Source, universeName: UniverseName = "default"): SignalRun {
  const stocks = stocksForUniverse(universeName).slice(0, 100);
  const signals = stocks.map((stock) => buildLocalSignal(stock));
  signals.sort((a, b) => b.score - a.score);
  return {
    run_id: "local-fixture-stock-run",
    source,
    universe: universeName,
    universe_total: stocks.length,
    scanned_count: signals.length,
    downgraded_by_data_count: signals.filter((signal) => signal.data_status?.data_quality !== "clean").length,
    provider_coverage: {
      universe_total: stocks.length,
      scanned: signals.length,
      available: source === "fixture" ? 0 : signals.length,
      stale_or_partial: 0,
      failed: source === "fixture" ? 0 : signals.length,
      unscanned: 0,
      coverage_pct: 100,
    },
    profile: { name: "swing_long_v1", buy_setup_threshold: 82, watch_threshold: 65, direction: "long_only" },
    provider_status: source === "fixture" ? "fixture_read_only" : "api_unavailable",
    provider_error_count: source === "fixture" ? 0 : 1,
    historical_validation: {
      sample_count: signals.reduce((total, signal) => total + signal.historical_edge.sample_count, 0),
      win_rate_5d: round(avg(signals.map((signal) => signal.historical_edge.win_rate_5d))),
      target_hit_rate_5d: round(avg(signals.map((signal) => signal.historical_edge.target_hit_rate_5d))),
      avg_forward_return_5d: round(avg(signals.map((signal) => signal.historical_edge.avg_forward_return_5d))),
      avg_max_drawdown_5d: round(avg(signals.map((signal) => signal.historical_edge.avg_max_drawdown_5d))),
    },
    counts: {
      buy_setup: signals.filter((signal) => signal.level === "BUY SETUP").length,
      watch: signals.filter((signal) => signal.level === "WATCH").length,
      pass: signals.filter((signal) => signal.level === "PASS").length,
      total: signals.length,
    },
    signals,
    llm_signal_core_enabled: false,
    broker_order_wiring_enabled: false,
  };
}

function makeUnavailableSignalRun(universeName: UniverseName = "default"): SignalRun {
  const signals = stocksForUniverse(universeName)
    .slice(0, 100)
    .map((stock) => makeUnavailableSignal(stock.symbol, stock));
  return {
    run_id: "live-provider-unavailable",
    source: "live",
    universe: universeName,
    universe_total: signals.length,
    scanned_count: 0,
    downgraded_by_data_count: signals.length,
    provider_coverage: {
      universe_total: signals.length,
      scanned: 0,
      available: 0,
      stale_or_partial: 0,
      failed: 0,
      unscanned: signals.length,
      coverage_pct: 0,
    },
    profile: { name: "swing_long_v1", buy_setup_threshold: 82, watch_threshold: 65, direction: "long_only" },
    provider_status: "provider_failed",
    provider_error_count: 1,
    trade_conclusion_counts: { BUY: 0, WAIT: 0, DO_NOT_BUY: signals.length, HOLD_TRAIL: 0, EXIT_REVIEW: 0 },
    historical_validation: {
      sample_count: 0,
      win_rate_5d: 0,
      target_hit_rate_5d: 0,
      avg_forward_return_5d: 0,
      avg_max_drawdown_5d: 0,
    },
    counts: {
      buy_setup: 0,
      watch: 0,
      pass: signals.length,
      total: signals.length,
    },
    signals,
    llm_signal_core_enabled: false,
    broker_order_wiring_enabled: false,
  };
}

function makeUnavailableSignal(symbol: string, stock?: UniverseStock): StockSignal {
  return {
    symbol,
    score: 0,
    level: "PASS",
    direction: "LONG",
    primary_layer: stock?.layer ?? "US Stock",
    tags: stock?.tags ?? [],
    liquidity_tier: stock?.liquidity_tier ?? "core",
    trend_summary: "Live public candles are unavailable.",
    trigger_summary: "No signal is generated without live candles.",
    score_breakdown: {
      trend_score: 0,
      trigger_score: 0,
      volume_score: 0,
      risk_score: 0,
      total_score: 0,
      buy_setup_threshold: 88,
      watch_threshold: 65,
      formula: "trend + 1h trigger + volume confirmation + risk window",
    },
    exit_risk: {
      status: "DATA CAUTION",
      level: "CAUTION",
      reasons: ["Provider failed or local API is unavailable; do not treat this as a setup."],
      checklist: ["Refresh live data later. Do not use fixture data as a live trading input."],
    },
    trade_conclusion: {
      action: "DO_NOT_BUY",
      confidence: "LOW",
      risk_bucket: "avoid",
      decision_summary: "DO NOT BUY: live public candles are unavailable.",
      why: ["Provider failed or local API is unavailable.", "No rule conclusion can be trusted without live candles."],
      blockers: ["provider_failed"],
      invalidation: ["Refresh live data and rerun analysis."],
      profile_name: "swing_long_v1",
      holding_period: "3-7 trading days",
      position_context: "no_position_assumed",
      read_only_research: true,
      llm_signal_core_enabled: false,
      broker_order_wiring_enabled: false,
    },
    risk_warnings: ["Provider failed or local API is unavailable; do not treat this as a setup."],
    manual_checklist: ["Refresh live data later. Do not use fixture data as a live trading input."],
    data_status: {
      daily_provider_status: "provider_failed",
      hourly_provider_status: "provider_failed",
      daily_candles: 0,
      hourly_candles: 0,
      source: "live_yahoo_chart",
      freshness: "missing",
      data_quality: "caution",
      live_does_not_fallback_to_fixture: true,
    },
    features: {},
    historical_edge: {
      sample_count: 0,
      win_rate_5d: 0,
      target_hit_rate_5d: 0,
      avg_forward_return_3d: 0,
      avg_forward_return_5d: 0,
      avg_forward_return_10d: 0,
      avg_max_drawdown_5d: 0,
      verdict: "missing",
    },
  };
}

function buildLocalSignal(stock: UniverseStock): StockSignal {
  const symbol = stock.symbol;
  const daily = makeCandles(symbol, "1y", "1d");
  const hourly = makeCandles(symbol, "5d", "1h");
  const closes = daily.map((bar) => bar.close);
  const hCloses = hourly.map((bar) => bar.close);
  const ema20 = lastEma(closes, 20);
  const ema50 = lastEma(closes, 50);
  const ema200 = lastEma(closes, 200);
  const close = closes[closes.length - 1] ?? 0;
  const previousClose = closes[Math.max(0, closes.length - 8)] ?? close;
  const hLast = hCloses[hCloses.length - 1] ?? 0;
  const hPrevious = hCloses[Math.max(0, hCloses.length - 8)] ?? hLast;
  const hMomentum = ((hLast / Math.max(hPrevious, 0.01)) - 1) * 100;
  const volumeRatio = (daily[daily.length - 1]?.volume ?? 0) / Math.max(avg(daily.slice(-21, -1).map((bar) => bar.volume)), 1);
  const atr = avg(daily.slice(-15).map((bar) => ((bar.high - bar.low) / Math.max(bar.close, 0.01)) * 100));
  const hEma20 = lastEma(hCloses, 20);
  const edge = localHistoricalEdge(symbol);
  const score = clamp(
    (close > ema20 ? 14 : 0) +
      (ema20 > ema50 ? 14 : 0) +
      (ema50 > ema200 ? 14 : 0) +
      clamp(((close / Math.max(previousClose, 0.01)) - 1) * 100 * 2.2, -8, 18) +
      (hLast > hEma20 ? 13 : 0) +
      clamp(hMomentum * 3, -8, 11) +
      clamp((volumeRatio - 0.75) * 18, 0, 18) +
      clamp(18 - Math.max(0, atr - 5) * 1.4, 0, 18),
    0,
    100,
  );
  const scoreBreakdown = {
    trend_score: round(
      (close > ema20 ? 14 : 0) +
        (ema20 > ema50 ? 14 : 0) +
        (ema50 > ema200 ? 14 : 0) +
        clamp(((close / Math.max(previousClose, 0.01)) - 1) * 100 * 2.2, -8, 18),
    ),
    trigger_score: round((hLast > hEma20 ? 13 : 0) + clamp(hMomentum * 3, -8, 11)),
    volume_score: round(clamp((volumeRatio - 0.75) * 18, 0, 18)),
    risk_score: round(clamp(18 - Math.max(0, atr - 5) * 1.4, 0, 18)),
    total_score: Math.round(score * 10) / 10,
    buy_setup_threshold: 88,
    watch_threshold: 65,
    formula: "trend + 1h trigger + volume confirmation + risk window",
  };
  const level: Level = score >= 82 ? "BUY SETUP" : score >= 65 ? "WATCH" : "PASS";
  return {
    symbol,
    score: Math.round(score * 10) / 10,
    level,
    direction: "LONG",
    primary_layer: stock.layer,
    tags: stock.tags,
    liquidity_tier: stock.liquidity_tier ?? "core",
    trend_summary: `Daily close ${close.toFixed(2)} vs EMA20 ${ema20.toFixed(2)}, EMA50 ${ema50.toFixed(2)}, EMA200 ${ema200.toFixed(2)}.`,
    trigger_summary: `1h momentum ${hMomentum.toFixed(2)}%; volume ${volumeRatio.toFixed(2)}x recent average.`,
    score_breakdown: scoreBreakdown,
    exit_risk: localExitRisk(close, ema20, ema50, hMomentum, volumeRatio, atr),
    risk_warnings:
      atr > 5
        ? ["ATR risk is elevated; wait for a cleaner pullback before acting."]
        : ["No hard data blocker. Still confirm candles manually before action."],
    manual_checklist: [
      "Review daily trend and EMA20/50/200 alignment.",
      "Confirm 1h entry structure and avoid chasing extended candles.",
      "Check volume expansion and ATR risk before any manual trade.",
      "Only after a stock BUY SETUP should ATM options be considered.",
    ],
    data_status: {
      daily_provider_status: "fixture_read_only",
      hourly_provider_status: "fixture_read_only",
      daily_candles: daily.length,
      hourly_candles: hourly.length,
      source: "fixture_read_only",
      freshness: "fixture",
      data_quality: "clean",
      live_does_not_fallback_to_fixture: false,
    },
    features: {
      close,
      ema20,
      ema50,
      ema200,
      atr_pct: atr,
      volume_ratio: volumeRatio,
    },
    historical_edge: edge,
  };
}

function localHistoricalEdge(symbol: string): StockSignal["historical_edge"] {
  const seed = [...symbol].reduce((total, char, index) => total + char.charCodeAt(0) * (index + 1), 0);
  const sampleCount = 18 + (seed % 38);
  const winRate = 42 + (seed % 28);
  const avgReturn = -0.4 + (seed % 24) / 10;
  return {
    sample_count: sampleCount,
    win_rate_5d: round(winRate),
    target_hit_rate_5d: round(Math.max(20, winRate - 12)),
    avg_forward_return_3d: round(avgReturn * 0.62),
    avg_forward_return_5d: round(avgReturn),
    avg_forward_return_10d: round(avgReturn * 1.35),
    avg_max_drawdown_5d: round(-1.2 - (seed % 20) / 10),
    verdict: winRate >= 52 && avgReturn > 0.2 ? "positive" : "unproven",
  };
}

function localExitRisk(close: number, ema20: number, ema50: number, hMomentum: number, volumeRatio: number, atr: number): NonNullable<StockSignal["exit_risk"]> {
  const reasons: string[] = [];
  let status = "CLEAR";
  let level = "HOLD";
  if (close < ema50) {
    status = "SETUP INVALIDATED";
    level = "EXIT RISK";
    reasons.push("Daily close is below EMA50; long setup structure is invalidated.");
  } else if (close < ema20) {
    status = "EXIT RISK";
    level = "CAUTION";
    reasons.push("Daily close is below EMA20; trend support needs manual review.");
  }
  if (hMomentum < -0.7) {
    status = status === "CLEAR" ? "EXIT RISK" : status;
    level = level === "HOLD" ? "CAUTION" : level;
    reasons.push("1h momentum is negative enough to review risk.");
  }
  if (volumeRatio >= 1.6 && hMomentum < 0) {
    status = "EXIT RISK";
    level = "EXIT RISK";
    reasons.push("Downside momentum is appearing with elevated volume.");
  }
  if (atr > 6) {
    status = status === "CLEAR" ? "EXIT RISK" : status;
    level = level === "HOLD" ? "CAUTION" : level;
    reasons.push("ATR is elevated; position risk is expanding.");
  }
  if (!reasons.length) reasons.push("No exit-risk trigger from trend, 1h momentum, ATR, or volume checks.");
  return {
    status,
    level,
    reasons,
    checklist: [
      "Review daily EMA20/EMA50 support first.",
      "Confirm whether 1h momentum is improving or deteriorating.",
      "Use this as a manual risk reminder, not an automated sell instruction.",
    ],
  };
}

function makeCandles(symbol: string, range: RangeValue, interval: IntervalValue): Candle[] {
  const timestamps = fixtureTimestamps(range, interval);
  const seed = [...symbol].reduce((total, char, index) => total + char.charCodeAt(0) * (index + 1), 0);
  let price = 45 + (seed % 420) + (["SPY", "QQQ", "DIA"].includes(symbol) ? 160 : 0);
  return timestamps.map((time, index) => {
    const wave = Math.sin((index + seed) * 0.17) * 0.015 + Math.cos((index + seed) * 0.043) * 0.01;
    const bias = (["NVDA", "MSFT", "AVGO", "AMZN", "AMD", "PLTR"].includes(symbol) ? 0.0014 : 0.0004) + ((seed % 17) - 7) / 12000;
    const open = price;
    const close = Math.max(2, price * (1 + bias + wave * 0.16));
    const spread = Math.max(close * (0.006 + Math.abs(wave) * 0.7), 0.05);
    price = close;
    return {
      time: time as Time,
      open: round(open),
      high: round(Math.max(open, close) + spread),
      low: round(Math.max(0.5, Math.min(open, close) - spread)),
      close: round(close),
      volume: Math.round(950_000 + (seed % 900_000) + Math.abs(wave) * 30_000_000 + (index % 13) * 32_000),
    };
  });
}

function fixtureTimestamps(range: RangeValue, interval: IntervalValue): number[] {
  const end = new Date(Date.UTC(2026, 5, 17, 20, 0));
  if (interval === "1d") {
    return previousTradingDays(end, 252).map((day) => Date.UTC(day.getUTCFullYear(), day.getUTCMonth(), day.getUTCDate(), 13, 30) / 1000);
  }
  if (range === "5d" && interval === "1h") {
    return previousTradingDays(end, 5).flatMap((day) => {
      const start = Date.UTC(day.getUTCFullYear(), day.getUTCMonth(), day.getUTCDate(), 13, 30) / 1000;
      return Array.from({ length: 7 }, (_, index) => start + index * 60 * 60);
    });
  }
  if (range === "5y" && interval === "1wk") {
    return previousWeeklyTradingDays(end, 260).map((day) => Date.UTC(day.getUTCFullYear(), day.getUTCMonth(), day.getUTCDate(), 13, 30) / 1000);
  }
  if (range === "10y" && interval === "1mo") {
    return previousMonthlyTradingDays(end, 120).map((day) => Date.UTC(day.getUTCFullYear(), day.getUTCMonth(), day.getUTCDate(), 13, 30) / 1000);
  }
  return previousTradingDays(end, 252).map((day) => Date.UTC(day.getUTCFullYear(), day.getUTCMonth(), day.getUTCDate(), 13, 30) / 1000);
}

function previousTradingDays(end: Date, count: number): Date[] {
  const days: Date[] = [];
  const cursor = new Date(Date.UTC(end.getUTCFullYear(), end.getUTCMonth(), end.getUTCDate()));
  while (days.length < count) {
    const weekday = cursor.getUTCDay();
    if (weekday >= 1 && weekday <= 5) {
      days.push(new Date(cursor));
    }
    cursor.setUTCDate(cursor.getUTCDate() - 1);
  }
  return days.reverse();
}

function previousWeeklyTradingDays(end: Date, count: number): Date[] {
  const anchor = previousTradingDays(end, 1)[0];
  const days: Date[] = [];
  const cursor = new Date(anchor);
  while (days.length < count) {
    days.push(new Date(cursor));
    cursor.setUTCDate(cursor.getUTCDate() - 7);
  }
  return days.reverse();
}

function previousMonthlyTradingDays(end: Date, count: number): Date[] {
  const days: Date[] = [];
  let year = end.getUTCFullYear();
  let month = end.getUTCMonth();
  while (days.length < count) {
    const cursor = new Date(Date.UTC(year, month, 1));
    while (cursor.getUTCDay() === 0 || cursor.getUTCDay() === 6) {
      cursor.setUTCDate(cursor.getUTCDate() + 1);
    }
    if (cursor <= end) {
      days.push(new Date(cursor));
    }
    month -= 1;
    if (month < 0) {
      month = 11;
      year -= 1;
    }
  }
  return days.reverse();
}

function normalizeCandles(input: unknown, fallback: Candle[]): Candle[] {
  if (!Array.isArray(input) || input.length === 0) return fallback;
  return input
    .map((bar) => {
      const item = bar as Record<string, unknown>;
      return {
        time: Number(item.time ?? 0) as Time,
        open_time: String(item.open_time ?? ""),
        open: Number(item.open ?? 0),
        high: Number(item.high ?? 0),
        low: Number(item.low ?? 0),
        close: Number(item.close ?? 0),
        volume: Number(item.volume ?? 0),
      };
    })
    .filter((bar) => Number.isFinite(bar.open) && Number.isFinite(bar.time) && bar.time);
}

function groupByLayer(stocks: UniverseStock[], signals: StockSignal[]) {
  const signalBySymbol = new Map(signals.map((signal) => [signal.symbol, signal]));
  const groups = new Map<string, UniverseStock[]>();
  for (const stock of stocks) {
    groups.set(stock.layer, [...(groups.get(stock.layer) ?? []), stock]);
  }
  return [...groups.entries()]
    .map(([name, layerStocks]) => {
      const layerSignals = layerStocks.map((stock) => signalBySymbol.get(stock.symbol)).filter(Boolean) as StockSignal[];
      const avgScore = avg(layerSignals.map((signal) => signal.score));
      return {
        name,
        avgScore,
        buySetup: layerSignals.filter((signal) => signal.level === "BUY SETUP").length,
        watch: layerSignals.filter((signal) => signal.level === "WATCH").length,
        providerCaution: layerSignals.some((signal) => signal.data_status?.data_quality === "caution"),
        stocks: layerStocks.sort((a, b) => (signalBySymbol.get(b.symbol)?.score ?? 0) - (signalBySymbol.get(a.symbol)?.score ?? 0)),
      };
    })
    .sort((a, b) => layerSortRank(a.name) - layerSortRank(b.name) || b.stocks.length - a.stocks.length);
}

function layerSortRank(layer: string): number {
  const order = ["Energy", "Chips", "Infrastructure", "Models", "Applications"];
  const index = order.indexOf(layer);
  return index >= 0 ? index : 20;
}

function selectedMetaBySymbol(stocks: UniverseStock[], symbol: string) {
  return stocks.find((stock) => stock.symbol === symbol);
}

function addLine(chart: IChartApi, data: LineData<Time>[], color: string) {
  const series = chart.addSeries(LineSeries, { color, lineWidth: 2, lastValueVisible: false, priceLineVisible: false });
  series.setData(data);
}

function ema(candles: Candle[], period: number): LineData<Time>[] {
  let current = candles[0]?.close ?? 0;
  const multiplier = 2 / (period + 1);
  return candles.map((bar, index) => {
    current = index === 0 ? bar.close : (bar.close - current) * multiplier + current;
    return { time: bar.time, value: round(current) };
  });
}

function sma(candles: Candle[], period: number): LineData<Time>[] {
  if (candles.length < period) return [];
  const result: LineData<Time>[] = [];
  let rolling = 0;
  candles.forEach((bar, index) => {
    rolling += bar.close;
    if (index >= period) rolling -= candles[index - period].close;
    if (index >= period - 1) {
      result.push({ time: bar.time, value: round(rolling / period) });
    }
  });
  return result;
}

function vwap(candles: Candle[]): LineData<Time>[] {
  let priceVolume = 0;
  let volume = 0;
  return candles.map((bar) => {
    const typical = (bar.high + bar.low + bar.close) / 3;
    priceVolume += typical * bar.volume;
    volume += bar.volume;
    return { time: bar.time, value: round(priceVolume / Math.max(volume, 1)) };
  });
}

function lastEma(values: number[], period: number) {
  const series = ema(values.map((value, index) => ({ time: index as Time, open: value, high: value, low: value, close: value, volume: 0 })), period);
  return series[series.length - 1]?.value ?? 0;
}

function useStoredState<T extends string>(key: string, initial: T): [T, (value: T) => void] {
  const [value, setValue] = useState<T>(() => {
    try {
      return (window.localStorage.getItem(key) as T | null) ?? initial;
    } catch {
      return initial;
    }
  });
  const setStored = (next: T) => {
    setValue(next);
    try {
      window.localStorage.setItem(key, next);
    } catch {
      // localStorage may be unavailable in strict privacy modes.
    }
  };
  return [value, setStored];
}

function levelClass(level: Level) {
  if (level === "BUY SETUP") return "buy";
  if (level === "WATCH") return "watch";
  return "pass";
}

function isLiveCandleMeta(meta: CandleMeta) {
  return meta.count > 0 && meta.providerStatus === "available" && meta.sourceType.includes("live") && !meta.sourceType.includes("fixture");
}

function parseRiskReward(value: string | undefined) {
  if (!value) return 0;
  const match = value.match(/(\d+(?:\.\d+)?)/);
  return match ? Number(match[1]) : 0;
}

function explicitPlanText(value: string | undefined) {
  if (!value) return false;
  const normalized = value.trim().toLowerCase();
  return Boolean(normalized) && !["-", "n/a", "na", "unavailable", "r:r unavailable"].includes(normalized);
}

function isLeveragedOrOptionsProxy(symbol: string) {
  return new Set(["MSTU", "MSTX", "TQQQ", "SQQQ", "UPRO", "SPXL", "SPXS", "SOXL", "SOXS", "TNA", "TZA", "LABU", "LABD"]).has(symbol.toUpperCase());
}

function deriveMondayReadiness({
  apiConnection,
  apiHealth,
  aiStatus,
  aiDailyReport,
  marketRegime,
  run,
  dailyMeta,
  hourlyMeta,
  text,
}: {
  apiConnection: ApiConnectionState;
  apiHealth: ApiHealthPayload | null;
  aiStatus: AiReviewStatusPayload | null;
  aiDailyReport: AiDailyAgentPayload | null;
  marketRegime: MarketRegimePayload | null;
  run: SignalRun;
  dailyMeta: CandleMeta;
  hourlyMeta: CandleMeta;
  text: (typeof copy)["en"] | (typeof copy)["zh"];
}): MondayReadiness {
  const checks = [
    {
      label: "Live API",
      value: apiConnection === "connected" && apiHealth?.live_data_enabled !== false ? "online" : "offline",
      ok: apiConnection === "connected" && apiHealth?.live_data_enabled !== false,
      critical: true,
    },
    {
      label: "AI Agent",
      value: aiStatus?.status === "available" ? aiStatus.models.batch ?? aiStatus.models.review ?? "available" : "unavailable",
      ok: aiStatus?.status === "available",
      critical: true,
    },
    {
      label: "AI Daily",
      value: aiDailyReport?.status === "available" && !aiDailyReport.is_stale ? "fresh" : aiDailyReport?.status ?? "missing",
      ok: aiDailyReport?.status === "available" && !aiDailyReport.is_stale,
      critical: true,
    },
    {
      label: "Market",
      value: marketRegime ? `${marketRegime.label} / ${marketRegime.score}` : "loading",
      ok: Boolean(marketRegime) && !["RISK_OFF", "DATA_CAUTION"].includes(marketRegime?.regime ?? ""),
      critical: true,
    },
    {
      label: "Provider",
      value: `${run.provider_status} / ${run.provider_error_count}`,
      ok: run.provider_status === "available" && run.provider_error_count === 0,
      critical: false,
    },
    {
      label: "Selected K-Line",
      value: `${dailyMeta.providerStatus}/${hourlyMeta.providerStatus}`,
      ok: isLiveCandleMeta(dailyMeta) && isLiveCandleMeta(hourlyMeta),
      critical: false,
    },
    {
      label: "Order Path",
      value: apiHealth?.broker_order_wiring_enabled || apiHealth?.order_submission_enabled ? "enabled" : "disabled",
      ok: !apiHealth?.broker_order_wiring_enabled && !apiHealth?.order_submission_enabled && !apiHealth?.account_access_enabled,
      critical: true,
    },
  ];
  const reasons = checks.filter((check) => !check.ok).map((check) => `${check.label}: ${check.value}`);
  const criticalFailed = checks.some((check) => check.critical && !check.ok);
  const status: MondayReadiness["status"] = criticalFailed ? "NO_TRADE" : reasons.length ? "CAUTION" : "READY";
  return {
    status,
    title: text.mondayReadiness,
    summary:
      status === "READY"
        ? "Ready for small-size manual pilot review. The system is still read-only and cannot place orders."
        : status === "CAUTION"
          ? "Use observation mode unless the listed caution items are cleared before entry."
          : "No real-money pilot until critical data, AI, market, or safety checks are clear.",
    checks,
    reasons,
    riskRules: [
      text.maxRiskPerTrade,
      text.maxTradesDay,
      text.noOptionsNoLeverage,
      text.noChasingNoAveraging,
      text.journalBeforeTrade,
    ],
  };
}

function deriveManualTradeTicket({
  selected,
  selectedSymbol,
  aiDecision,
  dailyMeta,
  hourlyMeta,
  stockJournal,
  text,
}: {
  selected: StockSignal;
  selectedSymbol: string;
  aiDecision: AiDecisionPayload | null;
  dailyMeta: CandleMeta;
  hourlyMeta: CandleMeta;
  stockJournal: StockJournalPayload | null;
  text: (typeof copy)["en"] | (typeof copy)["zh"];
}): ManualTradeTicket {
  const decision = aiDecision?.ai_decision;
  const riskRewardValue = parseRiskReward(decision?.risk_reward);
  const hasJournalToday = Boolean(
    stockJournal?.entries.some((entry) => entry.symbol === selectedSymbol && entry.reviewed_at.slice(0, 10) === new Date().toISOString().slice(0, 10)),
  );
  const checks = [
    { label: "AI action", value: decision?.action ?? "missing", ok: decision?.action === "AI_BUY_CANDIDATE" },
    { label: "Daily K-line", value: `${dailyMeta.providerStatus} / ${dailyMeta.count}`, ok: isLiveCandleMeta(dailyMeta) },
    { label: "Confirm K-line", value: `${hourlyMeta.providerStatus} / ${hourlyMeta.count}`, ok: isLiveCandleMeta(hourlyMeta) },
    { label: "Hard veto", value: aiDecision?.hard_veto?.active ? "active" : "clear", ok: !aiDecision?.hard_veto?.active },
    { label: "R:R", value: decision?.risk_reward ?? "-", ok: riskRewardValue >= 2 },
    { label: "Stop", value: decision?.stop_zone ?? "-", ok: explicitPlanText(decision?.stop_zone) },
    { label: "Position", value: decision?.position_size_hint ?? "-", ok: explicitPlanText(decision?.position_size_hint) },
    { label: "No leverage", value: isLeveragedOrOptionsProxy(selectedSymbol) ? "blocked" : "stock", ok: !isLeveragedOrOptionsProxy(selectedSymbol) },
  ];
  const reasons = checks.filter((check) => !check.ok).map((check) => `${check.label}: ${check.value}`);
  const status: ManualTradeTicket["status"] = reasons.length ? "blocked" : hasJournalToday ? "cleared_for_review" : "journal_required";
  return {
    status,
    title: text.manualTradeTicket,
    summary:
      status === "blocked"
        ? "This symbol is not a real-money buy candidate under the Monday pilot rules."
        : status === "journal_required"
          ? "All ticket checks are clear, but a journal record is required before any manual entry."
          : "Ticket checks are clear for manual review. This still does not place or recommend an automatic order.",
    checks,
    action: decision?.action ?? selected.trade_conclusion?.action ?? "DO_NOT_BUY",
    entryZone: decision?.entry_zone ?? "-",
    stopZone: decision?.stop_zone ?? "-",
    targetZone: decision?.target_zone ?? "-",
    riskReward: decision?.risk_reward ?? "-",
    positionSizeHint: decision?.position_size_hint ?? "-",
    invalidatedIf: decision?.what_invalidates_this_setup ?? selected.trade_conclusion?.invalidation ?? [],
    reasons,
  };
}

function actionClass(action: TradeAction | string | undefined) {
  if (action === "BUY" || action === "HOLD_TRAIL" || action === "AI_BUY_CANDIDATE" || action === "AI_HOLD_TRAIL") return "buy";
  if (action === "WAIT" || action === "AI_WAIT") return "watch";
  if (action === "EXIT_REVIEW" || action === "AI_EXIT_REVIEW") return "exit";
  return "pass";
}

function levelLabel(level: Level, lang: Lang) {
  if (lang === "zh") {
    if (level === "BUY SETUP") return "BUY SETUP";
    if (level === "WATCH") return "WATCH";
    return "PASS";
  }
  return level;
}

function regimeTone(regime: string | undefined): "good" | "warn" | "neutral" {
  if (regime === "RISK_ON") return "good";
  if (regime === "RISK_OFF" || regime === "DATA_CAUTION") return "warn";
  return "neutral";
}

function avg(values: number[]) {
  return values.reduce((total, value) => total + value, 0) / Math.max(values.length, 1);
}

function round(value: number) {
  return Math.round(value * 100) / 100;
}

function clamp(value: number, min: number, max: number) {
  return Math.min(Math.max(value, min), max);
}

function formatNumber(value: number | null | undefined) {
  if (value === undefined || value === null || Number.isNaN(value)) return "-";
  return value.toFixed(value > 50 ? 2 : 1);
}

function formatSigned(value: number | null | undefined) {
  if (value === undefined || value === null || Number.isNaN(value)) return "-";
  return `${value > 0 ? "+" : ""}${formatNumber(value)}`;
}

function money(value: number | null | undefined) {
  if (value === undefined || value === null || Number.isNaN(value)) return "-";
  if (value >= 1_000_000_000_000) return `$${(value / 1_000_000_000_000).toFixed(2)}T`;
  if (value >= 1_000_000_000) return `$${(value / 1_000_000_000).toFixed(2)}B`;
  if (value >= 1_000_000) return `$${(value / 1_000_000).toFixed(2)}M`;
  return `$${value.toFixed(value > 100 ? 0 : 2)}`;
}

function formatCandleTime(candle: Candle | undefined) {
  if (!candle) return "";
  if (candle.open_time) return candle.open_time.replace("T", " ").slice(0, 16);
  const seconds = Number(candle.time);
  if (!Number.isFinite(seconds)) return "";
  return new Date(seconds * 1000).toISOString().replace("T", " ").slice(0, 16);
}

export default App;
