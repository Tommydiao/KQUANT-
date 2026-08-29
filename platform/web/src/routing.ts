export type PlatformMode = "stocks" | "crypto";
export type Workspace = "today" | "search" | "stocks" | "crypto" | "charts" | "aiPlan" | "rollDesk" | "journal" | "settings";

const STOCK_WORKSPACES: Partial<Record<Workspace, string>> = {
  today: "today",
  search: "search",
  stocks: "stock",
  charts: "charts",
  aiPlan: "aiPlan",
  journal: "journal",
  settings: "settings",
};

export function workspaceMode(workspace: Workspace, current: PlatformMode): PlatformMode {
  if (workspace === "crypto" || workspace === "rollDesk") return "crypto";
  if (workspace === "stocks") return "stocks";
  return current;
}

export function buildWorkspaceUrl(baseUrl: string, mode: PlatformMode, workspace: Workspace): string {
  const base = baseUrl.replace(/\/$/, "");
  if (mode === "crypto") return `${base}/`;
  const target = STOCK_WORKSPACES[workspace] ?? "today";
  return `${base}/?workspace=${encodeURIComponent(target)}&platform=unified`;
}
