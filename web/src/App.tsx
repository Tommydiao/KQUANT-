import {
  Activity,
  AlertTriangle,
  BarChart3,
  BellRing,
  CheckCircle2,
  KeyRound,
  Languages,
  Lock,
  LogOut,
  MessageCircle,
  Moon,
  PanelRightClose,
  PanelRightOpen,
  RefreshCw,
  Search,
  Send,
  ShieldCheck,
  Sun,
  Trash2,
} from "lucide-react";
import type { Time } from "lightweight-charts";
import { type FormEvent, useEffect, useMemo, useRef, useState } from "react";
import { parseRiskReward } from "./tradingFormatters";
import { QuantOverviewPanel, type QuantOverviewPayload } from "./components/QuantOverviewPanel";
import { DeepResearchChatPanel as DeepResearchChatPanelView } from "./components/DeepResearchChatPanel";
import { EarlyTrendPanel as EarlyTrendPanelView } from "./features/quant/EarlyTrendPanel";
import { ChartPanel as ChartPanelView } from "./features/quant/ChartPanel";
import { TodayDecisionPanel as TodayDecisionPanelView } from "./features/quant/TodayDecisionPanel";
import { DataReliabilityPanel as DataReliabilityPanelView, RiskControlPanel as RiskControlPanelView } from "./features/operations/OperationsEvidencePanels";
import { RealtimeCommandCenter as RealtimeCommandCenterView } from "./features/operations/RealtimeCommandCenter";
import { SettingsPanel as SettingsPanelView } from "./features/operations/SettingsPanel";
import { StockJournalPanel as StockJournalPanelView } from "./features/operations/StockJournalPanel";
import { ThemeRadarPanel as ThemeRadarPanelView } from "./features/theme/ThemeRadarPanel";

type Lang = "en" | "zh";
type Theme = "light" | "dark";
type DisplayTimezone = "Asia/Shanghai" | "America/New_York";
type Source = "fixture" | "live";
type Level = "BUY SETUP" | "WATCH" | "PASS";
type TradeAction = "BUY" | "WAIT" | "DO_NOT_BUY" | "HOLD_TRAIL" | "EXIT_REVIEW";
type AiAction =
  | "AI_BUY_CANDIDATE"
  | "AI_PULLBACK_BUY"
  | "AI_PROBE_BUY"
  | "AI_REVERSAL_WATCH"
  | "AI_BREAKOUT_WATCH"
  | "AI_WAIT"
  | "AI_AVOID"
  | "AI_HOLD_TRAIL"
  | "AI_EXIT_REVIEW";
type UniverseName = "default" | "ai_five_layer" | "physical_ai" | "all";
type AppView = "stocks";
type WorkspaceName =
  | "today"
  | "search"
  | "watchlist"
  | "stock"
  | "charts"
  | "aiPlan"
  | "chat"
  | "journal"
  | "settings";
type StrategyProfileName =
  | "tactical_1w_v1"
  | "swing_1_2m_v1"
  | "position_6m_v1"
  | "cycle_1_3y_v1"
  | "high_beta_growth_v1";
type RangeValue = "1d" | "5d" | "1y" | "5y" | "10y";
type IntervalValue = "1m" | "5m" | "15m" | "1h" | "1d" | "1wk" | "1mo";
type ChartPresetKey = "today1m" | "today5m" | "5d15m" | "1h" | "1d" | "1w" | "1m";
type ApiConnectionState = "checking" | "connected" | "offline";
const FRONTEND_API_CONTRACT_VERSION = "kquant-api-2026-08-19-v2-overview-shadow-v1";
type AuthSession = {
  authentication_required: boolean;
  authenticated: boolean;
  mode: "not_required" | "local_email_password" | "setup_required" | string;
  expires_at?: number | null;
};

type EarlyTrendPayload = {
  symbol: string;
  strategy_stage: "NOT_READY" | "EARLY_WATCH" | "ARMED" | "BUY_REVIEW" | "LATE_WAIT_PULLBACK" | "INVALIDATED";
  setup_score: number;
  trigger_score: number | null;
  setup_as_of: string | null;
  confirmation_as_of: string | null;
  summary: string;
  pullback_zone: [number, number] | null;
  invalidation_price: number | null;
  setup_factors: Array<{ factor_id: string; contribution: number; maximum: number; detail: string }>;
  execution_eligibility: {
    status: string;
    eligible_for_manual_review: boolean;
    paper_only: boolean;
    blockers: string[];
  };
  lead_time_evidence: {
    status: string;
    historical_setup_trades: number;
    prospective_trigger_results: number;
    buy_review_activation_ready: boolean;
  };
};

type WebPushStatus = {
  enabled: boolean;
  configured: boolean;
  active_subscriptions: number;
  ios_requirement: string;
  preferences: NotificationPreferences;
};

type NotificationPreferences = {
  web_push_enabled: boolean;
  quiet_start: string;
  quiet_end: string;
  timezone: string;
  daily_routine_limit: number;
};

type Candle = {
  time: Time;
  open_time?: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  bar_state?: "forming_candle" | "closed_candle" | "unknown" | string;
  quote_merged?: boolean;
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
  session?: string;
  quoteTime?: string;
  exchangeTimezone?: string;
  displayTimezone?: string;
};

type RealtimeQuote = {
  symbol: string;
  provider: string;
  source_type: string;
  provider_status: string;
  last?: number | null;
  bid?: number | null;
  ask?: number | null;
  quote_time?: string | null;
  freshness_seconds?: number | null;
  session?: string;
};

type RealtimeSnapshotPayload = {
  symbol: string;
  provider: string;
  provider_status: string;
  source_type: string;
  quote: RealtimeQuote;
  candles_1m: Candle[];
  candles_5m: Candle[];
  quote_fresh: boolean;
  session: string;
  exchange_timezone: string;
  display_timezone: string;
  buy_actions_allowed_by_data: boolean;
  real_money_data_source: boolean;
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
  market_data_provider?: string;
  longbridge_status?: string;
  market_data?: {
    provider?: string;
    status?: string;
    longbridge_env?: string;
    longbridge_sdk?: string;
    default_source_type?: string;
    real_money_requires_longbridge_live?: boolean;
    market_clock?: { session?: string };
  };
  runtime?: {
    api_contract_version?: string;
    started_at_utc?: string;
    auth_routes_version?: string;
    static_assets_version?: string;
  };
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
  factor_snapshot?: {
    factor_snapshot_hash?: string;
    registry_version?: string;
    factors?: Array<{
      factor_id: string;
      label?: string;
      value?: string | number | boolean | null;
      contribution?: number | null;
      status?: string;
      note?: string;
    }>;
    supporting_factors?: string[];
    opposing_factors?: string[];
    unavailable_factors?: string[];
  };
  decision_evidence?: {
    supporting_factors?: Array<{ factor_id: string; label?: string; contribution?: number | null; value?: string | number | boolean | null }>;
    opposing_factors?: Array<{ factor_id: string; label?: string; contribution?: number | null; value?: string | number | boolean | null }>;
    unavailable_factors?: Array<{ factor_id: string; label?: string; note?: string }>;
    data_blockers?: string[];
  };
  ai_feature_packet_v2?: Record<string, unknown>;
  entry_plan?: {
    zone?: string;
    entry_low?: number | null;
    entry_high?: number | null;
    trigger?: string;
    no_chase_rule?: string;
    data_note?: string;
  };
  stop_plan?: {
    zone?: string;
    stop?: number | null;
    basis?: string;
    invalidation?: string[];
  };
  target_plan?: {
    zone?: string;
    target_low?: number | null;
    target_high?: number | null;
    management?: string;
  };
  risk_reward_plan?: {
    risk_reward?: string;
    risk_reward_value?: number;
    position_size_hint?: string;
    minimum_for_money_pilot?: number;
    eligible_for_manual_money_review?: boolean;
  };
  money_pilot_eligibility?: MoneyPilotEligibility;
  ai_action_validation?: {
    version?: string;
    action?: string;
    sample_count?: number;
    evidence_quality?: string;
    win_rate?: number;
    avg_forward_return?: number;
    avg_max_drawdown?: number;
    target_hit_rate?: number;
    stop_hit_rate?: number;
    target_before_stop_proxy?: number;
    risk_reward_value?: number;
    expected_value_r?: number;
    noise_rate?: number;
    money_pilot_eligible?: boolean;
    money_pilot_min_risk_reward?: number;
    money_pilot_min_win_rate?: number;
    money_pilot_min_samples?: number;
    probe_eligible?: boolean;
    probe_min_risk_reward?: number;
    probe_min_win_rate?: number;
    probe_min_samples?: number;
    verdict?: string;
    note?: string;
  };
  probe_eligibility?: ProbeEligibility;
  probe_risk_policy?: ProbeRiskPolicy;
  probe_blockers?: string[];
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
    guardrail_warnings?: string[];
    can_ai_buy: boolean;
    policy: string;
    veto_version?: string;
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
    guardrail_warnings?: string[];
    entry_plan?: StockSignal["entry_plan"];
    stop_plan?: StockSignal["stop_plan"];
    target_plan?: StockSignal["target_plan"];
    risk_reward_plan?: StockSignal["risk_reward_plan"];
    ai_action_validation?: StockSignal["ai_action_validation"];
    money_pilot_eligibility?: MoneyPilotEligibility;
    probe_eligibility?: ProbeEligibility;
    probe_risk_policy?: ProbeRiskPolicy;
    probe_blockers?: string[];
    ai_feature_packet_version?: string;
    ai_primary_engine_version?: string;
    read_only_research: boolean;
    broker_order_wiring_enabled: boolean;
    order_submission_enabled: boolean;
  };
  ai_feature_packet?: Record<string, unknown>;
  ai_feature_packet_version?: string;
  entry_plan?: StockSignal["entry_plan"];
  stop_plan?: StockSignal["stop_plan"];
  target_plan?: StockSignal["target_plan"];
  risk_reward_plan?: StockSignal["risk_reward_plan"];
  ai_action_validation?: StockSignal["ai_action_validation"];
  money_pilot_eligibility?: MoneyPilotEligibility;
  probe_eligibility?: ProbeEligibility;
  probe_risk_policy?: ProbeRiskPolicy;
  probe_blockers?: string[];
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
  ai_action_validation?: StockSignal["ai_action_validation"];
  money_pilot_eligibility?: MoneyPilotEligibility;
  probe_eligibility?: ProbeEligibility;
  probe_risk_policy?: ProbeRiskPolicy;
  probe_blockers?: string[];
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
    probe_candidates?: AiDailyItem[];
    watch_for_pullback: AiDailyItem[];
    avoid_or_risk_elevated: AiDailyItem[];
    data_quality_warnings: string[];
    daily_summary: string;
    validation_by_ai_action?: Record<string, unknown>;
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

type MoneyPilotEligibility = {
  version?: string;
  action?: string;
  eligible_for_review?: boolean;
  ready_for_real_money?: boolean;
  requires_journal?: boolean;
  journal_saved?: boolean;
  criteria?: Record<string, boolean>;
  blockers?: string[];
  minimum_risk_reward?: number;
  minimum_win_rate?: number;
  minimum_samples?: number;
  risk_reward_value?: number;
  historical_win_rate?: number;
  sample_count?: number;
  policy?: string;
};

type ProbeRiskPolicy = {
  version?: string;
  default_risk_pct_of_account?: number;
  max_risk_pct_of_account?: number;
  position_size_hint?: string;
  no_averaging_down?: boolean;
  requires_journal?: boolean;
  manual_execution_only?: boolean;
  policy?: string;
};

type ProbeEligibility = {
  version?: string;
  action?: string;
  eligible_for_probe_review?: boolean;
  ready_for_probe_trade?: boolean;
  requires_journal?: boolean;
  journal_saved?: boolean;
  criteria?: Record<string, boolean>;
  blockers?: string[];
  minimum_risk_reward?: number;
  minimum_win_rate?: number;
  minimum_samples?: number;
  risk_reward_value?: number;
  historical_win_rate?: number;
  sample_count?: number;
  expected_value_r?: number;
  risk_policy?: ProbeRiskPolicy;
  policy?: string;
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

type MondayReadinessReport = {
  latest_cache_status?: string;
  available?: boolean;
  run_id?: string;
  generated_at_utc?: string | null;
  status?: "READY" | "CAUTION" | "NO_TRADE" | "not_scanned" | "read_error" | string;
  summary?: string;
  critical_failure_count?: number;
  warning_count?: number;
  critical_failures?: ReadinessIssue[];
  warnings?: ReadinessIssue[];
  checks?: {
    name?: string;
    passed?: boolean;
    critical?: boolean;
    detail?: string;
  }[];
  pilot_rules?: Record<string, unknown>;
  report_path?: string;
  markdown_path?: string;
};

type ReadinessIssue =
  | string
  | {
      name?: string;
      detail?: string;
      passed?: boolean;
      critical?: boolean;
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

type TodayCandidate = {
  rank: number;
  bucket: string;
  symbol: string;
  strategy_score?: number;
  data_status?: string;
  system_action?: string;
  invalidation?: string[];
  risk?: { status?: string; warnings?: string[]; hard_vetoes?: string[] };
};

type TodayWorkbenchPayload = {
  decision: "NO_TRADE" | "MANUAL_REVIEW" | string;
  headline: string;
  market: { regime: string; label: string; score: number; session?: string };
  data_trust: { provider_status: string; provider_error_count: number; source: string; available: boolean };
  top_candidates: TodayCandidate[];
  watch_candidates: TodayCandidate[];
  risk: { production_decision?: string; failed_gate_count?: number; weekly_review?: Record<string, unknown> };
  exception_states: string[];
  diagnostics: { ai_status?: string; operational_status?: string; scan_run_id?: string };
  read_only_research: boolean;
  automatic_execution_allowed: boolean;
  order_submission_enabled: boolean;
};

type TradeInstructionPayload = {
  instruction_id: string;
  symbol: string;
  state: "MONITORING" | "READY" | "TRIGGERED" | "INVALIDATED" | "EXPIRED" | "EXIT_REVIEW" | string;
  action: string;
  severity: "INFO" | "ACTION" | "RISK" | "CRITICAL" | string;
  quote_time?: string | null;
  data_source: string;
  plan: {
    observed_price?: number | null;
    bid?: number | null;
    ask?: number | null;
    entry_low?: number | null;
    entry_high?: number | null;
    stop?: number | null;
    target_low?: number | null;
    target_high?: number | null;
    risk_reward_value?: number | null;
  };
  evidence: { blockers?: string[]; data_eligible?: boolean; bbo_valid?: boolean };
  created_at: string;
};

type AlertEventPayload = {
  alert_id: string;
  instruction_id?: string | null;
  symbol: string;
  severity: "INFO" | "ACTION" | "RISK" | "CRITICAL" | string;
  title: string;
  message: string;
  acknowledged_at?: string | null;
  created_at: string;
};

type OptionExpressionCandidate = {
  candidate_id: string;
  contract_symbol: string;
  expiry_date: string;
  strike_price: number;
  bid?: number | null;
  ask?: number | null;
  delta?: number | null;
  implied_volatility?: number | null;
  open_interest?: number;
  volume?: number;
  spread_pct?: number | null;
  status: "eligible" | "paper_only" | "blocked" | string;
  score: number;
  max_loss: number;
  breakeven: number;
  underlying_price?: number;
  blockers: string[];
};

type OptionCandidatesPayload = {
  symbol: string;
  status: string;
  candidates: OptionExpressionCandidate[];
  event_calendar_ready?: boolean;
  blockers?: string[];
};

type ProductionReadinessPayload = {
  strategy_version: string;
  decision: "GO" | "NO_GO" | string;
  failed_gate_count: number;
  failed_gates: { gate: string; reason: string }[];
  historical: { sample_count: number; average_r: number; profit_factor: number };
  forward?: { market_day_count?: number; completed_outcome_count?: number; data_incident_count?: number } | null;
  paper?: { closed_position_count?: number; average_r?: number } | null;
  automatic_execution_allowed: boolean;
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

const copy = {
  en: {
    title: "KQUANT US Stock Signal Terminal",
    subtitle: "Realtime stock research, deterministic validation, and manual review.",
    stockView: "Stock Terminal",
    source: "Source",
    fixture: "Fixture",
    live: "Live",
    refresh: "Run Stock Scan",
    readOnly: "Read-only research",
    llmLocked: "Research-led / safeguards",
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
    blockers: "Blockers",
    confidence: "Confidence",
    currentPage: "Current",
    systemStatus: "System",
    navigation: "Navigation",
    tradingSystem: "Trading System",
    universeControl: "Universe",
    actions: "Actions",
    preferences: "Preferences",
    todayNav: "Today",
    todaySub: "Opportunities",
    searchNav: "Search",
    searchSub: "Stocks",
    watchlistNav: "Watchlist",
    watchlistSub: "Universe",
    stockNav: "Stock",
    stockSub: "Detail",
    chartsNav: "Charts",
    chartsSub: "K-Line",
    aiPlanNav: "Trade Plan",
    aiPlanSub: "Plan",
    chatNav: "Chat",
    chatSub: "Deep Research",
    researchNav: "Research",
    researchSub: "Dossier",
    evidenceNav: "Evidence",
    evidenceSub: "Sources",
    reportsNav: "Reports",
    reportsSub: "Exports",
    journalNav: "Journal",
    journalSub: "Notes",
    settingsNav: "Settings",
    settingsSub: "Safety",
    refreshStock: "Refresh Stock",
    refreshAiToday: "Refresh today",
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
    stockDecisionTitle: "Can I buy this stock now?",
    stockDecisionLoading: "Checking whether {symbol} is buyable now...",
    directAnswer: "Direct answer",
    marketSetup: "Market setup",
    executionCheck: "Execution check",
    waitFor: "Wait for",
    chartEvidence: "Chart evidence",
    noAutoOrder: "Research only / no automatic order",
    systemStatusSummary: "Readiness, provider, and risk rules",
    answerBuyCandidate: "Buy candidate for manual review",
    answerPullbackBuy: "Pullback buy candidate",
    answerProbeBuy: "Small-size probe candidate",
    answerBreakoutWatch: "Breakout watch",
    answerReversalWatch: "Reversal watch",
    answerWait: "Wait",
    answerAvoid: "Do not buy",
    answerExitReview: "No fresh long / review existing position",
    answerHoldTrail: "Hold / trail if already in position",
    answerUnknown: "No clear answer yet",
    answerDataMissing: "Cannot judge: live K-lines are unavailable",
    answerAiThinking: "Preparing the trade plan",
    answerAiUnavailable: "Research service unavailable; using rule and K-line evidence only",
    aiTradingCommand: "Trade conclusion",
    regenerateAiCommand: "Refresh trade plan",
    aiCommandGenerating: "Updating trade plan...",
    aiKeyRequired: "Research service unavailable",
    aiModelNote: "Combines K-lines, score, regime, historical evidence, and risk controls.",
    aiUnavailableHint: "Research service is unavailable. Check the local backend configuration.",
    aiReviewRequired: "Extra review required: high-beta setups need smaller size, staged entry, volatility-aware stops, and no chasing.",
    aiSignalPlan: "Trade plan",
    aiAction: "Conclusion",
    hardVeto: "Hard Veto",
    entryZone: "Entry Zone",
    stopZone: "Stop Zone",
    targetZone: "Target Zone",
    riskReward: "Risk / Reward",
    sizeHint: "Size Hint",
    bestProfile: "Best Profile",
    strategyQuality: "Strategy Quality",
    moneyPilot: "Money Pilot",
    probeCandidate: "Probe Candidate",
    probeCandidates: "Probe Candidates",
    noProbeCandidate: "No small-size probe candidate yet.",
    probeRisk: "Probe risk",
    eligibleForProbe: "Eligible for probe review",
    blockedForProbe: "Blocked for probe",
    eligibleForReview: "Eligible for review",
    blockedForPilot: "Blocked for pilot",
    expectedR: "Expected R",
    targetHit: "Target Hit",
    stopHit: "Stop Hit",
    sampleQuality: "Sample Quality",
    whyNow: "Why Now",
    invalidation: "Invalidation",
    humanChecklist: "Human Checklist",
    ruleGuardrails: "Rule Guardrails",
    why: "Why",
    aiRequestFailed: "Research service request failed. Check the local backend configuration.",
    aiNotActive: "Research service is not active. Configure the local backend, then restart the dashboard.",
    aiToday: "Today",
    aiResearchSignals: "Research opportunities",
    aiTodayDescription: "Ranks today's research opportunities for {universe} and prepares entry, stop, target, risk/reward, and position-size plans. Data and risk controls still block unsafe conditions.",
    aiUnavailableUntilKey: "Research service unavailable",
    refreshAiSignals: "Refresh opportunities",
    generating: "Generating...",
    status: "Status",
    autoAgent: "Auto Agent",
    freshness: "Freshness",
    model: "Model",
    candidates: "Candidates",
    readOnlyShort: "Read Only",
    noBrokerNoOrder: "no broker / no order",
    guarded: "guarded",
    topAiSignals: "Top opportunities",
    noAiCandidate: "No clean buy candidate yet.",
    topProbeSignals: "Probe Candidates",
    watchForPullback: "Watch for Pullback",
    noAiWatchlist: "No watchlist items yet.",
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
    dataSourceCopy: "Longbridge is the primary market-data source. Yahoo is retained only as an isolated historical reference and cannot support a trade review.",
    remoteApi: "Remote API",
    aiStatusTitle: "Research Service",
    aiStatusCopy: "The research service ranks opportunities and prepares plans, while data and risk controls remain in force.",
    consumerSafetyCopy: "Consumer Safety Copy",
    consumerSafetyText: "KQUANT provides research signals for manual review. It does not read brokerage accounts, submit orders, manage portfolios, or promise returns.",
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
    afterCloseReview: "After-close review",
    journalCoverage: "Journal coverage",
    reviewedNotes: "Reviewed",
    skippedNotes: "Skipped",
    enteredManually: "Entered manually",
    exitedManually: "Exited manually",
    invalidatedNotes: "Invalidated",
    journalPilotHint: "For the live pilot, every manual entry needs planned entry, stop, target, and an after-close outcome.",
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
    source: "数据源",
    fixture: "演示数据",
    live: "实时",
    refresh: "运行股票扫描",
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
    blockers: "阻断因素",
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
    stockDecisionTitle: "这只股票现在能不能买？",
    stockDecisionLoading: "正在判断 {symbol} 现在是否可以买...",
    directAnswer: "直接答案",
    marketSetup: "行情判断",
    executionCheck: "执行检查",
    waitFor: "等待条件",
    chartEvidence: "K线证据",
    noAutoOrder: "仅研究信号 / 不自动下单",
    systemStatusSummary: "准备度、数据源、AI 和第一天风控规则",
    answerBuyCandidate: "可进入人工买入复核",
    answerPullbackBuy: "回踩买入候选",
    answerBreakoutWatch: "突破观察，等确认",
    answerReversalWatch: "反转观察，等结构修复",
    answerWait: "等待",
    answerAvoid: "不要买",
    answerExitReview: "不适合新开仓；如已持有需复核风险",
    answerHoldTrail: "如已持有可跟踪止盈",
    answerUnknown: "还没有明确答案",
    answerDataMissing: "无法判断：实时 K 线不可用",
    answerAiThinking: "正在整理交易计划",
    answerAiUnavailable: "研究服务暂时不可用；当前仅展示规则和 K 线证据",
    aiTradingCommand: "交易结论",
    regenerateAiCommand: "更新交易计划",
    aiCommandGenerating: "正在更新交易计划...",
    aiKeyRequired: "研究服务未配置",
    aiModelNote: "研究结论综合 K 线、评分、市场状态、历史样本与风险检查。",
    aiUnavailableHint: "后端缺少 OPENAI_API_KEY。请只放在本地后端环境变量，不要放进前端或 GitHub。",
    aiReviewRequired: "高波动形态需要额外复核：小仓、分批、按波动设置止损，避免追高。",
    aiSignalPlan: "交易计划",
    aiAction: "研究结论",
    hardVeto: "行情条件",
    entryZone: "入场区",
    stopZone: "止损区",
    targetZone: "目标区",
    riskReward: "盈亏比",
    sizeHint: "仓位提示",
    bestProfile: "最佳系统",
    strategyQuality: "策略质量",
    moneyPilot: "交易资格检查",
    eligibleForReview: "可进入人工复核",
    blockedForPilot: "当前不满足条件",
    expectedR: "期望R",
    targetHit: "触及目标",
    stopHit: "触及止损",
    sampleQuality: "样本质量",
    whyNow: "为什么现在",
    invalidation: "失效条件",
    humanChecklist: "人工检查清单",
    ruleGuardrails: "规则风控",
    why: "原因",
    aiRequestFailed: "研究服务暂时不可用，请稍后重试或在设置中检查本机服务。",
    aiNotActive: "研究服务尚未就绪；当前仅展示行情、规则与图表证据。",
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
    deepResearchSubtitle: "围绕当前股票的结构、风险、入场条件与图表证据展开复核。",
    researchModel: "研究服务",
    askResearchPlaceholder: "询问这个形态、风险、入场条件或需要继续确认的证据…",
    askResearch: "提问",
    askingResearch: "思考中...",
    researchChatUnavailable: "研究服务暂时不可用，请检查本机后端设置。",
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
    afterCloseReview: "盘后复盘",
    journalCoverage: "复盘覆盖",
    reviewedNotes: "已复核",
    skippedNotes: "已跳过",
    enteredManually: "手动进入",
    exitedManually: "手动退出",
    invalidatedNotes: "失效记录",
    journalPilotHint: "真钱 Pilot 中，每笔手工进入都必须记录计划入场、止损、目标和盘后结果。",
    mondayRunbook: "周一执行流程",
    runbookPremarket: "开盘前：启动 KQUANT，确认 READY，重新生成 AI Daily 报告",
    runbookOpen: "开盘后：等待 15-30 分钟，只看 Top AI 和回踩观察名单",
    runbookEntry: "入场前：确认日线/1H、入场、止损、目标、盈亏比、失效条件和 Journal",
    runbookClose: "盘后：更新 Journal，复盘 AI 和 K 线证据是否有效",
  },
} as const;
const CHART_PRESETS: ChartPreset[] = [
  { key: "today1m", label: "Today 1m", range: "1d", interval: "1m" },
  { key: "today5m", label: "Today 5m", range: "1d", interval: "5m" },
  { key: "5d15m", label: "5D 15m", range: "5d", interval: "15m" },
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
  "MSTR:MicroStrategy:Technology:Technology",
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
};

const STOCK_SEARCH_ALIASES: Record<string, string[]> = {
  NVDA: ["英伟达", "gpu", "accelerator"],
  MSFT: ["微软", "azure"],
  GOOGL: ["谷歌", "google", "gemini"],
  AMZN: ["亚马逊", "aws"],
  TSLA: ["特斯拉", "robotaxi", "autonomy"],
  MSTR: ["microstrategy", "strategy"],
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
  { label: "Chips", query: "半导体" },
  { label: "Compute", query: "gpu云" },
  { label: "Storage", query: "存储" },
  { label: "Optical", query: "光模块" },
  { label: "Robotics", query: "具身智能" },
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
  const [session, setSession] = useState<AuthSession | null>(null);
  const [authState, setAuthState] = useState<"checking" | "ready" | "login" | "setup" | "error">("checking");

  async function refreshSession() {
    try {
      const response = await apiFetch("/api/auth/session");
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const payload = (await response.json()) as AuthSession;
      setSession(payload);
      setAuthState(!payload.authentication_required || payload.authenticated ? "ready" : payload.mode === "setup_required" ? "setup" : "login");
    } catch {
      setSession(null);
      setAuthState("error");
    }
  }

  useEffect(() => {
    void refreshSession();
  }, []);

  async function handleLogout() {
    await apiFetch("/api/auth/logout", { method: "POST" });
    setSession(null);
    setAuthState("login");
  }

  if (authState === "checking") {
    return <div className="auth-loading"><BrandMark /><span>正在打开 KQUANT…</span></div>;
  }
  if (authState === "login" || authState === "setup" || authState === "error") {
    return <LoginScreen mode={authState} onAuthenticated={refreshSession} />;
  }
  return <TerminalApp onLogout={handleLogout} loginEnabled={Boolean(session?.authentication_required)} />;
}

function TerminalApp({ onLogout, loginEnabled }: { onLogout: () => void; loginEnabled: boolean }) {
  const [lang, setLang] = useStoredState<Lang>("kquant-stock:lang", initialLanguage());
  const [theme, setTheme] = useStoredState<Theme>("kquant-stock:theme", "light");
  const [chartTimezone, setChartTimezone] = useStoredState<DisplayTimezone>("kquant-stock:chart-timezone:v1", "Asia/Shanghai");
  const [view, setView] = useStoredState<AppView>("kquant-stock:view:v1", "stocks");
  const source: Source = "live";
  const [selectedUniverse, setSelectedUniverse] = useStoredState<UniverseName>("kquant-stock:universe:v2", "default");
  const [selectedProfile, setSelectedProfile] = useStoredState<StrategyProfileName>("kquant-stock:strategy-profile:v1", "tactical_1w_v1");
  const [primaryPresetKey, setPrimaryPresetKey] = useStoredState<ChartPresetKey>("kquant-stock:primary-preset:v2", "1d");
  const [confirmationPresetKey, setConfirmationPresetKey] = useStoredState<ChartPresetKey>("kquant-stock:confirmation-preset:v2", "1h");
  const [run, setRun] = useState<SignalRun>(() => makeUnavailableSignalRun(selectedUniverse));
  const [universe, setUniverse] = useState<UniverseStock[]>(() => stocksForUniverse(selectedUniverse));
  const linkedSymbol = initialUrlSymbol();
  const [selectedSymbol, setSelectedSymbol] = useStoredState<string>("kquant-stock:selected", linkedSymbol ?? "NVDA", Boolean(linkedSymbol));
  const [searchText, setSearchText] = useState("");
  const [recentSearches, setRecentSearches] = useStoredState<string>("kquant-stock:recent-searches:v1", "NVDA,MSTR,SPY");
  const primaryPreset = chartPresetByKey(primaryPresetKey);
  const confirmationPreset = chartPresetByKey(confirmationPresetKey);
  const [dailyCandles, setDailyCandles] = useState<Candle[]>([]);
  const [hourlyCandles, setHourlyCandles] = useState<Candle[]>([]);
  const [realtimeSnapshot, setRealtimeSnapshot] = useState<RealtimeSnapshotPayload | null>(null);
  const [realtimeState, setRealtimeState] = useState<"idle" | "loading" | "live" | "stale" | "offline">("idle");
  const [dailyMeta, setDailyMeta] = useState<CandleMeta>(() => failedMeta("NVDA", chartPresetByKey("1d")));
  const [hourlyMeta, setHourlyMeta] = useState<CandleMeta>(() => failedMeta("NVDA", chartPresetByKey("1h")));
  const [apiState, setApiState] = useState<"api" | "fallback">("fallback");
  const [apiConnection, setApiConnection] = useState<ApiConnectionState>("checking");
  const [apiHealth, setApiHealth] = useState<ApiHealthPayload | null>(null);
  const [aiStatus, setAiStatus] = useState<AiReviewStatusPayload | null>(null);
  const [marketRegime, setMarketRegime] = useState<MarketRegimePayload | null>(null);
  const [stockJournal, setStockJournal] = useState<StockJournalPayload | null>(null);
  const [fixtureBlocked, setFixtureBlocked] = useState(() => urlRequestedFixture());
  const [analysisState, setAnalysisState] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const [profileCompare, setProfileCompare] = useState<StockSignal[]>([]);
  const [compareState, setCompareState] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const [aiReview, setAiReview] = useState<AiReviewPayload | null>(null);
  const [aiReviewState, setAiReviewState] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const [aiDecision, setAiDecision] = useState<AiDecisionPayload | null>(null);
  const [aiDecisionState, setAiDecisionState] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const [researchChatsBySymbol, setResearchChatsBySymbol] = useState<Record<string, ResearchChatMessage[]>>({});
  const [researchChatInput, setResearchChatInput] = useState("");
  const [researchChatState, setResearchChatState] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const [aiDailyReport, setAiDailyReport] = useState<AiDailyAgentPayload | null>(null);
  const [aiDailyState, setAiDailyState] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const [mondayReadinessReport, setMondayReadinessReport] = useState<MondayReadinessReport | null>(null);
  const [todayWorkbench, setTodayWorkbench] = useState<TodayWorkbenchPayload | null>(null);
  const [quantOverview, setQuantOverview] = useState<QuantOverviewPayload | null>(null);
  const [productionReadiness, setProductionReadiness] = useState<ProductionReadinessPayload | null>(null);
  const [tradeInstructions, setTradeInstructions] = useState<TradeInstructionPayload[]>([]);
  const [realtimeAlerts, setRealtimeAlerts] = useState<AlertEventPayload[]>([]);
  const [unreadAlertCount, setUnreadAlertCount] = useState(0);
  const [optionCandidates, setOptionCandidates] = useState<OptionCandidatesPayload | null>(null);
  const [optionCandidateState, setOptionCandidateState] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const [optionPaperMessage, setOptionPaperMessage] = useState("");
  const [earlyTrend, setEarlyTrend] = useState<EarlyTrendPayload | null>(null);
  const [aiAgentAutoRunState, setAiAgentAutoRunState] = useState<"idle" | "checking" | "generating" | "ready" | "skipped" | "unavailable" | "error">("idle");
  const [activeWorkspace, setActiveWorkspace] = useState<WorkspaceName>(() => initialUrlWorkspace());
  const [researchOpen, setResearchOpen] = useState(() => window.innerWidth >= 1080);
  const [searchResults, setSearchResults] = useState<UniverseStock[]>([]);
  const [searchState, setSearchState] = useState<"idle" | "loading" | "ready" | "error">("idle");
  const [searchOpen, setSearchOpen] = useState(false);
  const analyzeRequestRef = useRef(0);
  const candleRequestRef = useRef(0);
  const quoteRequestRef = useRef(0);
  const lastCandleRefreshRef = useRef(0);
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
  const researchChatMessages = researchChatsBySymbol[selected.symbol] ?? [];
  const latestResearchMessage = [...researchChatMessages].reverse().find((message) => message.role === "assistant");
  const latestResearchAnswer = latestResearchMessage?.payload?.answer;
  const showStockWorkspace = ["watchlist", "stock", "charts", "aiPlan", "chat", "journal"].includes(activeWorkspace);
  const showSelectedPanel = ["stock", "aiPlan", "journal"].includes(activeWorkspace);
  const showDeepResearch = false;
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
    mondayReadinessReport,
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
    lang,
  });

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    document.documentElement.lang = lang === "zh" ? "zh-CN" : "en";
  }, [lang, theme]);

  useEffect(() => {
    void loadApiHealth();
    void loadAiStatus();
    void loadAiDailyReportLatest();
    void loadMondayReadinessReport();
    void loadTodayWorkbench();
    void loadQuantOverview();
    void loadProductionReadiness();
    void loadRealtimeCommandCenter();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const linkedSymbol = initialUrlSymbol();
    if (linkedSymbol) {
      void analyzeSymbol(linkedSymbol, { preserveWorkspace: true });
    }
    // A notification deep link must override the last locally viewed symbol once.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    const source = new EventSource(apiUrl("/api/alerts/stream"), { withCredentials: true });
    const handleAlert = (message: MessageEvent<string>) => {
      try {
        const alert = JSON.parse(message.data) as AlertEventPayload;
        setRealtimeAlerts((current) => [alert, ...current.filter((item) => item.alert_id !== alert.alert_id)].slice(0, 20));
        setUnreadAlertCount((count) => count + 1);
        void loadRealtimeCommandCenter();
      } catch {
        // Ignore malformed external stream messages; persisted alerts remain available through the REST endpoint.
      }
    };
    source.addEventListener("alert", handleAlert as EventListener);
    return () => source.close();
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
      void analyzeSymbol(selectedSymbol || "SPY", { keepSearch: true, preserveWorkspace: true });
      void loadSignals(false);
      void loadMarketRegime();
      void loadTodayWorkbench();
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
    setResearchChatInput("");
    setResearchChatState("idle");
    setOptionCandidates(null);
    setOptionCandidateState("idle");
    setOptionPaperMessage("");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selected.symbol, primaryPresetKey, confirmationPresetKey]);

  async function loadRealtimeCommandCenter() {
    try {
      const [instructionResponse, alertResponse] = await Promise.all([
        apiFetch("/api/instructions/current?limit=30"),
        apiFetch("/api/alerts?limit=20"),
      ]);
      if (!instructionResponse.ok || !alertResponse.ok) throw new Error("Realtime command center unavailable");
      const instructions = (await instructionResponse.json()) as { instructions?: TradeInstructionPayload[] };
      const alerts = (await alertResponse.json()) as { alerts?: AlertEventPayload[]; unread_count?: number };
      setTradeInstructions(instructions.instructions ?? []);
      setRealtimeAlerts(alerts.alerts ?? []);
      setUnreadAlertCount(alerts.unread_count ?? 0);
    } catch {
      setTradeInstructions([]);
    }
  }

  async function acknowledgeRealtimeAlert(alertId: string) {
    const response = await apiFetch(`/api/alerts/${encodeURIComponent(alertId)}/ack`, { method: "POST" });
    if (!response.ok) return;
    setRealtimeAlerts((current) => current.map((item) => item.alert_id === alertId ? { ...item, acknowledged_at: new Date().toISOString() } : item));
    setUnreadAlertCount((count) => Math.max(0, count - 1));
  }

  async function loadOptionCandidatesForSelected() {
    try {
      setOptionCandidateState("loading");
      const response = await apiFetch(`/api/options/candidates?symbol=${encodeURIComponent(selected.symbol)}`);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      setOptionCandidates((await response.json()) as OptionCandidatesPayload);
      setOptionCandidateState("ready");
    } catch {
      setOptionCandidates({ symbol: selected.symbol, status: "blocked", candidates: [], blockers: [lang === "zh" ? "期权行情或事件日历暂不可用。" : "Options data or the event calendar is unavailable."] });
      setOptionCandidateState("error");
    }
  }

  async function startOptionPaperObservation(candidate: OptionExpressionCandidate) {
    try {
      setOptionPaperMessage(lang === "zh" ? "正在建立观察记录…" : "Creating observation…");
      const response = await apiFetch("/api/options/paper-observations", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          action: "open",
          candidate_id: candidate.candidate_id,
          underlying_price: candidate.underlying_price ?? realtimeSnapshot?.quote.last ?? 0,
        }),
      });
      if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        throw new Error(String(error.detail || `HTTP ${response.status}`));
      }
      setOptionPaperMessage(lang === "zh" ? "已建立一张合约的本地观察记录。" : "One-contract local observation created.");
    } catch (error) {
      setOptionPaperMessage(error instanceof Error ? error.message : (lang === "zh" ? "建立观察记录失败。" : "Could not create observation."));
    }
  }

  useEffect(() => {
    if (view !== "stocks" || apiConnection !== "connected") return;
    void loadRealtimeSnapshot(selected.symbol);
    lastCandleRefreshRef.current = Date.now();
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") {
        void loadRealtimeQuote(selected.symbol);
        if (Date.now() - lastCandleRefreshRef.current >= 15_000) {
          lastCandleRefreshRef.current = Date.now();
          void loadCandles(selected.symbol, { silent: true });
        }
      }
    }, 5_000);
    return () => window.clearInterval(timer);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [view, apiConnection, selected.symbol, primaryPresetKey, confirmationPresetKey]);

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

  async function loadMondayReadinessReport() {
    try {
      const response = await apiFetch("/api/stocks/monday-readiness/latest");
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      setMondayReadinessReport((await response.json()) as MondayReadinessReport);
    } catch {
      setMondayReadinessReport(null);
    }
  }

  async function loadTodayWorkbench() {
    try {
      const response = await apiFetch(`/api/stocks/today-workbench?universe=${encodeURIComponent(selectedUniverse)}&profile=${encodeURIComponent(selectedProfile)}`);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      setTodayWorkbench((await response.json()) as TodayWorkbenchPayload);
    } catch {
      setTodayWorkbench(null);
    }
  }

  async function loadQuantOverview() {
    try {
      const response = await apiFetch("/api/quant/overview");
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      setQuantOverview((await response.json()) as QuantOverviewPayload);
    } catch {
      setQuantOverview(null);
    }
  }

  async function loadProductionReadiness() {
    try {
      const response = await apiFetch("/api/stocks/production-readiness?strategy_version=swing_long_v1.1.0");
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      setProductionReadiness((await response.json()) as ProductionReadinessPayload);
    } catch {
      setProductionReadiness(null);
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

  function submitStockSearch(query: string = searchText) {
    const symbol = resolveSearchSymbol(query, activeSearchResults, selected.symbol);
    setView("stocks");
    setActiveWorkspace("stock");
    setSearchOpen(false);
    void analyzeSymbol(symbol);
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

  async function analyzeSymbol(rawSymbol: string, options: { keepSearch?: boolean; preserveWorkspace?: boolean } = {}) {
    const symbol = rawSymbol.trim().toUpperCase().replace(/[^A-Z0-9.^-]/g, "");
    if (!symbol) return;
    const requestId = ++analyzeRequestRef.current;
    setView("stocks");
    if (!options.preserveWorkspace) setActiveWorkspace("stock");
    setSelectedSymbol(symbol);
    setAnalysisState("loading");
    setAiDecision(null);
    setAiDecisionState("idle");
    setEarlyTrend(null);
    const candlePromise = loadCandles(symbol);
    const journalPromise = loadStockJournal(symbol);
    const aiStatusPromise = loadAiStatus();
    const earlyTrendPromise = loadEarlyTrend(symbol, requestId);
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
      await Promise.allSettled([candlePromise, journalPromise, aiStatusPromise, earlyTrendPromise]);
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

  async function loadEarlyTrend(symbol: string, requestId: number) {
    const response = await apiFetch(`/api/stocks/${encodeURIComponent(symbol)}/early-trend`);
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    const payload = (await response.json()) as EarlyTrendPayload;
    if (requestId === analyzeRequestRef.current) setEarlyTrend(payload);
    return payload;
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
          model_tier: signal.profile_name === "cycle_1_3y_v1" ? "deep" : "review",
          signal_payload: signal,
          profile_comparison: profileCompare,
          trigger: options.trigger ?? "manual",
          research_context: {
            status: "removed",
            note: "External research layer has been removed. Use KQUANT live K-lines, rule guardrails, historical edge, and journal context.",
          },
          journal_context_limit: 5,
          force_regenerate: Boolean(options.force),
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
    const researchSymbol = selected.symbol;
    const requestId = ++researchChatRequestRef.current;
    const userMessage: ResearchChatMessage = {
      id: `user-${Date.now()}`,
      role: "user",
      content: question,
      created_at: new Date().toISOString(),
    };
    const nextMessages = [...(researchChatsBySymbol[researchSymbol] ?? []), userMessage].slice(-12);
    setResearchChatsBySymbol((current) => ({ ...current, [researchSymbol]: nextMessages }));
    setResearchChatInput("");
    setResearchChatState("loading");
    try {
      const response = await apiFetch("/api/stocks/research-chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          symbol: researchSymbol,
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
      setResearchChatsBySymbol((current) => ({
        ...current,
        [researchSymbol]: [
          ...nextMessages,
          {
            id: `assistant-${Date.now()}`,
            role: "assistant",
            content: payload.answer.answer,
            payload,
            created_at: payload.generated_at,
          },
        ],
      }));
      setResearchChatState("ready");
      setApiState("api");
    } catch {
      if (requestId !== researchChatRequestRef.current) return;
      setResearchChatsBySymbol((current) => ({
        ...current,
        [researchSymbol]: [
          ...nextMessages,
          {
            id: `assistant-error-${Date.now()}`,
            role: "assistant",
            content: lang === "zh" ? "研究服务暂时不可用，请稍后重试。" : "Research service is temporarily unavailable. Please try again.",
            created_at: new Date().toISOString(),
          },
        ],
      }));
      setResearchChatState("error");
      setApiState("fallback");
    }
  }

  async function loadCandles(symbol: string, options: { silent?: boolean } = {}) {
    const requestId = ++candleRequestRef.current;
    if (!options.silent) {
      setDailyCandles([]);
      setHourlyCandles([]);
      setDailyMeta(refreshingMeta(symbol, primaryPreset));
      setHourlyMeta(refreshingMeta(symbol, confirmationPreset));
    }
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
      if (options.silent) return;
      setDailyCandles([]);
      setHourlyCandles([]);
      setDailyMeta(failedMeta(symbol, primaryPreset));
      setHourlyMeta(failedMeta(symbol, confirmationPreset));
      setApiConnection((current) => (current === "connected" ? current : "offline"));
    }
  }

  async function loadRealtimeSnapshot(symbol: string) {
    const requestId = ++quoteRequestRef.current;
    try {
      setRealtimeState((current) => (current === "live" ? current : "loading"));
      const response = await apiFetch(`/api/stocks/realtime-snapshot?symbol=${encodeURIComponent(symbol)}`);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const payload = (await response.json()) as RealtimeSnapshotPayload;
      if (requestId !== quoteRequestRef.current || payload.symbol !== selectedSymbol) return;
      setRealtimeSnapshot(payload);
      setRealtimeState(payload.provider_status === "available" && payload.quote_fresh ? "live" : "stale");
      const realtimeOneMinute = normalizeCandles(payload.candles_1m, []);
      const realtimeFiveMinute = normalizeCandles(payload.candles_5m, []);
      if (primaryPreset.range === "1d" && primaryPreset.interval === "1m" && realtimeOneMinute.length) {
        setDailyCandles(realtimeOneMinute);
        setDailyMeta(metaFromRealtimeSnapshot(payload, primaryPreset, realtimeOneMinute));
      } else if (primaryPreset.range === "1d" && primaryPreset.interval === "5m" && realtimeFiveMinute.length) {
        setDailyCandles(realtimeFiveMinute);
        setDailyMeta(metaFromRealtimeSnapshot(payload, primaryPreset, realtimeFiveMinute));
      }
      if (confirmationPreset.range === "1d" && confirmationPreset.interval === "1m" && realtimeOneMinute.length) {
        setHourlyCandles(realtimeOneMinute);
        setHourlyMeta(metaFromRealtimeSnapshot(payload, confirmationPreset, realtimeOneMinute));
      } else if (confirmationPreset.range === "1d" && confirmationPreset.interval === "5m" && realtimeFiveMinute.length) {
        setHourlyCandles(realtimeFiveMinute);
        setHourlyMeta(metaFromRealtimeSnapshot(payload, confirmationPreset, realtimeFiveMinute));
      }
      applyRealtimeQuote(payload.quote, symbol);
    } catch {
      if (requestId !== quoteRequestRef.current) return;
      setRealtimeState("offline");
    }
  }

  async function loadRealtimeQuote(symbol: string) {
    const requestId = ++quoteRequestRef.current;
    try {
      const response = await apiFetch(`/api/stocks/quote?symbol=${encodeURIComponent(symbol)}`);
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      const quote = (await response.json()) as RealtimeQuote;
      if (requestId !== quoteRequestRef.current || quote.symbol !== selectedSymbol) return;
      setRealtimeSnapshot((current) => (current ? { ...current, quote, quote_fresh: Number(quote.freshness_seconds ?? 999) <= 15 } : current));
      setRealtimeState(quote.provider_status === "available" && Number(quote.freshness_seconds ?? 999) <= 15 ? "live" : "stale");
      applyRealtimeQuote(quote, symbol);
    } catch {
      if (requestId !== quoteRequestRef.current) return;
      setRealtimeState("offline");
    }
  }

  function applyRealtimeQuote(quote: RealtimeQuote, symbol: string) {
    if (symbol !== selectedSymbol || quote.provider_status !== "available" || quote.last == null || !quote.quote_time) return;
    const quoteTime = quote.quote_time;
    setDailyCandles((current) => mergeRealtimeQuote(current, quote, primaryPreset.interval));
    setHourlyCandles((current) => mergeRealtimeQuote(current, quote, confirmationPreset.interval));
    setDailyMeta((current) => ({ ...current, quoteTime: formatDateTimeUtc8(quoteTime, { withDate: true }), session: quote.session }));
    setHourlyMeta((current) => ({ ...current, quoteTime: formatDateTimeUtc8(quoteTime, { withDate: true }), session: quote.session }));
  }

  function openWorkspace(workspace: WorkspaceName) {
    setActiveWorkspace(workspace);
    if (workspace === "chat") setResearchOpen(true);
    if (view !== "stocks") setView("stocks");
  }

  const runtimeMismatch = apiConnection === "connected" && apiHealth?.runtime?.api_contract_version !== FRONTEND_API_CONTRACT_VERSION;

  return (
    <main className={`app-shell ${researchOpen ? "research-open" : ""}`}>
      <header className="topbar">
        <div className="brand">
          <BrandMark />
          <div>
            <h1>{lang === "zh" ? "KQUANT 美股研究终端" : "KQUANT US Stock Research"}</h1>
            <p>{lang === "zh" ? "实时行情、交易计划与人工复核" : "Realtime data, trade plans, and manual review."}</p>
          </div>
        </div>
        <div className="top-context">
          <span>{lang === "zh" ? "当前标的" : "Selected"}</span>
          <strong>{selected.symbol} / {lang === "zh" ? "交易结论" : "Trade conclusion"}</strong>
        </div>
        <div className="top-status-mini" aria-label={text.systemStatus}>
          {runtimeMismatch ? <span className="runtime-warning">Restart local service</span> : null}
          <Pill
            tone={apiConnection === "connected" ? "good" : "warn"}
            icon={<Activity size={14} />}
            label={apiConnection === "connected" ? marketDataMiniLabel(apiHealth) : lang === "zh" ? "行情离线" : "Market offline"}
          />
          <button type="button" className="topbar-icon-button" onClick={() => setResearchOpen((open) => !open)} title={researchOpen ? (lang === "zh" ? "收起深度研究" : "Close research") : (lang === "zh" ? "打开深度研究" : "Open research")}>
            {researchOpen ? <PanelRightClose size={17} /> : <PanelRightOpen size={17} />}
          </button>
          {loginEnabled ? (
            <button type="button" className="topbar-icon-button" onClick={onLogout} title={lang === "zh" ? "退出登录" : "Sign out"}>
              <LogOut size={17} />
            </button>
          ) : null}
        </div>
      </header>

      <section className="stock-workspace-shell">
        <aside className="workspace-sidebar" aria-label="Workspace navigation">
          <div className="sidebar-section primary-nav-section">
            <span className="sidebar-section-title">{text.navigation}</span>
            {[
              ["today", lang === "zh" ? "今日" : "Today", lang === "zh" ? "机会" : "Opportunities"],
              ["stock", lang === "zh" ? "股票" : "Stock", lang === "zh" ? "结论" : "Conclusion"],
              ["charts", lang === "zh" ? "图表" : "Charts", "K 线"],
              ["aiPlan", lang === "zh" ? "交易计划" : "Trade Plan", lang === "zh" ? "计划" : "Plan"],
              ["chat", lang === "zh" ? "深度研究" : "Research", lang === "zh" ? "问答" : "Ask"],
              ["journal", lang === "zh" ? "日志" : "Journal", lang === "zh" ? "复盘" : "Review"],
              ["settings", lang === "zh" ? "设置" : "Settings", lang === "zh" ? "状态" : "Status"],
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
            <button className="sidebar-action-button" type="button" onClick={() => void loadSignals(true)}>
              <RefreshCw size={14} />
              {text.refresh}
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
          </div>
        </aside>
        <div className="stock-workspace-main">

      <section className="research-command-panel" id="stock-search-workspace" aria-label="Stock command search">
        <form
          className="symbol-command symbol-command-large"
          onSubmit={(event) => {
            event.preventDefault();
            submitStockSearch();
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
                submitStockSearch();
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
                  submitStockSearch(shortcut.symbol);
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
                  onClick={() => submitStockSearch(stock.symbol)}
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
          <button key={symbol} type="button" className={symbol === selected.symbol ? "symbol-chip active" : "symbol-chip"} onClick={() => submitStockSearch(symbol)}>
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

      <>
      <div id="ai-trade-desk-workspace" className={activeWorkspace === "today" ? "" : "workspace-hidden"}>
      <QuantOverviewPanel
        overview={quantOverview}
        lang={lang}
        onPick={(symbol) => void analyzeSymbol(symbol)}
      />
      <RealtimeCommandCenterView
        instructions={tradeInstructions}
        alerts={realtimeAlerts}
        unreadCount={unreadAlertCount}
        selectedSymbol={selected.symbol}
        optionCandidates={optionCandidates}
        optionState={optionCandidateState}
        lang={lang}
        onPick={(symbol) => void analyzeSymbol(symbol)}
        onAcknowledge={(alertId) => void acknowledgeRealtimeAlert(alertId)}
        onLoadOptions={() => void loadOptionCandidatesForSelected()}
        onStartPaper={(candidate) => void startOptionPaperObservation(candidate)}
        optionPaperMessage={optionPaperMessage}
      />
      <TodayDecisionPanelView
        payload={todayWorkbench}
        onPick={(symbol) => void analyzeSymbol(symbol)}
        onRefresh={() => {
          void loadSignals(true);
          void loadTodayWorkbench();
        }}
      />
      <ThemeRadarPanelView
        run={run}
        universe={universe}
        selected={selected}
        selectedMeta={selectedMeta}
        aiDecision={aiDecision}
        dailyMeta={dailyMeta}
        hourlyMeta={hourlyMeta}
        readiness={mondayReadiness}
        lang={lang}
        onPick={(symbol) => void analyzeSymbol(symbol)}
        onOpenStock={() => openWorkspace("stock")}
      />
      <details className="system-status-details">
        <summary>
          <span>{text.systemStatus}</span>
          <strong>{mondayReadiness.status}</strong>
          <small>{text.systemStatusSummary}</small>
        </summary>
        <MondayReadinessPanel readiness={mondayReadiness} text={text} />
      </details>
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
      <DataReliabilityPanelView
        apiConnection={apiConnection}
        apiHealth={apiHealth}
        realtimeSnapshot={realtimeSnapshot}
        run={run}
        dailyMeta={dailyMeta}
        hourlyMeta={hourlyMeta}
        selectedSymbol={selected.symbol}
        apiBaseUrl={API_BASE_URL}
      />
      <RiskControlPanelView report={productionReadiness} onRefresh={() => void loadProductionReadiness()} />
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
            <StockDecisionAnswerCard
              selected={selected}
              aiDecision={aiDecision}
              aiDecisionState={aiDecisionState}
              analysisState={analysisState}
              dailyMeta={dailyMeta}
              hourlyMeta={hourlyMeta}
              realtimeSnapshot={realtimeSnapshot}
              realtimeState={realtimeState}
              text={text}
              lang={lang}
              onRegenerate={() => void requestAiDecision({ trigger: "manual", force: true })}
              onOpenJournal={() => openWorkspace("journal")}
            />
            <EarlyTrendPanelView snapshot={earlyTrend} lang={lang} />
            <ManualTradeTicketPanel
              ticket={manualTradeTicket}
              aiDecision={aiDecision}
              text={text}
              lang={lang}
              onOpenJournal={() => openWorkspace("journal")}
            />
            <section className="factor-evidence-panel" aria-label={lang === "zh" ? "判断依据" : "Decision evidence"}>
              <div className="factor-evidence-head">
                <div>
                  <span className="eyebrow">{lang === "zh" ? "判断依据" : "Decision evidence"}</span>
                  <strong>{lang === "zh" ? "已登记因子" : "Registered factors"}</strong>
                </div>
                <small>{selected.factor_snapshot?.factor_snapshot_hash?.slice(0, 10) ?? "-"}</small>
              </div>
              <div className="factor-evidence-grid">
                <EvidenceColumn title={lang === "zh" ? "支持因素" : "Supports"} entries={selected.decision_evidence?.supporting_factors} tone="positive" />
                <EvidenceColumn title={lang === "zh" ? "反对因素" : "Risks"} entries={selected.decision_evidence?.opposing_factors} tone="negative" />
                <EvidenceColumn title={lang === "zh" ? "尚缺数据" : "Missing data"} entries={selected.decision_evidence?.unavailable_factors} tone="neutral" />
              </div>
            </section>
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
          </section>
          ) : null}

          {showDeepResearch ? (
          <DeepResearchChatPanelView
            text={text}
            lang={lang}
            selected={selected}
            aiStatus={aiStatus}
            aiDecision={aiDecision}
            conclusion={displayTradeAction(aiDecision?.ai_decision?.action ?? "-", lang)}
            dataStatus={displayDataQuality(selected.data_status?.data_quality, lang)}
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
            <ChartPanelView
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
              displayTimezone={chartTimezone}
              onDisplayTimezoneChange={setChartTimezone}
              labels={{
                source: text.chartSource,
                status: text.chartStatus,
                range: text.chartRange,
                candles: text.candles,
                firstLast: text.firstLast,
              }}
            />
            <ChartPanelView
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
              displayTimezone={chartTimezone}
              onDisplayTimezoneChange={setChartTimezone}
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
          <StockJournalPanelView
              runId={run.run_id}
              symbol={selected.symbol}
              journal={stockJournal}
              text={text}
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
        <PanelTitle title={lang === "zh" ? "主题股票分层" : "Theme stock layers"} detail={`${universe.length} selected stocks / ${universeOptionLabel(selectedUniverse, lang)}`} />
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
      <SettingsPanelView
        apiConnection={apiConnection}
        aiStatus={aiStatus}
        apiBaseUrl={API_BASE_URL}
        apiHealth={apiHealth}
        text={text}
        lang={lang}
        apiFetch={apiFetch}
      />
      ) : null}
        </>
        </div>
      </section>
      <aside className={`research-drawer ${researchOpen ? "open" : ""}`} aria-label={lang === "zh" ? "深度研究" : "Deep research"}>
        <div className="research-drawer-head">
          <div>
            <span>{lang === "zh" ? "当前股票" : "Selected stock"}</span>
            <strong>{selected.symbol}</strong>
          </div>
          <button type="button" className="topbar-icon-button" onClick={() => setResearchOpen(false)} title={lang === "zh" ? "收起深度研究" : "Close research"}>
            <PanelRightClose size={17} />
          </button>
        </div>
        <DeepResearchChatPanelView
          text={text}
          lang={lang}
          selected={selected}
          aiStatus={aiStatus}
          aiDecision={aiDecision}
          conclusion={displayTradeAction(aiDecision?.ai_decision?.action ?? "-", lang)}
          dataStatus={displayDataQuality(selected.data_status?.data_quality, lang)}
          state={researchChatState}
          messages={researchChatMessages}
          input={researchChatInput}
          onInputChange={setResearchChatInput}
          onSend={() => void sendResearchChat()}
          onAsk={(question) => void sendResearchChat(question)}
        />
      </aside>
    </main>
  );
}

function BrandMark() {
  return (
    <div className="brand-mark" aria-label="KQUANT">
      <span>K</span><span>Q</span>
    </div>
  );
}

function LoginScreen({ mode, onAuthenticated }: { mode: "login" | "setup" | "error"; onAuthenticated: () => Promise<void> }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [state, setState] = useState<"idle" | "submitting" | "error">("idle");
  const [message, setMessage] = useState("");

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!email.trim() || !password || state === "submitting") return;
    setState("submitting");
    setMessage("");
    try {
      const response = await apiFetch("/api/auth/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: email.trim(), password }),
      });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      setPassword("");
      await onAuthenticated();
    } catch {
      setState("error");
      setMessage("邮箱或密码不正确，或服务暂时不可用，请稍后重试。");
    }
  }

  const setup = mode === "setup";
  return (
    <main className="login-shell">
      <section className="login-panel" aria-labelledby="login-title">
        <BrandMark />
        <div className="login-copy">
          <span className="eyebrow">KQUANT</span>
          <h1 id="login-title">美股研究终端</h1>
          <p>{setup ? "本机登录尚未配置。完成一次本机初始化后，研究数据将只在登录后可见。" : mode === "error" ? "无法连接本机服务。请确认 KQUANT 已启动后重试。" : "请输入邮箱和密码以进入研究工作台。"}</p>
        </div>
        {setup ? (
          <div className="login-setup">
            <KeyRound size={20} />
            <p>在项目目录运行以下命令，并将输出内容写入私有 <code>.env</code>：</p>
            <code>python -m kquant local-login-config</code>
          </div>
        ) : mode === "error" ? (
          <button className="primary-action" type="button" onClick={() => window.location.reload()}>重新连接</button>
        ) : (
          <form className="login-form" onSubmit={submit}>
            <label htmlFor="kquant-email">邮箱</label>
            <input id="kquant-email" type="email" value={email} onChange={(event) => setEmail(event.target.value)} autoFocus autoComplete="email" inputMode="email" />
            <label htmlFor="kquant-password">密码</label>
            <input id="kquant-password" type="password" value={password} onChange={(event) => setPassword(event.target.value)} autoComplete="current-password" />
            {message ? <p className="login-error">{message}</p> : null}
            <button className="primary-action" type="submit" disabled={state === "submitting" || !email.trim() || !password}>
              <Lock size={16} />
              {state === "submitting" ? "验证中" : "进入工作台"}
            </button>
          </form>
        )}
      </section>
    </main>
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
  const probe = aiReport?.probe_candidates ?? [];
  const watch = aiReport?.watch_for_pullback ?? [];
  const warnings = aiReport?.data_quality_warnings ?? [];
  return (
    <section className="panel ai-trade-desk">
      <div className="ai-trade-desk-head">
        <div>
          <span>{lang === "zh" ? "今日复核" : "Today"}</span>
          <h2>{lang === "zh" ? "研究机会" : "Research opportunities"}</h2>
          <p>
            {lang === "zh" ? `为 ${universeOptionLabel(selectedUniverse, lang)} 整理入场、止损、目标与风险收益，并由数据与风控条件决定是否可复核。` : `Prepare entry, stop, target, and risk/reward for ${universeOptionLabel(selectedUniverse, lang)}, subject to data and risk controls.`}
          </p>
        </div>
        <div className="ai-trade-desk-actions">
          <Pill
            tone={aiConnected ? "good" : "warn"}
            icon={<Activity size={14} />}
            label={aiConnected ? (lang === "zh" ? "研究服务已连接" : "Research ready") : (lang === "zh" ? "研究服务不可用" : "Research unavailable")}
          />
          <button className="primary-action" type="button" onClick={onRun} disabled={state === "loading"}>
            <RefreshCw size={15} />
            {state === "loading" ? (lang === "zh" ? "更新中" : "Updating") : (lang === "zh" ? "刷新机会" : "Refresh opportunities")}
          </button>
        </div>
      </div>
      <div className="ai-trade-summary">
        <Fact label={text.status} value={report?.status ?? "not_scanned"} />
        <Fact label={text.autoAgent} value={autoRunState} />
        <Fact label={text.freshness} value={report?.is_stale ? `stale ${report.age_seconds ?? "-"}s` : "fresh"} />
        <Fact label={lang === "zh" ? "研究服务" : "Research service"} value={aiConnected ? (lang === "zh" ? "已连接" : "Connected") : (lang === "zh" ? "不可用" : "Unavailable")} />
        <Fact label={text.candidates} value={String(report?.ai_context_candidate_count ?? 0)} />
        <Fact label={text.readOnlyShort} value={report?.broker_order_wiring_enabled === false ? text.noBrokerNoOrder : text.guarded} />
      </div>
      <div className="ai-opportunity-grid">
        <AiOpportunityColumn lang={lang} title={lang === "zh" ? "优先复核" : "Priority review"} empty={lang === "zh" ? "暂无满足条件的买入候选。" : "No clean buy candidate yet."} items={top} onPick={onPick} />
        <AiOpportunityColumn
          lang={lang}
          title={lang === "zh" ? "小仓观察" : "Small-size observation"}
          empty={lang === "zh" ? "暂无小仓试错候选。" : "No small-size probe candidate yet."}
          items={probe.slice(0, 6)}
          onPick={onPick}
        />
        <AiOpportunityColumn lang={lang} title={text.watchForPullback} empty={lang === "zh" ? "暂无观察项目。" : "No watchlist items yet."} items={watch.slice(0, 5)} onPick={onPick} />
        <AiOpportunityColumn
          lang={lang}
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
  lang,
  title,
  empty,
  items,
  onPick,
  passive = false,
}: {
  lang: Lang;
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
            {(() => {
              const validation = item.ai_action_validation;
              const moneyPilot = item.money_pilot_eligibility;
              const probe = item.probe_eligibility;
              return (
                <>
            <div>
              <b>{item.symbol}</b>
              <span>{displayTradeAction(item.action, lang)} / {item.confidence}</span>
            </div>
            <small>{item.best_profile || (lang === "zh" ? "交易计划" : "Trade plan")} / R:R {item.risk_reward || "-"}</small>
            <div className="opportunity-quality">
              <span>EV {formatNumber(validation?.expected_value_r)}R</span>
              <span>Win {formatNumber(validation?.win_rate)}%</span>
              <span>
                {moneyPilot?.eligible_for_review
                  ? (lang === "zh" ? "可人工复核" : "Manual review")
                  : probe?.eligible_for_probe_review
                    ? (lang === "zh" ? "小仓观察" : "Small-size review")
                    : (lang === "zh" ? "暂不满足条件" : "Not ready")}
              </span>
            </div>
            {item.action === "AI_PROBE_BUY" ? (
              <small>
                {lang === "zh" ? "小仓风险" : "Small-size risk"} {formatNumber(item.probe_risk_policy?.default_risk_pct_of_account ?? 0.15)}% / max{" "}
                {formatNumber(item.probe_risk_policy?.max_risk_pct_of_account ?? 0.2)}%
              </small>
            ) : null}
            <p>{item.entry_zone || item.why_now?.[0] || "Open for details."}</p>
            {item.hard_veto_applied ? <em>{lang === "zh" ? "当前风险条件未通过" : "Current risk conditions are not cleared"}</em> : null}
                </>
              );
            })()}
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
  lang,
  onOpenJournal,
}: {
  ticket: ManualTradeTicket;
  aiDecision: AiDecisionPayload | null;
  text: (typeof copy)["en"] | (typeof copy)["zh"];
  lang: Lang;
  onOpenJournal: () => void;
}) {
  const title =
    ticket.status === "cleared_for_review"
      ? (lang === "zh" ? "可进入人工复核" : "Ready for manual review")
      : ticket.status === "journal_required"
        ? (lang === "zh" ? "需先完成交易日志" : "Journal required")
        : (lang === "zh" ? "当前不满足人工交易条件" : "Not ready for manual trading");
  return (
    <section className={`manual-ticket ${ticket.status.replace(/_/g, "-")}`}>
      <div className="manual-ticket-head">
        <div>
          <span>{lang === "zh" ? "交易资格检查" : "Trade eligibility"}</span>
          <strong>{title}</strong>
          <p>{ticket.summary}</p>
        </div>
        <b>{displayTradeAction(ticket.action, lang)}</b>
      </div>
      <div className="manual-ticket-grid">
        <Fact label={text.entryZone} value={displayPlanField(ticket.entryZone, "entry", lang)} />
        <Fact label={text.stopZone} value={displayPlanField(ticket.stopZone, "stop", lang)} />
        <Fact label={text.targetZone} value={displayPlanField(ticket.targetZone, "target", lang)} />
        <Fact label={text.riskReward} value={displayPlanField(ticket.riskReward, "riskReward", lang)} />
        <Fact label={text.sizeHint} value={displayPlanField(ticket.positionSizeHint, "position", lang)} />
        <Fact label={lang === "zh" ? "风控状态" : "Risk control"} value={aiDecision?.hard_veto?.active ? (lang === "zh" ? "暂不通过" : "Not cleared") : (lang === "zh" ? "已通过" : "Cleared")} />
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
        <Narrative title={text.invalidation} items={(ticket.invalidatedIf.length ? ticket.invalidatedIf : [lang === "zh" ? "暂无失效条件。" : "No invalidation details yet."]).map((item) => displayResearchText(item, lang))} />
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

function StockDecisionAnswerCard({
  selected,
  aiDecision,
  aiDecisionState,
  analysisState,
  dailyMeta,
  hourlyMeta,
  realtimeSnapshot,
  realtimeState,
  text,
  lang,
  onRegenerate,
  onOpenJournal,
}: {
  selected: StockSignal;
  aiDecision: AiDecisionPayload | null;
  aiDecisionState: "idle" | "loading" | "ready" | "error";
  analysisState: "idle" | "loading" | "ready" | "error";
  dailyMeta: CandleMeta;
  hourlyMeta: CandleMeta;
  realtimeSnapshot: RealtimeSnapshotPayload | null;
  realtimeState: "idle" | "loading" | "live" | "stale" | "offline";
  text: (typeof copy)["en"] | (typeof copy)["zh"];
  lang: Lang;
  onRegenerate: () => void;
  onOpenJournal: () => void;
}) {
  const decision = aiDecision?.ai_decision;
  const rawAction = decision?.action ?? selected.trade_conclusion?.action ?? selected.level;
  const liveDataReady = isLiveCandleMeta(dailyMeta) && isLiveCandleMeta(hourlyMeta);
  const isLoading = analysisState === "loading";
  const actionAnswer = tradeAnswerCopy(rawAction, lang);
  const headline = isLoading
    ? text.stockDecisionLoading.replace("{symbol}", selected.symbol)
    : !liveDataReady
      ? text.answerDataMissing
      : aiDecisionState === "loading"
        ? text.answerAiThinking
        : aiDecisionState === "error"
          ? text.answerAiUnavailable
          : actionAnswer.label;
  const tone = isLoading || aiDecisionState === "loading" ? "watch" : !liveDataReady ? "pass" : actionClass(rawAction);
  const summary = displayResearchText(
    decision?.summary ??
      selected.trade_conclusion?.decision_summary ??
      selected.trigger_summary ??
      text.answerUnknown,
    lang,
  );
  const whyItems = (
    decision?.why_now?.length
      ? decision.why_now
      : selected.trade_conclusion?.why?.length
        ? selected.trade_conclusion.why
        : [selected.trend_summary, selected.trigger_summary]
  ).filter(Boolean).slice(0, 4).map((item) => displayResearchText(item, lang));
  const waitItems = (
    decision?.what_invalidates_this_setup?.length
      ? decision.what_invalidates_this_setup
      : selected.trade_conclusion?.invalidation?.length
        ? selected.trade_conclusion.invalidation
        : selected.exit_risk?.reasons ?? []
  ).filter(Boolean).slice(0, 4).map((item) => displayResearchText(item, lang));
  const moneyPilot = decision?.money_pilot_eligibility ?? aiDecision?.money_pilot_eligibility;
  const probe =
    decision?.probe_eligibility ??
    aiDecision?.probe_eligibility ??
    selected.probe_eligibility;
  const probePolicy =
    decision?.probe_risk_policy ??
    aiDecision?.probe_risk_policy ??
    selected.probe_risk_policy ??
    probe?.risk_policy;
  const probeReviewLabel = lang === "zh" ? "小仓观察" : "Small-size observation";
  const probeEligibleLabel = lang === "zh" ? "可复核" : "eligible";
  const probeBlockedLabel = lang === "zh" ? "未达门槛" : "blocked";
  const probeRiskLabel = lang === "zh" ? "小仓风险" : "Small-size risk";
  return (
    <section className={`stock-answer-card ${tone}`}>
      <div className="stock-answer-head">
        <div>
          <span className="eyebrow">{text.stockDecisionTitle}</span>
          <h3>{headline}</h3>
          <p>{summary}</p>
        </div>
        <div className={`answer-badge ${tone}`}>
          <span>{text.directAnswer}</span>
          <strong>{actionAnswer.shortLabel}</strong>
        </div>
      </div>
      <div className="stock-answer-facts">
        <Fact label={lang === "zh" ? "实时价格" : "Live Price"} value={realtimeSnapshot?.quote?.last == null ? "-" : formatNumber(realtimeSnapshot.quote.last)} />
        <Fact label={lang === "zh" ? "行情时间" : "Quote Time"} value={realtimeSnapshot?.quote?.quote_time ? formatDateTimeUtc8(realtimeSnapshot.quote.quote_time, { withDate: true }) : "-"} />
        <Fact label={lang === "zh" ? "实时状态" : "Realtime"} value={displayRealtimeState(realtimeState, realtimeSnapshot?.session, lang)} />
        <Fact label={text.aiAction} value={displayTradeAction(rawAction, lang)} />
        <Fact label={text.confidence} value={displayConfidence(decision?.confidence ?? selected.trade_conclusion?.confidence, lang)} />
        <Fact label={text.entryZone} value={displayPlanField(decision?.entry_zone, "entry", lang)} />
        <Fact label={text.stopZone} value={displayPlanField(decision?.stop_zone, "stop", lang)} />
        <Fact label={text.targetZone} value={displayPlanField(decision?.target_zone, "target", lang)} />
        <Fact label={text.riskReward} value={displayPlanField(decision?.risk_reward, "riskReward", lang)} />
      </div>
      <div className="stock-answer-body">
        <Narrative title={text.marketSetup} items={whyItems.length ? whyItems : [text.answerUnknown]} />
        <Narrative title={text.waitFor} items={waitItems.length ? waitItems : [actionAnswer.nextStep]} />
      </div>
      <div className="stock-answer-strip">
        <span>
          {text.chartEvidence}: {dailyMeta.providerStatus}/{dailyMeta.count} + {hourlyMeta.providerStatus}/{hourlyMeta.count}
        </span>
        <span>
          {text.hardVeto}: {aiDecision?.hard_veto?.active ? "active" : "clear"}
        </span>
        <span>
          {text.moneyPilot}: {moneyPilot?.eligible_for_review ? text.eligibleForReview : text.blockedForPilot}
        </span>
        <span>
          {probeReviewLabel}: {probe?.eligible_for_probe_review ? probeEligibleLabel : probeBlockedLabel}
        </span>
        <span>
          {probeRiskLabel}: {formatNumber(probePolicy?.default_risk_pct_of_account ?? 0.15)}% / max {formatNumber(probePolicy?.max_risk_pct_of_account ?? 0.2)}%
        </span>
        <span>{text.noAutoOrder}</span>
      </div>
      <div className="stock-answer-actions">
        <button type="button" onClick={onRegenerate} disabled={aiDecisionState === "loading"}>
          {aiDecisionState === "loading" ? text.aiCommandGenerating : text.regenerateAiCommand}
        </button>
        <button type="button" className="secondary-action" onClick={onOpenJournal}>
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
  lang,
  onReview,
}: {
  conclusion: StockSignal["trade_conclusion"] | undefined;
  aiReview: AiReviewPayload | null;
  aiReviewState: "idle" | "loading" | "ready" | "error";
  aiDecision: AiDecisionPayload | null;
  aiDecisionState: "idle" | "loading" | "ready" | "error";
  aiStatus: AiReviewStatusPayload | null;
  text: (typeof copy)["en"] | (typeof copy)["zh"];
  lang: Lang;
  onReview: () => void;
}) {
  const action = conclusion?.action ?? "DO_NOT_BUY";
  const ai = aiReview?.ai_review;
  const decision = aiDecision?.ai_decision;
  const actionValidation = decision?.ai_action_validation ?? aiDecision?.ai_action_validation ?? undefined;
  const baselineRiskReward = decision?.risk_reward_plan ?? aiDecision?.risk_reward_plan ?? undefined;
  const moneyPilot = decision?.money_pilot_eligibility ?? aiDecision?.money_pilot_eligibility ?? undefined;
  const probeEligibility = decision?.probe_eligibility ?? aiDecision?.probe_eligibility ?? undefined;
  const probePolicy =
    decision?.probe_risk_policy ??
    aiDecision?.probe_risk_policy ??
    probeEligibility?.risk_policy ??
    undefined;
  const displayAction = decision?.action ?? action;
  const displaySummary = decision?.summary ?? conclusion?.decision_summary ?? "No rule conclusion loaded yet.";
  const aiConnected = aiStatus?.status === "available";
  const aiReviewRequired =
    conclusion?.profile_name === "high_beta_growth_v1" && (action === "BUY" || action === "WAIT");
  return (
    <section className={`manual-conclusion ${actionClass(displayAction)}`}>
      <div className="manual-conclusion-main">
        <span>{lang === "zh" ? "交易结论" : "Trade conclusion"}</span>
        <strong>{displayTradeAction(displayAction, lang)}</strong>
        <p>{displaySummary}</p>
        {aiReviewRequired ? (
          <p className="compare-error">
            {lang === "zh" ? "高波动形态需要更小仓位、分批入场、波动止损，并且不能追高。" : "High-beta setups require smaller size, staged entries, volatility-aware stops, and no chasing."}
          </p>
        ) : null}
      </div>
      <div className="manual-conclusion-facts">
        <Fact label={lang === "zh" ? "结论可信度" : "Confidence"} value={displayConfidence(decision?.confidence ?? conclusion?.confidence, lang)} />
        <Fact label={lang === "zh" ? "风险状态" : "Risk status"} value={displayRiskBucket(decision?.risk_bucket ?? conclusion?.risk_bucket, lang)} />
        <Fact label={lang === "zh" ? "持仓假设" : "Position context"} value={conclusion?.position_context === "no_position_assumed" ? (lang === "zh" ? "未假设持仓" : "No position assumed") : String(conclusion?.position_context ?? "-")} />
      </div>
      <div className="manual-conclusion-actions">
        <button type="button" onClick={onReview} disabled={aiDecisionState === "loading"}>
          {aiDecisionState === "loading" ? (lang === "zh" ? "更新中" : "Updating") : aiConnected ? (lang === "zh" ? "更新交易计划" : "Refresh trade plan") : (lang === "zh" ? "研究服务未连接" : "Research service unavailable")}
        </button>
        <small>
          {aiConnected
            ? (lang === "zh" ? "研究服务已连接；所有结论仍需人工复核。" : "Research service connected; every conclusion still needs manual review.")
            : (lang === "zh" ? "研究服务暂时不可用，当前仅展示规则与图表证据。" : "Research service is unavailable; showing rule and chart evidence only.")}
        </small>
      </div>
      {aiDecisionState === "ready" && aiDecision ? (
        <div className={`ai-decision-panel ${actionClass(decision?.action)}`}>
          <div className="ai-review-head">
            <strong>{lang === "zh" ? "交易计划" : "Trade plan"}</strong>
            <span>{lang === "zh" ? "研究结果" : "Research result"}</span>
          </div>
          <div className="ai-review-facts">
            <Fact label={lang === "zh" ? "交易结论" : "Conclusion"} value={displayTradeAction(decision?.action ?? "-", lang)} />
            <Fact label={text.confidence} value={decision?.confidence ?? "-"} />
            <Fact label={lang === "zh" ? "风控状态" : "Risk control"} value={aiDecision.hard_veto?.active ? (lang === "zh" ? "暂不通过" : "Not cleared") : (lang === "zh" ? "已通过" : "Cleared")} />
            <Fact label={lang === "zh" ? "研究版本" : "Research version"} value={decision?.ai_feature_packet_version ?? aiDecision.ai_feature_packet_version ?? "v2"} />
          </div>
          <div className="ai-plan-grid">
            <Fact label={text.entryZone} value={displayPlanField(decision?.entry_zone, "entry", lang)} />
            <Fact label={text.stopZone} value={displayPlanField(decision?.stop_zone, "stop", lang)} />
            <Fact label={text.targetZone} value={displayPlanField(decision?.target_zone, "target", lang)} />
            <Fact label={text.riskReward} value={displayPlanField(decision?.risk_reward, "riskReward", lang)} />
            <Fact label={text.sizeHint} value={displayPlanField(decision?.position_size_hint, "position", lang)} />
            <Fact label={text.bestProfile} value={decision?.best_profile ?? "-"} />
            <Fact label="Baseline R:R" value={baselineRiskReward?.risk_reward ?? "-"} />
            <Fact label="Evidence" value={actionValidation?.evidence_quality ?? "-"} />
            <Fact label="Samples" value={formatNumber(actionValidation?.sample_count)} />
            <Fact label="Win Rate" value={`${formatNumber(actionValidation?.win_rate)}%`} />
            <Fact label={text.expectedR} value={`${formatNumber(actionValidation?.expected_value_r)}R`} />
            <Fact label={text.targetHit} value={`${formatNumber(actionValidation?.target_hit_rate)}%`} />
            <Fact label={text.stopHit} value={`${formatNumber(actionValidation?.stop_hit_rate)}%`} />
            <Fact label="Avg Return" value={`${formatNumber(actionValidation?.avg_forward_return)}%`} />
            <Fact label="Avg Drawdown" value={`${formatNumber(actionValidation?.avg_max_drawdown)}%`} />
          </div>
          <div className={`strategy-quality-panel ${moneyPilot?.eligible_for_review ? "eligible" : "blocked"}`}>
            <div className="ai-review-head">
              <strong>{lang === "zh" ? "交易资格检查" : "Trade eligibility"}</strong>
              <span>{moneyPilot?.eligible_for_review ? (lang === "zh" ? "可人工复核" : "Reviewable") : (lang === "zh" ? "暂不满足条件" : "Not ready")}</span>
            </div>
            <div className="ai-review-facts">
              <Fact label={lang === "zh" ? "当前状态" : "Current status"} value={moneyPilot?.eligible_for_review ? (lang === "zh" ? "可人工复核" : "Reviewable") : (lang === "zh" ? "暂不满足条件" : "Not ready")} />
              <Fact label={text.riskReward} value={`${formatNumber(moneyPilot?.risk_reward_value)}R / min ${formatNumber(moneyPilot?.minimum_risk_reward)}R`} />
              <Fact label="Win Rate" value={`${formatNumber(moneyPilot?.historical_win_rate)}% / min ${formatNumber(moneyPilot?.minimum_win_rate)}%`} />
              <Fact label={text.sampleQuality} value={`${formatNumber(moneyPilot?.sample_count)} / min ${formatNumber(moneyPilot?.minimum_samples)}`} />
            </div>
            {moneyPilot?.blockers?.length ? (
              <Narrative title={lang === "zh" ? "暂不满足的原因" : "What needs attention"} items={moneyPilot.blockers.slice(0, 6).map((reason) => displayEligibilityReason(reason, lang))} />
            ) : (
              <p className="secondary-note">{text.journalRequired}</p>
            )}
          </div>
          <div className={`strategy-quality-panel ${probeEligibility?.eligible_for_probe_review ? "eligible probe" : "blocked"}`}>
            <div className="ai-review-head">
              <strong>{lang === "zh" ? "小仓观察" : "Small-size observation"}</strong>
              <span>{probeEligibility?.eligible_for_probe_review ? "eligible" : "blocked"}</span>
            </div>
            <div className="ai-review-facts">
              <Fact label="Probe review" value={probeEligibility?.eligible_for_probe_review ? "starter review" : "blocked"} />
              <Fact label={text.riskReward} value={`${formatNumber(probeEligibility?.risk_reward_value)}R / min ${formatNumber(probeEligibility?.minimum_risk_reward)}R`} />
              <Fact label="Win Rate" value={`${formatNumber(probeEligibility?.historical_win_rate)}% / min ${formatNumber(probeEligibility?.minimum_win_rate)}%`} />
              <Fact label={text.sampleQuality} value={`${formatNumber(probeEligibility?.sample_count)} / min ${formatNumber(probeEligibility?.minimum_samples)}`} />
              <Fact label="Risk" value={`${formatNumber(probePolicy?.default_risk_pct_of_account ?? 0.15)}% default / ${formatNumber(probePolicy?.max_risk_pct_of_account ?? 0.2)}% max`} />
              <Fact label="No averaging" value={probePolicy?.no_averaging_down ? "yes" : "required"} />
            </div>
            {probeEligibility?.blockers?.length ? (
              <Narrative title={lang === "zh" ? "暂不满足的原因" : "What needs attention"} items={probeEligibility.blockers.slice(0, 6).map((reason) => displayEligibilityReason(reason, lang))} />
            ) : (
              <p className="secondary-note">Starter only: no full-size, no chase, no averaging down, journal required.</p>
            )}
          </div>
          {actionValidation?.verdict ? (
            <p className="secondary-note">
              {lang === "zh" ? "历史验证" : "Historical validation"}: {actionValidation.verdict} / noise {formatNumber(actionValidation.noise_rate)}%. {actionValidation.note ?? ""}
            </p>
          ) : null}
          <Narrative title={text.whyNow} items={(decision?.why_now?.length ? decision.why_now : [lang === "zh" ? "研究结论尚未生成。" : "No research rationale yet."]).map((item) => displayResearchText(item, lang))} />
          <Narrative title={text.invalidation} items={(decision?.what_invalidates_this_setup?.length ? decision.what_invalidates_this_setup : [lang === "zh" ? "暂无失效条件。" : "No invalidation details yet."]).map((item) => displayResearchText(item, lang))} />
          <Narrative title={text.humanChecklist} items={decision?.human_checklist?.length ? decision.human_checklist : [lang === "zh" ? "行动前先保存交易日志。" : "Save the journal before acting manually."]} />
          {aiDecision.hard_veto?.active ? <p className="compare-error">{lang === "zh" ? "当前风险条件未通过：" : "Current risk conditions are not cleared: "}{aiDecision.hard_veto.reasons.map((reason) => displayRiskReason(reason, lang)).join("; ")}</p> : null}
          {aiDecision.hard_veto?.guardrail_warnings?.length ? (
            <p className="secondary-note">{lang === "zh" ? "风险检查：" : "Risk checks: "}{aiDecision.hard_veto.guardrail_warnings.map((item) => displayResearchText(item, lang)).join("；")}</p>
          ) : null}
          <p className="secondary-note">{displayResearchText(decision?.summary ?? aiDecision.reason, lang)}</p>
        </div>
      ) : null}
      <div className="manual-conclusion-detail">
        <Narrative title={text.why} items={(conclusion?.why?.length ? conclusion.why : [lang === "zh" ? "请先更新股票分析。" : "Refresh analysis to load reasons."]).map((item) => displayResearchText(item, lang))} />
        <Narrative title={text.blockers} items={(conclusion?.blockers?.length ? conclusion.blockers : [lang === "zh" ? "暂无额外限制。" : "No additional restrictions."]).map((item) => displayResearchText(item, lang))} />
        <Narrative title={text.invalidation} items={(conclusion?.invalidation?.length ? conclusion.invalidation : [lang === "zh" ? "暂无失效条件。" : "No invalidation details yet."]).map((item) => displayResearchText(item, lang))} />
      </div>
      {aiReviewState === "ready" && aiReview ? (
        <div className="ai-review-panel">
          <div className="ai-review-head">
            <strong>{lang === "zh" ? "补充复核" : "Supplemental review"}</strong>
            <span>{lang === "zh" ? "研究结果" : "Research result"}</span>
          </div>
          <div className="ai-review-facts">
            <Fact label="Verdict" value={ai?.ai_review_verdict ?? "-"} />
            <Fact label="Quality" value={ai?.quality_filter ?? "-"} />
            <Fact label="Downgrade" value={ai?.downgrade_suggestion ?? "-"} />
          </div>
          <Narrative title="R/R Improvement" items={ai?.rr_improvement_notes?.length ? ai.rr_improvement_notes : ["No review notes."]} />
          <Narrative title="Risk Questions" items={ai?.risk_questions?.length ? ai.risk_questions : ["No risk questions."]} />
          <Narrative title="Journal Prompt" items={ai?.journal_prompt?.length ? ai.journal_prompt : ["No journal prompt."]} />
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


function EvidenceColumn({
  title,
  entries,
  tone,
}: {
  title: string;
  entries?: Array<{ factor_id: string; label?: string; contribution?: number | null; value?: string | number | boolean | null; note?: string }>;
  tone: "positive" | "negative" | "neutral";
}) {
  return (
    <div className={`factor-evidence-column ${tone}`}>
      <strong>{title}</strong>
      {entries?.length ? entries.slice(0, 3).map((entry) => (
        <div key={entry.factor_id}>
          <span>{entry.label ?? entry.factor_id}</span>
          <small>{entry.contribution == null ? (entry.note ?? "-") : `${entry.contribution > 0 ? "+" : ""}${formatNumber(entry.contribution)}`}</small>
        </div>
      )) : <small>-</small>}
    </div>
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

function initialUrlSymbol(): string | null {
  try {
    const value = new URLSearchParams(window.location.search).get("symbol")?.trim().toUpperCase() ?? "";
    return /^[A-Z0-9.^-]{1,16}$/.test(value) ? value : null;
  } catch {
    return null;
  }
}

function initialUrlWorkspace(): WorkspaceName {
  try {
    const value = new URLSearchParams(window.location.search).get("workspace") as WorkspaceName | null;
    return value && ["today", "search", "watchlist", "stock", "charts", "aiPlan", "chat", "journal", "settings"].includes(value) ? value : "today";
  } catch {
    return "today";
  }
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
    session: String(payload.session ?? ""),
    quoteTime: payload.quote_time ? formatDateTimeUtc8(String(payload.quote_time), { withDate: true }) : undefined,
    exchangeTimezone: String(payload.exchange_timezone ?? "America/New_York"),
    displayTimezone: String(payload.display_timezone ?? "Asia/Shanghai"),
  };
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
    sourceType: "unavailable",
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
    sourceType: "unavailable",
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

function urlBase64ToUint8Array(value: string): ArrayBuffer {
  const padding = "=".repeat((4 - (value.length % 4)) % 4);
  const normalized = (value + padding).replace(/-/g, "+").replace(/_/g, "/");
  const raw = window.atob(normalized);
  const bytes = Uint8Array.from([...raw].map((character) => character.charCodeAt(0)));
  return bytes.buffer.slice(bytes.byteOffset, bytes.byteOffset + bytes.byteLength) as ArrayBuffer;
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
    if (universeName === "ai_five_layer") return "科技主题";
    if (universeName === "physical_ai") return "机器人";
    if (universeName === "all") return "All";
    return "Core 200";
  }
  if (universeName === "ai_five_layer") return "Technology themes";
  if (universeName === "physical_ai") return "Robotics";
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
      source: "unavailable",
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
  if (range === "1d" && (interval === "1m" || interval === "5m")) {
    const day = previousTradingDays(end, 1)[0];
    const start = Date.UTC(day.getUTCFullYear(), day.getUTCMonth(), day.getUTCDate(), 13, 30) / 1000;
    const step = interval === "1m" ? 60 : 5 * 60;
    const bars = interval === "1m" ? 390 : 78;
    return Array.from({ length: bars }, (_, index) => start + index * step);
  }
  if (range === "5d" && interval === "15m") {
    return previousTradingDays(end, 5).flatMap((day) => {
      const start = Date.UTC(day.getUTCFullYear(), day.getUTCMonth(), day.getUTCDate(), 13, 30) / 1000;
      return Array.from({ length: 26 }, (_, index) => start + index * 15 * 60);
    });
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
        bar_state: String(item.bar_state ?? "unknown"),
        quote_merged: Boolean(item.quote_merged),
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

function ema(candles: Candle[], period: number): Array<{ time: Time; value: number }> {
  let current = candles[0]?.close ?? 0;
  const multiplier = 2 / (period + 1);
  return candles.map((bar, index) => {
    current = index === 0 ? bar.close : (bar.close - current) * multiplier + current;
    return { time: bar.time, value: round(current) };
  });
}

function lastEma(values: number[], period: number) {
  const series = ema(values.map((value, index) => ({ time: index as Time, open: value, high: value, low: value, close: value, volume: 0 })), period);
  return series[series.length - 1]?.value ?? 0;
}

function useStoredState<T extends string>(key: string, initial: T, preferInitial = false): [T, (value: T) => void] {
  const [value, setValue] = useState<T>(() => {
    try {
      return preferInitial ? initial : (window.localStorage.getItem(key) as T | null) ?? initial;
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
  return (
    meta.count > 0
    && meta.providerStatus === "available"
    && (meta.sourceType.startsWith("longbridge_") || meta.sourceType.includes("live"))
    && !meta.sourceType.includes("fixture")
  );
}

function metaFromRealtimeSnapshot(
  payload: RealtimeSnapshotPayload,
  preset: ChartPreset,
  candles: Candle[],
): CandleMeta {
  const quoteAge = Number(payload.quote?.freshness_seconds ?? 0);
  return {
    symbol: payload.symbol,
    range: preset.range,
    interval: preset.interval,
    sourceType: "longbridge_realtime_snapshot",
    providerStatus: payload.provider_status,
    freshness: payload.quote_fresh ? "live_quote" : "stale_quote",
    staleAge: Number.isFinite(quoteAge) ? formatStaleAge(quoteAge, payload.quote_fresh ? "live" : "stale") : "unknown",
    count: candles.length,
    first: formatCandleTime(candles[0]),
    last: formatCandleTime(candles[candles.length - 1]),
    errors: [],
    session: payload.session,
    quoteTime: payload.quote?.quote_time ? formatDateTimeUtc8(payload.quote.quote_time, { withDate: true }) : undefined,
    exchangeTimezone: payload.exchange_timezone,
    displayTimezone: payload.display_timezone,
  };
}

function chartIntervalSeconds(interval: string): number {
  return ({ "1m": 60, "5m": 300, "15m": 900, "1h": 3600 } as Record<string, number>)[interval] ?? 0;
}

function mergeRealtimeQuote(candles: Candle[], quote: RealtimeQuote, interval: string): Candle[] {
  const duration = chartIntervalSeconds(interval);
  const price = Number(quote.last);
  const quoteMs = quote.quote_time ? new Date(quote.quote_time).getTime() : Number.NaN;
  if (!duration || !candles.length || !Number.isFinite(price) || !Number.isFinite(quoteMs)) return candles;
  const next = candles.map((candle) => ({ ...candle }));
  const latest = next[next.length - 1];
  const latestMs = latest.open_time ? new Date(latest.open_time).getTime() : Number(latest.time) * 1000;
  if (!Number.isFinite(latestMs) || quoteMs < latestMs) return candles;
  const durationMs = duration * 1000;
  if (quoteMs < latestMs + durationMs) {
    latest.high = Math.max(latest.high, price);
    latest.low = Math.min(latest.low, price);
    latest.close = price;
    latest.bar_state = "forming_candle";
    latest.quote_merged = true;
    return next;
  }
  const elapsedBuckets = Math.max(1, Math.floor((quoteMs - latestMs) / durationMs));
  const openMs = latestMs + elapsedBuckets * durationMs;
  next.push({
    time: Math.floor(openMs / 1000) as Time,
    open_time: new Date(openMs).toISOString(),
    open: price,
    high: price,
    low: price,
    close: price,
    volume: 0,
    bar_state: "forming_candle",
    quote_merged: true,
  });
  return next;
}

function marketDataMiniLabel(apiHealth: ApiHealthPayload | null) {
  const provider = apiHealth?.market_data?.provider ?? apiHealth?.market_data_provider ?? "live";
  const status = apiHealth?.market_data?.status ?? apiHealth?.longbridge_status ?? "";
  if (provider === "longbridge") {
    const session = String(apiHealth?.market_data?.market_clock?.session ?? "").toLowerCase();
    if (session === "closed") return "Longbridge 已收盘";
    if (status !== "available") return "Longbridge 数据需确认";
    if (session && session !== "regular") return "Longbridge 非常规时段";
    if (status === "available") return "Longbridge Live";
    return "Longbridge 数据需确认";
  }
  return "Yahoo reference";
}

function displayTradeAction(action: unknown, lang: Lang): string {
  const value = String(action ?? "").toUpperCase();
  const zh: Record<string, string> = {
    AI_BUY_CANDIDATE: "可人工复核",
    AI_PULLBACK_BUY: "等待回踩",
    AI_PROBE_BUY: "小仓观察",
    AI_REVERSAL_WATCH: "观察反转",
    AI_BREAKOUT_WATCH: "观察突破",
    AI_WAIT: "暂时等待",
    AI_AVOID: "暂不介入",
    AI_HOLD_TRAIL: "持有并跟踪",
    AI_EXIT_REVIEW: "检查持仓风险",
    BUY: "可人工复核",
    WAIT: "暂时等待",
    DO_NOT_BUY: "暂不介入",
  };
  const en: Record<string, string> = {
    AI_BUY_CANDIDATE: "Reviewable",
    AI_PULLBACK_BUY: "Wait for pullback",
    AI_PROBE_BUY: "Small-size watch",
    AI_REVERSAL_WATCH: "Watch reversal",
    AI_BREAKOUT_WATCH: "Watch breakout",
    AI_WAIT: "Wait",
    AI_AVOID: "Do not enter",
    AI_HOLD_TRAIL: "Hold and trail",
    AI_EXIT_REVIEW: "Review position risk",
    BUY: "Reviewable",
    WAIT: "Wait",
    DO_NOT_BUY: "Do not enter",
  };
  return (lang === "zh" ? zh : en)[value] ?? (lang === "zh" ? "等待数据" : "Awaiting data");
}

function displayDataQuality(value: unknown, lang: Lang): string {
  const clean = String(value ?? "").toLowerCase() === "clean";
  return lang === "zh" ? (clean ? "数据正常" : "数据需确认") : (clean ? "Data ready" : "Data needs review");
}

function displayProviderStatus(value: unknown, lang: Lang): string {
  const status = String(value ?? "").toLowerCase();
  if (status === "available") return lang === "zh" ? "可用" : "Available";
  if (status === "refreshing") return lang === "zh" ? "更新中" : "Refreshing";
  if (status === "stale") return lang === "zh" ? "已过期" : "Stale";
  return lang === "zh" ? "待确认" : "Needs review";
}

function displayRiskReason(value: unknown, lang: Lang): string {
  const reason = String(value ?? "").toLowerCase();
  const zh: Record<string, string> = {
    non_regular_session: "当前不在美股常规交易时段",
    depth_unavailable: "深度报价暂不可用",
    quote_unavailable: "实时价格暂不可用",
    quote_stale: "实时价格已过期",
    trust_unavailable: "行情可信度暂不足",
    trust_yahoo_reference_only: "当前仅有参考行情",
  };
  const en: Record<string, string> = {
    non_regular_session: "Outside regular US market hours",
    depth_unavailable: "Depth quote unavailable",
    quote_unavailable: "Realtime quote unavailable",
    quote_stale: "Realtime quote is stale",
    trust_unavailable: "Market data trust is insufficient",
    trust_yahoo_reference_only: "Only reference market data is available",
  };
  return (lang === "zh" ? zh : en)[reason] ?? (lang === "zh" ? "当前风险条件需要确认" : "A current risk condition needs review");
}

function displayResearchText(value: unknown, lang: Lang): string {
  const text = String(value ?? "").trim();
  if (!text || lang !== "zh") return text;
  const normalized = text.toLowerCase();
  if (normalized.includes("deterministic hard veto") || normalized.includes("hard veto")) return "当前行情或风险条件未通过检查。";
  if (normalized.includes("ai decision request failed") || normalized.includes("ai trading agent is unavailable")) return "研究服务暂时不可用，当前仅依据行情、规则与图表证据。";
  if (normalized.includes("rule system and live-data guardrails")) return "规则与行情数据检查仍然生效。";
  if (normalized.includes("trade readiness is blocked")) return "当前不满足人工交易条件。";
  if (normalized.includes("rule system classifies")) return "当前形态尚未达到建立新仓的复核标准。";
  if (normalized.includes("market regime is")) return "当前市场环境仍需确认。";
  if (normalized.includes("provider status becomes stale")) return "行情更新中断或过期时，结论自动失效。";
  if (normalized.includes("price loses the profile")) return "价格跌破当前策略的关键均线结构。";
  if (normalized.includes("exit risk changes")) return "风险状态转弱或形态失效。";
  if (normalized.includes("historical focus")) return "历史样本仅作参考，需结合当前行情复核。";
  if (normalized.includes("data quality is not clean")) return "行情数据仍需确认。";
  if (normalized.includes("data_quality=caution")) return "行情数据仍需确认。";
  if (normalized.includes("exit_risk=data caution") || normalized.includes("exit risk is data caution")) return "当前风险状态需要确认。";
  if (normalized.includes("market regime turns risk_off")) return "市场环境转弱时，当前计划失效。";
  if (normalized.includes("confirm live candles")) return "请先确认实时 K 线数据可用。";
  if (normalized.includes("check rule conclusion")) return "请检查交易结论、市场环境与风险状态。";
  if (normalized.includes("save a journal plan")) return "行动前请先保存交易日志。";
  if (normalized.includes("risk conditions are not cleared")) return "当前风险条件尚未通过。";
  return text;
}

function displayPlanField(value: unknown, kind: "entry" | "stop" | "target" | "position" | "riskReward", lang: Lang): string {
  const text = String(value ?? "").trim();
  const normalized = text.toLowerCase();
  if (!text || normalized === "-" || normalized === "unavailable") {
    const zh = { entry: "待补充入场条件", stop: "待补充止损条件", target: "待补充目标条件", position: "待补充仓位计划", riskReward: "待补充" };
    const en = { entry: "Entry conditions pending", stop: "Stop plan pending", target: "Target plan pending", position: "Position plan pending", riskReward: "Pending" };
    return (lang === "zh" ? zh : en)[kind];
  }
  if (normalized.includes("ai unavailable")) {
    if (kind === "entry") return lang === "zh" ? "研究服务暂不可用，请先按图表和规则补充入场条件。" : "Research service unavailable; define entry conditions from the chart and rules.";
    if (kind === "stop") return lang === "zh" ? "请在人工复核前明确止损区。" : "Define a stop before manual review.";
    if (kind === "target") return lang === "zh" ? "请在人工复核前明确目标区。" : "Define a target before manual review.";
    if (kind === "position") return lang === "zh" ? "研究服务暂不可用，请保持仓位保守。" : "Research service unavailable; keep sizing conservative.";
  }
  if (normalized.includes("no ai stop plan")) return lang === "zh" ? "请在人工复核前明确止损区。" : "Define a stop before manual review.";
  if (normalized.includes("no ai target plan")) return lang === "zh" ? "请在人工复核前明确目标区。" : "Define a target before manual review.";
  return text;
}

function displayRealtimeState(value: unknown, session: unknown, lang: Lang): string {
  const state = String(value ?? "").toLowerCase();
  const marketSession = String(session ?? "").toLowerCase();
  if (state === "live") return lang === "zh" ? "实时更新" : "Live";
  if (state === "loading") return lang === "zh" ? "正在更新" : "Refreshing";
  if (state === "stale") return lang === "zh" ? "数据需确认" : "Data needs review";
  if (marketSession === "closed") return lang === "zh" ? "美股已收盘" : "US market closed";
  return lang === "zh" ? "等待行情" : "Awaiting data";
}

function displayConfidence(value: unknown, lang: Lang): string {
  const confidence = String(value ?? "-").toUpperCase();
  if (confidence === "LOW") return lang === "zh" ? "较低" : "Low";
  if (confidence === "MEDIUM") return lang === "zh" ? "中等" : "Medium";
  if (confidence === "HIGH") return lang === "zh" ? "较高" : "High";
  return confidence || "-";
}

function displayRiskBucket(value: unknown, lang: Lang): string {
  const bucket = String(value ?? "-").toLowerCase();
  if (bucket === "avoid") return lang === "zh" ? "暂不介入" : "Avoid";
  if (bucket === "watch") return lang === "zh" ? "继续观察" : "Watch";
  if (bucket === "review") return lang === "zh" ? "可人工复核" : "Reviewable";
  return bucket || "-";
}

function displayEligibilityReason(value: unknown, lang: Lang): string {
  const reason = String(value ?? "").toLowerCase();
  if (reason.includes("action is not")) return lang === "zh" ? "当前交易结论不支持建立新仓。" : "The current conclusion does not support a new position.";
  if (reason.includes("live daily") || reason.includes("candles are not clean")) return lang === "zh" ? "实时日线或确认周期数据尚未满足条件。" : "Live daily or confirmation data is not ready.";
  if (reason.includes("hard veto")) return lang === "zh" ? "当前行情或风险条件仍需确认。" : "Current market or risk conditions still need review.";
  if (reason.includes("r:r")) return lang === "zh" ? "风险收益比尚未达到门槛。" : "Risk/reward is below the required threshold.";
  if (reason.includes("win rate")) return lang === "zh" ? "历史胜率证据尚未达到门槛。" : "Historical win-rate evidence is below the threshold.";
  if (reason.includes("sample count")) return lang === "zh" ? "历史样本量仍然不足。" : "Historical sample size is still insufficient.";
  if (reason.includes("entry/stop/target")) return lang === "zh" ? "入场、止损、目标或失效条件尚未完整。" : "Entry, stop, target, or invalidation is incomplete.";
  if (reason.includes("journal")) return lang === "zh" ? "行动前需要先保存交易日志。" : "Save the trade journal before acting.";
  return lang === "zh" ? "当前条件仍需进一步确认。" : "A current condition still needs review.";
}

function tradeAnswerCopy(action: TradeAction | AiAction | Level | string | undefined, lang: Lang) {
  const normalized = String(action ?? "").toUpperCase();
  const nextStep = ["AI_BUY_CANDIDATE", "AI_PULLBACK_BUY", "BUY", "BUY SETUP"].includes(normalized)
    ? (lang === "zh" ? "确认入场区、止损区、目标区和仓位后，再进行人工复核。" : "Confirm entry, stop, target, and size before manual review.")
    : ["AI_AVOID", "DO_NOT_BUY", "PASS"].includes(normalized)
      ? (lang === "zh" ? "暂不建立新仓，等待结构与数据改善。" : "Do not open a new position; wait for structure and data to improve.")
      : (lang === "zh" ? "等待价格、量能或结构给出更清晰的确认。" : "Wait for clearer confirmation from price, volume, or structure.");
  return {
    label: displayTradeAction(normalized, lang),
    shortLabel: displayTradeAction(normalized, lang),
    nextStep,
  };
}

function explicitPlanText(value: string | undefined) {
  if (!value) return false;
  const normalized = value.trim().toLowerCase();
  return Boolean(normalized) && !["-", "n/a", "na", "unavailable", "r:r unavailable"].includes(normalized);
}

function isLeveragedOrOptionsProxy(symbol: string) {
  return new Set(["MSTU", "MSTX", "TQQQ", "SQQQ", "UPRO", "SPXL", "SPXS", "SOXL", "SOXS", "TNA", "TZA", "LABU", "LABD"]).has(symbol.toUpperCase());
}

function readinessIssueText(issue: ReadinessIssue): string {
  if (typeof issue === "string") {
    return issue;
  }
  const name = issue.name || "readiness";
  const detail = issue.detail ? `: ${issue.detail}` : "";
  return `${name}${detail}`;
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
  mondayReadinessReport,
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
  mondayReadinessReport: MondayReadinessReport | null;
  text: (typeof copy)["en"] | (typeof copy)["zh"];
}): MondayReadiness {
  const auditStatus = mondayReadinessReport?.status ?? "not_scanned";
  const auditAvailable = mondayReadinessReport?.latest_cache_status === "available" || mondayReadinessReport?.available === true;
  const auditIsNoTrade = auditStatus === "NO_TRADE" || auditStatus === "read_error";
  const auditIsCaution = auditStatus === "CAUTION" || auditStatus === "not_scanned";
  const auditGenerated = mondayReadinessReport?.generated_at_utc ? shortDateTime(mondayReadinessReport.generated_at_utc) : "not scanned";
  const checks = [
    {
      label: "Readiness Audit",
      value: auditAvailable ? `${auditStatus} / ${auditGenerated}` : String(auditStatus),
      ok: auditAvailable && !auditIsNoTrade && !auditIsCaution,
      critical: auditIsNoTrade,
    },
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
  const reportReasons = [
    ...(mondayReadinessReport?.critical_failures ?? []),
    ...(mondayReadinessReport?.warnings ?? []),
  ]
    .map(readinessIssueText)
    .filter(Boolean);
  const reasons = [
    ...checks.filter((check) => !check.ok).map((check) => `${check.label}: ${check.value}`),
    ...reportReasons.slice(0, 6),
  ];
  const criticalFailed = checks.some((check) => check.critical && !check.ok);
  const status: MondayReadiness["status"] = criticalFailed ? "NO_TRADE" : reasons.length ? "CAUTION" : "READY";
  const reportSummary = mondayReadinessReport?.summary || (auditAvailable ? `Latest local audit: ${auditStatus}.` : "");
  return {
    status,
    title: text.mondayReadiness,
    summary:
      reportSummary ||
      (status === "READY"
        ? "Ready for small-size manual pilot review. The system is still read-only and cannot place orders."
        : status === "CAUTION"
          ? "Use observation mode unless the listed caution items are cleared before entry."
          : "No real-money pilot until critical data, AI, market, or safety checks are clear."),
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
  lang,
}: {
  selected: StockSignal;
  selectedSymbol: string;
  aiDecision: AiDecisionPayload | null;
  dailyMeta: CandleMeta;
  hourlyMeta: CandleMeta;
  stockJournal: StockJournalPayload | null;
  text: (typeof copy)["en"] | (typeof copy)["zh"];
  lang: Lang;
}): ManualTradeTicket {
  const decision = aiDecision?.ai_decision;
  const riskRewardValue = parseRiskReward(decision?.risk_reward);
  const hasJournalToday = Boolean(
    stockJournal?.entries.some((entry) => isManualPilotJournalReady(entry, selectedSymbol)),
  );
  const checks = [
    { label: lang === "zh" ? "交易结论" : "Conclusion", value: displayTradeAction(decision?.action ?? "", lang), ok: decision?.action === "AI_BUY_CANDIDATE" || decision?.action === "AI_PULLBACK_BUY", reason: lang === "zh" ? "当前结论不支持建立新仓。" : "The current conclusion does not support a new position." },
    { label: lang === "zh" ? "日线数据" : "Daily data", value: `${displayProviderStatus(dailyMeta.providerStatus, lang)} / ${dailyMeta.count}`, ok: isLiveCandleMeta(dailyMeta), reason: lang === "zh" ? "日线实时数据尚未满足复核条件。" : "Daily market data is not ready for review." },
    { label: lang === "zh" ? "确认周期" : "Confirmation", value: `${displayProviderStatus(hourlyMeta.providerStatus, lang)} / ${hourlyMeta.count}`, ok: isLiveCandleMeta(hourlyMeta), reason: lang === "zh" ? "确认周期数据尚未满足复核条件。" : "Confirmation data is not ready for review." },
    { label: lang === "zh" ? "实时风控" : "Live risk", value: aiDecision?.hard_veto?.active ? (lang === "zh" ? "暂不通过" : "Not cleared") : (lang === "zh" ? "已通过" : "Cleared"), ok: !aiDecision?.hard_veto?.active, reason: lang === "zh" ? "当前行情或风险条件仍需确认。" : "Current market or risk conditions still need review." },
    { label: "R:R", value: decision?.risk_reward ?? "-", ok: riskRewardValue >= 2, reason: lang === "zh" ? "风险收益比尚未达到人工复核门槛。" : "Risk/reward does not meet the manual-review threshold." },
    { label: lang === "zh" ? "止损" : "Stop", value: decision?.stop_zone ?? "-", ok: explicitPlanText(decision?.stop_zone), reason: lang === "zh" ? "止损计划尚未完整。" : "The stop plan is incomplete." },
    { label: lang === "zh" ? "仓位" : "Position", value: decision?.position_size_hint ?? "-", ok: explicitPlanText(decision?.position_size_hint), reason: lang === "zh" ? "仓位计划尚未完整。" : "The position plan is incomplete." },
    { label: lang === "zh" ? "标的范围" : "Instrument scope", value: isLeveragedOrOptionsProxy(selectedSymbol) ? (lang === "zh" ? "不适用" : "Not eligible") : (lang === "zh" ? "股票/普通 ETF" : "Stock / standard ETF"), ok: !isLeveragedOrOptionsProxy(selectedSymbol), reason: lang === "zh" ? "杠杆 ETF 和期权不进入当前人工复核流程。" : "Leveraged ETFs and options are outside the current manual-review scope." },
  ];
  const reasons = checks.filter((check) => !check.ok).map((check) => check.reason);
  const status: ManualTradeTicket["status"] = reasons.length ? "blocked" : hasJournalToday ? "cleared_for_review" : "journal_required";
  return {
    status,
    title: text.manualTradeTicket,
    summary:
      status === "blocked"
        ? (lang === "zh" ? "当前不满足人工交易条件。请先处理下方原因，并在美股常规交易时段重新检查。" : "This symbol does not currently meet the conditions for a manual trade. Review the reasons below during regular market hours.")
        : status === "journal_required"
          ? (lang === "zh" ? "交易计划已完整，但仍需先保存交易日志。" : "The trade plan is complete, but a journal entry is still required.")
          : (lang === "zh" ? "交易条件已通过人工复核；KQUANT 不会连接券商或代替你下单。" : "The conditions are ready for manual review; KQUANT does not connect to a broker or place orders."),
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

function isManualPilotJournalReady(entry: StockJournalEntry, symbol: string) {
  const today = new Date().toISOString().slice(0, 10);
  const entrySymbol = String(entry.symbol || "").toUpperCase();
  const validStatus = entry.status === "entered-manually" || entry.status === "manual-traded";
  const hasPlan =
    entry.planned_entry !== null &&
    entry.planned_entry !== undefined &&
    entry.planned_stop !== null &&
    entry.planned_stop !== undefined &&
    entry.planned_target !== null &&
    entry.planned_target !== undefined &&
    Number.isFinite(Number(entry.planned_entry)) &&
    Number.isFinite(Number(entry.planned_stop)) &&
    Number.isFinite(Number(entry.planned_target));
  return entrySymbol === symbol.toUpperCase() && entry.reviewed_at.slice(0, 10) === today && validStatus && hasPlan;
}

function actionClass(action: TradeAction | string | undefined) {
  if (action === "BUY" || action === "HOLD_TRAIL" || action === "AI_BUY_CANDIDATE" || action === "AI_PULLBACK_BUY" || action === "AI_HOLD_TRAIL") return "buy";
  if (action === "AI_PROBE_BUY") return "probe";
  if (action === "WAIT" || action === "AI_WAIT" || action === "AI_REVERSAL_WATCH" || action === "AI_BREAKOUT_WATCH") return "watch";
  if (action === "EXIT_REVIEW" || action === "AI_EXIT_REVIEW") return "exit";
  return "pass";
}

function actionAnswerCopy(action: TradeAction | AiAction | Level | string | undefined, lang: Lang) {
  const zh = lang === "zh";
  const normalized = String(action ?? "").toUpperCase();
  if (normalized === "AI_PROBE_BUY") {
    return {
      label: zh ? "AI 小仓试错候选" : "AI small-size probe candidate",
      shortLabel: zh ? "小仓试错" : "Probe",
      nextStep: zh
        ? "仅按 0.15% 默认风险人工复核，不追高，不摊平，必须保存 Journal。"
        : "Review as a starter only: 0.15% default risk, no chase, no averaging down, journal required.",
    };
  }
  if (normalized === "AI_PROBE_BUY") {
    return {
      label: zh ? "AI 小仓试错候选" : "AI small-size probe candidate",
      shortLabel: zh ? "小仓试错" : "Probe",
      nextStep: zh
        ? "仅按 0.15% 默认风险人工复核，不追高，不摊平，必须保存 Journal。"
        : "Review as a starter only: 0.15% default risk, no chase, no averaging down, journal required.",
    };
  }
  const copyByAction: Record<string, { label: string; shortLabel: string; nextStep: string }> = {
    BUY: {
      label: zh ? "可以进入人工买入复核" : "Buy candidate for manual review",
      shortLabel: zh ? "可复核" : "Review",
      nextStep: zh ? "确认入场区、止损区、目标区和仓位。" : "Confirm entry, stop, target, and size.",
    },
    "BUY SETUP": {
      label: zh ? "可以进入人工买入复核" : "Buy candidate for manual review",
      shortLabel: zh ? "可复核" : "Review",
      nextStep: zh ? "确认 AI 计划和 K 线后再考虑。" : "Confirm AI plan and chart evidence first.",
    },
    AI_BUY_CANDIDATE: {
      label: zh ? "AI 认为可进入买入复核" : "AI buy candidate for manual review",
      shortLabel: zh ? "AI买入候选" : "AI buy",
      nextStep: zh ? "只在入场区内复核，不追高。" : "Review only inside the entry zone; do not chase.",
    },
    AI_PULLBACK_BUY: {
      label: zh ? "AI 认为等回踩可买" : "AI pullback buy candidate",
      shortLabel: zh ? "等回踩" : "Pullback",
      nextStep: zh ? "等待价格回到 AI 入场区并守住止损条件。" : "Wait for the AI entry zone and keep the stop valid.",
    },
    AI_BREAKOUT_WATCH: {
      label: zh ? "突破观察，暂不追" : "Breakout watch, no chase",
      shortLabel: zh ? "看突破" : "Breakout",
      nextStep: zh ? "等待突破确认和成交量确认。" : "Wait for breakout and volume confirmation.",
    },
    AI_REVERSAL_WATCH: {
      label: zh ? "反转观察，等结构修复" : "Reversal watch, wait for repair",
      shortLabel: zh ? "看反转" : "Reversal",
      nextStep: zh ? "等待均线结构和动量修复。" : "Wait for trend and momentum repair.",
    },
    WAIT: {
      label: zh ? "等待，不是买点" : "Wait, not a buy point",
      shortLabel: zh ? "等待" : "Wait",
      nextStep: zh ? "等待规则或 AI 条件转强。" : "Wait for stronger rule or AI conditions.",
    },
    AI_WAIT: {
      label: zh ? "AI 建议等待" : "AI says wait",
      shortLabel: zh ? "等待" : "Wait",
      nextStep: zh ? "等待入场区、量能或结构改善。" : "Wait for entry zone, volume, or structure improvement.",
    },
    DO_NOT_BUY: {
      label: zh ? "不要买" : "Do not buy",
      shortLabel: zh ? "不买" : "Avoid",
      nextStep: zh ? "等失效因素解除后再看。" : "Wait until blockers clear.",
    },
    AI_AVOID: {
      label: zh ? "AI 建议不要买" : "AI says avoid",
      shortLabel: zh ? "不买" : "Avoid",
      nextStep: zh ? "不要开新仓，等待新结构。" : "Do not open a new position; wait for a new setup.",
    },
    EXIT_REVIEW: {
      label: zh ? "不适合新开仓；如已持有需复核" : "No fresh long; review existing position",
      shortLabel: zh ? "复核退出" : "Exit review",
      nextStep: zh ? "如果已有仓位，检查止损和减仓计划。" : "If already holding, review stop and de-risk plan.",
    },
    AI_EXIT_REVIEW: {
      label: zh ? "AI 不支持新买入；如已持有需复核风险" : "AI blocks fresh buy; review existing risk",
      shortLabel: zh ? "退出复核" : "Exit review",
      nextStep: zh ? "等待日线/1H 结构修复后再看。" : "Wait for daily/1H structure repair.",
    },
    HOLD_TRAIL: {
      label: zh ? "如已持有可继续跟踪止盈" : "Hold and trail if already in",
      shortLabel: zh ? "持有跟踪" : "Trail",
      nextStep: zh ? "不新增仓位，按移动止损管理。" : "Do not add; manage with trailing stop.",
    },
    AI_HOLD_TRAIL: {
      label: zh ? "AI 建议持有跟踪，不新增仓位" : "AI suggests hold/trail, no add",
      shortLabel: zh ? "持有跟踪" : "Trail",
      nextStep: zh ? "已有仓位按止盈/移动止损处理。" : "Manage existing position with target/trailing stop.",
    },
    PASS: {
      label: zh ? "当前不是买点" : "Not a buy point now",
      shortLabel: zh ? "跳过" : "Pass",
      nextStep: zh ? "等待信号重新出现。" : "Wait for a new signal.",
    },
  };
  return (
    copyByAction[normalized] ?? {
      label: zh ? "还没有明确答案" : "No clear answer yet",
      shortLabel: zh ? "未知" : "Unknown",
      nextStep: zh ? "先确认真实 K 线和 AI 计划是否加载。" : "Confirm live K-lines and AI plan first.",
    }
  );
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

function formatPrice(value: number | null | undefined): string {
  return value == null || !Number.isFinite(value) ? "-" : `$${value.toFixed(2)}`;
}

function formatSigned(value: number | null | undefined) {
  if (value === undefined || value === null || Number.isNaN(value)) return "-";
  return `${value > 0 ? "+" : ""}${formatNumber(value)}`;
}

function shortDateTime(value: string | null | undefined) {
  if (!value) return "-";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return value;
  return parsed.toLocaleString(undefined, {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function money(value: number | null | undefined) {
  if (value === undefined || value === null || Number.isNaN(value)) return "-";
  if (value >= 1_000_000_000_000) return `$${(value / 1_000_000_000_000).toFixed(2)}T`;
  if (value >= 1_000_000_000) return `$${(value / 1_000_000_000).toFixed(2)}B`;
  if (value >= 1_000_000) return `$${(value / 1_000_000).toFixed(2)}M`;
  return `$${value.toFixed(value > 100 ? 0 : 2)}`;
}

function formatCandleTime(candle: Candle | undefined, timeZone: DisplayTimezone = "Asia/Shanghai") {
  if (!candle) return "";
  if (candle.open_time) return formatDateTimeUtc8(candle.open_time, { timeZone });
  const seconds = Number(candle.time);
  if (!Number.isFinite(seconds)) return "";
  return formatDateTimeUtc8(seconds * 1000, { timeZone });
}

function formatDateTimeUtc8(
  value: string | number | Date,
  options: { withDate?: boolean; timeZone?: DisplayTimezone } = {},
) {
  const date = value instanceof Date ? value : new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  const timeZone = options.timeZone ?? "Asia/Shanghai";
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone,
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  })
    .formatToParts(date)
    .reduce<Record<string, string>>((acc, part) => {
      if (part.type !== "literal") acc[part.type] = part.value;
      return acc;
    }, {});
  const timeText = `${parts.hour ?? "00"}:${parts.minute ?? "00"}`;
  if (!options.withDate) return timeText;
  const timezoneSuffix = timeZone === "Asia/Shanghai" ? "UTC+8" : "ET";
  return `${parts.month ?? "--"}/${parts.day ?? "--"} ${timeText} ${timezoneSuffix}`;
}

export default App;
