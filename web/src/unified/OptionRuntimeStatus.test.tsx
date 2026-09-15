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
});
