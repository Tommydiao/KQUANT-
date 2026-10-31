import { describe, expect, it } from "vitest";
import { renderToStaticMarkup } from "react-dom/server";
import OptionRuntimeStatus, { pushKeyBytes } from "./OptionRuntimeStatus";
import { I18nProvider } from "./i18n";

describe("option daily runtime", () => {
  it("decodes a public VAPID key without credentials", () => {
    expect([...pushKeyBytes("AQID")]).toEqual([1, 2, 3]);
    expect([...pushKeyBytes("AQI")]).toEqual([1, 2]);
  });
  it("does not claim running on a stale heartbeat and never asks permission on render", () => {
    const markup = renderToStaticMarkup(<I18nProvider language="zh"><OptionRuntimeStatus status={{runtime_checkpoints:{workers:[{worker:"scan",live_heartbeat:false}]}}} notifications={{active_subscriptions:0}} reload={() => undefined} /></I18nProvider>);
    expect(markup).toContain("未运行");
    expect(markup).toContain("发送测试通知");
    expect(markup).toContain("disabled");
  });
  it("shows foundation validation instead of the legacy radar schedule", () => {
    const markup = renderToStaticMarkup(<I18nProvider language="en"><OptionRuntimeStatus status={{
      supervisor: { mode: "foundation", next_foundation_market_check_at: "2026-09-21T13:35:00Z" },
      runtime_checkpoints: { workers: [{ worker: "scan", live_heartbeat: true }] },
    }} notifications={{ active_subscriptions: 0 }} reload={() => undefined} /></I18nProvider>);
    expect(markup).toContain("Foundation observation service");
    expect(markup).toContain("Next market validation");
    expect(markup).toContain("Strategy definition pending");
    expect(markup).not.toContain("Daily radar operation");
  });
  it("does not present a push subscription as confirmed device display", () => {
    const markup = renderToStaticMarkup(<I18nProvider language="zh"><OptionRuntimeStatus
      status={{}} notifications={{ active_subscriptions: 1, latest_delivery: { status: "sent", created_at: "2026-09-23T13:40:00Z" } }}
      reload={() => undefined} notificationsOnly /></I18nProvider>);
    expect(markup).toContain("设备订阅数");
    expect(markup).toContain("屏幕显示待确认");
    expect(markup).toContain("最近投递尝试");
    expect(markup).not.toContain("已连接授权设备");
  });
});
