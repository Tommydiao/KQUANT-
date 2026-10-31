export type ManualReportPayload = Readonly<Record<string, string | number | null | undefined>>;
export type ManualReportPath = "/api/options/one-minute/manual/entries" | "/api/options/one-minute/manual/exits";

const rejectionCodes = new Set([
  "IDEMPOTENCY_KEY_CONFLICT", "IDEMPOTENCY_KEY_REQUIRED", "IDEMPOTENCY_OR_POSITION_INVALID",
  "CONTRACT_OR_QUANTITY_INVALID", "MULTIPLIER_OR_PREMIUM_INVALID", "UNDERLYING_REFERENCE_INVALID",
  "ENTRY_FEES_INVALID", "EXIT_FEE_ESTIMATE_INVALID", "EXIT_FEES_INVALID", "FUTURE_EXECUTION_TIME",
  "ONE_MINUTE_EVALUATION_NOT_FOUND", "STRATEGY_VERSION_MISMATCH", "POSITION_POLICY_HASH_MISMATCH",
  "REPORTED_CONTRACT_DIFFERS_FROM_SIGNAL", "REPORTED_CONTRACT_IDENTITY_UNVERIFIED",
  "REPORTED_CONTRACT_IDENTITY_MISMATCH", "POSITION_NOT_FOUND", "EXIT_QUANTITY_OR_PRICE_INVALID",
  "EXIT_EXCEEDS_REPORTED_OPEN_QUANTITY", "EXIT_BEFORE_REPORTED_ENTRY",
]);

export class ManualReportError extends Error {
  constructor(readonly code: string, readonly uncertain: boolean) {
    super(code);
    this.name = "ManualReportError";
  }
}

export async function reconcileManualReport(payload: ManualReportPayload,
  fetcher: typeof fetch = fetch, timeoutMs = 3000): Promise<Record<string, unknown> | null> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetcher(`/api/options/one-minute/manual?operation_key=${encodeURIComponent(String(payload.operation_key))}`,
      { credentials: "same-origin", signal: controller.signal });
    if (response.status === 401 || response.status === 403) throw new ManualReportError("SIGN_IN_REQUIRED", false);
    if (!response.ok) throw new ManualReportError("REPORT_OUTCOME_UNKNOWN", true);
    const result = await response.json();
    if (result.operation_key !== payload.operation_key) throw new ManualReportError("REPORT_ACKNOWLEDGEMENT_INVALID", true);
    if (result.operation_status === "NOT_FOUND") return null;
    if (result.operation_status === "COMMITTED" && result.report?.operation_key === payload.operation_key
        && typeof result.report.position_id === "string") return result.report;
    throw new ManualReportError("REPORT_OUTCOME_UNKNOWN", true);
  } catch (cause) {
    if (cause instanceof ManualReportError) throw cause;
    throw new ManualReportError("REPORT_OUTCOME_UNKNOWN", true);
  } finally { clearTimeout(timeout); }
}

export async function sendManualReport(path: ManualReportPath, payload: ManualReportPayload,
  fetcher: typeof fetch = fetch, timeoutMs = 10000): Promise<Record<string, unknown>> {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const response = await fetcher(path, { method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload), signal: controller.signal });
    if (response.status === 401 || response.status === 403) throw new ManualReportError("SIGN_IN_REQUIRED", false);
    if (!response.ok) {
      const body = await response.json().catch(() => null);
      const code = [400, 409].includes(response.status) && typeof body?.detail === "string" && rejectionCodes.has(body.detail)
        ? body.detail : "REPORT_OUTCOME_UNKNOWN";
      throw new ManualReportError(code, code === "REPORT_OUTCOME_UNKNOWN");
    }
    const report = await response.json();
    if (!report || report.operation_key !== payload.operation_key || typeof report.position_id !== "string") {
      throw new ManualReportError("REPORT_ACKNOWLEDGEMENT_INVALID", true);
    }
    return report;
  } catch (cause) {
    if (cause instanceof ManualReportError) throw cause;
    // A failed response does not prove that the server rolled back the report.
    throw new ManualReportError("REPORT_OUTCOME_UNKNOWN", true);
  } finally {
    clearTimeout(timeout);
  }
}
