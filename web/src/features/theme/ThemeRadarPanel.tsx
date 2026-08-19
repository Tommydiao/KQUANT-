import type { ReactNode } from "react";

type Lang = "en" | "zh";

type CandleMeta = {
  providerStatus: string;
  count: number;
};

type RadarUniverseStock = {
  symbol: string;
  name: string;
  layer: string;
  primary_layer?: string;
};

type RadarSignal = {
  symbol: string;
  score: number;
  level: string;
  primary_layer?: string;
  trigger_summary: string;
  features: Record<string, number>;
  trade_conclusion?: {
    action?: string;
    decision_summary?: string;
  };
  historical_edge?: {
    focus_win_rate?: number;
    win_rate_5d?: number;
  };
  ai_action_validation?: {
    win_rate?: number;
    expected_value_r?: number;
  };
  entry_plan?: { zone?: string };
  stop_plan?: { zone?: string };
  target_plan?: { zone?: string };
};

type RadarRun = {
  universe_total?: number;
  scanned_count?: number;
  provider_error_count: number;
  provider_coverage?: { available: number };
  counts: { buy_setup: number; watch: number; pass: number; total: number };
  review_counts?: { high_priority?: number };
  profile: { label?: string; name: string };
  signals: RadarSignal[];
};

type RadarAiDecision = {
  ai_decision?: {
    action?: string;
    summary?: string;
    entry_zone?: string;
    stop_zone?: string;
    target_zone?: string;
  };
};

type Readiness = { status: string };

function number(value: number | null | undefined): string {
  return value == null || !Number.isFinite(value) ? "-" : value.toLocaleString("en-US", { maximumFractionDigits: 2 });
}

function layerFor(signal: RadarSignal, stock: RadarUniverseStock | undefined): string {
  return signal.primary_layer || stock?.primary_layer || stock?.layer || "US Stock";
}

function actionClass(action: string | undefined): string {
  const value = String(action || "").toUpperCase();
  if (value.includes("BUY")) return "buy";
  if (value.includes("WATCH") || value.includes("WAIT")) return "watch";
  return "pass";
}

function labelFor(level: string, lang: Lang): string {
  if (lang === "en") return level;
  const labels: Record<string, string> = {
    "BUY SETUP": "买入准备",
    WATCH: "观察",
    PASS: "通过",
  };
  return labels[level] || level;
}

function Fact({ label, value }: { label: string; value: ReactNode }) {
  return <div className="fact"><span>{label}</span><strong>{value}</strong></div>;
}

function MiniMetric({ label, value, tone }: { label: string; value: string; tone?: "good" | "watch" | "probe" }) {
  return (
    <div className={`terminal-mini-metric ${tone || ""}`}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

export function ThemeRadarPanel({
  run,
  universe,
  selected,
  selectedMeta,
  aiDecision,
  dailyMeta,
  hourlyMeta,
  readiness,
  lang,
  onPick,
  onOpenStock,
}: {
  run: RadarRun;
  universe: RadarUniverseStock[];
  selected: RadarSignal;
  selectedMeta: RadarUniverseStock;
  aiDecision: RadarAiDecision | null;
  dailyMeta: CandleMeta;
  hourlyMeta: CandleMeta;
  readiness: Readiness;
  lang: Lang;
  onPick: (symbol: string) => void;
  onOpenStock: () => void;
}) {
  const zh = lang === "zh";
  const currentAi = aiDecision?.ai_decision;
  const selectedAction = currentAi?.action || selected.trade_conclusion?.action || selected.level;
  const selectedLayer = layerFor(selected, selectedMeta);
  const selectedScore = Number(selected.score || 0);
  const selectedWinRate = selected.ai_action_validation?.win_rate ?? selected.historical_edge?.focus_win_rate ?? selected.historical_edge?.win_rate_5d ?? 0;
  const selectedExpectedR = selected.ai_action_validation?.expected_value_r ?? 0;
  const rankedSignals = [...run.signals]
    .sort((a, b) => {
      const rank = (signal: RadarSignal) => {
        const action = signal.trade_conclusion?.action || signal.level;
        if (String(action).includes("BUY")) return 4;
        if (String(action).includes("WATCH")) return 3;
        if (String(action).includes("WAIT")) return 2;
        return 1;
      };
      return rank(b) - rank(a) || Number(b.score || 0) - Number(a.score || 0);
    })
    .slice(0, 12);
  const layerNames = Array.from(new Set(universe.map((stock) => stock.layer || stock.primary_layer || "US Stock"))).slice(0, 12);
  const layerTiles = layerNames.map((layer) => {
    const layerSymbols = universe.filter((stock) => (stock.layer || stock.primary_layer) === layer);
    const layerSignals = run.signals.filter((signal) => signal.primary_layer === layer || universe.find((stock) => stock.symbol === signal.symbol)?.layer === layer);
    const avgScore = layerSignals.length ? layerSignals.reduce((sum, signal) => sum + Number(signal.score || 0), 0) / layerSignals.length : 0;
    const hotCount = layerSignals.filter((signal) => String(signal.trade_conclusion?.action || signal.level).includes("BUY") || String(signal.trade_conclusion?.action || signal.level).includes("WATCH")).length;
    return { layer, count: layerSymbols.length, avgScore, hotCount, symbols: layerSymbols.slice(0, 4).map((stock) => stock.symbol) };
  });
  const text = (cn: string, en: string) => (zh ? cn : en);

  return (
    <section className="terminal-radar-panel" aria-label={text("KQUANT 交易终端总览", "KQUANT terminal overview")}>
      <div className="terminal-radar-header">
        <div>
          <span>{text("实时交易雷达", "Live Trading Radar")}</span>
          <h2>{text("KQUANT 股票雷达", "KQUANT Stock Radar")}</h2>
          <p>{text("把机会、主题热度、当前股票结论和数据健康压缩到一屏，方便开盘后快速扫描。", "A compact view of opportunities, theme heat, the selected stock, and data health.")}</p>
        </div>
        <div className="terminal-clock-stack">
          <b>{readiness.status}</b>
          <span>{text("交易准备度", "Readiness")}</span>
        </div>
      </div>

      <div className="terminal-radar-layout">
        <div className="terminal-radar-left">
          <div className="terminal-metric-grid">
            <MiniMetric label={text("买入候选", "Buy")} value={String(run.counts.buy_setup)} tone="good" />
            <MiniMetric label={text("观察", "Watch")} value={String(run.counts.watch)} tone="watch" />
            <MiniMetric label={text("重点复核", "Priority")} value={String(run.review_counts?.high_priority ?? 0)} tone="probe" />
            <MiniMetric label={text("数据覆盖", "Coverage")} value={`${run.provider_coverage?.available ?? 0}/${run.universe_total ?? universe.length}`} />
            <MiniMetric label={text("研究服务", "Research")} value={run.provider_error_count ? text("需确认", "Caution") : text("可用", "Ready")} tone={run.provider_error_count ? "watch" : "good"} />
            <MiniMetric label={text("当前池", "Universe")} value={`${run.scanned_count ?? run.counts.total}/${run.universe_total ?? universe.length}`} />
          </div>

          <div className="terminal-tape">
            <div className="terminal-section-title"><strong>{text("信号列表", "Signal Tape")}</strong><span>{run.profile.label || run.profile.name}</span></div>
            {rankedSignals.length ? rankedSignals.map((signal) => (
              <button type="button" key={`terminal-signal-${signal.symbol}`} className={`terminal-tape-row ${actionClass(signal.trade_conclusion?.action || signal.level)}`} onClick={() => onPick(signal.symbol)}>
                <b>{signal.symbol}</b>
                <span>{layerFor(signal, universe.find((stock) => stock.symbol === signal.symbol))}</span>
                <em>{signal.trade_conclusion?.action || labelFor(signal.level, lang)}</em>
                <strong>{number(signal.score)}</strong>
              </button>
            )) : <p className="terminal-empty">{text("暂无信号，请先运行扫描或搜索股票。", "No signals loaded. Run a scan or search a symbol.")}</p>}
          </div>
        </div>

        <div className="terminal-radar-center">
          <div className="terminal-section-title"><strong>{text("主题热度", "Theme Heatmap")}</strong><span>{text("按市场层级分组", "Grouped by market layer")}</span></div>
          <div className="terminal-layer-grid">
            {layerTiles.map((tile) => (
              <button type="button" className={`terminal-layer-tile ${tile.avgScore >= 70 ? "hot" : tile.hotCount ? "warm" : ""}`} key={`terminal-layer-${tile.layer}`} onClick={() => tile.symbols[0] && onPick(tile.symbols[0])}>
                <div><strong>{tile.layer}</strong><span>{tile.count} {text("只", "stocks")}</span></div>
                <b>{number(tile.avgScore)}</b>
                <small>{tile.symbols.join(" / ") || "-"}</small>
              </button>
            ))}
          </div>
        </div>

        <aside className="terminal-radar-detail">
          <div className="terminal-section-title"><strong>{text("当前股票", "Selected Stock")}</strong><button type="button" onClick={onOpenStock}>{text("打开详情", "Open detail")}</button></div>
          <div className="terminal-stock-head"><span>{selectedMeta.name}</span><h3>{selected.symbol}</h3><b>{number(selectedScore)}/100</b></div>
          <div className={`terminal-action-card ${actionClass(String(selectedAction))}`}>
            <span>{text("研究结论", "Decision")}</span>
            <strong>{String(selectedAction)}</strong>
            <small>{currentAi?.summary || selected.trade_conclusion?.decision_summary || selected.trigger_summary}</small>
          </div>
          <div className="terminal-detail-grid">
            <Fact label={text("层级", "Layer")} value={selectedLayer} />
            <Fact label={text("日线", "Daily")} value={`${dailyMeta.providerStatus} / ${dailyMeta.count}`} />
            <Fact label={text("确认线", "Confirm")} value={`${hourlyMeta.providerStatus} / ${hourlyMeta.count}`} />
            <Fact label={text("胜率", "Win Rate")} value={`${number(selectedWinRate)}%`} />
            <Fact label="EV R" value={`${number(selectedExpectedR)}R`} />
            <Fact label="ATR" value={`${number(selected.features.atr_pct)}%`} />
            <Fact label="EMA20" value={number(selected.features.ema20)} />
            <Fact label={text("成交量", "Volume")} value={`${number(selected.features.volume_ratio)}x`} />
          </div>
          <div className="terminal-plan-lines">
            <p><b>{text("入场", "Entry")}</b>{currentAi?.entry_zone || selected.entry_plan?.zone || "-"}</p>
            <p><b>{text("止损", "Stop")}</b>{currentAi?.stop_zone || selected.stop_plan?.zone || "-"}</p>
            <p><b>{text("目标", "Target")}</b>{currentAi?.target_zone || selected.target_plan?.zone || "-"}</p>
          </div>
        </aside>
      </div>
    </section>
  );
}
