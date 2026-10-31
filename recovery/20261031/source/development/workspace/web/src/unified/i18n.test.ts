import { describe, expect, it } from "vitest";
import {
  actionText,
  backendText,
  candidateStateText,
  messageKeys,
  optionGroupText,
  optionReasonText,
  optionStateText,
  statusText,
  translate,
} from "./i18n";

describe("unified bilingual catalog", () => {
  it("uses Chinese by default and English without mixed-script shell copy", () => {
    expect(translate("zh", "Opportunities")).toBe("机会");
    expect(translate("en", "Opportunities")).toBe("Opportunities");
    expect(messageKeys.length).toBeGreaterThan(150);
    expect(messageKeys.every((key) => !/[\u3400-\u9fff]/.test(translate("en", key)))).toBe(true);
  });

  it("localizes shared action, status, option, and candidate contracts", () => {
    expect(actionText("BUY_REVIEW", "zh")).toBe("买入复核");
    expect(actionText("BUY_REVIEW", "en")).toBe("Buy review");
    expect(statusText("not_detected", "zh")).toBe("未检测到权限");
    expect(statusText("not_detected", "en")).toBe("Permission not detected");
    expect(statusText("pending", "zh")).toBe("等待确认");
    expect(statusText("running", "zh")).toBe("运行中");
    expect(optionStateText("REFERENCE_ONLY", "en")).toBe("Reference only");
    expect(optionGroupText("SWING_14_35DTE", "zh")).toBe("短波段");
    expect(candidateStateText("UP_TREND", "en")).toBe("Up trend");
  });

  it("keeps raw provider diagnostics out of ordinary Chinese UI", () => {
    expect(optionReasonText("OPRA realtime option quote permission is not available.", "zh")).toBe("期权实时行情权限未确认。");
    expect(optionReasonText("OPRA realtime options entitlement was not detected.", "zh")).toBe("未检测到 OPRA 美股期权实时行情权限。");
    expect(optionReasonText("Earnings/dividend/macro event coverage is incomplete.", "zh")).toBe("财报、分红和宏观事件覆盖不完整。");
    expect(optionReasonText("Unknown provider detail in English.", "zh")).toBe("请查看完整诊断。");
    expect(backendText("Unknown upstream failure with secret details", "zh")).toBe("请查看完整诊断。");
    expect(backendText("中文后端错误", "en")).toBe("See full diagnostics");
  });
});
