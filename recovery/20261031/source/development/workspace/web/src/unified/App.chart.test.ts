import { describe, expect, it } from "vitest";
import { extractCandles, workspaceServiceLabel } from "./App";

describe("unified chart data contract", () => {
  it("prefers the ISO candle open time over the numeric provider timestamp", () => {
    const rows = extractCandles({
      candles: [{
        open_time: "2026-09-18T04:00:00+00:00",
        time: 1789704000,
        open: 176,
        high: 178,
        low: 175,
        close: 177,
        volume: 100,
      }],
    });

    expect(rows).toHaveLength(1);
    expect(rows[0].time).toBe("2026-09-18T04:00:00+00:00");
  });
});

describe("workspace service scope", () => {
  it("labels gateway liveness without claiming research or quote readiness", () => {
    expect(workspaceServiceLabel("options", "online")).toBe("Web service online");
    expect(workspaceServiceLabel("options", "unavailable")).toBe("Web service unavailable");
    expect(workspaceServiceLabel("options", "")).toBe("Checking web service");
    expect(workspaceServiceLabel("options", "stale")).toBe("Web service unavailable");
  });

  it("does not substitute SSE connectivity for backend health", () => {
    expect(workspaceServiceLabel("options", "error")).not.toBe("Alerts online");
    expect(workspaceServiceLabel("stocks", "online")).toBe("Service ready");
    expect(workspaceServiceLabel("crypto", "unavailable")).toBe("Service unavailable");
    expect(workspaceServiceLabel("stocks", "")).toBe("Connecting");
  });
});
