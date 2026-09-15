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
  if (!response.ok) throw new Error("request_failed");
  return response.json();
}

export default function OptionRuntimeStatus({ status, notifications, reload }: {
  status: Payload; notifications: Payload; reload: () => void;
}) {
  const { t, language } = useI18n();
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const supervisor = status.supervisor ?? {};
  const workers = status.runtime_checkpoints?.workers ?? [];
  const running = workers.some((worker: Payload) => worker.worker === "scan" && worker.live_heartbeat);
  const enable = async () => {
    setBusy(true); setMessage("");
    try {
      if (!window.isSecureContext || !("serviceWorker" in navigator) || !("PushManager" in window) || !("Notification" in window)) {
        setMessage(t("Push is unavailable in this browser")); return;
      }
      // Permission must be requested in the user's click gesture, never on page load.
      if (await Notification.requestPermission() !== "granted") {
        setMessage(t("Notification permission was not granted")); return;
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
    } catch { setMessage(t("Notification setup failed; check permissions and HTTPS")); }
    finally { setBusy(false); }
  };
  const test = async () => {
    setBusy(true); setMessage("");
    try {
      const result = await api("web-push/test", {});
      setMessage(result.sent > 0 ? t("Test sent; verify on your device") : t("No notification delivered; check subscription status"));
      reload();
    } catch { setMessage(t("Notification setup failed; check permissions and HTTPS")); }
    finally { setBusy(false); }
  };
  return <section className="option-detail-section" aria-label={t("Daily radar operation")}>
    <div className="section-title"><h3>{t("Daily radar operation")}</h3></div>
    <dl className="option-runtime-grid">
      <div><dt>{t("Automatic monitoring")}</dt><dd>{running ? t("Running") : t("Not running")}</dd></div>
      <div><dt>{t("Next premarket scan")}</dt><dd>{formatUiTime(supervisor.next_premarket_at, language)}</dd></div>
      <div><dt>{t("Report date")}</dt><dd>{status.latest_premarket?.market_date ?? "—"}{status.report_is_current === false ? ` · ${t("Previous report")}` : ""}</dd></div>
      <div><dt>{t("Phone subscriptions")}</dt><dd>{notifications.active_subscriptions ?? "—"}</dd></div>
      <div><dt>{t("Latest delivery")}</dt><dd>{notifications.latest_delivery ? formatUiTime(notifications.latest_delivery.created_at, language) : t("No delivery yet")}</dd></div>
    </dl>
    <div className="option-actions">
      <button type="button" className="quiet-button" disabled={busy} onClick={() => void enable()}><BellRing size={15} />{t("Enable notifications on this device")}</button>
      <button type="button" className="quiet-button" disabled={busy || !notifications.active_subscriptions} onClick={() => void test()}><Send size={15} />{t("Send test notification")}</button>
    </div>
    {message ? <p role="status">{message}</p> : null}
  </section>;
}
