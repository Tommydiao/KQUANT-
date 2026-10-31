import { describe, expect, it } from "vitest";
import { mergeQuote, referenceNumber } from "./OptionReferenceChain";

describe("contract quote merge", () => {
  it("keeps omitted fields on a partial quote, including legitimate zero", () => {
    const row = mergeQuote({ previous_close: 2, last: 3, bid: 2.5, delta: 0.4 }, { last: 0 });
    expect(row).toMatchObject({ last: 0, delta: 0.4, bid: 2.5, change: -2, change_pct: -100 });
  });
  it("does not invent a percentage when previous close is zero or missing", () => {
    expect(mergeQuote({ previous_close: 0 }, { last: 2 }).change_pct).toBeNull();
    expect(mergeQuote({}, { last: 2 }).change_pct).toBeNull();
    expect(referenceNumber(null)).toBe("—");
    expect(referenceNumber(0)).toBe("0");
  });
  it("rejects out-of-order quote updates", () => {
    const row = { last: 3, quote_received_at: "2026-09-21T14:00:02Z" };
    expect(mergeQuote(row, { last: 1, quote_received_at: "2026-09-21T14:00:01Z" })).toEqual(row);
  });
  it("merges independent Greeks when their accompanying quote is older", () => {
    const row = mergeQuote({ last: 4, quote_received_at: "2026-09-21T14:00:02Z" }, { last: 3, quote_received_at: "2026-09-21T14:00:01Z", delta: 0.5 });
    expect(row.last).toBe(4);
    expect(row.delta).toBe(0.5);
  });
  it("invalidates an empty book without giving old prices a new receipt time", () => {
    const row = mergeQuote({ bid: 4, ask: 4.2, bbo_received_at: "2026-09-21T14:00:00Z" },
      { bid: null, ask: null, bid_size: 0, ask_size: 0, bbo_received_at: "2026-09-21T14:01:00Z", depth_status: "unavailable" });
    expect(row).toMatchObject({ bid: null, ask: null, bbo_received_at: null, last_known_bbo: { bid: 4, ask: 4.2, bbo_received_at: "2026-09-21T14:00:00Z" } });
  });
  it("does not treat a no-depth batch as invalidation", () => {
    expect(mergeQuote({ bid: 4, ask: 5, depth_status: "available", bbo_received_at: "old" }, { depth_status: "not_requested", bid: null, ask: null, bbo_received_at: null }).bid).toBe(4);
  });
  it("rejects crossed and partial books but preserves a valid zero", () => {
    expect(mergeQuote({ bid: 4, ask: 5 }, { bid: 6 }).ask).toBeNull();
    expect(mergeQuote({}, { bid: 6, ask: 5 }).bid).toBeNull();
    expect(mergeQuote({}, { bid: 0, ask: 1, bid_size: 0, ask_size: 2 }).bid).toBe(0);
  });
  it("uses sequence only within the same connection epoch", () => {
    const old = { bid: 4, ask: 5, bbo_epoch: "a", bbo_sequence: 9 };
    expect(mergeQuote(old, { bid: 1, ask: 2, bbo_epoch: "a", bbo_sequence: 8 }).bid).toBe(4);
    expect(mergeQuote(old, { bid: 1, ask: 2, bbo_epoch: "b", bbo_sequence: 1 }).bid).toBe(1);
  });
  it("does not leave an expired contract with a current book", () => {
    expect(mergeQuote({ bid: 4, ask: 5 }, { trade_status: "TradeStatus.Expired", provider_status: "available" })).toMatchObject({ bid: null, ask: null, depth_status: "non_trading" });
  });
  it("retains each unchanged field's own timestamp", () => {
    const old = mergeQuote({}, { last: 3, volume: 10, quote_received_at: "2026-09-21T14:00:00Z" });
    const next = mergeQuote(old, { last: 4, quote_received_at: "2026-09-21T14:01:00Z" });
    expect(next.field_times.volume.received_at).toBe("2026-09-21T14:00:00Z");
    expect(next.field_times.last.received_at).toBe("2026-09-21T14:01:00Z");
  });
  it("does not renew retained BBO prices from heartbeat or size-only updates", () => {
    const old = { bid: 4, ask: 4.2, bbo_received_at: "2026-09-21T14:00:00Z", bbo_observed_at: "2026-09-21T14:00:00Z" };
    for (const patch of [{ bbo_received_at: "2026-09-21T14:01:00Z" },
      { bid_size: 1, ask_size: 2, bbo_received_at: "2026-09-21T14:01:00Z" }]) {
      const next = mergeQuote(old, patch);
      expect(next.bid).toBe(4);
      expect(next.ask).toBe(4.2);
      expect(next.bbo_received_at).toBe(old.bbo_received_at);
    }
  });
  it("does not let an older contract status invalidate a newer book", () => {
    const old = { bid: 4, ask: 4.2, trade_status: "Normal", contract_validity: "UNEXPIRED", quote_received_at: "2026-09-21T14:01:00Z" };
    const next = mergeQuote(old, { trade_status: "Expired", contract_validity: "EXPIRED", quote_received_at: "2026-09-21T14:00:00Z" });
    expect(next).toEqual(old);
  });
  it("keeps open interest independent of an older Greeks result", () => {
    const old = { delta: 0.5, calc_received_at: "2026-09-21T14:01:00Z", open_interest: 10, oi_received_at: "2026-09-21T14:00:00Z" };
    const next = mergeQuote(old, { delta: 0.1, calc_received_at: "2026-09-21T14:00:00Z", open_interest: 0, oi_received_at: "2026-09-21T14:02:00Z" });
    expect(next.delta).toBe(0.5);
    expect(next.open_interest).toBe(0);
  });
});
