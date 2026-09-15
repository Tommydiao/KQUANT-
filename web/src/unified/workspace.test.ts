import { describe, expect, it } from "vitest";
import { canonicalWorkspaceUrl, symbolFromSearch, viewFromSearch, workspaceFromSearch, workspaceSearchPlaceholder } from "./workspace";

describe("unified workspace routing", () => {
  it("maps legacy stock and crypto links into the shared information architecture", () => {
    expect(workspaceFromSearch("?market=crypto&view=journal")).toBe("crypto");
    expect(viewFromSearch("?market=crypto&view=journal", "crypto")).toBe("review");
    expect(viewFromSearch("?workspace=stocks&view=discover", "stocks")).toBe("opportunities");
  });

  it("keeps old options links useful and defaults them to the opportunity list", () => {
    expect(workspaceFromSearch("?workspace=options")).toBe("options");
    expect(viewFromSearch("?workspace=options", "options")).toBe("opportunities");
    expect(symbolFromSearch("?workspace=options&symbol=amd", "options")).toBe("AMD");
  });

  it("writes one canonical URL without mixing market and workspace parameters", () => {
    const result = canonicalWorkspaceUrl(
      "http://127.0.0.1:8020/?market=stocks&view=discover&opportunity=old",
      "crypto",
      "opportunities",
      "ETHUSDT",
    );
    expect(result).toBe("/?view=opportunities&workspace=crypto&symbol=ETHUSDT");
  });

  it("localizes each workspace search prompt", () => {
    expect(workspaceSearchPlaceholder("stocks", "zh")).toContain("股票");
    expect(workspaceSearchPlaceholder("options", "en")).toBe("Search an underlying or option contract");
    expect(workspaceSearchPlaceholder("crypto", "en")).toContain("BTC");
  });
});
