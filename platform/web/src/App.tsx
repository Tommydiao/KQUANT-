import { useEffect, useMemo, useState } from "react";
import {
  BarChart3, Bitcoin, BookOpenCheck, Bot, ExternalLink, HeartPulse,
  LayoutDashboard, RefreshCw, Search, Settings, TrendingUp, WalletCards,
} from "lucide-react";
import { buildWorkspaceUrl, workspaceMode, type PlatformMode, type Workspace } from "./routing";

type BackendHealth = { status?: string; build_sha?: string; app_version?: string };
type PlatformSummary = {
  status?: string;
  build_sha?: string;
  modes?: Array<{ id: PlatformMode; label: string; url: string; health?: BackendHealth }>;
  research_only?: boolean;
  order_submission?: boolean;
};

const NAV_ITEMS: Array<{ id: Workspace; label: string; icon: typeof LayoutDashboard }> = [
  { id: "today", label: "Today", icon: LayoutDashboard },
  { id: "search", label: "Search", icon: Search },
  { id: "stocks", label: "Stocks", icon: TrendingUp },
  { id: "crypto", label: "Crypto", icon: Bitcoin },
  { id: "charts", label: "Charts", icon: BarChart3 },
  { id: "aiPlan", label: "AI Plan", icon: Bot },
  { id: "rollDesk", label: "Roll Desk", icon: WalletCards },
  { id: "journal", label: "Journal", icon: BookOpenCheck },
  { id: "settings", label: "Settings", icon: Settings },
];

const FALLBACK_URLS: Record<PlatformMode, string> = { stocks: "http://127.0.0.1:8001", crypto: "http://127.0.0.1:8010" };

function healthTone(status?: string) {
  return status === "available" ? "ok" : status ? "warn" : "muted";
}

export default function App() {
  const [summary, setSummary] = useState<PlatformSummary>({});
  const [mode, setMode] = useState<PlatformMode>("stocks");
  const [workspace, setWorkspace] = useState<Workspace>("today");
  const [refreshKey, setRefreshKey] = useState(0);
  const [loading, setLoading] = useState(true);

  async function refreshHealth() {
    setLoading(true);
    try {
      const response = await fetch("/api/platform/summary", { cache: "no-store" });
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      setSummary(await response.json());
    } catch {
      setSummary({ status: "unavailable", build_sha: "unknown", research_only: true, order_submission: false });
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    void refreshHealth();
    const timer = window.setInterval(refreshHealth, 15_000);
    return () => window.clearInterval(timer);
  }, []);

  const modeInfo = summary.modes?.find((item) => item.id === mode);
  const baseUrl = modeInfo?.url ?? FALLBACK_URLS[mode];
  const workspaceUrl = useMemo(
    () => buildWorkspaceUrl(baseUrl, mode, workspace),
    [baseUrl, mode, workspace, refreshKey],
  );

  function openWorkspace(next: Workspace) {
    const nextMode = workspaceMode(next, mode);
    setMode(nextMode);
    setWorkspace(next);
  }

  function switchMode(next: PlatformMode) {
    setMode(next);
    setWorkspace(next === "stocks" ? "today" : "crypto");
  }

  return (
    <div className="platform-shell">
      <header className="topbar">
        <div className="brand"><span className="brand-mark">KQ</span><div><strong>KQUANT</strong><small>Unified quantitative research</small></div></div>
        <div className="mode-switch" aria-label="Asset mode">
          <button className={mode === "stocks" ? "active" : ""} onClick={() => switchMode("stocks")}>Stocks</button>
          <button className={mode === "crypto" ? "active" : ""} onClick={() => switchMode("crypto")}>Crypto</button>
        </div>
        <div className="system-status"><span className={`status-dot ${healthTone(modeInfo?.health?.status)}`} /><span>{modeInfo?.health?.status ?? (loading ? "checking" : "offline")}</span><span className="sha">{summary.build_sha?.slice(0, 8) ?? "unknown"}</span></div>
      </header>

      <aside className="sidebar">
        <nav aria-label="Platform navigation">
          {NAV_ITEMS.map(({ id, label, icon: Icon }) => (
            <button key={id} className={workspace === id ? "active" : ""} onClick={() => openWorkspace(id)} title={label}><Icon size={18} aria-hidden="true" /><span>{label}</span></button>
          ))}
        </nav>
        <div className="sidebar-foot"><span><HeartPulse size={16} /> Research only</span><small>No account, wallet, or order access</small></div>
      </aside>

      <main className="workspace">
        <div className="workspace-head">
          <div><span className="eyebrow">{mode}</span><h1>{NAV_ITEMS.find((item) => item.id === workspace)?.label}</h1></div>
          <div className="workspace-actions"><button onClick={() => setRefreshKey((value) => value + 1)} title="Reload workspace"><RefreshCw size={17} /></button><a href={workspaceUrl} target="_blank" rel="noreferrer" title="Open standalone"><ExternalLink size={17} /></a></div>
        </div>
        <section className="backend-frame" aria-label={`${mode} research workspace`}><iframe key={`${workspaceUrl}-${refreshKey}`} src={workspaceUrl} title={`${mode} ${workspace}`} /></section>
      </main>
    </div>
  );
}
