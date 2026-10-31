import { Activity, RefreshCw, ShieldCheck } from "lucide-react";
import type { ReactNode } from "react";

type ApiConnectionState = "checking" | "connected" | "offline";

type ApiHealthPayload = {
  backend?: string;
  market_data_provider?: string;
  market_data?: { provider?: string; status?: string; market_clock?: { session?: string } };
};

type RealtimeSnapshotPayload = {
  session?: string;
  quote?: { provider_status?: string; bid?: number | null; ask?: number | null };
};

type SignalRun = {
  provider_status: string;
  provider_error_count: number;
  provider_coverage?: { available: number; stale_or_partial: number; failed: number };
  scanned_count?: number;
  universe_total?: number;
  counts: { total: number };
};

type CandleMeta = {
  sourceType: string;
  providerStatus: string;
  staleAge: string;
  count: number;
  last: string;
};

type ProductionReadinessPayload = {
  strategy_version: string;
  decision: "GO" | "NO_GO" | string;
  failed_gate_count: number;
  failed_gates: { gate: string; reason: string }[];
  historical: { sample_count: number; average_r: number; profit_factor: number };
  forward?: { market_day_count?: number; data_incident_count?: number } | null;
  paper?: { closed_position_count?: number } | null;
};

function formatNumber(value: number | null | undefined): string {
  if (value === null || value === undefined || Number.isNaN(value)) return "-";
  return Number(value).toFixed(2);
}

function Fact({ label, value }: { label: string; value: string }) {
  return <div className="fact"><span>{label}</span><strong>{value}</strong></div>;
}

function Pill({ label, icon, tone }: { label: string; icon: ReactNode; tone: "good" | "warn" | "neutral" }) {
  return <span className={`pill ${tone}`}>{icon}{label}</span>;
}

export function RiskControlPanel({ report, onRefresh }: { report: ProductionReadinessPayload | null; onRefresh: () => void }) {
  const noGo = !report || report.decision !== "GO";
  return (
    <section className={`panel risk-control-panel ${noGo ? "no-go" : "go"}`} aria-label="Risk control center">
      <div className="risk-control-head">
        <div>
          <span>Risk Control Center</span>
          <h2>{report?.decision ?? "NO_GO"}</h2>
          <p>This is an evidence gate, not a broker permission. Any actual manual trade remains outside KQUANT and must satisfy the separate checklist.</p>
        </div>
        <button className="secondary-action" type="button" onClick={onRefresh}><RefreshCw size={15} />Refresh Gate</button>
      </div>
      <div className="risk-control-grid">
        <Fact label="Frozen Strategy" value={report?.strategy_version ?? "not verified"} />
        <Fact label="Historical Samples" value={String(report?.historical.sample_count ?? 0)} />
        <Fact label="Average R" value={`${formatNumber(report?.historical.average_r)}R`} />
        <Fact label="Profit Factor" value={formatNumber(report?.historical.profit_factor)} />
        <Fact label="Forward Days" value={String(report?.forward?.market_day_count ?? 0)} />
        <Fact label="Paper Exits" value={String(report?.paper?.closed_position_count ?? 0)} />
        <Fact label="Forward Incidents" value={String(report?.forward?.data_incident_count ?? 0)} />
        <Fact label="Failed Gates" value={String(report?.failed_gate_count ?? 0)} />
      </div>
      {noGo ? (
        <div className="risk-control-failures">
          {(report?.failed_gates ?? [{ gate: "evidence", reason: "Production readiness has not loaded." }]).slice(0, 6).map((gate) => (
            <p key={gate.gate}><b>{gate.gate}</b>{gate.reason}</p>
          ))}
        </div>
      ) : <p className="risk-control-pass">All defined evidence gates are currently satisfied. Automatic execution remains disabled.</p>}
    </section>
  );
}

export function DataReliabilityPanel({
  apiConnection,
  apiHealth,
  realtimeSnapshot,
  run,
  dailyMeta,
  hourlyMeta,
  selectedSymbol,
  apiBaseUrl,
}: {
  apiConnection: ApiConnectionState;
  apiHealth: ApiHealthPayload | null;
  realtimeSnapshot: RealtimeSnapshotPayload | null;
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
  const configuredProvider = String(apiHealth?.market_data?.provider ?? apiHealth?.market_data_provider ?? "").toLowerCase();
  const marketSession = String(realtimeSnapshot?.session ?? apiHealth?.market_data?.market_clock?.session ?? "").toLowerCase();
  const depthAvailable = realtimeSnapshot?.quote?.provider_status === "available" && realtimeSnapshot.quote.bid != null && realtimeSnapshot.quote.ask != null;
  const longbridgeLive = configuredProvider === "longbridge" && apiHealth?.market_data?.status === "available" && marketSession === "regular" && (dailyMeta.sourceType.includes("longbridge") || hourlyMeta.sourceType.includes("longbridge"));
  const yahooReference = configuredProvider === "yahoo" || dailyMeta.sourceType.includes("yahoo") || hourlyMeta.sourceType.includes("yahoo");
  const worstStatus = apiConnection !== "connected"
    ? "Local API offline"
    : configuredProvider === "longbridge" && marketSession === "closed"
      ? "Longbridge closed"
      : longbridgeLive
        ? "Longbridge live data available"
        : yahooReference
          ? "Yahoo reference data only"
          : run.provider_status === "available" ? "Latest scan available" : "Provider degraded";
  const providerExplanation = configuredProvider === "longbridge" && marketSession === "closed"
    ? "Longbridge is connected, but the US market is closed. The displayed quote is the last market quote and cannot satisfy a manual trade review."
    : longbridgeLive
      ? "Longbridge is supplying the selected market-data path. Forming candles remain display-only and cannot confirm an action."
      : yahooReference
        ? "Yahoo public data is display/reference only. It cannot support buy-class actions or forward-pilot entries."
        : "Data is unavailable or degraded. KQUANT keeps the decision state at NO TRADE until a trusted source recovers.";
  return (
    <section className="panel data-reliability-panel" id="data-reliability-workspace">
      <div className="data-reliability-head">
        <div><span>Data Reliability</span><h2>{worstStatus}</h2><p>{providerExplanation}</p></div>
        <Pill tone={apiConnection === "connected" && longbridgeLive ? "good" : "warn"} icon={<Activity size={14} />} label={apiConnection === "connected" ? "Local backend connected" : "Local backend offline"} />
      </div>
      <div className="data-reliability-grid">
        <Fact label="Provider Status" value={`${configuredProvider || run.provider_status} / ${run.provider_status}`} />
        <Fact label="Coverage" value={`${available} available / ${stale} stale / ${failed} failed`} />
        <Fact label="Scanned Symbols" value={`${run.scanned_count ?? run.counts.total}/${run.universe_total ?? run.counts.total}`} />
        <Fact label="Last Candle" value={`${selectedSymbol} / ${latestCandle}`} />
        <Fact label="Selected Daily" value={`${dailyMeta.providerStatus} / ${dailyMeta.count} candles`} />
        <Fact label="Selected Confirm" value={`${hourlyMeta.providerStatus} / ${hourlyMeta.count} candles`} />
        <Fact label="Depth Quote" value={depthAvailable ? "available" : "unavailable / not entitled"} />
        <Fact label="Stale Age" value={`${dailyMeta.staleAge || "none"} / ${hourlyMeta.staleAge || "none"}`} />
        <Fact label="Environment" value={apiBaseUrl ? `remote API ${apiBaseUrl.replace(/^https?:\/\//, "")}` : `local ${apiHealth?.backend ?? "stdlib_server"}`} />
      </div>
    </section>
  );
}
