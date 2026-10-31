import { RefreshCw, ShieldCheck } from "lucide-react";
import type { ReactNode } from "react";

type TodayCandidate = {
  rank: number;
  bucket: string;
  symbol: string;
  strategy_score?: number;
  data_status?: string;
  system_action?: string;
  invalidation?: string[];
  risk?: { warnings?: string[] };
};

type TodayWorkbenchPayload = {
  decision: "NO_TRADE" | "MANUAL_REVIEW" | string;
  headline: string;
  market: { label: string; score: number };
  data_trust: { provider_status: string; source: string };
  top_candidates: TodayCandidate[];
  watch_candidates: TodayCandidate[];
  risk: { production_decision?: string; failed_gate_count?: number };
  exception_states: string[];
  diagnostics: { ai_status?: string };
};

function Fact({ label, value }: { label: string; value: string }) {
  return <div className="fact"><span>{label}</span><strong>{value}</strong></div>;
}

function Pill({ label, icon, tone }: { label: string; icon: ReactNode; tone: "good" | "warn" }) {
  return <span className={`pill ${tone}`}>{icon}{label}</span>;
}

export function TodayDecisionPanel({
  payload,
  onPick,
  onRefresh,
}: {
  payload: TodayWorkbenchPayload | null;
  onPick: (symbol: string) => void;
  onRefresh: () => void;
}) {
  const noTrade = !payload || payload.decision === "NO_TRADE";
  const candidates = payload?.top_candidates ?? [];
  const watches = payload?.watch_candidates ?? [];
  return (
    <section className={`today-decision-panel ${noTrade ? "no-trade" : "manual-review"}`} aria-label="Today decision workbench">
      <div className="today-decision-head">
        <div>
          <span>Today Decision</span>
          <h2>{payload?.headline ?? "Data check required"}</h2>
          <p>{noTrade ? "Do not open a new manual trade until the displayed data, forward-evidence, and hard-veto checks clear." : "Candidates are for human review only. KQUANT does not connect to an account or submit an order."}</p>
        </div>
        <div className="today-decision-actions">
          <Pill tone={noTrade ? "warn" : "good"} icon={<ShieldCheck size={14} />} label={payload?.decision ?? "NO TRADE"} />
          <button className="secondary-action" type="button" onClick={onRefresh}><RefreshCw size={15} />Refresh</button>
        </div>
      </div>
      <div className="today-decision-facts">
        <Fact label="Market" value={`${payload?.market.label ?? "Unknown"} / ${payload?.market.score ?? 0}`} />
        <Fact label="Data" value={`${payload?.data_trust.provider_status ?? "unknown"} / ${payload?.data_trust.source ?? "-"}`} />
        <Fact label="研究服务" value={payload?.diagnostics.ai_status === "available" ? "已连接" : "暂不可用"} />
        <Fact label="Forward Gate" value={`${payload?.risk.production_decision ?? "NO_GO"} / ${payload?.risk.failed_gate_count ?? 0} failed`} />
      </div>
      <div className="today-decision-grid">
        <div className="today-candidate-list">
          <div className="today-section-title"><strong>Top Manual Review</strong><span>{candidates.length}/3</span></div>
          {candidates.length ? candidates.map((item) => (
            <button type="button" className="today-candidate" key={`today-${item.symbol}`} onClick={() => onPick(item.symbol)}>
              <b>#{item.rank} {item.symbol}</b>
              <span>{item.system_action ?? item.bucket} / {item.strategy_score ?? "-"}</span>
              <small>{item.data_status ?? "unknown"}{item.risk?.warnings?.[0] ? `: ${item.risk.warnings[0]}` : ""}</small>
            </button>
          )) : <p className="today-empty">No clean BUY SETUP is available.</p>}
        </div>
        <div className="today-candidate-list">
          <div className="today-section-title"><strong>Watch</strong><span>{watches.length}/7</span></div>
          {watches.length ? watches.slice(0, 4).map((item) => (
            <button type="button" className="today-candidate watch" key={`watch-${item.symbol}`} onClick={() => onPick(item.symbol)}>
              <b>#{item.rank} {item.symbol}</b>
              <span>{item.system_action ?? item.bucket} / {item.strategy_score ?? "-"}</span>
              <small>{item.invalidation?.[0] ?? "Wait for planned trigger."}</small>
            </button>
          )) : <p className="today-empty">No clean WATCH item is available.</p>}
        </div>
        <div className="today-exception-list">
          <div className="today-section-title"><strong>Why It Is Blocked</strong><span>{payload?.exception_states.length ?? 0}</span></div>
          {(payload?.exception_states ?? ["Today workbench has not loaded yet."]).slice(0, 5).map((reason) => <p key={reason}>{reason}</p>)}
        </div>
      </div>
    </section>
  );
}
