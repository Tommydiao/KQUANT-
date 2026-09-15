import { translate, type MessageKey, type UiLanguage } from "./i18n";

export type WorkspaceId = "stocks" | "options" | "crypto";
export type ViewName = "today" | "opportunities" | "chart" | "plans" | "review" | "settings";

export const DEFAULT_SYMBOL: Record<WorkspaceId, string> = {
  stocks: "NVDA",
  options: "NVDA",
  crypto: "BTCUSDT",
};

const WORKSPACE_ALIASES: Record<string, WorkspaceId> = {
  stock: "stocks",
  stocks: "stocks",
  equity: "stocks",
  equities: "stocks",
  option: "options",
  options: "options",
  crypto: "crypto",
};

const VIEW_ALIASES: Record<string, ViewName> = {
  today: "today",
  discover: "opportunities",
  discovery: "opportunities",
  opportunities: "opportunities",
  opportunity: "opportunities",
  chart: "chart",
  charts: "chart",
  plan: "plans",
  plans: "plans",
  research: "review",
  journal: "review",
  review: "review",
  settings: "settings",
  status: "settings",
};

export function workspaceFromSearch(search: string): WorkspaceId {
  const params = new URLSearchParams(search);
  const workspace = String(params.get("workspace") ?? "").toLowerCase();
  if (WORKSPACE_ALIASES[workspace]) return WORKSPACE_ALIASES[workspace];
  const market = String(params.get("market") ?? "").toLowerCase();
  return WORKSPACE_ALIASES[market] ?? "stocks";
}

export function viewFromSearch(search: string, workspace: WorkspaceId): ViewName {
  const params = new URLSearchParams(search);
  const raw = String(params.get("view") ?? "").toLowerCase();
  if (VIEW_ALIASES[raw]) return VIEW_ALIASES[raw];
  return workspace === "options" ? "opportunities" : "today";
}

export function symbolFromSearch(search: string, workspace: WorkspaceId): string {
  const params = new URLSearchParams(search);
  const raw = String(params.get("symbol") ?? "").trim().toUpperCase();
  return raw || DEFAULT_SYMBOL[workspace];
}

export function canonicalWorkspaceUrl(
  href: string,
  workspace: WorkspaceId,
  view: ViewName,
  symbol: string,
): string {
  const url = new URL(href);
  url.searchParams.delete("market");
  url.searchParams.set("workspace", workspace);
  url.searchParams.set("view", view);
  url.searchParams.set("symbol", symbol.toUpperCase());
  if (workspace !== "options") {
    url.searchParams.delete("opportunity");
    url.searchParams.delete("plan");
  }
  return `${url.pathname}${url.search}${url.hash}`;
}

export function workspaceLabel(workspace: WorkspaceId, language: UiLanguage = "zh"): string {
  const keys: Record<WorkspaceId, MessageKey> = { stocks: "Stocks", options: "Options", crypto: "Crypto" };
  return translate(language, keys[workspace]);
}

export function workspaceSearchPlaceholder(workspace: WorkspaceId, language: UiLanguage = "zh"): string {
  const keys: Record<WorkspaceId, MessageKey> = {
    stocks: "Search a stock, theme, or ticker",
    options: "Search an underlying or option contract",
    crypto: "Search BTC, ETH, SOL, or a token",
  };
  return translate(language, keys[workspace]);
}
