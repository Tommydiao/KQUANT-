export type RecordData = Record<string, any>;

export function currentCoverage(two: RecordData): RecordData[] {
  const latest = new Map<string, RecordData>();
  for (const item of two.current_evaluations ?? []) {
    latest.set(`${item.symbol}:${item.right}`, item);
  }
  return (two.prewarm ?? []).filter((item: RecordData) => item.session === two.summary?.session).flatMap((item: RecordData) =>
    ["CALL", "PUT"].map(right => latest.get(`${item.symbol}:${right}`) ?? {
      symbol: item.symbol, right, state: item.state === "READY" ? "WAITING_CLOSED_PAIR" : item.state,
      blockers: [item.reason || (item.state === "READY" ? "WAITING_CLOSED_PAIR" : item.state)],
      session: item.session, evaluated_at: null,
    }));
}

export function paperRows(paper: RecordData): RecordData[] {
  return [
    ...(paper.intents ?? []).map((item: RecordData) => ({ ...item, source_kind: "INTENT" })),
    ...(paper.positions ?? []).map((item: RecordData) => ({ ...item, source_kind: "POSITION" })),
  ];
}

export function planCategory(item: RecordData): string {
  if (item.source_kind === "WATCH") return item.active ? "watch" : "ended";
  if (["EXIT_PENDING_DATA", "EXIT_REVIEW"].includes(item.state) || (item.action === "EXIT" && item.state === "PENDING_QUOTE")) return "exit";
  if (item.source_kind === "POSITION" && item.state === "OPEN") return "positions";
  if (["PENDING_QUOTE", "WAIT_CONFIRMATION", "OWNER_CONFIRMATION_REQUIRED"].includes(item.state)) return "pending";
  return "ended";
}

export function displaySymbol(item: RecordData): string {
  return item.symbol ?? item.underlying ?? item.payload?.contract?.underlying ?? "-";
}

export function jsonExport(value: unknown, name: string) {
  const url = URL.createObjectURL(new Blob([JSON.stringify(value, null, 2)], { type: "application/json" }));
  const link = document.createElement("a"); link.href = url; link.download = `${name}.json`; link.click();
  URL.revokeObjectURL(url);
}
