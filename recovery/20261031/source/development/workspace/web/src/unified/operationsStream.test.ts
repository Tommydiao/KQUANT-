import { afterEach, describe, expect, it, vi } from "vitest";
import { coalescedRefresh, operationEventMatches } from "./operationsStream";
import { needsSnapshotFallback, operationsStreamConnected, setOperationsStreamConnected, snapshotNeedsRecovery, snapshotReadyResetsBackoff, snapshotReadyMatches, subscribeOperationsStream } from "./operationsStream";

it('matches compact trend snapshots without matching other resources or bypassing backoff', () => {
  const original = '/api/options/one-minute/status?research_strategy=opening_trend';
  const compact = `${original}&compact=true`;
  expect(snapshotReadyMatches(compact, original)).toBe(true);
  expect(snapshotReadyResetsBackoff(compact, original, 503, false)).toBe(true);
  for (const status of [429, 401, 403]) expect(snapshotReadyResetsBackoff(compact, original, status, false)).toBe(false);
  expect(snapshotReadyResetsBackoff(compact, original, 503, true)).toBe(false);
  expect(snapshotReadyMatches(compact, '/api/options/one-minute/status')).toBe(false);
  expect(snapshotReadyMatches(`${compact}&scope=other`, original)).toBe(false);
});

it('retries a completed 503 snapshot without bypassing rate limits or auth', () => {
  expect(snapshotReadyResetsBackoff('/trend', '/trend', 503, false)).toBe(true);
  for (const status of [429, 401, 403, 200, undefined]) {
    expect(snapshotReadyResetsBackoff('/trend', '/trend', status, false)).toBe(false);
  }
  expect(snapshotReadyResetsBackoff('/trend', '/other', 503, false)).toBe(false);
  expect(snapshotReadyResetsBackoff('/trend', '/trend', 503, true)).toBe(false);
});

afterEach(() => { setOperationsStreamConnected(false); vi.useRealTimers(); });
it('refreshes option data without refetching static version on every worker event', () => {
  expect(operationEventMatches('/api/workspace/version')).toBe(false);
  expect(operationEventMatches('/api/options/opening-trend/current')).toBe(true);
  vi.useFakeTimers();
  const run = vi.fn();
  const refresh = coalescedRefresh(run);
  for (let i = 0; i < 200; i++) refresh.request();
  vi.advanceTimersByTime(499);
  expect(run).not.toHaveBeenCalled();
  vi.advanceTimersByTime(1);
  expect(run).toHaveBeenCalledTimes(1);
  refresh.request(); refresh.cancel(); vi.advanceTimersByTime(500);
  expect(run).toHaveBeenCalledTimes(1);
  refresh.request(); vi.advanceTimersByTime(500);
  expect(run).toHaveBeenCalledTimes(2);
});
describe("operational stream", () => {
  it("continues bounded foreground recovery until checkpoint projection catches up", () => {
    const snapshot = { state: "FRESH" };
    const recovering = snapshotNeedsRecovery(snapshot, { state: "UNAVAILABLE", projection: { state: "PROJECTION_CATCHING_UP" } });
    expect(recovering).toBe(true);
    expect(needsSnapshotFallback(false, true, recovering)).toBe(true);
    expect(needsSnapshotFallback(true, true, recovering)).toBe(false);
    expect(snapshotNeedsRecovery(snapshot, { state: "NO_COMPLETE_NUMERIC_EVIDENCE" })).toBe(false);
  });
  it("polls only a visible disconnected page", () => {
    expect(needsSnapshotFallback(false, false)).toBe(true);
    expect(needsSnapshotFallback(false, true)).toBe(false);
    expect(needsSnapshotFallback(true, false)).toBe(false);
    expect(needsSnapshotFallback(true, true)).toBe(false);
  });
  it("exposes disconnect immediately and emits only state changes", () => {
    const states: boolean[] = [];
    const release = subscribeOperationsStream(() => states.push(operationsStreamConnected()));
    setOperationsStreamConnected(true);
    setOperationsStreamConnected(true);
    setOperationsStreamConnected(false);
    release();
    setOperationsStreamConnected(true);
    expect(states).toEqual([true, false]);
  });
  it("retries failed snapshots even when SSE is healthy, never in the background", () => {
    expect(needsSnapshotFallback(false, true, true)).toBe(true);
    expect(needsSnapshotFallback(true, true, true)).toBe(false);
    expect(needsSnapshotFallback(false, true, false)).toBe(false);
  });
  it("recovers successful stale or refresh-pending snapshots without polling fresh data", () => {
    for (const snapshot of [{ state: "STALE" }, { state: "FRESH", refresh_pending: true }]) {
      expect(snapshotNeedsRecovery(snapshot)).toBe(true);
      expect(needsSnapshotFallback(false, true, snapshotNeedsRecovery(snapshot))).toBe(true);
      expect(needsSnapshotFallback(true, true, snapshotNeedsRecovery(snapshot))).toBe(false);
    }
    for (const snapshot of [undefined, null, [], { state: "FRESH", refresh_pending: false }]) {
      expect(snapshotNeedsRecovery(snapshot)).toBe(false);
      expect(needsSnapshotFallback(false, true, snapshotNeedsRecovery(snapshot))).toBe(false);
    }
  });
  it("snapshot recovery does not alter price timestamps or the original deadline", () => {
    const payload = { snapshot: { state: "STALE", refresh_pending: true },
      quote: { bbo_received_at: "2026-09-30T13:55:01Z", bid: 0 }, deadline_at: "2026-09-30T14:00:00Z" };
    const original = JSON.stringify(payload);
    expect(snapshotNeedsRecovery(payload.snapshot)).toBe(true);
    expect(JSON.stringify(payload)).toBe(original);
  });
});
