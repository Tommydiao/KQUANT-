import { describe, expect, it } from "vitest";
import { currentEligibilityValid, currentTrendContract, currentResearchReady } from "./currentEligibility";

describe("current endpoint research readiness", () => {
  it("rejects a stopped observed runtime even with an old ready worker", () => {
    for (const state of ["STOPPED", "UNKNOWN_STALE", "UNAVAILABLE", "DEGRADED"]) {
      expect(currentResearchReady({ service_observation: { enforced: true, state, research_worker: { research_ready: true } } })).toBe(false);
    }
  });
  it("uses the current API service observation, not compact worker shape", () => {
    const payload = { service_observation: { research_worker: { research_ready: true } } };
    expect(currentResearchReady(payload)).toBe(true);
    expect(currentResearchReady({ ...payload, snapshot: { state: "STALE" } })).toBe(false);
    expect(currentResearchReady({ worker: { research_ready: true } })).toBe(false);
    expect(currentResearchReady({ service_observation: { research_worker: { research_ready: false } } })).toBe(false);
    expect(currentResearchReady(undefined)).toBe(false);
  });
});

describe("current eligibility", () => {
  const now = Date.parse("2026-09-29T13:31:01Z");
  const row = { contract_id: "c", deadline_at: "2026-09-29T13:31:30Z", current_eligibility: {
    contract_id: "c", state: "QUALIFIED", checked_at: "2026-09-29T13:31:01Z", valid_until: "2026-09-29T13:31:03Z",
    underlying_quote: { received_at: "2026-09-29T13:31:00Z" },
    contract_qualification: { selected: { snapshot: { bbo_received_at: "2026-09-29T13:31:00Z" } } },
  } };
  it("requires current evidence, not the original candidate", () => {
    expect(currentEligibilityValid(row, now)).toBe(true);
    expect(currentEligibilityValid({ ...row, current_eligibility: null }, now)).toBe(false);
    expect(currentEligibilityValid(row, now + 2000)).toBe(false);
  });
  it("rejects withdrawal, changed contracts and future evidence", () => {
    expect(currentEligibilityValid({ ...row, contract_id: "other" }, now)).toBe(false);
    expect(currentEligibilityValid({ ...row, current_eligibility: { ...row.current_eligibility, state: "REVOKED" } }, now)).toBe(false);
    expect(currentEligibilityValid(row, now - 2000)).toBe(false);
  });
  it("rejects missing, malformed or future graded-risk timestamps", () => {
    const risk = { decision: "WARN", checked_at: "2026-09-29T13:31:00Z", valid_until: "2026-09-29T13:31:30Z" };
    const withRisk = (value: object) => ({ ...row, current_eligibility: { ...row.current_eligibility, event_decision: value } });
    expect(currentEligibilityValid(withRisk(risk), now)).toBe(true);
    for (const checked_at of [undefined, "invalid", "2026-09-29T13:31:02Z"]) {
      expect(currentEligibilityValid(withRisk({ ...risk, checked_at }), now)).toBe(false);
    }
    expect(currentEligibilityValid(withRisk({ ...risk, decision: "BLOCK" }), now)).toBe(false);
    expect(currentEligibilityValid(withRisk({ ...risk, valid_until: "2026-09-29T13:31:00Z" }), now)).toBe(false);
  });
  it("a trend entry requires the same concrete contract with expiry and strike", () => {
    const selected = { contract_id: "c", underlying: "TEST", right: "CALL", strike: 100, expiry_date: "2026-10-02",
      snapshot: { bbo_received_at: "2026-09-29T13:31:00Z" } };
    const trend = { ...row, policy_id: "STRAT-OPENING-TREND-PULLBACK-5M-V1", symbol: "TEST", right: "CALL",
      current_eligibility: { ...row.current_eligibility, contract_qualification: { selected } } };
    expect(currentEligibilityValid(trend, now)).toBe(true);
    for (const change of [{ strike: null }, { strike: 0 }, { expiry_date: "2026-02-30" }, { expiry_date: "" },
      { underlying: "OTHER" }, { right: "PUT" }, { contract_id: "other" }]) {
      const invalid = { ...trend, current_eligibility: { ...trend.current_eligibility,
        contract_qualification: { selected: { ...selected, ...change } } } };
      expect(currentTrendContract(invalid)).toBeNull();
      expect(currentEligibilityValid(invalid, now)).toBe(false);
    }
  });
  it("momentum cannot bypass concrete contract identity validation", () => {
    expect(currentEligibilityValid({ ...row, policy_id: "STRAT-OPENING-MOMENTUM-5M-V1" }, now)).toBe(false);
  });
});
