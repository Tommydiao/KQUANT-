let connected = false;
let connectedAt = 0;
const listeners = new Set<() => void>();

export function operationEventMatches(path: string) {
  return path.startsWith("/api/options/");
}

export function coalescedRefresh(run: () => void, delay = 500) {
  let timer: ReturnType<typeof setTimeout> | undefined;
  return {
    request() {
      if (timer !== undefined) return;
      timer = setTimeout(() => { timer = undefined; run(); }, delay);
    },
    cancel() { clearTimeout(timer); timer = undefined; },
  };
}

export const operationsStreamConnected = () => connected;
export const operationsStreamConnectedAt = () => connectedAt;
export const operationsStreamServerSnapshot = () => false;
export function subscribeOperationsStream(listener: () => void) {
  listeners.add(listener);
  return () => { listeners.delete(listener); };
}
export function setOperationsStreamConnected(value: boolean) {
  if (connected === value) return;
  connected = value;
  if (value) connectedAt = Date.now();
  listeners.forEach(listener => listener());
}

export function snapshotNeedsRecovery(snapshot: unknown, coverage?: unknown): boolean {
  if (coverage && typeof coverage === "object" && !Array.isArray(coverage)
      && (coverage as { state?: unknown }).state === "UNAVAILABLE") return true;
  if (!snapshot || typeof snapshot !== "object" || Array.isArray(snapshot)) return false;
  const state = snapshot as { state?: unknown; refresh_pending?: unknown };
  return state.state === "STALE" || state.refresh_pending === true;
}

export function needsSnapshotFallback(hidden: boolean, streamConnected: boolean, snapshotDegraded = false) {
  return !hidden && (!streamConnected || snapshotDegraded);
}

export function snapshotReadyResetsBackoff(path: string, readyPath: unknown, status: number | undefined, hidden: boolean) {
  return !hidden && snapshotReadyMatches(path, readyPath) && status === 503;
}

export function snapshotReadyMatches(path: string, readyPath: unknown) {
  if (path === readyPath) return true;
  return ["opening_trend", "opening_momentum"].some(strategy => {
    const route = `/api/options/one-minute/status?research_strategy=${strategy}`;
    return (path === `${route}&compact=true` || path === `/api/options/opening-trend/current?research_strategy=${strategy}`) && readyPath === route;
  });
}
