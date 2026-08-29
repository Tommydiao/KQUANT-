import { describe, expect, it } from "vitest";

import { parseRiskReward } from "./tradingFormatters";

describe("parseRiskReward", () => {
  it("extracts the displayed R multiple", () => {
    expect(parseRiskReward("2.6R")).toBe(2.6);
    expect(parseRiskReward("R:R 1.5")).toBe(1.5);
  });

  it("treats absent or non-numeric text as unavailable", () => {
    expect(parseRiskReward(undefined)).toBe(0);
    expect(parseRiskReward("unavailable")).toBe(0);
  });
});
