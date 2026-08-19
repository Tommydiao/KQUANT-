type Lang = "en" | "zh";

type EarlyTrendPayload = {
  symbol: string;
  strategy_stage: "NOT_READY" | "EARLY_WATCH" | "ARMED" | "BUY_REVIEW" | "LATE_WAIT_PULLBACK" | "INVALIDATED";
  setup_score: number;
  trigger_score: number | null;
  summary: string;
  pullback_zone: [number, number] | null;
  invalidation_price: number | null;
  setup_factors: Array<{ factor_id: string; contribution: number; maximum: number; detail: string }>;
  lead_time_evidence: { status: string };
};

export function EarlyTrendPanel({ snapshot, lang }: { snapshot: EarlyTrendPayload | null; lang: Lang }) {
  if (!snapshot) return null;
  const stageCopy: Record<EarlyTrendPayload["strategy_stage"], string> = {
    NOT_READY: lang === "zh" ? "尚未转强" : "Not ready",
    EARLY_WATCH: lang === "zh" ? "早期观察" : "Early watch",
    ARMED: lang === "zh" ? "等待盘中确认" : "Armed",
    BUY_REVIEW: lang === "zh" ? "可做模拟复核" : "Paper review",
    LATE_WAIT_PULLBACK: lang === "zh" ? "走势转强，等待回踩" : "Strong, wait for pullback",
    INVALIDATED: lang === "zh" ? "结构失效" : "Invalidated",
  };
  const factorNames: Record<string, string> = {
    setup_fast_ema_turn: lang === "zh" ? "均线刚转强" : "Fast EMA turn",
    setup_relative_strength_acceleration: lang === "zh" ? "相对强弱加速" : "Relative strength",
    setup_volume_accumulation: lang === "zh" ? "量价累积" : "Volume accumulation",
    setup_base_breakout: lang === "zh" ? "平台与突破" : "Base and breakout",
    setup_liquidity_risk: lang === "zh" ? "波动与流动性" : "Risk and liquidity",
  };
  return (
    <section className={`early-trend-band stage-${snapshot.strategy_stage.toLowerCase()}`}>
      <div className="early-trend-heading">
        <div>
          <span>{lang === "zh" ? "早期转强观察" : "Early trend"}</span>
          <strong>{stageCopy[snapshot.strategy_stage]}</strong>
          <p>{snapshot.summary}</p>
        </div>
        <div className="early-trend-scores">
          <span>{lang === "zh" ? "结构" : "Setup"}<b>{snapshot.setup_score}</b></span>
          <span>{lang === "zh" ? "触发" : "Trigger"}<b>{snapshot.trigger_score ?? "-"}</b></span>
        </div>
      </div>
      <div className="early-factor-strip">
        {snapshot.setup_factors.map((factor) => (
          <div key={factor.factor_id}>
            <span>{factorNames[factor.factor_id] ?? factor.factor_id}</span>
            <strong>{factor.contribution}/{factor.maximum}</strong>
          </div>
        ))}
      </div>
      <div className="early-trend-foot">
        <span>{lang === "zh" ? "回踩区" : "Pullback"}: {snapshot.pullback_zone ? `${snapshot.pullback_zone[0]} - ${snapshot.pullback_zone[1]}` : "-"}</span>
        <span>{lang === "zh" ? "结构失效位" : "Invalidation"}: {snapshot.invalidation_price ?? "-"}</span>
        <span>{lang === "zh" ? "证据状态" : "Evidence"}: {snapshot.lead_time_evidence.status === "limited_evidence" ? (lang === "zh" ? "样本积累中" : "Limited") : snapshot.lead_time_evidence.status}</span>
      </div>
    </section>
  );
}
