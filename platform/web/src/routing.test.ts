import { describe, expect, it } from "vitest";
import { buildWorkspaceUrl, workspaceMode } from "./routing";

describe("unified platform routing", () => {
  it("deep-links stock workspaces without mixing the crypto backend", () => {
    expect(buildWorkspaceUrl("http://stocks/", "stocks", "charts")).toBe("http://stocks/?workspace=charts&platform=unified");
  });

  it("keeps crypto and roll desk on the crypto backend", () => {
    expect(workspaceMode("rollDesk", "stocks")).toBe("crypto");
    expect(buildWorkspaceUrl("http://crypto/", "crypto", "rollDesk")).toBe("http://crypto/");
  });
});
