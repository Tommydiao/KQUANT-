type ReadinessText = Record<string, string>;

type Readiness = {
  status: "READY" | "CAUTION" | "NO_TRADE" | string;
  summary: string;
  checks: Array<{ label: string; value: string; ok: boolean; critical?: boolean }>;
  reasons: string[];
  riskRules: string[];
};

export function ReadinessPanel({ readiness, text }: { readiness: Readiness; text: ReadinessText }) {
  const statusLabel = readiness.status === "READY" ? text.readinessReady : readiness.status === "CAUTION" ? text.readinessCaution : text.readinessNoTrade;
  return (
    <section className={`panel live-readiness-panel ${readiness.status.toLowerCase().replace(/_/g, "-")}`}>
      <div className="readiness-head"><div><span className="eyebrow">{text.realMoneyPilot}</span><h2>{text.mondayReadiness}</h2><p>{readiness.summary}</p></div><b>{statusLabel}</b></div>
      {readiness.status === "NO_TRADE" ? <p className="compare-error">{text.noRealMoneyTrade}</p> : null}
      <div className="readiness-check-grid">{readiness.checks.map((check) => <div className={`readiness-check ${check.ok ? "ok" : check.critical ? "critical" : "warn"}`} key={check.label}><span>{check.label}</span><strong>{check.value}</strong></div>)}</div>
      {readiness.reasons.length ? <div className="readiness-reasons">{readiness.reasons.map((reason) => <span key={reason}>{reason}</span>)}</div> : null}
      <div className="pilot-runbook"><strong>{text.firstDayRiskRules}</strong>{readiness.riskRules.map((rule) => <span key={rule}>{rule}</span>)}</div>
      <div className="pilot-runbook compact"><strong>{text.mondayRunbook}</strong>{[text.runbookPremarket, text.runbookOpen, text.runbookEntry, text.runbookClose].map((step) => <span key={step}>{step}</span>)}</div>
    </section>
  );
}
