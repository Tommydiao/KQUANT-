// These routes publish their own business-watermark updates through SSE.
// Generic worker progress must not duplicate the same snapshot request.
export function publishedSnapshotResource(path: string): boolean {
  const [route, query = ""] = path.split("?", 2);
  const params = new URLSearchParams(query);
  const strategy = params.get("research_strategy");
  if (strategy !== "opening_momentum" && strategy !== "opening_trend") return false;
  return route === "/api/options/opening-trend/current" ||
    route === "/api/options/one-minute/status" && params.get("compact") === "true";
}
