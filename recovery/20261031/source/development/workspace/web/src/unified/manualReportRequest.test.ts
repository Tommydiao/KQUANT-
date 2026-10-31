import { describe, expect, it, vi } from "vitest";
import { ManualReportError, reconcileManualReport, sendManualReport } from "./manualReportRequest";

const path = "/api/options/one-minute/manual/entries";
const payload = { operation_key: "stable-operation", contract_id: "NVDA261002C100000.US", quantity: 2 };
const response = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status });

describe("manual report acknowledgement", () => {
  it("reconciles an acknowledged operation without writing", async () => {
    const report = { operation_key: payload.operation_key, position_id: "position" };
    const fetcher = vi.fn().mockResolvedValue(response({ operation_key: payload.operation_key, operation_status: "COMMITTED", report }));
    await expect(reconcileManualReport(payload, fetcher)).resolves.toEqual(report);
    expect(fetcher.mock.calls[0][1].method).toBeUndefined();
  });
  it("does not treat an unavailable lookup as not committed", async () => {
    await expect(reconcileManualReport(payload, vi.fn().mockResolvedValue(response({}, 503))))
      .rejects.toMatchObject({ uncertain: true });
  });
  it("distinguishes a successful not-found lookup", async () => {
    await expect(reconcileManualReport(payload, vi.fn().mockResolvedValue(response({
      operation_key: payload.operation_key, operation_status: "NOT_FOUND" })))) .resolves.toBeNull();
  });
  it("requires a matching operation acknowledgement and uses authenticated local requests", async () => {
    const fetcher = vi.fn().mockResolvedValue(response({ operation_key: payload.operation_key, position_id: "position" }));
    await expect(sendManualReport(path, payload, fetcher)).resolves.toHaveProperty("position_id", "position");
    expect(fetcher.mock.calls[0][1]).toMatchObject({ credentials: "same-origin", method: "POST", body: JSON.stringify(payload) });
  });
  it.each([401, 403])("keeps authentication rejection distinct from unknown outcome (%i)", async status => {
    const fetcher = vi.fn().mockResolvedValue(response({}, status));
    await expect(sendManualReport(path, payload, fetcher)).rejects.toMatchObject({ code: "SIGN_IN_REQUIRED", uncertain: false });
  });
  it.each(["IDEMPOTENCY_KEY_CONFLICT", "REPORTED_CONTRACT_IDENTITY_MISMATCH", "EXIT_EXCEEDS_REPORTED_OPEN_QUANTITY"])("reports a proven rejection without raw server text: %s", async detail => {
    await expect(sendManualReport(path, payload, vi.fn().mockResolvedValue(response({ detail }, 400))))
      .rejects.toMatchObject({ code: detail, uncertain: false });
  });
  it.each([400, 500, 503])("treats unrecognized failures as uncertain and does not expose detail (%i)", async status => {
    await expect(sendManualReport(path, payload, vi.fn().mockResolvedValue(response({ detail: "private server diagnostic" }, status))))
      .rejects.toMatchObject({ code: "REPORT_OUTCOME_UNKNOWN", uncertain: true });
  });
  it("does not treat a server error as proof of rejection even with a known code", async () => {
    await expect(sendManualReport(path, payload, vi.fn().mockResolvedValue(response({ detail: "IDEMPOTENCY_KEY_CONFLICT" }, 500))))
      .rejects.toMatchObject({ code: "REPORT_OUTCOME_UNKNOWN", uncertain: true });
  });
  it.each([{}, { operation_key: "other-operation", position_id: "p" }, { operation_key: payload.operation_key }])("rejects unmatched success evidence", async body => {
    await expect(sendManualReport(path, payload, vi.fn().mockResolvedValue(response(body))))
      .rejects.toMatchObject({ code: "REPORT_ACKNOWLEDGEMENT_INVALID", uncertain: true });
  });
  it("treats malformed success JSON as uncertain", async () => {
    await expect(sendManualReport(path, payload, vi.fn().mockResolvedValue(new Response("not-json"))))
      .rejects.toMatchObject({ uncertain: true });
  });
  it("does not generate a new key or retry automatically after a lost response", async () => {
    const fetcher = vi.fn().mockRejectedValueOnce(new TypeError("connection lost"))
      .mockResolvedValueOnce(response({ operation_key: payload.operation_key, position_id: "position" }));
    await expect(sendManualReport(path, payload, fetcher)).rejects.toBeInstanceOf(ManualReportError);
    expect(fetcher).toHaveBeenCalledTimes(1);
    await sendManualReport(path, payload, fetcher);
    expect(fetcher.mock.calls[0][1].body).toEqual(fetcher.mock.calls[1][1].body);
  });
  it("bounds a stalled request while preserving the unknown-outcome state", async () => {
    const fetcher = vi.fn((_input: RequestInfo | URL, init?: RequestInit) => new Promise<Response>((_resolve, reject) => {
      init?.signal?.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")));
    }));
    await expect(sendManualReport(path, payload, fetcher, 10)).rejects.toMatchObject({ uncertain: true });
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
});
