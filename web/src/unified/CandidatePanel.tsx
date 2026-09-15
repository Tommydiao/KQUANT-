import { useEffect, useState } from "react";
import { candidateStateText, formatUiNumber, formatUiTime, useI18n } from "./i18n";

type Data = Record<string, any>;

export default function CandidatePanel() {
  const { language, t } = useI18n();
  const label = (value: unknown) => candidateStateText(value, language);
  const number = (value: unknown) => typeof value === "number" && Number.isFinite(value) ? formatUiNumber(value, language, 2) : t("No data");
  const time = (value: unknown) => typeof value === "number" && Number.isFinite(value) ? formatUiTime(value, language, "Asia/Shanghai", "UTC+8") : t("No data");
  const [snapshot, setSnapshot] = useState<Data | null>(null);
  const [report, setReport] = useState<Data>({});
  const [trades, setTrades] = useState<Data>({});
  const [error, setError] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    async function get(path: string) {
      const response = await fetch(`/api/crypto/candidate-simulation/${path}`, { credentials: "same-origin", cache: "no-store", signal: controller.signal });
      if (!response.ok) throw new Error(t("Candidate evidence is unavailable; displayed data may be stale"));
      return response.json();
    }
    async function refresh() {
      try {
        const current = await get("status");
        if (controller.signal.aborted) return;
        setSnapshot(current);
        setReport({});
        setTrades({});
        const results = await Promise.allSettled([
          current.historical_report_run_id ? get(`report?run_id=${encodeURIComponent(current.historical_report_run_id)}`) : Promise.resolve({}),
          current.run_id ? get(`trades?run_id=${encodeURIComponent(current.run_id)}`) : Promise.resolve({}),
        ]);
        if (controller.signal.aborted) return;
        if (results[0].status === "fulfilled") setReport(results[0].value);
        if (results[1].status === "fulfilled") setTrades(results[1].value);
        setError(results.some(result => result.status === "rejected") ? t("Some candidate evidence is unavailable") : "");
      } catch {
        if (!controller.signal.aborted) setError(t("Candidate evidence is unavailable; displayed data may be stale"));
      } finally {
        if (!controller.signal.aborted) timer = setTimeout(refresh, 30000);
      }
    }
    void refresh();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [language, t]);
  const state = snapshot?.state ?? {};
  const metrics = report.metrics ?? {};
  const evidence = metrics.independent_evidence_status ?? "PERFORMANCE_UNPROVEN";
  const numericEvidence = metrics.gates?.status ?? metrics.performance_status ?? "PENDING";
  const decisions: [string, Data][] = Object.entries(state.decisions ?? {});
  const positions: [string, Data][] = Object.entries(state.positions ?? {});
  return <section className="work-surface compact-surface" aria-label={t("Candidate simulation")} style={{ minWidth: 0, overflowWrap: "anywhere" }}>
    <div className="surface-head"><h3>{t("Candidate simulation")}</h3><span>{snapshot ? `${t("Ledger status")}: ${label(snapshot.status)}` : t("Loading")}</span></div>
    {snapshot?.run_id ? <p role="status">{t("Process status is not verified. The values below are persisted candidate-ledger records, not the live Hybrid observer status.")}</p> : null}
    {error ? <p role="status">{error}</p> : null}
    <p>{t("Forward candidate, simulated fills, no orders")}</p>
    {snapshot?.run_id ? <>
      <p>{t("Simulated cash")} {number(state.cash)} USDT · {t("Net equity")} {state.unable_to_value || error ? t("Unknown") : number(state.equity)} · {t("Net P&L")} {state.unable_to_value || error ? t("Unknown") : number(state.net_pnl)} · {t("Positions")} {positions.length}</p>
      {state.unable_to_value ? <p>{t("Unable to value")} · {t("Quotes are stale or disconnected")}: {(state.stale_quote_symbols ?? []).join(", ") || t("Insufficient valuation data")} · {t("Last known equity")} {number(state.last_known_equity)}</p> : null}
      {state.day_paused || state.pause_until || snapshot.stop_requested ? <p>{t("Entries paused")}: {state.day_paused ? t("Daily risk control") : ""} {state.pause_until ? `${t("Cooldown until")} ${time(state.pause_until)}` : ""} {snapshot.stop_requested ? t("Stop requested") : ""}</p> : null}
      <p>{t("Ledger updated, China time")}: {time(snapshot.updated_at)} · {label(state.forward?.reason)}</p>
      {decisions.map(([symbol, decision]) => <div key={symbol} style={{ marginBottom: 12 }}>
        <strong>{symbol} · {label(decision.mode)}</strong>
        <p>{t("Last closed 5m")}: {time(typeof state.last_bars?.[symbol] === "number" ? state.last_bars[symbol] + 300 : null)} · 1H: {time(state.last_hours?.[symbol])}</p>
        <p>{t("Current reason")}: {(decision.reason_codes ?? []).map(label).join(", ") || t("No data")}</p>
        {decision.signal ? <p>{t("Entry reference")} {number(decision.signal.entry_reference)} · {t("Stop")} {number(decision.signal.stop)} · {t("Take profit")} {number(decision.signal.target)} · {t("Estimated net RR")} {number(decision.signal.expected_net_rr)}</p> : null}
      </div>)}
      {!decisions.length ? <p>{t("Current mode and no-trade reason: waiting for closed data")}</p> : null}
      {positions.map(([symbol, position]) => <p key={symbol}>{symbol} · {label(position.mode)} · {t("Simulated quantity")} {number(position.quantity)} · {t("Entry")} {number(position.entry_price)}</p>)}
      <details><summary>{t("Forward trades and data evidence")}</summary><p>{t("Forward run")} {snapshot.run_id} · {t("Recent trades")} {trades.items?.length ?? 0} / {trades.total ?? 0}</p><pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere", maxHeight: 360, overflow: "auto", fontSize: 12 }}>{JSON.stringify({ metadata: snapshot.metadata, trades: trades.items ?? [] }, null, 2)}</pre></details>
    </> : <p>{snapshot ? t("No forward candidate run") : t("Loading candidate status")}</p>}
    <h4>{t("Development history, frozen BASE replay")}</h4>
    <p>{t("Numeric target")}: {label(numericEvidence)} ({numericEvidence}) · {t("Independent evidence")}: {label(evidence)} ({evidence})</p>
    {snapshot?.historical_report_run_id ? <>
      <div style={{ overflowX: "auto" }}><table style={{ width: "100%", minWidth: 360 }}><caption>{t("Development history performance by mode")}</caption><thead><tr><th>{t("Mode")}</th><th>{t("Samples")}</th><th>{t("Net payoff")}</th><th>{t("Net PF")}</th><th>{t("Average net R")}</th></tr></thead><tbody>{["UP_TREND", "RANGE"].map(mode => {
        const row = metrics.by_mode?.[mode] ?? {};
        return <tr key={mode}><td>{label(mode)}</td><td>{number(row.sample_count)}</td><td>{number(row.payoff)}</td><td>{number(row.profit_factor)}</td><td>{number(row.expectancy_r)}</td></tr>;
      })}</tbody></table></div>
      <details><summary>{t("Development history performance evidence")}</summary><p>{t("Historical run")} {snapshot.historical_report_run_id} · {t("Report time")} {time(report.report_updated_at)}</p><pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere", maxHeight: 360, overflow: "auto", fontSize: 12 }}>{JSON.stringify(report.metrics ?? { status: t("Report not generated") }, null, 2)}</pre></details>
    </> : <p>{t("No valid frozen selection; no historical report is linked")}</p>}
  </section>;
}
