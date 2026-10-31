import { describe, expect, it } from "vitest";
import { extractCandles, isHealthReady, numberValue } from "./App";
import { referenceNumber } from "./OptionReferenceChain";

describe("data visibility boundary", () => {
  it.each(["unavailable", "unhealthy", "not_ready", "unknown", ""])("does not mark %s ready", value => {
    expect(isHealthReady(value)).toBe(false);
  });
  it.each(["available", "healthy", "OK"])("accepts exact healthy status %s", value => {
    expect(isHealthReady(value)).toBe(true);
  });
  it("does not turn absent numbers into zero", () => {
    expect(numberValue(null, undefined, "", " ", false)).toBeNull();
    expect(numberValue(null, 0)).toBe(0);
    expect(referenceNumber(null)).toBe("—");
    expect(referenceNumber(0)).toBe("0");
  });
  it("does not create a candle from a null open or close", () => {
    expect(extractCandles({candles: [{open: null, close: null}]})).toEqual([]);
  });
});
