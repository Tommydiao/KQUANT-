import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import App from "./App";

describe("KQUANT CRYPTO foundation", () => {
  beforeEach(() => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, json: async () => ({ authenticated: false, configured: false }) }));
  });

  it("waits for a local session before showing the research terminal", async () => {
    render(<App />);
    expect(await screen.findByText("加密资产研究终端")).toBeTruthy();
    expect(screen.queryByText("EVAL Agent")).toBeNull();
  });
});
