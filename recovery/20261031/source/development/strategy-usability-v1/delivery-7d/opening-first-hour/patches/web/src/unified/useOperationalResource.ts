import { useEffect, useRef, useState } from "react";
import { publishedSnapshotResource } from "./snapshotRefreshPolicy";
import type { RecordData } from "./operationalData";
import { coalescedRefresh, operationEventMatches, needsSnapshotFallback, operationsStreamConnected, snapshotNeedsRecovery, snapshotReadyResetsBackoff, snapshotReadyMatches } from "./operationsStream";

export type Resource = { path: string; data?: RecordData; loading: boolean; error?: string; receivedAt?: string; requestedAt?: number };

export function useOperationalResource(path: string | null, refresh: number, poll = false): Resource {
  const [resource, setResource] = useState<Resource>({ path: "", loading: true });
  const reload = useRef<() => void>(() => {});
  const lastRefresh = useRef(refresh);
  useEffect(() => {
    if (!path) return;
    let alive = true;
    let inFlight = false;
    let rerun = false;
    let retryAfter = 0;
    let snapshotDegraded = false;
    let lastStatus: number | undefined;
    let controller: AbortController | null = null;
    const run = async () => {
      if (!alive || Date.now() < retryAfter) return;
      if (inFlight) { rerun = true; return; }
      inFlight = true;
      const requestedAt = Date.now();
      controller = new AbortController();
      const signal = controller.signal;
      const timeout = window.setTimeout(() => controller?.abort(), 12000);
      setResource(old => ({ ...(old.path === path ? old : {}), path, loading: true, error: undefined }));
      try {
        lastStatus = undefined;
        const response = await fetch(path, { credentials: "same-origin", cache: "no-store", signal });
        lastStatus = response.status;
        if (response.status === 429) retryAfter = Date.now() + 60000;
        if (!response.ok) throw new Error(`HTTP_${response.status}`);
        const data = await response.json();
        if (["UNAVAILABLE", "ERROR", "NOT_INITIALIZED"].includes(data.status)) throw new Error(data.status);
        snapshotDegraded = snapshotNeedsRecovery(data.snapshot, data.checkpoint_coverage);
        if (alive) setResource({ path, data, loading: false, receivedAt: new Date().toISOString(), requestedAt });
      } catch (error) {
        snapshotDegraded = true;
        retryAfter = Math.max(retryAfter, Date.now() + 15000);
        if (alive) setResource(old => ({ ...old, path, loading: false, error: error instanceof Error ? error.message : "REQUEST_FAILED" }));
      } finally {
        window.clearTimeout(timeout); inFlight = false;
        if (rerun && alive) { rerun = false; if (!document.hidden) void run(); }
      }
    };
    reload.current = () => { void run(); };
    void run();
    const visible = () => { if (!document.hidden) void run(); };
    const eventRefresh = coalescedRefresh(visible);
    const operationUpdate = () => {
      if (!document.hidden && !publishedSnapshotResource(path) && operationEventMatches(path)) eventRefresh.request();
    };
    const snapshotReady = (event: Event) => {
      const readyPath = (event as CustomEvent<{ path?: string }>).detail?.path;
      if (document.hidden || !snapshotReadyMatches(path, readyPath)) return;
      if (snapshotReadyResetsBackoff(path, readyPath, lastStatus, document.hidden)) retryAfter = 0;
      eventRefresh.request();
    };
    const timer = poll ? window.setInterval(() => {
      if (needsSnapshotFallback(document.hidden, operationsStreamConnected(), snapshotDegraded)) void run();
    }, 15000) : undefined;
    if (poll) document.addEventListener("visibilitychange", visible);
    if (poll) window.addEventListener("kquant:operations-update", operationUpdate);
    if (poll) window.addEventListener("kquant:operations-connected", visible);
    if (poll) window.addEventListener("kquant:snapshot-ready", snapshotReady);
    return () => {
      alive = false; controller?.abort(); window.clearInterval(timer); eventRefresh.cancel();
      document.removeEventListener("visibilitychange", visible); reload.current = () => {};
      window.removeEventListener("kquant:operations-update", operationUpdate);
      window.removeEventListener("kquant:operations-connected", visible);
      window.removeEventListener("kquant:snapshot-ready", snapshotReady);
    };
  }, [path, poll]);
  useEffect(() => {
    if (lastRefresh.current === refresh) return;
    lastRefresh.current = refresh;
    reload.current();
  }, [refresh]);
  return resource.path === path ? resource : { path: path ?? "", loading: true };
}
