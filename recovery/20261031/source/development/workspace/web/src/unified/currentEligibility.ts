type Row = Record<string, any>;

export function currentResearchReady(payload: Row | null | undefined): boolean {
  return payload?.snapshot?.state !== "STALE"
    && (!payload?.service_observation?.enforced || payload.service_observation.state === "RUNNING")
    && payload?.service_observation?.research_worker?.research_ready === true;
}

export function currentTrendContract(row: Row): Row | null {
  const selected = row.current_eligibility?.contract_qualification?.selected;
  if (!selected || !row.contract_id || selected.contract_id !== row.contract_id
    || selected.contract_id !== row.current_eligibility.contract_id
    || selected.underlying !== row.symbol || selected.right !== row.right
    || !["CALL", "PUT"].includes(selected.right)
    || typeof selected.strike !== "number" || !Number.isFinite(selected.strike) || selected.strike <= 0) return null;
  const expiry = selected.expiry_date;
  if (typeof expiry !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(expiry)) return null;
  const parsed = new Date(`${expiry}T00:00:00Z`);
  if (!Number.isFinite(parsed.getTime()) || parsed.toISOString().slice(0, 10) !== expiry) return null;
  return selected;
}

export function currentEligibilityValid(row: Row, now: number): boolean {
  const current = row.current_eligibility;
  if (!current || current.state !== "QUALIFIED" || current.contract_id !== row.contract_id) return false;
  if (current.event_decision && (!["PASS", "WARN"].includes(current.event_decision.decision)
    || !(Date.parse(current.event_decision.checked_at) <= now)
    || !(Date.parse(current.event_decision.valid_until) > now))) return false;
  if (["STRAT-OPENING-TREND-PULLBACK-5M-V1", "STRAT-OPENING-MOMENTUM-5M-V1"].includes(row.policy_id) && !currentTrendContract(row)) return false;
  const age = now - Date.parse(current.underlying_quote?.received_at ?? "");
  const bboAge = now - Date.parse(current.contract_qualification?.selected?.snapshot?.bbo_received_at ?? "");
  return Date.parse(current.valid_until) > now && Date.parse(row.deadline_at) > now
    && Date.parse(current.checked_at) <= now && age >= 0 && age <= 3000 && bboAge >= 0 && bboAge <= 3000;
}

export function trendReferenceContract(row: Row): Row | null {
  const selected = row.current_eligibility?.reference_contract;
  if (!selected || typeof selected.contract_id !== "string" || !selected.contract_id
    || selected.underlying !== row.symbol || selected.right !== row.right
    || !["CALL", "PUT"].includes(selected.right)
    || typeof selected.strike !== "number" || !Number.isFinite(selected.strike) || selected.strike <= 0
    || typeof selected.expiry_date !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(selected.expiry_date)) return null;
  const expiry = new Date(`${selected.expiry_date}T00:00:00Z`);
  if (!Number.isFinite(expiry.getTime()) || expiry.toISOString().slice(0, 10) !== selected.expiry_date) return null;
  return selected;
}

export function displayedEligibilityState(row: Row, now: number, connected: boolean): string {
  const state = row.current_eligibility?.state ?? "PENDING";
  if (["EXPIRED", "WITHDRAWN", "REJECTED"].includes(state)) return state;
  if (Date.parse(row.deadline_at) <= now) return "EXPIRED";
  if (!connected || (state === "QUALIFIED" && !currentEligibilityValid(row, now))) {
    return "CURRENT_ELIGIBILITY_UNCONFIRMED";
  }
  return state;
}
