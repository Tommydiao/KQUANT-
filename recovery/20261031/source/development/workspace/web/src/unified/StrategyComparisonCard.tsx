import { useI18n, formatUiTime } from "./i18n";
import { useState } from "react";
import { BrainCircuit } from "lucide-react";
import { trendReferenceContract } from "./currentEligibility";
import type { RecordData as Json } from "./operationalData";
import "./strategyComparison.css";

export function StrategyComparisonCard({ row, now, connected, actions }: { row: Json; now: number; connected: boolean; actions?: React.ReactNode }) {
  const [aiRequest, setAiRequest] = useState("");
  const { language } = useI18n();
  const c = (zh: string, en: string) => language === "zh" ? zh : en;
  const pair = row.strategy_comparison;
  if (!pair) return null;
  const a = pair.amplitude ?? {};
  const cost = pair.option_cost ?? {};
  const s1 = pair.s1 ?? {};
  const ai = s1.ai_review ?? row.ai_review;
  const requestAstra = async () => {
    setAiRequest("PENDING");
    try {
      const response = await fetch("/api/options/opening-trend/ai-review", { method: "POST", credentials: "same-origin",
        headers: { "Content-Type": "application/json" }, body: JSON.stringify({ role: "ASTRA", evaluation_id: s1.state === "NUMERIC_PASS" ? s1.evaluation_id : row.evaluation_id }) });
      const result = await response.json();
      setAiRequest(response.ok ? result.state : result.detail ?? "UNAVAILABLE");
    } catch { setAiRequest("UNAVAILABLE"); }
  };
  const contract = trendReferenceContract({ ...row, current_eligibility: pair.reference_eligibility ?? row.current_eligibility });
  const num = (value: unknown) => typeof value === "number" && Number.isFinite(value) ? value.toLocaleString(language === "zh" ? "zh-CN" : "en-US", { maximumFractionDigits: 4 }) : c("未知", "Unknown");
  const labels: Record<string, string> = {
    NUMERIC_PASS: c("技术触发", "Technical trigger"), NO_TRIGGER: c("条件未触发", "No trigger"),
    INCOMPLETE: c("输入不完整", "Incomplete inputs"), EXPIRED: c("原期限已过", "Expired"),
    PASS: c("通过", "Pass"), FAIL: c("不满足", "Fail"), UNKNOWN: c("未知", "Unknown"),
    NOT_REQUIRED: c("不需要", "Not required"), NOT_MEASURED: c("尚未测量", "Not measured"),
    NOT_MATURE: c("尚未到观察时刻", "Not mature"), PATH_INCOMPLETE: c("路径缺失", "Incomplete path"),
    READY_COMMIT_TIME_UNAVAILABLE: c("缺少提交可用时刻，不能计算主标签", "Commit availability time missing; primary label unavailable"),
    NOT_A_FIRST_TECHNICAL_EVENT: c("非首次技术触发，未计算标签", "Not a first technical event; no label"),
  };
  const state = (value: string) => labels[value] ?? value;
  const expired = Number.isFinite(Date.parse(s1.deadline_at)) && now >= Date.parse(s1.deadline_at);
  const quoteAge = now - Date.parse(contract?.snapshot?.bbo_received_at ?? "");
  const quoteFresh = connected && Number.isFinite(quoteAge) && quoteAge >= 0 && quoteAge <= 3000;
  const costAge = now - Date.parse(cost.quote_received_at ?? "");
  const amountFresh = quoteFresh && Number.isFinite(costAge) && costAge >= 0 && costAge <= 3000;
  const keys = [...new Set([...Object.keys(pair.s0?.conditions ?? {}), ...Object.keys(s1.conditions ?? {})])];
  const conditionNames: Record<string, string> = { previous_close_direction: c("昨收方向", "Previous-close direction"),
    daily_direction: c("S0方向合并条件", "S0 combined direction"), session_direction: c("当日开盘方向", "Session direction"),
    momentum: "M", close_position: "Q", prior_breakout: c("前序突破", "Prior breakout") };
  return <article className="ops-signal-item ops-trend-observation strategy-comparison" aria-label={`${row.symbol} ${row.right} S0 S1`}>
    <div className="ops-signal-identity"><strong>{row.symbol} · {row.right}</strong>
      <p>{c("研究候选，非合格买入提示", "Research observation, not a qualified entry")}</p>
      <small>{pair.cohort === "PAIRED_POLICY_COMPARISON" ? c("共同可比输入", "Paired comparable inputs") : pair.cohort === "S1_INTRADAY_ONLY_DATA" ? c("仅S1日内输入齐全；S0不是否决", "S1 intraday inputs complete; S0 is not a rejection") : c("输入仍有缺口", "Input gaps remain")}</small>
      <small>{formatUiTime(row.calculation_bar_end, language)} · {expired ? c("原期限已过", "Original deadline expired") : formatUiTime(s1.deadline_at, language)}</small>
      {!connected ? <p className="ops-warning">{c("连接或快照不可用，当前资格未知", "Connection or snapshot unavailable; current eligibility unknown")}</p> : null}
    </div>
    <div className="ops-signal-why"><strong>S0: {state(pair.s0?.state)} · S1: {state(s1.state)}</strong>
      <table style={{ width: "100%", tableLayout: "fixed", overflowWrap: "anywhere" }}><thead><tr><th>{c("条件", "Condition")}</th><th>S0</th><th>S1</th></tr></thead>
        <tbody>{keys.map(key => <tr key={key}><td>{conditionNames[key] ?? key}</td><td>{state(pair.s0?.conditions?.[key] ?? "UNKNOWN")}</td><td>{state(s1.conditions?.[key] ?? "UNKNOWN")}</td></tr>)}</tbody></table>
      <p>{c("振幅 / 实体", "Range / body")}: {num(a.range_bps)} / {num(a.body_bps)} bps</p>
      <small>{c("同槽历史 / ATR支持数", "Same-slot / ATR support")}: {a.same_slot_support ?? 0} / {a.atr_support ?? 0}</small>
      <small style={{ overflowWrap: "anywhere" }}>{(s1.reasons ?? []).join(" · ")}</small>
    </div>
    <div className="ops-signal-when"><strong>{c("具体参考合约", "Specific reference contract")}</strong>
      {contract ? <><p style={{ overflowWrap: "anywhere" }}>{contract.contract_id}</p><small>{contract.expiry_date} · {num(contract.strike)} · {contract.right} · DTE {num(contract.dte)}</small>
        <small>bid / ask: {num(contract.bid)} / {num(contract.ask)} · {contract.quote_currency ?? c("币种未知", "Currency unknown")}</small>
        <small>{formatUiTime(contract.snapshot?.bbo_received_at, language)} · {quoteFresh ? c("接收年龄≤3秒；源时间另验", "Receipt age <=3s; source time separate") : c("历史参考报价，非当前资格", "Historical reference quote; not current eligibility")}</small></> : <p>{c("尚无可核验参考合约", "No verifiable reference contract yet")}</p>}
      <small>{c("每张权利金 / 价差金额", "Premium / spread cash")}: {num(amountFresh ? cost.premium_cash_reference : null)} / {num(amountFresh ? cost.spread_cash_reference : null)}</small>
      <small>{c("仅Delta价差等效正股变化", "Delta-only spread-equivalent stock move")}: {num(quoteFresh ? cost.spread_equivalent_underlying_move : null)}</small>
      <small>{c("完整往返成本", "Full round-trip cost")}: {num(quoteFresh ? cost.round_trip_cost_per_unit : null)}</small>
      <small>{c("局部成本近似，非目标价或盈亏预测", "Local friction approximation; not a target or profit forecast")}</small>
      <small style={{ overflowWrap: "anywhere" }}>{(cost.reasons ?? [cost.state]).join(" · ")}</small>
      <p>{c("60分钟正股观察", "60-minute stock observation")}: {state(pair.outcome?.state ?? "NOT_MEASURED")}{typeof pair.outcome?.y60_pct === "number" ? ` · ${num(pair.outcome.y60_pct * 100)}%` : ""}</p>
      <small>{c("正股路径标签，不是期权收益或自动退出", "Stock-path label, not option return or automatic exit")}</small>
    </div>
    <details style={{ overflowWrap: "anywhere", gridColumn: "1 / -1" }}><summary>{c("AI证据复核", "AI evidence review")}{ai ? ` · ${ai.model ?? ai.state}` : ""}</summary>
      {ai ? <><p>{ai.model ?? c("模型未就绪", "Model unavailable")} · {ai.state}</p>
        <p>{!connected || expired || !quoteFresh || ai.display_state !== "SAME_EVALUATION" || ai.delivery_state !== "CURRENT_RESEARCH_REVIEW"
          ? c("历史或待复核分析，当前资格以行情和规则结果为准", "Historical or pending review; current market and rule checks govern eligibility")
          : c("研究证据复核，非买入批准", "Research evidence review, not entry approval")}</p>
        {ai.assessment ? <><p>{c("支持证据", "Supporting evidence")}: {(ai.assessment.support_refs ?? []).join(" · ") || c("无", "None")}</p>
          <p>{c("反对证据", "Opposing evidence")}: {(ai.assessment.opposing_refs ?? []).join(" · ") || c("无", "None")}</p>
          <p>{c("缺失资料", "Missing inputs")}: {(ai.assessment.missing_inputs ?? []).join(" · ") || c("未列出", "Not listed")}</p>
          <p>{c("复核状态", "Review status")}: {(ai.assessment.review_reasons ?? []).join(" · ") || ai.delivery_state}</p></> : null}
        <small>{c("本次API估算费用", "Estimated API cost")}: {ai.actual_cost_usd != null ? `$${ai.actual_cost_usd}` : c("未知或尚未调用", "Unknown or not called")}</small>
        {ai.error_code ? <small>{ai.error_code}</small> : null}
      </> : <p>{c("尚无AI分析，研究计算照常显示", "No AI assessment yet; research calculations remain available")}</p>}
      <button className="quiet-button" title={c("使用Astra复核当前研究证据", "Review current research evidence with Astra")}
        disabled={!connected || expired || aiRequest === "PENDING" || (s1.state !== "NUMERIC_PASS" && pair.s0?.state !== "NUMERIC_PASS")}
        onClick={requestAstra}><BrainCircuit size={16} />{c("Astra复核", "Astra review")}</button>
      {aiRequest ? <small role="status">{aiRequest}</small> : null}
    </details>
    <details style={{ overflowWrap: "anywhere" }}><summary>{c("版本与输入方法", "Versions and input method")}</summary><p>S0 {pair.s0?.policy_hash}</p><p>S1 {s1.policy_hash}</p><p>{s1.data_method_id}</p></details>
    <div className="ops-row-actions">{actions}</div>
  </article>;
}
