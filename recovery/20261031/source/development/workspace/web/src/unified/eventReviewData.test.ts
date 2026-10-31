import { describe, expect, it } from "vitest";
import { parseReviewedEvents } from "./eventReviewData";

const start = "2026-09-30T13:00:00Z", end = "2026-09-30T20:00:00Z";
const event = { name: "TEST_ONLY", blocks_entry: true, start_at: "2026-09-30T14:00:00Z", end_at: "2026-09-30T14:15:00Z" };
const parse = (events: unknown, risk = "KNOWN_BLOCKER") => parseReviewedEvents(JSON.stringify(events), start, end, risk);
describe("reviewed event input", () => {
  it("requires an actual blocking event for a known-risk conclusion", () => {
    expect(() => parse([])).toThrow("KNOWN_BLOCKER_NEEDS_BLOCKING_EVENT");
    expect(() => parse([{ ...event, blocks_entry: false }])).toThrow("KNOWN_BLOCKER_NEEDS_BLOCKING_EVENT");
    expect(parse([event])).toEqual([event]);
  });
  it("does not mix a clear conclusion with a blocker", () => {
    expect(() => parse([event], "CLEAR")).toThrow("CLEAR_CANNOT_CONTAIN_BLOCKER");
    expect(parse([], "CLEAR")).toEqual([]);
  });
  it("requires explicit field types and timezone-aware times", () => {
    for (const input of [null, "risk", [], { ...event, blocks_entry: "true" }, { ...event, name: " " }]) {
      expect(() => parse([input])).toThrow();
    }
    for (const value of [undefined, 0, "2026-09-30T14:00:00", "invalidZ"]) {
      expect(() => parse([{ ...event, start_at: value }])).toThrow("EVENT_TIME_INVALID_OR_TIMEZONE_MISSING");
    }
  });
  it("rejects reversed or out-of-window events without changing original evidence", () => {
    for (const changes of [{ start_at: "2026-09-30T20:01:00Z" }, { end_at: "2026-10-01T14:15:00Z" }]) {
      expect(() => parse([{ ...event, ...changes }])).toThrow("EVENT_OUTSIDE_COVERAGE_WINDOW");
    }
    const payload = [{ ...event, source_reference: "TEST_ONLY_ORIGINAL" }];
    expect(parse(payload)).toEqual(payload);
  });
});
