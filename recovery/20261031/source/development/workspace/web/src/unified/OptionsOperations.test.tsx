import { describe, it, expect } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import OptionsOperations, { copilotPaperAllowed, PolicyAvailabilityNotice, AutomaticEventCoverage, ManualContinuityNotice, ManualReportProblem, OneMinutePanel, SignalList, TrendCheckpointCoverage, TrendCalculationSummary, TrendSignalCard, TrendStatusHealth, TrendObservationCard, TrendEventRisk } from "./OptionsOperations";
import { ManualReportError } from "./manualReportRequest";
import OptionsWorkspace from "./OptionsWorkspace";
import { I18nProvider } from "./i18n";
import { currentCoverage, paperRows, planCategory } from "./operationalData";

describe("daily options operations", () => {
  it("shows an observed stop and reboot without trusting old RUNNING or worker readiness", () => {
    for (const language of ["zh", "en"] as const) {
      const data = { worker: { research_ready: true, state: "SHADOW_MONITORING" }, service_observation: {
        enforced: true, state: "STOPPED", reported_state: "RUNNING", exit_reason: "UNKNOWN",
        recovery_reason: "PREVIOUS_BOOT_NOT_RESTARTED", run_session_id: "TEST_ONLY-session",
      } };
      const markup = renderToStaticMarkup(<I18nProvider language={language}><TrendStatusHealth data={data} /></I18nProvider>);
      expect(markup).toContain("STOPPED");
      expect(markup).toContain("RUNNING");
      expect(markup).toContain("UNKNOWN");
      expect(markup).toContain("TEST_ONLY-session");
      expect(markup).toContain(language === "zh" ? "尚未重新启动" : "has not restarted");
      expect(markup).toContain(language === "zh" ? "未就绪" : "Not ready");
    }
  });
  it("separates research readiness from a reachable HTTP page", () => {
    for (const language of ["zh", "en"] as const) {
      const markup = renderToStaticMarkup(<I18nProvider language={language}><TrendStatusHealth data={{ worker: {
        state: "FAILED_INIT", research_ready: false, failed_stage: "INIT_OPENING_RESEARCH", error_id: "TEST_ONLY-error", loop_count: 0,
      } }} /></I18nProvider>);
      expect(markup).toContain('role="alert"');
      for (const value of ['FAILED_INIT', 'INIT_OPENING_RESEARCH', 'TEST_ONLY-error']) expect(markup).toContain(value);
      expect(markup).toContain(language === 'zh' ? '不能确认正常扫描' : 'normal scanning is not established');
    }
  });
  it("separates source scope, actual arguments, limits and unknown evidence", () => {
    const worker = { source_request_budget: { local_cap: 12, used: 0, provider_limit_verified: false },
      source_call: { in_flight: true }, price_action_sources: { coverage_counts: { fresh: 0, expired: 2, deferred: 3 },
        recent_observations: [{ symbol: "TEST", state: "SOURCE_CAPABILITY_UNCONFIRMED", desired_from: "2026-10-09", desired_through: "2026-10-12", actual_query: null, reasons: ["DATED_INTERFACE_UNAVAILABLE"], observation_id: "TEST_ONLY-observation" }] } };
    for (const language of ["zh", "en"] as const) {
      const markup = renderToStaticMarkup(<I18nProvider language={language}><TrendStatusHealth data={{ worker }} /></I18nProvider>);
      for (const value of ["2026-10-09", "2026-10-12", "DATED_INTERFACE_UNAVAILABLE", "TEST_ONLY-observation", "0/12"]) expect(markup).toContain(value);
      expect(markup).toContain(language === "zh" ? "未取得请求依据" : "Request evidence unavailable");
      expect(markup).toContain(language === "zh" ? "未核验" : "Unverified");
      expect(markup).toContain(language === "zh" ? "仍在执行" : "In flight");
    }
  });
  it("keeps absent policy distinct from restored history and confirmed empty positions", () => {
    for (const language of ["zh", "en"] as const) {
      const markup = renderToStaticMarkup(<I18nProvider language={language}><PolicyAvailabilityNotice data={{ current_policy_available: false, reason: "POLICY_CONFIG_MISSING", config_file: "options_signal_copilot_v1.json" }} /></I18nProvider>);
      expect(markup).toContain("role=\"alert\"");
      expect(markup).toContain("POLICY_CONFIG_MISSING");
      expect(markup).toContain(language === "zh" ? "不能按空列表或零数量解释" : "an empty list or zero count is not established");
      expect(markup).not.toContain("PAPER_MANUAL_CONFIRM");
    }
    expect(renderToStaticMarkup(<I18nProvider language="en"><PolicyAvailabilityNotice data={{ current_policy_available: true }} /></I18nProvider>)).toBe("");
  });
  it("disables existing-position paper confirmation until its policy is available", () => {
    const position = { source_kind: "POSITION", strategy_id: "STRAT-SHORT-ATM-RANGE-EXPANSION-2H-V1" };
    expect(copilotPaperAllowed(position, null)).toBe(false);
    expect(copilotPaperAllowed(position, { current_policy_available: false })).toBe(false);
    expect(copilotPaperAllowed(position, { current_policy_available: true })).toBe(true);
    expect(copilotPaperAllowed({ source_kind: "SIGNAL" }, { current_policy_available: true, paper_execution: { enabled: false } })).toBe(false);
  });
  it("does not present an empty new-epoch list as confirmed no positions", () => {
    for (const language of ["zh", "en"] as const) {
      const markup = renderToStaticMarkup(<I18nProvider language={language}><ManualContinuityNotice data={{ positions: [], old_position_continuity: "UNKNOWN", position_records_complete: false, data_epoch: { session: "2026-10-07" } }} /></I18nProvider>);
      expect(markup).toContain("role=\"alert\"");
      expect(markup).toContain("2026-10-07");
      expect(markup).toContain(language === "zh" ? "空列表不代表没有持仓或已经平仓" : "An empty list does not establish no positions or confirmed exits");
    }
  });
  it("retains the legacy current-store display without inventing a recovery boundary", () => {
    expect(renderToStaticMarkup(<I18nProvider language="en"><ManualContinuityNotice data={{ positions: [], record_scope: "CURRENT_STORE_ONLY" }} /></I18nProvider>)).toBe("");
  });
  it("uses active checkpoint minutes instead of the old 09:45 default", () => {
    const markup = renderToStaticMarkup(<I18nProvider language="en"><TrendCalculationSummary coverage={{ state: "READY", checkpoints: [], checkpoint_minutes: [5, 10, 15, 20, 25] }} /></I18nProvider>);
    expect(markup).toContain("09:35 ET");
    expect(markup).not.toContain("09:45 ET");
  });
  it("keeps incomplete event coverage visibly unknown rather than falsely clear", () => {
    const markup = renderToStaticMarkup(<I18nProvider language="zh"><TrendEventRisk decision={{ decision: "WARN", warnings: ["EVENT_COVERAGE_INCOMPLETE_OR_STALE"], checked_at: "2026-10-01T13:50:00Z" }} /></I18nProvider>);
    expect(markup).toContain("事件资料不完整");
    expect(markup).toContain("不代表已证明无事件");
    expect(markup).not.toContain("截至核验时未发现已知重大风险");
  });
  it("shows an unqualified specific reference without default currency or multiplier amounts", () => {
    const row = { symbol: "TEST", right: "CALL", deadline_at: "2026-10-01T13:55:00Z", entry_range: [100, 101],
      current_eligibility: { state: "PENDING", reasons: ["EXACT_POLICY_NOT_APPROVED"],
        event_decision: { decision: "WARN", warnings: ["EVENT_COVERAGE_INCOMPLETE_OR_STALE"] },
        reference_contract: { contract_id: "TEST261005C100000.US", underlying: "TEST", right: "CALL", expiry_date: "2026-10-05", strike: 100, bid: 1, ask: 1.05, multiplier: null } } };
    for (const language of ["zh", "en"] as const) {
      const markup = renderToStaticMarkup(<I18nProvider language={language}><TrendObservationCard row={row} now={Date.parse("2026-10-01T13:50:01Z")} connected={false} /></I18nProvider>);
      expect(markup).toContain("TEST261005C100000.US");
      expect(markup).toContain(language === "zh" ? "非买入提示" : "not an entry signal");
      expect(markup).toContain(language === "zh" ? "不能确认当前资格" : "current eligibility unconfirmed");
      expect(markup).not.toContain("USD");
      expect(markup).not.toContain("105.00");
      const mismatched = { ...row, current_eligibility: { ...row.current_eligibility, reference_contract: { ...row.current_eligibility.reference_contract, underlying: "OTHER" } } };
      expect(renderToStaticMarkup(<I18nProvider language={language}><TrendObservationCard row={mismatched} now={Date.now()} connected={true} /></I18nProvider>)).not.toContain("TEST261005C100000.US");
    }
  });
  const contractSignal = {
    policy_id: "STRAT-OPENING-TREND-PULLBACK-5M-V1", evaluation_id: "isolated-contract-display", symbol: "TEST", right: "CALL",
    contract_id: "TEST261002C100000.US", deadline_at: "2026-09-29T13:55:00Z", entry_range: [100, 100.25], structure_line: 99,
    current_eligibility: { state: "QUALIFIED", contract_id: "TEST261002C100000.US", checked_at: "2026-09-29T13:50:00Z",
      valid_until: "2026-09-29T13:50:03Z", underlying_quote: { received_at: "2026-09-29T13:50:00Z" },
      contract_qualification: { selected: { contract_id: "TEST261002C100000.US", underlying: "TEST", right: "CALL",
        expiry_date: "2026-10-02", dte: 3, strike: 100, multiplier: 100, bid: 1.2, ask: 1.25, quote_currency: "USD",
        snapshot: { bbo_received_at: "2026-09-29T13:50:00Z" } } } },
  };
  it("shows an exact option, separate premium, and underlying entry range in both languages", () => {
    for (const language of ["zh", "en"] as const) {
      const markup = renderToStaticMarkup(<I18nProvider language={language}><TrendSignalCard row={contractSignal} now={Date.parse("2026-09-29T13:50:01Z")} /></I18nProvider>);
      for (const value of ["TEST261002C100000.US", "2026-10-02", "125.00", "USD", "100.00", "299s"]) expect(markup).toContain(value);
      expect(markup).toContain(language === "zh" ? "行权价" : "Strike price");
      expect(markup).toContain(language === "zh" ? "正股参考入场区间" : "Underlying entry range");
      expect(markup).toContain(language === "zh" ? "复制合约代码" : "Copy contract code");
    }
  });
  it("never labels an expired or disconnected observation as currently qualified", () => {
    const before = JSON.stringify(contractSignal);
    for (const language of ["zh", "en"] as const) {
      for (const [time, connected] of [["2026-09-29T13:50:03Z", true], ["2026-09-29T13:50:01Z", false]] as const) {
        const markup = renderToStaticMarkup(<I18nProvider language={language}><TrendObservationCard row={contractSignal} now={Date.parse(time)} connected={connected} /></I18nProvider>);
        expect(markup).not.toContain(language === "zh" ? "当前核验通过" : "Currently qualified");
        expect(markup).toContain(language === "zh" ? "当前资格无法确认" : "Current eligibility unconfirmed");
      }
      const fresh = renderToStaticMarkup(<I18nProvider language={language}><TrendObservationCard row={contractSignal} now={Date.parse("2026-09-29T13:50:01Z")} connected={true} /></I18nProvider>);
      expect(fresh).toContain(language === "zh" ? "当前核验通过" : "Currently qualified");
      const expired = renderToStaticMarkup(<I18nProvider language={language}><TrendObservationCard row={contractSignal} now={Date.parse(contractSignal.deadline_at)} connected={true} /></I18nProvider>);
      expect(expired).toContain(language === "zh" ? "已过期，非当前买入提示" : "Expired; not a current entry");
    }
    expect(JSON.stringify(contractSignal)).toBe(before);
  });
  it("hides expired option entries and does not substitute a 100 multiplier or USD currency", () => {
    expect(renderToStaticMarkup(<I18nProvider language="en"><TrendSignalCard row={contractSignal} now={Date.parse("2026-09-29T13:50:04Z")} /></I18nProvider>)).toBe("");
    const selected = { ...contractSignal.current_eligibility.contract_qualification.selected, multiplier: null, quote_currency: null };
    const row = { ...contractSignal, current_eligibility: { ...contractSignal.current_eligibility, contract_qualification: { selected } } };
    const markup = renderToStaticMarkup(<I18nProvider language="en"><TrendSignalCard row={row} now={Date.parse("2026-09-29T13:50:01Z")} /></I18nProvider>);
    expect(markup).toContain("Currency unverified");
    expect(markup).not.toContain("125.00");
    expect(markup).not.toContain("USD");
  });
  it("does not turn unexecuted pipeline stages into zero or sum other checkpoints", () => {
    const markup = renderToStaticMarkup(<I18nProvider language="zh"><TrendCalculationSummary coverage={{ checkpoints: [{
      registered_directions: 222, evaluated_directions: 200, numeric_directions: 0, items: [],
      pipeline_stages: { registered: { state: "COUNTED", directions: 222 }, input_complete: { state: "COUNTED", directions: 0 },
        numeric_complete: { state: "COUNTED", directions: 0 }, setup_triggered: { state: "NOT_RUN", directions: null },
        event_passed: { state: "NOT_RUN", directions: null }, contract_passed: { state: "UNAVAILABLE", directions: null },
        actionable: { state: "NOT_RUN", directions: null } },
    }] }} /></I18nProvider>);
    expect(markup).toContain("输入完整</dt><dd>0");
    expect(markup).toContain("事件资料完整</dt><dd>未执行");
    expect(markup).toContain("合约通过</dt><dd>不可用");
    expect(markup).not.toContain("事件资料完整</dt><dd>0");
  });
  it("keeps absolute synchronization separate from continuity and shows safe errors", () => {
    const markup = renderToStaticMarkup(<I18nProvider language="en"><TrendStatusHealth data={{
      worker: { qualification: { clock_health: { state: "CONTINUOUS_NOT_SYNC_VERIFIED" } } },
      snapshot: { as_of: "2026-09-30T13:45:00Z", error_detail: { code: "DATABASE_LOCKED", phase: "latest_status", returncode: 1, elapsed_ms: 210 } },
    }} /></I18nProvider>);
    expect(markup).toContain("External synchronization");
    expect(markup).toContain("Not verified");
    expect(markup).toContain("Continuous, not proof of synchronization");
    expect(markup).toContain("DATABASE_LOCKED");
    expect(markup).toContain("Exit code");
  });
  it("shows the sampled OS synchronization without hiding a runtime clock jump", () => {
    const markup = renderToStaticMarkup(<I18nProvider language="en"><TrendStatusHealth data={{
      worker: { qualification: { clock_health: { state: "CLOCK_DISCONTINUITY" } } },
      external_clock: { state: "SYNCED_SYSTEM_REPORT", source: "time.cloudflare.com", checked_at: "2026-10-01T06:18:00Z" },
    }} /></I18nProvider>);
    expect(markup).toContain("Windows reports synchronized");
    expect(markup).toContain("Discontinuity detected; immediate eligibility paused");
    expect(markup).toContain("not a precision guarantee or signal approval");
  });
  it("surfaces zero numeric completion at the latest checkpoint without summing checkpoints", () => {
    const markup = renderToStaticMarkup(<I18nProvider language="zh"><TrendCalculationSummary coverage={{ checkpoints: [
      { bar_end: "2026-09-30T13:45:00Z", registered_directions: 222, evaluated_directions: 200, numeric_directions: 80 },
      { bar_end: "2026-09-30T13:55:00Z", registered_directions: 222, evaluated_directions: 200, numeric_directions: 0,
        explicitly_incomplete_directions: 200, missing_directions: 0, identity_excluded_directions: 22,
        items: [{ reasons: ["REFERENCE_TIME_CONFLICT", "REFERENCE_TIME_CONFLICT"] }] },
    ] }} /></I18nProvider>);
    expect(markup).toContain("本次数值计算未完成，不能判断为没有机会");
    expect(markup).toContain("数值完整</dt><dd>0");
    expect(markup).toContain("有评价记录</dt><dd>200");
    expect(markup).not.toContain("<dd>400");
    expect(markup).toContain("暂停资格核验: 1");
  });
  it("does not substitute zero for unavailable coverage", () => {
    const markup = renderToStaticMarkup(<I18nProvider language="en"><TrendCalculationSummary coverage={{ state: "UNAVAILABLE" }} /></I18nProvider>);
    expect(markup).toContain("Calculation coverage unavailable");
    expect(markup).not.toContain("<dd>0</dd>");
  });
  it("shows projection catchup as progress rather than no opportunities", () => {
    const markup = renderToStaticMarkup(<I18nProvider language="zh"><TrendCalculationSummary coverage={{
      state: "UNAVAILABLE", projection: { state: "PROJECTION_CATCHING_UP", records: 128, source_count: 2674 },
    }} /></I18nProvider>);
    expect(markup).toContain("正在补齐检查点对账");
    expect(markup).toContain("128 / 2674");
    expect(markup).not.toContain("<dd>0</dd>");
  });
  it("complete numeric coverage is not an entry qualification", () => {
    const markup = renderToStaticMarkup(<I18nProvider language="en"><TrendCalculationSummary coverage={{ checkpoints: [
      { registered_directions: 2, evaluated_directions: 2, numeric_directions: 2, items: [] },
    ] }} /></I18nProvider>);
    expect(markup).toContain("contract and entry eligibility are separate");
    expect(markup).not.toContain("Calculation partially complete");
  });
  it("makes an uncertain report distinct from a rejected change in both languages", () => {
    const unknown = renderToStaticMarkup(<I18nProvider language="en"><ManualReportProblem error={new ManualReportError("REPORT_OUTCOME_UNKNOWN", true)} check={() => {}} /></I18nProvider>);
    expect(unknown).toContain("may already be recorded");
    expect(unknown).toContain("original ID and values");
    expect(unknown).toContain("Check existing records");
    const conflict = renderToStaticMarkup(<I18nProvider language="zh"><ManualReportProblem error={new ManualReportError("IDEMPOTENCY_KEY_CONFLICT", false)} check={() => {}} /></I18nProvider>);
    expect(conflict).toContain("未记录本次修改");
    expect(conflict).toContain("核对现有登记");
    expect(conflict).not.toContain("提交结果尚未确认");
  });
  it("keeps login rejection explicit without claiming a successful report", () => {
    const markup = renderToStaticMarkup(<I18nProvider language="zh"><ManualReportProblem error={new ManualReportError("SIGN_IN_REQUIRED", false)} check={() => {}} /></I18nProvider>);
    expect(markup).toContain("请先在本机设置并登录工作台账号");
    expect(markup).not.toContain("核对现有登记");
  });
  it("automatic evidence keeps unknown, risk, verified and inapplicable categories distinct", () => {
    const markup = renderToStaticMarkup(<I18nProvider language="en"><AutomaticEventCoverage data={{
      as_of: "2026-09-30T13:45:00+00:00", category_states: {
        earnings: { trade_eligible: true, applicability: "NOT_APPLICABLE_UNDER_POLICY" },
        dividends: { trade_eligible: true }, corporate: { trade_eligible: false },
        macro: { trade_eligible: false, known_risk_state: "KNOWN_BLOCKER" },
      },
    }} onEvidence={() => {}} /></I18nProvider>);
    for (const label of ["Not applicable, verified", "Evidence verified", "Pending verification", "Known risk"]) expect(markup).toContain(label);
    expect(markup).not.toContain("No opportunity");
    expect(markup).not.toContain("OWNER");
  });
  it("checkpoint coverage keeps missing directions distinct from explicit incomplete results", () => {
    const markup = renderToStaticMarkup(<I18nProvider language="zh"><TrendCheckpointCoverage coverage={{
      state: "SYSTEM_GAPS", checkpoints: [{ bar_end: "2026-09-30T13:45:00+00:00", registered_directions: 222,
        evaluated_directions: 198, numeric_directions: 180, explicitly_incomplete_directions: 18,
        missing_directions: 2, identity_excluded_directions: 22, items: [
          { symbol: "BE", right: "CALL", state: "MISSING_EVALUATION", reasons: [] },
        ] }],
    }} onReason={() => {}} /></I18nProvider>);
    expect(markup).toContain("登记方向</dt><dd>222");
    expect(markup).toContain("系统漏评</dt><dd>2");
    expect(markup).toContain("明确缺资料</dt><dd>18");
    expect(markup).toContain("漏评：无持久记录");
    expect(markup).toContain("非合格信号");
  });
  it("unavailable checkpoint coverage does not invent zeros", () => {
    const markup = renderToStaticMarkup(<I18nProvider language="en"><TrendCheckpointCoverage coverage={{ state: "UNAVAILABLE" }} onReason={() => {}} /></I18nProvider>);
    expect(markup).toContain("Checkpoint coverage unavailable");
    expect(markup).not.toContain("<dd>0</dd>");
  });
  it("distinguishes a responsive worker from missing research progress", () => {
    const markup = renderToStaticMarkup(<I18nProvider language="zh"><OneMinutePanel one={{
      initialized: true, enabled: true, worker: { state: "SHADOW_MONITORING", research_progress: "BAR_PROGRESS_STALE" },
      summary: {}, prewarm: [], current_evaluations: [],
    }} onReason={() => {}} onChain={() => {}} onReport={() => {}} /></I18nProvider>);
    expect(markup).toContain("未收到近期完整分钟评价");
    expect(markup).toContain("不能判断为没有机会");
  });
  it("does not invent zero counts before APIs arrive", () => {
    const markup = renderToStaticMarkup(<I18nProvider language="zh"><OptionsOperations view="signals" symbol="MSTR" refreshNonce={0} onOpenChain={() => {}} /></I18nProvider>);
    expect(markup).toContain("正在加载");
    expect(markup).not.toContain("Windows提醒设备");
    expect(markup).not.toContain("通知设置与测试");
    expect(markup).not.toContain("not started");
    expect(markup).not.toContain("NOT_BUILT");
    expect(markup).not.toContain("<dd>0</dd>");
  });
  it("review defaults to daily, not real-money approval archive", () => {
    const markup = renderToStaticMarkup(<I18nProvider language="en"><OptionsOperations view="review" symbol="MSTR" refreshNonce={0} onOpenChain={() => {}} /></I18nProvider>);
    expect(markup).toContain("Daily review");
    expect(markup).not.toContain("LIVE_NOT_ENABLED");
    expect(markup).not.toContain("R6");
  });
  it("renders the active signal first with a contract and one-line reason", () => {
    const markup = renderToStaticMarkup(<I18nProvider language="zh"><SignalList rows={[{
      evaluation_id: "one", symbol: "MSTR", right: "CALL", contract_id: "MSTR261016C100.US",
      bar_end: "2026-09-21T14:00:00+00:00", deadline_at: "2026-09-21T14:01:00+00:00",
      rule_evidence: { compression: { actual: 0.7 }, participation: { actual: 1.8 } },
      contract_qualification: { selected: { expiry_date: "2026-10-16", strike: 100 } },
    }]} onReason={() => {}} onChain={() => {}} /></I18nProvider>);
    expect(markup).toContain("MSTR · 看涨 Call");
    expect(markup).toContain("MSTR261016C100.US");
    expect(markup).toContain("2026-10-16");
    expect(markup).toContain("收缩 0.70");
    expect(markup).toContain("量能 1.80");
    expect(markup).toContain("查看原因");
  });
  it("today no longer renders legacy forward research and Core12 daily scope", () => {
    const markup = renderToStaticMarkup(<I18nProvider language="zh"><OptionsWorkspace view="today" symbol="MSTR" refreshNonce={0} chart={null}
      onSymbolChange={() => {}} onOpenChain={() => {}} language="zh" theme="dark" onLanguageChange={() => {}} onThemeChange={() => {}} /></I18nProvider>);
    expect(markup).toContain("ops-workspace");
    expect(markup).toContain("正在加载");
    expect(markup).not.toContain("冻结前向研究");
    expect(markup).not.toContain("已批准 Paper 每日范围");
  });
  it("keeps every registered symbol and direction, without using page limit as coverage", () => {
    const prewarm = Array.from({ length: 111 }, (_, index) => ({ symbol: `S${index}`, session: "2026-09-21", state: "READY" }));
    const rows = currentCoverage({ summary: { session: "2026-09-21" }, prewarm, current_evaluations: [{ symbol: "S0", right: "CALL", state: "UNKNOWN" }] });
    expect(rows).toHaveLength(222);
    expect(rows[0].state).toBe("UNKNOWN");
    expect(rows[1].state).toBe("WAITING_CLOSED_PAIR");
    expect(currentCoverage({ summary: { session: "2026-09-22" }, prewarm })).toHaveLength(0);
  });
  it("separates intent, position, observations and unconfirmed exit", () => {
    const rows = paperRows({ intents: [{ intent_id: "x", state: "EXIT_PENDING_DATA" }], positions: [{ position_id: "p", state: "OPEN" }] });
    expect(rows.map(planCategory)).toEqual(["exit", "positions"]);
    expect(planCategory({ source_kind: "WATCH", active: true })).toBe("watch");
    expect(planCategory({ source_kind: "INTENT", state: "CANCELLED" })).toBe("ended");
  });
  it("makes the weekend-only calendar DTE mismatch visible without inventing chain eligibility", () => {
    const markup = renderToStaticMarkup(<I18nProvider language="zh"><OneMinutePanel one={{
      initialized: true, enabled: true, session: "2026-09-24",
      policy: { policy_id: "STRAT-INTRADAY-MOMENTUM-1M-V1", status: "RESEARCH_ONLY_PENDING_O_SETUP" },
      contract_window: { dates: ["2026-09-26", "2026-09-27"], weekend_only: true,
        provider_expiries_verified_for_all: false },
      summary: { registered_symbols: 111, history_pending: 100, complete_directions: 0, qualified_candidates: 0 },
      worker: { state: "WAIT_PREWARM_WINDOW" }, prewarm: [], current_evaluations: [],
    }} onReason={() => {}} onChain={() => {}} onReport={() => {}} /></I18nProvider>);
    expect(markup).toContain("2026-09-26 / 2026-09-27");
    expect(markup).toContain("不会自动改选1日或4日合约");
    expect(markup).toContain("等待完整一分钟计算");
  });
  it("shows the full-watchlist expiry check without treating unresolved identities as no options", () => {
    const markup = renderToStaticMarkup(<I18nProvider language="zh"><OneMinutePanel one={{
      initialized: true, enabled: true, session: "2026-09-24",
      policy: { policy_id: "STRAT-INTRADAY-MOMENTUM-1M-V1", status: "RESEARCH_ONLY_PENDING_O_SETUP" },
      contract_window: { dates: ["2026-09-26", "2026-09-27"], weekend_only: true,
        universe_expiry_audit: { status: "COMPLETE_WITH_IDENTITY_GAPS", matched: 0,
          verified_identity_queried: 100, no_matching_expiry: 100,
          identity_unconfirmed: 11, query_failed: 0, checked_at: "2026-09-24T11:40:00+00:00",
          matched_symbols: [], items: [] } },
      summary: { registered_symbols: 111, complete_directions: 0, qualified_candidates: 0 },
      worker: { state: "WAIT_PREWARM_WINDOW" }, prewarm: [], current_evaluations: [],
    }} onReason={() => {}} onChain={() => {}} onReport={() => {}} /></I18nProvider>);
    expect(markup).toContain("全自选到期日核查");
    expect(markup).toContain("无匹配");
    expect(markup).toContain("身份未确认 11");
    expect(markup).toContain("100");
    expect(markup).toContain("11");
    expect(markup).toContain("没有匹配标的");
  });
  it("retains prior numeric observations as expired research, not live entry signals", () => {
    const markup = renderToStaticMarkup(<I18nProvider language="zh"><OneMinutePanel one={{
      initialized: true, enabled: true, session: "2026-09-24",
      policy: { policy_id: "STRAT-INTRADAY-MOMENTUM-1M-V1", status: "RESEARCH_ONLY_PENDING_O_SETUP" },
      summary: { registered_symbols: 111, numeric_directions: 2, complete_directions: 2,
        qualified_candidates: 0, saved_evaluations: 10, saved_numeric_triggers: 1,
        history_days_fetched: 400, history_days_required: 2000, history_ready: 0 },
      worker: { state: "SHADOW_MONITORING" }, prewarm: [], current_evaluations: [
        { evaluation_id: "latest", symbol: "NVDA", right: "CALL", state: "NO_TRIGGER" }],
      recent_numeric_observations: [{ evaluation_id: "prior", symbol: "NVDA", right: "CALL",
        state: "NUMERIC_PASS_EVENT_PENDING", observation_expired: true }],
    }} onReason={() => {}} onChain={() => {}} onReport={() => {}} /></I18nProvider>);
    expect(markup).toContain("当日数值触发记录");
    expect(markup).toContain("400 / 2000");
    expect(markup).toContain("已过期");
    expect(markup).toContain("不是买入信号");
    expect(markup).toContain("等待完整一分钟计算");
  });
  it("shows same-bar metrics separately and labels stale snapshots", () => {
    const markup = renderToStaticMarkup(<I18nProvider language="zh"><OneMinutePanel one={{
      initialized: true, enabled: true, summary: { evaluated_directions: 999, qualified_candidates: 0 },
      bar_summary: { evaluated_directions: 4, numeric_complete_directions: 2, expected_directions: 222 },
      snapshot: { state: "STALE", as_of: "2026-09-24T14:00:00+00:00" },
      current_evaluations: [], prewarm: [],
    }} onReason={() => {}} onChain={() => {}} onReport={() => {}} /></I18nProvider>);
    expect(markup).toContain("当前显示旧快照");
    expect(markup).toContain("同分钟已评价方向</dt><dd>4");
    expect(markup).not.toContain("999");
    expect(markup).toContain("可能不同分钟");
  });
});
