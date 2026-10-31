import { BarChart3, ListFilter, Plus, RefreshCw, Search, Trash2 } from "lucide-react";
import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import type { UiLanguage } from "./i18n";
import "./stock-watchlist.css";

type Row = Record<string, any>;
type Props = {
  language: UiLanguage;
  onOpenChart: (symbol: string) => void;
  onOpenOptions: (symbol: string) => void;
};

async function request(path: string, init?: RequestInit, signal?: AbortSignal): Promise<Row> {
  const response = await fetch(path, { ...init, signal, cache: "no-store", credentials: "same-origin" });
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  const payload = await response.json();
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) throw new Error("Invalid response");
  return payload;
}

function number(value: unknown, digits = 2): string {
  const parsed = Number(value);
  return value == null || !Number.isFinite(parsed) ? "—" : parsed.toLocaleString(undefined, { maximumFractionDigits: digits });
}

function compact(value: unknown): string {
  const parsed = Number(value);
  if (value == null || !Number.isFinite(parsed)) return "—";
  return new Intl.NumberFormat(undefined, { notation: "compact", maximumFractionDigits: 1 }).format(parsed);
}

function sessionLabel(value: unknown, zh: boolean): string {
  const key = String(value ?? "");
  const labels: Record<string, [string, string]> = {
    pre: ["盘前", "Pre"],
    regular: ["常规", "Regular"],
    post: ["盘后", "Post"],
    closed_reference: ["休市参考", "Closed ref"],
  };
  return labels[key]?.[zh ? 0 : 1] ?? (zh ? "状态未知" : "Unknown");
}

function supportReason(value: unknown, zh: boolean): string {
  const key = String(value ?? "");
  const labels: Record<string, [string, string]> = {
    provider_mapping_requires_manual_review: ["需核对交易所与证券代码", "Exchange and symbol need review"],
    provider_returned_no_metadata: ["Longbridge 未返回证券元数据", "Longbridge returned no security metadata"],
    awaiting_provider_metadata: ["等待证券元数据核验", "Waiting for security metadata"],
  };
  return labels[key]?.[zh ? 0 : 1] ?? (zh ? "请查看数据诊断" : "See data diagnostics");
}

export default function StockWatchlist({ language, onOpenChart, onOpenOptions }: Props) {
  const zh = language === "zh";
  const [groups, setGroups] = useState<Row[]>([]);
  const [groupId, setGroupId] = useState("");
  const [rows, setRows] = useState<Row[]>([]);
  const [selected, setSelected] = useState("");
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<"order" | "symbol" | "change">("order");
  const [newSymbol, setNewSymbol] = useState("");
  const [loading, setLoading] = useState(true);
  const [mutating, setMutating] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [session, setSession] = useState("");
  const [receivedAt, setReceivedAt] = useState("");
  const [refreshAfter, setRefreshAfter] = useState(120);
  const [nonce, setNonce] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    request("/api/stocks/watchlist/groups", undefined, controller.signal)
      .then(payload => {
        const next = Array.isArray(payload.groups) ? payload.groups : [];
        setGroups(next);
        setGroupId(current => current || String(next[0]?.group_id ?? ""));
      })
      .catch(reason => { if (!controller.signal.aborted) setError(String(reason)); });
    return () => controller.abort();
  }, []);

  const load = useCallback(async (signal?: AbortSignal) => {
    if (!groupId) return;
    setLoading(true);
    setError("");
    try {
      const suffix = selected ? `&selected_symbol=${encodeURIComponent(selected)}` : "";
      const payload = await request(`/api/stocks/watchlist/quotes?group_id=${encodeURIComponent(groupId)}${suffix}`, undefined, signal);
      if (signal?.aborted) return;
      setRows(Array.isArray(payload.items) ? payload.items : []);
      setSession(String(payload.session ?? ""));
      setReceivedAt(String(payload.received_at ?? ""));
      setRefreshAfter(Math.max(15, Number(payload.refresh_after_seconds ?? 120)));
    } catch (reason) {
      if (!signal?.aborted) setError(String(reason));
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, [groupId, selected]);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load, nonce]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      if (document.visibilityState === "visible") setNonce(value => value + 1);
    }, refreshAfter * 1000);
    return () => window.clearInterval(timer);
  }, [refreshAfter]);

  const visible = useMemo(() => {
    const token = query.trim().toLowerCase();
    const filtered = token ? rows.filter(item => `${item.raw_symbol} ${item.display_name ?? ""}`.toLowerCase().includes(token)) : rows;
    return [...filtered].sort((left, right) => {
      if (sort === "symbol") return String(left.raw_symbol).localeCompare(String(right.raw_symbol));
      if (sort === "change") return Number(right.quote?.change_pct ?? -Infinity) - Number(left.quote?.change_pct ?? -Infinity);
      return Number(left.sort_order ?? 0) - Number(right.sort_order ?? 0);
    });
  }, [query, rows, sort]);

  const add = async (event: FormEvent) => {
    event.preventDefault();
    if (!newSymbol.trim() || !groupId) return;
    setMutating(true); setError(""); setNotice("");
    try {
      await request("/api/stocks/watchlist/members", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ group_id: groupId, symbol: newSymbol.trim() }),
      });
      setNewSymbol(""); setNotice(zh ? "已保存到当前分组" : "Saved to this group"); setNonce(value => value + 1);
    } catch (reason) { setError(String(reason)); }
    finally { setMutating(false); }
  };

  const remove = async (memberId: string) => {
    setMutating(true); setError(""); setNotice("");
    try {
      await request(`/api/stocks/watchlist/members/${encodeURIComponent(memberId)}`, { method: "DELETE" });
      setNotice(zh ? "已从当前分组移除" : "Removed from this group"); setNonce(value => value + 1);
    } catch (reason) { setError(String(reason)); }
    finally { setMutating(false); }
  };

  return <section className={`watchlist-workbench ${loading ? "is-loading" : ""} ${error ? "is-error" : ""} ${notice ? "is-success" : ""}`}>
    <div className="watchlist-toolbar">
      <div className="watchlist-controls">
        <label><span>{zh ? "分组" : "Group"}</span><select value={groupId} onChange={event => { setGroupId(event.target.value); setSelected(""); }}>{groups.map(group => <option key={group.group_id} value={group.group_id}>{group.display_name} · {group.member_count}</option>)}</select></label>
        <label className="watchlist-search"><Search size={15} /><input value={query} onChange={event => setQuery(event.target.value)} placeholder={zh ? "搜索当前分组" : "Search this group"} /></label>
        <label><span>{zh ? "排序" : "Sort"}</span><select value={sort} onChange={event => setSort(event.target.value as typeof sort)}><option value="order">{zh ? "原顺序" : "Original order"}</option><option value="symbol">{zh ? "代码" : "Symbol"}</option><option value="change">{zh ? "涨跌幅" : "Change"}</option></select></label>
      </div>
      <div className="watchlist-actions">
        <form onSubmit={add}><input value={newSymbol} onChange={event => setNewSymbol(event.target.value.toUpperCase())} placeholder={zh ? "添加代码" : "Add symbol"} maxLength={32} /><button type="submit" disabled={mutating || !newSymbol.trim()} title={zh ? "添加到当前分组" : "Add to current group"}><Plus size={15} /></button></form>
        <button type="button" onClick={() => setNonce(value => value + 1)} disabled={loading} title={zh ? "刷新行情" : "Refresh quotes"}><RefreshCw size={15} className={loading ? "spin" : ""} /></button>
      </div>
    </div>
    <div className="watchlist-meta"><span>Longbridge</span><span>{sessionLabel(rows[0]?.quote?.display_session ?? session, zh)}</span><span>{receivedAt ? new Date(receivedAt).toLocaleString(language === "zh" ? "zh-CN" : "en-US") : "—"}</span><span>{zh ? "单个标的失败不会隐藏整组" : "One failed symbol does not hide the group"}</span></div>
    {error ? <div className="watchlist-message error" role="alert">{zh ? "自选行情读取失败" : "Watchlist quote request failed"} · {error}</div> : null}
    {notice ? <div className="watchlist-message success" role="status">{notice}</div> : null}
    <div className="watchlist-table" role="table" aria-label={zh ? "分组自选行情" : "Grouped watchlist quotes"}>
      <div className="watchlist-row watchlist-head" role="row"><span>{zh ? "代码 / 名称" : "Symbol / name"}</span><span>{zh ? "最近价" : "Last"}</span><span>{zh ? "涨跌" : "Change"}</span><span>{zh ? "开盘" : "Open"}</span><span>{zh ? "成交量" : "Volume"}</span><span>Bid / Ask</span><span>{zh ? "时间 / 状态" : "Time / status"}</span><span>{zh ? "操作" : "Actions"}</span></div>
      {visible.map(item => {
        const quote = item.quote ?? {};
        const change = Number(quote.change);
        const tone = Number.isFinite(change) ? (change > 0 ? "positive" : change < 0 ? "negative" : "") : "";
        const available = quote.provider_status === "available";
        return <div className={`watchlist-row ${selected === item.normalized_symbol ? "selected" : ""}`} role="row" key={item.member_id} onClick={() => setSelected(String(item.normalized_symbol))}>
          <span className="watchlist-symbol"><strong>{item.raw_symbol}</strong><small>{item.display_name || (item.identity_status === "verified" ? "Longbridge" : (zh ? "身份待确认" : "Identity pending"))}</small></span>
          <span className="watchlist-price"><strong>{number(quote.display_last ?? quote.last, 4)}</strong><small>{sessionLabel(quote.display_session, zh)}</small></span>
          <span className={tone}><strong>{number(quote.change, 4)}</strong><small>{quote.change_pct == null ? "—" : `${number(quote.change_pct, 2)}%`}</small></span>
          <span className="secondary-cell">{number(quote.open, 4)}</span>
          <span className="secondary-cell">{compact(quote.volume)}</span>
          <span className="bbo-cell"><strong>{number(quote.bid, 4)} / {number(quote.ask, 4)}</strong><small>{number(quote.bid_size, 0)} / {number(quote.ask_size, 0)}</small></span>
          <span className="status-cell"><strong>{available ? (zh ? "行情可用" : "Quote available") : (zh ? "暂无行情" : "No quote")}</strong><small>{quote.quote_time ?? supportReason(item.identity_reason, zh)}</small></span>
          <span className="row-actions"><button type="button" onClick={event => { event.stopPropagation(); onOpenChart(String(item.normalized_symbol)); }} title={zh ? "打开图表" : "Open chart"}><BarChart3 size={15} /></button><button type="button" onClick={event => { event.stopPropagation(); onOpenOptions(String(item.normalized_symbol)); }} disabled={!item.provider_symbol} title={zh ? "打开期权链" : "Open option chain"}><ListFilter size={15} /></button><button type="button" onClick={event => { event.stopPropagation(); void remove(String(item.member_id)); }} disabled={mutating} title={zh ? "从分组移除" : "Remove from group"}><Trash2 size={15} /></button></span>
        </div>;
      })}
    </div>
    {!loading && !visible.length ? <div className="watchlist-empty">{zh ? "当前分组没有匹配标的。" : "No matching symbols in this group."}</div> : null}
  </section>;
}
