export function parseReviewedEvents(value: string, start: string, end: string, risk: string): unknown[] {
  let events: unknown;
  try { events = JSON.parse(value); } catch { throw new Error("EVENTS_MUST_BE_ARRAY"); }
  if (!Array.isArray(events)) throw new Error("EVENTS_MUST_BE_ARRAY");
  const time = (value: unknown) => {
    if (typeof value !== "string" || !/(?:Z|[+-]\d{2}:\d{2})$/.test(value)) {
      throw new Error("EVENT_TIME_INVALID_OR_TIMEZONE_MISSING");
    }
    const result = Date.parse(value);
    if (!Number.isFinite(result)) throw new Error("EVENT_TIME_INVALID_OR_TIMEZONE_MISSING");
    return result;
  };
  const from = time(start), until = time(end);
  if (from >= until) throw new Error("EVENT_OUTSIDE_COVERAGE_WINDOW");
  let blocking = false;
  for (const raw of events) {
    if (!raw || typeof raw !== "object" || Array.isArray(raw)) throw new Error("EVENT_MUST_BE_OBJECT");
    const event = raw as Record<string, unknown>;
    if (typeof event.name !== "string" || !event.name.trim() || typeof event.blocks_entry !== "boolean") {
      throw new Error("EVENT_NAME_AND_BLOCKING_FLAG_REQUIRED");
    }
    const eventStart = time(event.start_at), eventEnd = time(event.end_at);
    if (!(from <= eventStart && eventStart <= eventEnd && eventEnd <= until)) throw new Error("EVENT_OUTSIDE_COVERAGE_WINDOW");
    blocking ||= event.blocks_entry;
  }
  if (risk === "KNOWN_BLOCKER" && !blocking) throw new Error("KNOWN_BLOCKER_NEEDS_BLOCKING_EVENT");
  if (risk === "CLEAR" && blocking) throw new Error("CLEAR_CANNOT_CONTAIN_BLOCKER");
  return events;
}
