import { type FormEvent, useState } from "react";

type JournalText = {
  journalCoverage: string;
  reviewedNotes: string;
  enteredManually: string;
  exitedManually: string;
  skippedNotes: string;
  invalidatedNotes: string;
  journalPilotHint: string;
  afterCloseReview: string;
  runbookClose: string;
};

type StockJournalPayload = {
  entries: Array<{
    id: string | number;
    status: string;
    reviewed_at: string;
    notes?: string;
    outcome?: string;
    strategy_profile?: string;
    planned_entry?: number | null;
    planned_stop?: number | null;
    planned_target?: number | null;
    rule_conclusion?: string;
    ai_review_verdict?: string;
  }>;
  summary?: Record<string, number>;
};

function PanelTitle({ title, detail }: { title: string; detail: string }) {
  return <div className="panel-title"><h2>{title}</h2><span>{detail}</span></div>;
}

function Fact({ label, value }: { label: string; value: string }) {
  return <div className="fact"><span>{label}</span><strong>{value}</strong></div>;
}

function formatNumber(value: number | null | undefined): string {
  return value === null || value === undefined || Number.isNaN(value) ? "-" : Number(value).toFixed(2);
}

export function StockJournalPanel({
  symbol,
  journal,
  text,
  onSave,
}: {
  runId: string;
  symbol: string;
  journal: StockJournalPayload | null;
  text: JournalText;
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
      await onSave({ status, notes, planned_entry: plannedEntry, planned_stop: plannedStop, planned_target: plannedTarget, outcome });
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
      <div className="journal-summary-strip">
        <Fact label={text.journalCoverage} value={`${journal?.summary?.total_entries ?? 0}`} />
        <Fact label={text.reviewedNotes} value={`${journal?.summary?.reviewed_count ?? 0}`} />
        <Fact label={text.enteredManually} value={`${journal?.summary?.entered_manually_count ?? 0}`} />
        <Fact label={text.exitedManually} value={`${journal?.summary?.exited_manually_count ?? 0}`} />
        <Fact label={text.skippedNotes} value={`${journal?.summary?.skipped_count ?? 0}`} />
        <Fact label={text.invalidatedNotes} value={`${journal?.summary?.invalidated_count ?? 0}`} />
      </div>
      <p className="journal-pilot-hint">{text.journalPilotHint}</p>
      <form className="journal-form stock-journal-form" onSubmit={handleSubmit}>
        <select value={status} onChange={(event) => setStatus(event.target.value)}>
          <option value="reviewed">reviewed</option><option value="probe">probe</option><option value="full_review">full review</option><option value="watch">watch</option><option value="skipped">skipped</option><option value="paper-observed">paper-observed</option><option value="manual-traded">manual-traded note</option><option value="entered-manually">entered manually</option><option value="exited-manually">exited manually</option><option value="invalidated">invalidated</option>
        </select>
        <textarea value={notes} onChange={(event) => setNotes(event.target.value)} placeholder="Manual review note: daily, 1H, regime, entry plan..." />
        <div className="journal-price-grid">
          <input value={plannedEntry} onChange={(event) => setPlannedEntry(event.target.value)} placeholder="Planned entry" inputMode="decimal" />
          <input value={plannedStop} onChange={(event) => setPlannedStop(event.target.value)} placeholder="Planned stop" inputMode="decimal" />
          <input value={plannedTarget} onChange={(event) => setPlannedTarget(event.target.value)} placeholder="Planned target" inputMode="decimal" />
        </div>
        <input value={outcome} onChange={(event) => setOutcome(event.target.value)} placeholder="Outcome / follow-up" />
        <button className="primary-action" type="submit" disabled={saveState === "saving"}>{saveState === "saving" ? "Saving..." : "Save Journal"}</button>
        {saveState === "saved" ? <small>Saved locally. Read-only note only.</small> : null}
        {saveState === "error" ? <small>Save failed. Check local API and try again.</small> : null}
      </form>
      <section className="after-close-review">
        <div><span className="eyebrow">{text.afterCloseReview}</span><strong>{symbol}</strong><p>{text.runbookClose}</p></div>
        <div className="after-close-checks"><span>{text.enteredManually}: {journal?.summary?.entered_manually_count ?? 0}</span><span>{text.exitedManually}: {journal?.summary?.exited_manually_count ?? 0}</span><span>{text.invalidatedNotes}: {journal?.summary?.invalidated_count ?? 0}</span></div>
      </section>
      <div className="journal-list">
        {(journal?.entries ?? []).slice(0, 4).map((entry) => (
          <div className="journal-entry" key={entry.id}>
            <strong>{entry.status}</strong><span>{entry.reviewed_at}</span><p>{entry.notes || entry.outcome || "No note"}</p>
            <small>{entry.strategy_profile || "profile"} / entry {formatNumber(entry.planned_entry)} / stop {formatNumber(entry.planned_stop)} / target {formatNumber(entry.planned_target)}</small>
            <small>Rule {entry.rule_conclusion || "-"} / AI {entry.ai_review_verdict || "-"}</small>
          </div>
        ))}
        {journal && journal.entries.length === 0 ? <p className="probability-note">No manual stock review entries yet.</p> : null}
      </div>
    </section>
  );
}
