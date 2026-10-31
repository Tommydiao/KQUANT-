import { ArrowLeft, ArrowRight, ChevronDown, RefreshCw, Rows3 } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

type Row = Record<string, any>;
type Side = "call" | "put";
const hasField = (row: Row, key: string): boolean => Object.prototype.hasOwnProperty.call(row, key);

async function read(path: string, signal?: AbortSignal): Promise<Row> {
  const response = await fetch(path, { signal, credentials: "same-origin", cache: "no-store" });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  const body = await response.json();
  if (!body || typeof body !== "object" || Array.isArray(body)) throw new Error("Invalid response");
  return body;
}

export function referenceNumber(value: unknown, digits = 4): string {
  const parsed = Number(value);
  return value == null || value === "" || !Number.isFinite(parsed) ? "—" : parsed.toLocaleString(undefined, { maximumFractionDigits: digits });
}

function percent(value: unknown): string {
  const parsed = Number(value);
  return value == null || !Number.isFinite(parsed) ? "—" : `${(parsed * 100).toFixed(1)}%`;
}

function dte(expiry: string): number | null {
  const end = new Date(`${expiry}T12:00:00Z`).getTime();
  const today = new Intl.DateTimeFormat("en-CA", { timeZone: "America/New_York" }).format(new Date());
  const start = new Date(`${today}T12:00:00Z`);
  return Number.isFinite(end) ? Math.ceil((end - start.getTime()) / 86_400_000) : null;
}

export function mergeQuote(current: Row = {}, patch: Row): Row {
  const accepted = { ...patch };
  const fieldTimes = { ...current.field_times };
  const groups = [
    ["quote_received_at", ["last", "previous_close", "change", "change_pct", "volume", "turnover", "quote_time", "quote_received_at", "quote_request_started_at", "trade_status", "provider_status", "contract_validity"]],
    ["bbo_received_at", ["bid", "ask", "bid_size", "ask_size", "bbo_received_at", "bbo_event_time", "bid_event_time", "ask_event_time", "depth_status", "bbo_observed_at", "bbo_snapshot", "bbo_epoch", "bbo_sequence"]],
    ["calc_received_at", ["delta", "gamma", "theta", "vega", "rho", "calc_received_at", "greeks_status"]],
    ["oi_received_at", ["open_interest", "oi_received_at"]],
    ["iv_received_at", ["implied_volatility", "iv_received_at"]],
  ] as const;
  for (const [stamp, fields] of groups) {
    const oldTime = Date.parse(current[stamp === "bbo_received_at" ? "bbo_observed_at" : stamp] ?? current[stamp] ?? "");
    const newTime = Date.parse(patch[stamp === "bbo_received_at" ? "bbo_observed_at" : stamp] ?? patch[stamp] ?? "");
    const tradeOlder = stamp === "quote_received_at" && Date.parse(patch.quote_time ?? "") < Date.parse(current.quote_time ?? "");
    const seqOlder = stamp === "bbo_received_at" && patch.bbo_epoch != null && patch.bbo_epoch === current.bbo_epoch && patch.bbo_sequence <= current.bbo_sequence;
    if (tradeOlder || seqOlder || stamp === "bbo_received_at" && patch.depth_status === "not_requested" || Number.isFinite(oldTime) && Number.isFinite(newTime) && newTime < oldTime) {
      for (const field of fields) delete accepted[field];
    }
    for (const field of fields) {
      if (hasField(accepted, field) && !field.endsWith("_at")) {
        fieldTimes[field] = patch.field_times?.[field] ?? { received_at: patch[stamp] ?? null, native_at: stamp === "quote_received_at" ? patch.quote_time ?? null : null };
      }
    }
  }
  const hasBid = hasField(accepted, "bid");
  const hasAsk = hasField(accepted, "ask");
  const explicitInvalidation = accepted.depth_status === "unavailable" || accepted.depth_status === "non_trading";
  const completeBook = hasBid && hasAsk && accepted.bid != null && accepted.ask != null && accepted.bid >= 0 && accepted.ask >= accepted.bid;
  // A heartbeat or sizes-only update cannot renew the receipt time of retained prices.
  if (!completeBook && !explicitInvalidation) {
    delete accepted.bbo_received_at;
    delete accepted.bbo_event_time;
    for (const key of ["bid_size", "ask_size"]) {
      if (hasField(accepted, key)) fieldTimes[key] = patch.field_times?.[key] ?? { received_at: patch.bbo_observed_at ?? patch.bbo_received_at ?? null, native_at: null };
    }
  }
  delete accepted.field_times;
  const next: Row = { ...current, ...accepted };
  // A book packet is atomic. Never make an old ask and a new bid look like one BBO.
  const touchesBook = hasBid || hasAsk || explicitInvalidation;
  const tradeState = String(next.trade_status ?? "").split(".").pop()?.toUpperCase();
  const validityState = String(next.contract_validity ?? "").toUpperCase();
  const invalidTrade = ["EXPIRED", "HALTED", "SUSPEND", "SUSPENDED", "EXPIRY_SESSION_ENDED"].includes(tradeState ?? "") ||
    ["EXPIRED", "HALTED", "SUSPEND", "SUSPENDED", "EXPIRY_SESSION_ENDED"].includes(validityState);
  if (touchesBook || invalidTrade) {
    const paired = hasField(accepted, "bid") && hasField(accepted, "ask");
    const valid = paired && accepted.bid != null && accepted.ask != null && accepted.bid >= 0 && accepted.ask >= accepted.bid && accepted.depth_status !== "unavailable" && !invalidTrade;
    if (!valid) {
      if (current.bid != null || current.ask != null) next.last_known_bbo = Object.fromEntries(["bid", "ask", "bid_size", "ask_size", "bbo_received_at", "bbo_event_time"].map(key => [key, current[key] ?? null]));
      next.bid = next.ask = next.bid_size = next.ask_size = next.bbo_received_at = next.bbo_event_time = null;
      next.depth_status = invalidTrade ? "non_trading" : "unavailable";
      for (const key of ["bid", "ask", "bid_size", "ask_size"]) fieldTimes[key] = { received_at: null, native_at: null };
    }
  }
  if (Object.keys(fieldTimes).length) next.field_times = fieldTimes;
  if (next.last != null && next.previous_close != null) {
    next.change = next.last - next.previous_close;
    next.change_pct = next.previous_close > 0 ? next.change / next.previous_close * 100 : null;
  } else if (hasField(accepted, "last") || hasField(accepted, "previous_close")) {
    next.change = next.change_pct = null;
  }
  return next;
}

export default function OptionReferenceChain({ symbol, language, refreshNonce = 0 }: { symbol: string; language: string; refreshNonce?: number }) {
  const zh = language === "zh";
  const [expiries, setExpiries] = useState<string[]>([]);
  const [expiry, setExpiry] = useState("");
  const [chain, setChain] = useState<Row[]>([]);
  const [spot, setSpot] = useState<Row>({});
  const [snapshots, setSnapshots] = useState<Record<string, Row>>({});
  const [selectedContract, setSelectedContract] = useState("");
  const [standardOnly, setStandardOnly] = useState(true);
  const [showAll, setShowAll] = useState(false);
  const [page, setPage] = useState(0);
  const [streamState, setStreamState] = useState("connecting");
  const context = useRef("");
  context.current = `${symbol}|${expiry}`;
  const detailController = useRef<AbortController | null>(null);
  const [mobileSide, setMobileSide] = useState<Side>("call");
  const [loading, setLoading] = useState(true);
  const [depthLoading, setDepthLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setExpiries([]); setExpiry(""); setChain([]); setSnapshots({}); setSelectedContract(""); setError(""); setSpot({});
    read(`/api/options/expiries?symbol=${encodeURIComponent(symbol)}`, controller.signal).then(expiryBody => {
      if (controller.signal.aborted) return;
      const today = new Intl.DateTimeFormat("en-CA", { timeZone: "America/New_York" }).format(new Date());
      const dates = (expiryBody.eligible_expiries ?? expiryBody.expiries ?? []).filter((value: string) => value >= today);
      setExpiries(dates); setExpiry(dates[0] ?? "");
      if (!dates.length) setLoading(false);
    }).catch(reason => { if (!controller.signal.aborted) { setError(String(reason)); setLoading(false); } });
    read(`/api/stocks/quote?symbol=${encodeURIComponent(symbol)}`, controller.signal)
      .then(body => { if (!controller.signal.aborted) setSpot(body); })
      .catch(reason => { if (!controller.signal.aborted) setError(String(reason)); });
    return () => { controller.abort(); detailController.current?.abort(); };
  }, [symbol, refreshNonce]);

  useEffect(() => {
    if (!expiry) return;
    const controller = new AbortController();
    setLoading(true); setChain([]); setSnapshots({}); setSelectedContract(""); setError(""); setPage(0);
    detailController.current?.abort();
    read(`/api/options/chain?symbol=${encodeURIComponent(symbol)}&expiry=${encodeURIComponent(expiry)}`, controller.signal)
      .then(body => { if (!controller.signal.aborted) setChain(Array.isArray(body.contracts) ? body.contracts : []); })
      .catch(reason => { if (!controller.signal.aborted) setError(String(reason)); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [symbol, expiry]);

  const spotPrice = Number(spot.display_last ?? spot.last);
  const visibleRows = useMemo(() => {
    const eligible = chain.filter(row => !standardOnly || row.is_standard !== false);
    if (showAll) return [...eligible].sort((a, b) => Number(a.strike_price) - Number(b.strike_price)).slice(page * 21, (page + 1) * 21);
    if (eligible.length <= 21) return [...eligible].sort((a, b) => Number(a.strike_price) - Number(b.strike_price));
    if (!Number.isFinite(spotPrice) || spotPrice <= 0) return eligible.slice(0, 21).sort((a, b) => Number(a.strike_price) - Number(b.strike_price));
    return [...eligible].sort((a, b) => Math.abs(Number(a.strike_price) - spotPrice) - Math.abs(Number(b.strike_price) - spotPrice)).slice(0, 21).sort((a, b) => Number(a.strike_price) - Number(b.strike_price));
  }, [chain, showAll, spotPrice, standardOnly, page]);

  const visibleContracts = useMemo(() => visibleRows.flatMap(row => [row.call_symbol, row.put_symbol]).filter(Boolean), [visibleRows]);

  useEffect(() => {
    if (!visibleContracts.length) return;
    const controller = new AbortController();
    const query = visibleContracts.map(value => encodeURIComponent(String(value))).join(",");
    setLoading(true);
    let inFlight = false;
    let connected = false;
    const snapshot = (greeksOnly = false) => {
      if (inFlight || controller.signal.aborted) return;
      inFlight = true;
      read(`/api/options/contracts/snapshots?contracts=${query}${greeksOnly ? "&greeks_only=true" : ""}`, controller.signal)
      .then(body => {
        if (controller.signal.aborted) return;
        setSnapshots(current => {
          const next = { ...current };
          for (const item of body.items ?? []) next[String(item.contract_symbol)] = mergeQuote(next[String(item.contract_symbol)], item);
          return next;
        });
      })
      .catch(reason => { if (!controller.signal.aborted) setError(String(reason)); })
      .finally(() => { inFlight = false; if (!controller.signal.aborted) setLoading(false); });
    };
    snapshot();
    const closed = spot.market_session === "closed" || spot.session === "closed" || spot.display_session === "closed_reference";
    let source: EventSource | null = null;
    let retryAt = 0;
    let retries = 0;
    setStreamState(closed ? "reference" : "connecting");
    const message = (event: Event) => {
      if (controller.signal.aborted) return;
      const body = JSON.parse((event as MessageEvent).data);
      if (body.kind === "underlying" && body.contract_symbol === `${symbol.replace(/\.US$/, "")}.US`) {
        setSpot(current => ({ ...current, ...(body.payload?.last != null ? { last: body.payload.last, display_last: body.payload.last } : {}), display_quote_time: body.payload?.quote_time ?? current.display_quote_time }));
        return;
      }
      if (!visibleContracts.includes(body.contract_symbol)) return;
      setSnapshots(current => ({ ...current, [body.contract_symbol]: mergeQuote(current[body.contract_symbol], body.payload ?? {}) }));
    };
    const offline = () => {
      connected = false; source?.close(); source = null;
      retryAt = Date.now() + Math.min(60000, 15000 * 2 ** retries++);
      if (!controller.signal.aborted) setStreamState("reconnecting");
    };
    const connect = () => {
      if (closed || source || controller.signal.aborted || retries >= 5 || Date.now() < retryAt) return;
      source = new EventSource(`/api/options/contracts/stream?contracts=${query}`);
      source.addEventListener("ready", () => { connected = true; retries = 0; setStreamState("connected"); snapshot(); });
      source.addEventListener("message", message);
      source.addEventListener("error", offline);
      source.addEventListener("failure", offline);
    };
    connect();
    const timer = window.setInterval(() => { if (!closed && !connected && document.visibilityState === "visible") { snapshot(); connect(); } }, 15000);
    const greekTimer = window.setInterval(() => { if (!closed && connected && document.visibilityState === "visible") snapshot(true); }, 60000);
    const visible = () => { if (!closed && document.visibilityState === "visible") snapshot(); };
    document.addEventListener("visibilitychange", visible);
    return () => { controller.abort(); source?.close(); window.clearInterval(timer); window.clearInterval(greekTimer); document.removeEventListener("visibilitychange", visible); };
  }, [symbol, expiry, visibleContracts.join("|"), spot.market_session, spot.session, spot.display_session, refreshNonce]);

  const loadDepth = useCallback(async (contracts: string[], signal?: AbortSignal) => {
    const origin = context.current;
    setDepthLoading(true);
    try {
      for (let index = 0; index < contracts.length; index += 4) {
        const chunk = contracts.slice(index, index + 4);
        const results = await Promise.allSettled(chunk.map(contract => read(`/api/options/contracts/${encodeURIComponent(contract)}`, signal)));
        if (signal?.aborted || origin !== context.current) return;
        setSnapshots(current => {
          const next = { ...current };
          for (const result of results) {
            if (result.status !== "fulfilled") continue;
            const item = result.value;
            next[String(item.contract_symbol)] = mergeQuote(next[String(item.contract_symbol)], item);
          }
          return next;
        });
        if (results.some(result => result.status === "rejected")) setError("Partial contract request failure");
      }
    } catch (reason) {
      if (!signal?.aborted && origin === context.current) setError(String(reason));
    } finally {
      if (!signal?.aborted && origin === context.current) setDepthLoading(false);
    }
  }, []);


  const openContract = async (contract: string) => {
    if (!contract) return;
    setSelectedContract(contract);
    if (snapshots[contract]?.depth_status === "available") return;
    detailController.current?.abort();
    detailController.current = new AbortController();
    await loadDepth([contract], detailController.current.signal);
  };

  const selected = snapshots[selectedContract] ?? null;
  const pages = Math.max(1, Math.ceil(chain.filter(row => !standardOnly || row.is_standard !== false).length / 21));
  const lastCell = (contract: string) => {
    const quote = snapshots[contract] ?? {};
    return <span className="chain-last" title={`${quote.quote_time ?? "—"} · ${quote.trade_status ?? "—"}`}>
      {referenceNumber(quote.last)}
      <small className={quote.change > 0 ? "chain-up" : quote.change < 0 ? "chain-down" : ""}>
        {referenceNumber(quote.change, 2)} / {quote.change_pct == null ? "—" : `${referenceNumber(quote.change_pct, 2)}%`}
      </small>
    </span>;
  };
  const contractCell = (contract: string, field: string, format: "number" | "percent" = "number") => {
    const value = snapshots[contract]?.[field];
    return format === "percent" ? percent(value) : referenceNumber(value, field === "volume" || field === "open_interest" ? 0 : 4);
  };

  return <section className={`option-section option-chain-workbench ${loading ? "is-loading" : ""} ${error ? "is-error" : ""}`} aria-label={zh ? "券商式期权链" : "Broker-style option chain"}>
    <div className="chain-heading"><div><h2>{symbol} · {zh ? "期权链" : "Option chain"}</h2><p>Longbridge · {zh ? "参考行情与严格模拟资格分开；最近成交时间不是盘口时间。" : "Reference quotes are separate from strict fill eligibility; last-trade time is not BBO time."}</p></div><div className="chain-underlying"><span>{zh ? "正股" : "Underlying"}</span><strong>{referenceNumber(spot.display_last ?? spot.last)}</strong><small>{spot.display_quote_time ?? spot.quote_time ?? "—"}</small></div></div>
    <div className="chain-toolbar">
      <label>{zh ? "到期日" : "Expiry"}<select value={expiry} onChange={event => setExpiry(event.target.value)}><option value="">—</option>{expiries.map(value => <option value={value} key={value}>{value} · {dte(value) ?? "—"} DTE</option>)}</select></label>
      <label>{zh ? "合约类型" : "Contract type"}<select value={standardOnly ? "standard" : "all"} onChange={event => setStandardOnly(event.target.value === "standard")}><option value="standard">{zh ? "仅标准合约" : "Standard only"}</option><option value="all">{zh ? "包含调整合约" : "Include adjusted"}</option></select></label>
      <button type="button" className="quiet-button" onClick={() => { setShowAll(value => !value); setPage(0); }}><Rows3 size={15} />{showAll ? (zh ? "显示21档" : "Show 21 strikes") : (zh ? "展开全部" : "Show all")}</button>
      <button type="button" className="quiet-button" disabled={depthLoading || !visibleContracts.length} onClick={() => void loadDepth(visibleContracts.map(String))}><RefreshCw size={15} className={depthLoading ? "spin" : ""} />{zh ? "加载可见盘口" : "Load visible BBO"}</button>
    </div>
    <div className="chain-toolbar"><span>{zh ? "行情连接" : "Quote connection"}: {streamState === "connected" ? (zh ? "已连接，时效见各合约时间" : "Connected; freshness per contract") : streamState === "reference" ? (zh ? "休市参考" : "Closed-market reference") : (zh ? "连接恢复中，快照补偿" : "Reconnecting; snapshot fallback")}</span>{showAll ? <><button disabled={page === 0} onClick={() => setPage(value => value - 1)} aria-label={zh ? "上一页" : "Previous page"}><ArrowLeft size={15} /></button><span>{page + 1} / {pages}</span><button disabled={page + 1 >= pages} onClick={() => setPage(value => value + 1)} aria-label={zh ? "下一页" : "Next page"}><ArrowRight size={15} /></button></> : null}</div>
    {!Number.isFinite(spotPrice) ? <div className="chain-notice">{zh ? "没有可靠正股价格，未自动判断ATM；当前按行权价顺序显示。" : "No reliable underlying price; ATM is not inferred and strikes remain in provider order."}</div> : null}
    {error ? <div className="chain-notice error" role="alert">{zh ? "部分期权数据读取失败" : "Some option data could not be loaded"} · {error}</div> : null}
    <div className="broker-chain desktop-chain" role="table">
      <div className="broker-chain-group"><strong>CALL</strong><span>{zh ? "买" : "Bid"}</span><span>{zh ? "卖" : "Ask"}</span><span>{zh ? "最新 / 涨跌" : "Last / Change"}</span><span>Vol</span><span>OI</span><span>IV</span><span>Delta</span><b>{zh ? "行权价" : "Strike"}</b><strong>PUT</strong><span>{zh ? "买" : "Bid"}</span><span>{zh ? "卖" : "Ask"}</span><span>{zh ? "最新 / 涨跌" : "Last / Change"}</span><span>Vol</span><span>OI</span><span>IV</span><span>Delta</span></div>
      {visibleRows.map(row => {
        const call = String(row.call_symbol ?? "");
        const put = String(row.put_symbol ?? "");
        const near = Number.isFinite(spotPrice) && Math.abs(Number(row.strike_price) - spotPrice) === Math.min(...visibleRows.map(item => Math.abs(Number(item.strike_price) - spotPrice)));
        return <div className={`broker-chain-row ${near ? "atm" : ""}`} role="row" key={`${row.strike_price}-${call}-${put}`}>
          <button type="button" className="contract-code" onClick={() => void openContract(call)} disabled={!call}>{call || "—"}</button><button type="button" onClick={() => void openContract(call)}>{contractCell(call, "bid")}</button><button type="button" onClick={() => void openContract(call)}>{contractCell(call, "ask")}</button>{lastCell(call)}<span>{contractCell(call, "volume")}</span><span>{contractCell(call, "open_interest")}</span><span>{contractCell(call, "implied_volatility", "percent")}</span><span>{contractCell(call, "delta")}</span>
          <strong className="strike-cell">{referenceNumber(row.strike_price, 3)}{row.is_standard === false ? <small>{zh ? "调整" : "Adj"}</small> : null}</strong>
          <button type="button" className="contract-code" onClick={() => void openContract(put)} disabled={!put}>{put || "—"}</button><button type="button" onClick={() => void openContract(put)}>{contractCell(put, "bid")}</button><button type="button" onClick={() => void openContract(put)}>{contractCell(put, "ask")}</button>{lastCell(put)}<span>{contractCell(put, "volume")}</span><span>{contractCell(put, "open_interest")}</span><span>{contractCell(put, "implied_volatility", "percent")}</span><span>{contractCell(put, "delta")}</span>
        </div>;
      })}
    </div>
    <div className="mobile-chain"><div className="mobile-chain-tabs" role="tablist"><button type="button" className={mobileSide === "call" ? "active" : ""} onClick={() => setMobileSide("call")}>Call</button><button type="button" className={mobileSide === "put" ? "active" : ""} onClick={() => setMobileSide("put")}>Put</button></div><div className="mobile-chain-head"><span>{zh ? "合约" : "Contract"}</span><b>{zh ? "行权价" : "Strike"}</b><span>Bid / Ask</span><span>IV · Delta</span></div>{visibleRows.map(row => { const contract = String(row[`${mobileSide}_symbol`] ?? ""); return <button type="button" className="mobile-chain-row" key={`${mobileSide}-${row.strike_price}`} onClick={() => void openContract(contract)}><span>{contract || "—"}</span><b>{referenceNumber(row.strike_price, 3)}</b><span>{contractCell(contract, "bid")} / {contractCell(contract, "ask")}</span><span>{contractCell(contract, "implied_volatility", "percent")} · {contractCell(contract, "delta")}</span></button>; })}</div>
    {!visibleRows.length ? <div className="chain-empty" role="status">{loading ? (zh ? "正在读取期权链…" : "Loading option chain…") : error ? (zh ? "期权链未完成读取，请刷新重试。" : "Chain could not be loaded; refresh to retry.") : (zh ? "该到期日没有可显示合约。" : "No contracts are available for this expiry.")}</div> : null}
    {selected ? <details className="contract-detail" open><summary><span>{selected.contract_symbol}</span><ChevronDown size={15} /></summary><dl className="settings-lines"><div><dt>{zh ? "买价 / 卖价" : "Bid / ask"}</dt><dd>{referenceNumber(selected.bid)} / {referenceNumber(selected.ask)}</dd></div><div><dt>{zh ? "买量 / 卖量" : "Bid / ask size"}</dt><dd>{referenceNumber(selected.bid_size, 0)} / {referenceNumber(selected.ask_size, 0)}</dd></div><div><dt>{zh ? "一张参考权利金" : "One-contract reference premium"}</dt><dd>{selected.ask != null && selected.contract_multiplier ? `$${referenceNumber(selected.ask * selected.contract_multiplier, 2)}` : "—"}</dd></div><div><dt>{zh ? "费用" : "Fees"}</dt><dd>{zh ? "未包含" : "Not included"}</dd></div><div><dt>Gamma / Theta / Vega</dt><dd>{referenceNumber(selected.gamma)} / {referenceNumber(selected.theta)} / {referenceNumber(selected.vega)}</dd></div><div><dt>{zh ? "乘数" : "Multiplier"}</dt><dd>{referenceNumber(selected.contract_multiplier, 0)}</dd></div><div><dt>{zh ? "最近成交时间" : "Last trade time"}</dt><dd>{selected.quote_time ?? "—"}</dd></div><div><dt>{zh ? "原生盘口时间" : "Native BBO time"}</dt><dd>{selected.bbo_event_time ?? "—"}</dd></div><div><dt>{zh ? "严格模拟资格" : "Strict simulated-fill eligibility"}</dt><dd>{selected.strict_fill_eligible ? "VERIFIED" : "BLOCKED"}</dd></div></dl><p>{zh ? "最大权利金损失等于实际支付权利金与费用；当前未产生交易建议或张数建议。" : "Maximum premium loss equals premium paid plus fees; no trade or sizing recommendation is generated here."}</p></details> : null}
    {selected ? <dl className="settings-lines" aria-label={zh ? "报价证据时间" : "Quote evidence times"}>
      <div><dt>{zh ? "合约状态" : "Contract validity"}</dt><dd>{selected.contract_validity ?? "UNKNOWN"}</dd></div>
      <div><dt>{zh ? "双边报价接收时间" : "Bilateral BBO received"}</dt><dd>{selected.bbo_received_at ?? "—"}</dd></div>
      <div><dt>{zh ? "盘口检查时间" : "BBO observation time"}</dt><dd>{selected.bbo_observed_at ?? "—"}</dd></div>
      <div><dt>{zh ? "Greeks 接收时间" : "Greeks received"}</dt><dd>{selected.calc_received_at ?? "—"}</dd></div>
      {selected.last_known_bbo ? <div><dt>{zh ? "已失效历史盘口（非当前）" : "Invalidated historical BBO (not current)"}</dt><dd>{referenceNumber(selected.last_known_bbo.bid)} / {referenceNumber(selected.last_known_bbo.ask)} · {selected.last_known_bbo.bbo_received_at ?? "—"}</dd></div> : null}
    </dl> : null}
  </section>;
}
