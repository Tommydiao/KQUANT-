import { BellRing, CheckCircle2, RefreshCw, TrendingUp } from "lucide-react";

type Lang = "en" | "zh";
type TradeInstructionPayload = {
  symbol: string;
  state: string;
  plan: { observed_price?: number | null; entry_low?: number | null; entry_high?: number | null; stop?: number | null; target_low?: number | null };
  evidence: { blockers?: string[] };
};
type AlertEventPayload = {
  alert_id: string;
  symbol: string;
  severity: string;
  title: string;
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
  max_loss: number;
  score: number;
  breakeven: number;
  underlying_price?: number;
  status: string;
  blockers: string[];
};
type OptionCandidatesPayload = {
  candidates: OptionExpressionCandidate[];
  blockers?: string[];
};
function Fact({ label, value }: { label: string; value: string }) {
  return <div className="fact"><span>{label}</span><strong>{value}</strong></div>;
}
function formatNumber(value: number | null | undefined): string {
  return value === null || value === undefined || Number.isNaN(value) ? "-" : Number(value).toFixed(2);
}
function formatPrice(value: number | null | undefined): string {
  return value === null || value === undefined || Number.isNaN(value) ? "-" : Number(value).toFixed(2);
}
function formatDateTimeUtc8(value: string, options: { withDate: boolean }): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "-";
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: "Asia/Shanghai",
    month: options.withDate ? "2-digit" : undefined,
    day: options.withDate ? "2-digit" : undefined,
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

export function RealtimeCommandCenter({
  instructions,
  alerts,
  unreadCount,
  selectedSymbol,
  optionCandidates,
  optionState,
  lang,
  onPick,
  onAcknowledge,
  onLoadOptions,
  onStartPaper,
  optionPaperMessage,
}: {
  instructions: TradeInstructionPayload[];
  alerts: AlertEventPayload[];
  unreadCount: number;
  selectedSymbol: string;
  optionCandidates: OptionCandidatesPayload | null;
  optionState: "idle" | "loading" | "ready" | "error";
  lang: Lang;
  onPick: (symbol: string) => void;
  onAcknowledge: (alertId: string) => void;
  onLoadOptions: () => void;
  onStartPaper: (candidate: OptionExpressionCandidate) => void;
  optionPaperMessage: string;
}) {
  const active = instructions.find((item) => item.symbol === selectedSymbol) ?? instructions[0];
  const instructionLabel: Record<string, string> = lang === "zh"
    ? { MONITORING: "观察中", READY: "进入计划区", TRIGGERED: "可人工复核", INVALIDATED: "计划失效", EXPIRED: "计划过期", EXIT_REVIEW: "复核退出" }
    : { MONITORING: "Monitoring", READY: "In plan zone", TRIGGERED: "Review now", INVALIDATED: "Invalidated", EXPIRED: "Expired", EXIT_REVIEW: "Review exit" };
  const instructionTone = active?.state === "TRIGGERED" ? "action" : active?.state === "EXIT_REVIEW" ? "risk" : "info";
  return (
    <section className="realtime-command-center" aria-label={lang === "zh" ? "主动交易指令中心" : "Live instruction center"}>
      <div className="command-center-head">
        <div>
          <span>{lang === "zh" ? "主动预警" : "Live alerts"}</span>
          <h2>{lang === "zh" ? "人工复核指令中心" : "Manual review instructions"}</h2>
          <p>{lang === "zh" ? "系统持续监控闭合 K 线与实时买卖盘，只推送需要你确认的计划，不连接账户，也不会下单。" : "KQUANT monitors closed candles and live BBO, then pushes plans for your review. It never connects to an account or submits an order."}</p>
        </div>
        <div className="command-live-badge"><BellRing size={17} /><strong>{unreadCount}</strong><span>{lang === "zh" ? "条未读" : "unread"}</span></div>
      </div>

      <div className="command-center-grid">
        <div className={`instruction-focus ${instructionTone}`}>
          <div className="command-section-title"><strong>{lang === "zh" ? "当前指令" : "Current instruction"}</strong><span>{instructions.length}</span></div>
          {active ? (
            <>
              <button type="button" className="instruction-symbol" onClick={() => onPick(active.symbol)}>
                <span>{active.symbol}</span>
                <strong>{instructionLabel[active.state] ?? active.state}</strong>
              </button>
              <div className="instruction-price-grid">
                <Fact label={lang === "zh" ? "现价" : "Last"} value={formatPrice(active.plan.observed_price)} />
                <Fact label={lang === "zh" ? "入场区" : "Entry"} value={`${formatPrice(active.plan.entry_low)} - ${formatPrice(active.plan.entry_high)}`} />
                <Fact label={lang === "zh" ? "止损" : "Stop"} value={formatPrice(active.plan.stop)} />
                <Fact label={lang === "zh" ? "目标" : "Target"} value={formatPrice(active.plan.target_low)} />
              </div>
              <p className="instruction-next">{active.state === "TRIGGERED"
                ? (lang === "zh" ? "下一步：核对报价、止损和日志后，由你决定是否在外部券商手工执行。" : "Next: verify BBO, stop, and journal, then decide manually outside KQUANT.")
                : (active.evidence.blockers?.[0] ?? (lang === "zh" ? "等待价格与确认条件变化。" : "Wait for the next material state change."))}</p>
            </>
          ) : <p className="command-empty">{lang === "zh" ? "还没有有效指令。后台会在合格候选出现后主动推送。" : "No active instruction yet. The supervisor will push one when a qualified setup appears."}</p>}
        </div>

        <div className="alert-inbox">
          <div className="command-section-title"><strong>{lang === "zh" ? "最新预警" : "Latest alerts"}</strong><span>{unreadCount}</span></div>
          <div className="alert-list">
            {alerts.slice(0, 4).map((alert) => (
              <div className={`alert-row severity-${alert.severity.toLowerCase()} ${alert.acknowledged_at ? "acknowledged" : ""}`} key={alert.alert_id}>
                <button type="button" className="alert-main" onClick={() => onPick(alert.symbol)}>
                  <b>{alert.symbol}</b><span>{alert.title}</span><small>{formatDateTimeUtc8(alert.created_at, { withDate: true })}</small>
                </button>
                {!alert.acknowledged_at ? <button type="button" className="ack-alert" onClick={() => onAcknowledge(alert.alert_id)} title={lang === "zh" ? "标记已读" : "Acknowledge"}><CheckCircle2 size={15} /></button> : null}
              </div>
            ))}
            {!alerts.length ? <p className="command-empty">{lang === "zh" ? "暂无预警。" : "No alerts yet."}</p> : null}
          </div>
        </div>

        <div className="option-expression-panel">
          <div className="command-section-title"><strong>{lang === "zh" ? "期权表达" : "Options expression"}</strong><span>{selectedSymbol}</span></div>
          <p>{lang === "zh" ? "只筛选 14-45 天、流动性合格的单腿看涨期权。当前仅做一张合约的本地观察模拟。" : "Screens liquid 14-45 DTE single-leg calls. One-contract local observation only."}</p>
          <button type="button" className="option-load-button" onClick={onLoadOptions} disabled={optionState === "loading"}>
            {optionState === "loading" ? <RefreshCw className="spin" size={15} /> : <TrendingUp size={15} />}
            {lang === "zh" ? "检查期权候选" : "Check option candidates"}
          </button>
          {optionCandidates?.candidates?.[0] ? (
            <div className={`option-candidate-summary ${optionCandidates.candidates[0].status}`}>
              <strong>{optionCandidates.candidates[0].contract_symbol}</strong>
              <span>{optionCandidates.candidates[0].expiry_date} / Δ {formatNumber(optionCandidates.candidates[0].delta)}</span>
              <small>{lang === "zh" ? "最大权利金风险" : "Max premium risk"} ${formatNumber(optionCandidates.candidates[0].max_loss)}</small>
              {optionCandidates.candidates[0].status === "eligible" ? (
                <button type="button" className="option-paper-button" onClick={() => onStartPaper(optionCandidates.candidates[0])}>
                  {lang === "zh" ? "加入一张合约观察" : "Observe one contract"}
                </button>
              ) : null}
            </div>
          ) : optionCandidates ? <p className="option-blocker">{optionCandidates.blockers?.[0] ?? (lang === "zh" ? "当前没有合格期权候选。" : "No eligible option candidate.")}</p> : null}
          {optionPaperMessage ? <p className="option-paper-message">{optionPaperMessage}</p> : null}
        </div>
      </div>
    </section>
  );
}

