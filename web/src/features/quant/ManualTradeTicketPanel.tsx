type Lang = "en" | "zh";

type ManualTradeTicket = {
  status: "cleared_for_review" | "journal_required" | "blocked";
  summary: string;
  checks: Array<{ label: string; value: string; ok: boolean }>;
  action: string;
  entryZone: string;
  stopZone: string;
  targetZone: string;
  riskReward: string;
  positionSizeHint: string;
  invalidatedIf: string[];
  reasons: string[];
};

type AiDecision = {
  hard_veto?: { active?: boolean | null } | null;
};

type TicketCopy = {
  entryZone: string;
  stopZone: string;
  targetZone: string;
  riskReward: string;
  sizeHint: string;
  invalidation: string;
  blockers: string;
  journalBeforeTrade: string;
};

type DisplayPlanKind = "entry" | "stop" | "target" | "position" | "riskReward";

type Props = {
  ticket: ManualTradeTicket;
  aiDecision: AiDecision | null;
  text: TicketCopy;
  lang: Lang;
  onOpenJournal: () => void;
  displayTradeAction: (action: unknown, lang: Lang) => string;
  displayPlanField: (value: unknown, kind: DisplayPlanKind, lang: Lang) => string;
  displayResearchText: (value: unknown, lang: Lang) => string;
};

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
      <strong>{title}</strong>
      <ul>
        {items.map((item, index) => <li key={`${title}-${index}`}>{item}</li>)}
      </ul>
    </div>
  );
}

export function ManualTradeTicketPanel({
  ticket,
  aiDecision,
  text,
  lang,
  onOpenJournal,
  displayTradeAction,
  displayPlanField,
  displayResearchText,
}: Props) {
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
        <Fact
          label={lang === "zh" ? "风控状态" : "Risk control"}
          value={aiDecision?.hard_veto?.active ? (lang === "zh" ? "暂不通过" : "Not cleared") : (lang === "zh" ? "已通过" : "Cleared")}
        />
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
        <Narrative
          title={text.invalidation}
          items={(ticket.invalidatedIf.length ? ticket.invalidatedIf : [lang === "zh" ? "暂无失效条件。" : "No invalidation details yet."]).map((item) => displayResearchText(item, lang))}
        />
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

export type { ManualTradeTicket };
