import { BellRing, Send } from "lucide-react";
import { useState } from "react";
import { useI18n, formatUiTime } from "./i18n";

type Payload = Record<string, any>;

export function pushKeyBytes(value: string): Uint8Array<ArrayBuffer> {
  const decoded = atob(value.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - value.length % 4) % 4));
  return Uint8Array.from(decoded, char => char.charCodeAt(0));
}

async function api(path: string, body?: object): Promise<Payload> {
  const response = await fetch(`/api/stocks/notifications/${path}`, {
    credentials: "same-origin", method: body ? "POST" : "GET",
    headers: body ? { "Content-Type": "application/json" } : undefined,
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!response.ok) throw new Error(`request_failed_${response.status}`);
  return response.json();
}

export default function OptionRuntimeStatus({ status, notifications, reload, notificationsOnly = false }: {
  status: Payload; notifications: Payload; reload: () => void; notificationsOnly?: boolean;
}) {
  const { t, language } = useI18n();
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const supervisor = status.supervisor ?? {};
  const workers = status.runtime_checkpoints?.workers ?? [];
  const running = workers.some((worker: Payload) => worker.worker === "scan" && worker.live_heartbeat);
  const foundationMode = String(supervisor.mode ?? "") === "foundation";
  const title = notificationsOnly ? t("Desktop alerts") : foundationMode ? t("Foundation observation service") : t("Daily radar operation");
  const hasAuthorizedDevice = Number(notifications.active_subscriptions ?? 0) > 0;
  const windowsDesktop = typeof navigator !== "undefined" && /Windows NT/i.test(navigator.userAgent);
  const capabilityIssue = typeof window === "undefined" ? "" : !windowsDesktop ? "WINDOWS_BROWSER_REQUIRED" : !window.isSecureContext ? "SECURE_CONTEXT_REQUIRED" : !("serviceWorker" in navigator) ? "SERVICE_WORKER_UNAVAILABLE" : !("PushManager" in window) ? "PUSH_UNAVAILABLE" : !("Notification" in window) ? "NOTIFICATION_UNAVAILABLE" : "";
  const issueText = capabilityIssue ? language === "zh" ? `此浏览器无法注册 Windows 提醒（${capabilityIssue}）。请在这台电脑的 Chrome 或 Edge 打开本机链接。` : `This browser cannot register Windows alerts (${capabilityIssue}). Open the local link in Chrome or Edge on this PC.` : "";
  const enable = async () => {
    setBusy(true); setMessage("");
    try {
      if (capabilityIssue) {
        setMessage(issueText); return;
      }
      // Permission must be requested in the user's click gesture, never on page load.
      if (await Notification.requestPermission() !== "granted") {
        setMessage(language === "zh" ? "通知权限未获准。请在浏览器地址栏的网站权限中允许通知，然后重试。" : "Notification permission was denied. Allow notifications for this site in browser settings, then retry."); return;
      }
      const key = await api("web-push/public-key");
      if (!key.configured || !key.public_key) throw new Error("push_not_configured");
      await navigator.serviceWorker.register("/service-worker.js", { updateViaCache: "none" });
      const registration = await navigator.serviceWorker.ready;
      const subscription = await registration.pushManager.getSubscription() ?? await registration.pushManager.subscribe({
        userVisibleOnly: true, applicationServerKey: pushKeyBytes(key.public_key),
      });
      await api("web-push/subscribe", subscription.toJSON());
      setMessage(t("Device subscription saved")); reload();
    } catch (error) { setMessage(`${t("Notification setup failed; check permissions and HTTPS")} (${error instanceof Error ? error.name + ":" + error.message : "unknown"})`); }
    finally { setBusy(false); }
  };
  const test = async () => {
    setBusy(true); setMessage("");
    try {
      const result = await api("web-push/test", {});
      setMessage(result.sent > 0 ? t("Test sent; verify on your device") : t("No notification delivered; check subscription status"));
      reload();
    } catch (error) { setMessage(`${t("Notification setup failed; check permissions and HTTPS")} (${error instanceof Error ? error.name + ":" + error.message : "unknown"})`); }
    finally { setBusy(false); }
  };
  return <section className="option-detail-section" aria-label={title}>
    <div className="section-title"><h3>{title}</h3></div>
    <dl className="option-runtime-grid">
      {!notificationsOnly ? <><div><dt>{t("Automatic monitoring")}</dt><dd>{running ? t("Running") : t("Not running")}</dd></div>
      <div><dt>{foundationMode ? t("Next market validation") : t("Next premarket scan")}</dt><dd>{formatUiTime(foundationMode ? supervisor.next_foundation_market_check_at : supervisor.next_premarket_at, language)}</dd></div>
      {foundationMode ? <><div><dt>{t("Strategy status")}</dt><dd>{t("Strategy definition pending")}</dd></div><div><dt>{t("Performance status")}</dt><dd>{t("Performance not evaluated")}</dd></div></> : <div><dt>{t("Report date")}</dt><dd>{status.latest_premarket?.market_date ?? "—"}{status.report_is_current === false ? ` · ${t("Previous report")}` : ""}</dd></div>}
      </> : null}<div><dt>{t("Device subscriptions")}</dt><dd>{notifications.active_subscriptions ?? "—"}</dd></div>
      <div><dt>{t("Delivery validation")}</dt><dd>{hasAuthorizedDevice ? t("Device registered; display unverified") : t("Waiting for device permission")}</dd></div>
      <div><dt>{t("Latest delivery attempt")}</dt><dd>{notifications.latest_delivery ? `${formatUiTime(notifications.latest_delivery.created_at, language)} · ${notifications.latest_delivery.status ?? "—"}` : t("No delivery yet")}</dd></div>
    </dl>
    <div className="option-actions">
      <button type="button" className="quiet-button" disabled={busy || Boolean(capabilityIssue)} onClick={() => void enable()}><BellRing size={15} />{t("Enable notifications on this device")}</button>
      <button type="button" className="quiet-button" disabled={busy || !notifications.active_subscriptions} onClick={() => void test()}><Send size={15} />{t("Send test notification")}</button>
    </div>
    {issueText ? <p role="status">{issueText}</p> : null}
    {message ? <p role="status">{message}</p> : null}
  </section>;
}
