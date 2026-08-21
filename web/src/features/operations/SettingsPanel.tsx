import { BellRing, ShieldCheck, Trash2 } from "lucide-react";
import { useEffect, useState } from "react";

type Lang = "en" | "zh";
type ApiFetcher = (input: string, init?: RequestInit) => Promise<Response>;
type SettingsText = Record<string, string>;

type WebPushStatus = {
  configured: boolean;
  active_subscriptions: number;
  preferences?: NotificationPreferences | null;
};

type NotificationPreferences = {
  quiet_start: string;
  quiet_end: string;
  daily_routine_limit: number;
};

type CoveragePayload = {
  universe_symbols: number;
  interval_summary: Record<string, { longbridge_eligible_symbols: number; coverage_pct: number; target_pct: number }>;
  universe_registry?: { registry_id: string };
  backfill_quota?: {
    status: string;
    month: string;
    tracked_unique_symbols: number;
    configured_monthly_symbol_cap: number;
    provider_quota_lock: boolean;
    provider_error_code?: string | null;
    next_recheck_at?: string | null;
  };
  historical_validation?: {
    status: string;
    universe_symbols?: number;
    eligible_symbols?: number | null;
    coverage_pct?: number | null;
    target_symbols?: number | null;
    target_pct?: number;
    additional_symbols_required?: number | null;
    target_met?: boolean;
  };
};

type TaxonomyPayload = {
  status: string;
  taxonomy_version?: string;
  as_of_date?: string;
  summary?: { mapped_coverage_pct?: number; unmapped_theme_symbols?: number; target_met?: boolean; registry_symbol_count?: number };
  definitions?: Array<{ definition_id: string; display_name: string; membership_count: number }>;
};

type RotationPayload = {
  status: string;
  as_of_time?: string;
  summary?: { ranked_theme_count?: number; stress_direction_flips?: number; stress_unreasonable_flips?: number; data_source?: string };
  scores?: Array<{ definition_id: string; rank_value?: number | null; score?: number | null; eligible_member_count: number }>;
};

type ThemePredictionPayload = {
  status: string;
  gate_status?: string;
  prediction_version?: string;
  summary?: { display_probability?: boolean; calibration_gate?: { observed_oos_folds?: number; minimum_oos_folds?: number } };
};

type LeadershipPayload = {
  status: string;
  as_of_time?: string;
  summary?: { unique_symbol_count?: number; theme_membership_count?: number; state_counts?: Record<string, number>; future_prediction_used?: boolean };
};

function toUint8Array(value: string): ArrayBuffer {
  const padding = "=".repeat((4 - (value.length % 4)) % 4);
  const decoded = window.atob((value + padding).replace(/-/g, "+").replace(/_/g, "/"));
  const bytes = new Uint8Array(decoded.length);
  for (let index = 0; index < decoded.length; index += 1) bytes[index] = decoded.charCodeAt(index);
  return bytes.buffer;
}

function label(lang: Lang, zh: string, en: string): string {
  return lang === "zh" ? zh : en;
}

function localTime(value?: string | null): string {
  if (!value) return "-";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
}

export function SettingsPanel({
  apiConnection,
  aiStatus,
  apiBaseUrl,
  apiHealth,
  text,
  lang,
  apiFetch,
}: {
  apiConnection: string;
  aiStatus: { status: string; models?: { review?: string } } | null;
  apiBaseUrl: string;
  apiHealth: { backend?: string } | null;
  text: SettingsText;
  lang: Lang;
  apiFetch: ApiFetcher;
}) {
  const [pushStatus, setPushStatus] = useState<WebPushStatus | null>(null);
  const [preferences, setPreferences] = useState<NotificationPreferences | null>(null);
  const [coverage, setCoverage] = useState<CoveragePayload | null>(null);
  const [taxonomy, setTaxonomy] = useState<TaxonomyPayload | null>(null);
  const [rotation, setRotation] = useState<RotationPayload | null>(null);
  const [themePrediction, setThemePrediction] = useState<ThemePredictionPayload | null>(null);
  const [leadership, setLeadership] = useState<LeadershipPayload | null>(null);
  const [pushMessage, setPushMessage] = useState("");
  const [pushBusy, setPushBusy] = useState(false);

  async function loadPushStatus() {
    const response = await apiFetch("/api/notifications/status");
    if (!response.ok) return;
    const payload = (await response.json()) as WebPushStatus;
    setPushStatus(payload);
    setPreferences(payload.preferences ?? null);
  }

  useEffect(() => {
    void loadPushStatus();
    void apiFetch("/api/data/coverage").then(async (response) => { if (response.ok) setCoverage(await response.json() as CoveragePayload); });
    void apiFetch("/api/themes").then(async (response) => { if (response.ok) setTaxonomy(await response.json() as TaxonomyPayload); });
    void apiFetch("/api/themes/ranking").then(async (response) => { if (response.ok) setRotation(await response.json() as RotationPayload); });
    void apiFetch("/api/models/theme-prediction/latest").then(async (response) => { if (response.ok) setThemePrediction(await response.json() as ThemePredictionPayload); });
    void apiFetch("/api/leadership/latest").then(async (response) => { if (response.ok) setLeadership(await response.json() as LeadershipPayload); });
  }, []);

  async function enablePush() {
    setPushBusy(true);
    setPushMessage("");
    try {
      if (!("serviceWorker" in navigator) || !("PushManager" in window)) throw new Error(label(lang, "当前浏览器不支持手机通知。", "Push is not supported in this browser."));
      const permission = await Notification.requestPermission();
      if (permission !== "granted") throw new Error(label(lang, "你尚未允许通知。", "Notification permission was not granted."));
      const keyResponse = await apiFetch("/api/notifications/web-push/public-key");
      const keyPayload = await keyResponse.json() as { configured: boolean; public_key: string };
      if (!keyPayload.configured || !keyPayload.public_key) throw new Error(label(lang, "本机尚未配置手机通知密钥。", "Web Push keys are not configured."));
      const registration = await navigator.serviceWorker.ready;
      const existing = await registration.pushManager.getSubscription();
      const subscription = existing ?? await registration.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: toUint8Array(keyPayload.public_key) });
      const response = await apiFetch("/api/notifications/web-push/subscribe", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(subscription.toJSON()) });
      if (!response.ok) throw new Error(label(lang, "通知订阅保存失败。", "Could not save the subscription."));
      setPushMessage(label(lang, "此设备已启用主动提醒。", "Notifications are enabled on this device."));
      await loadPushStatus();
    } catch (error) {
      setPushMessage(error instanceof Error ? error.message : String(error));
    } finally {
      setPushBusy(false);
    }
  }

  async function disablePush() {
    setPushBusy(true);
    try {
      const registration = await navigator.serviceWorker.ready;
      const subscription = await registration.pushManager.getSubscription();
      if (subscription) {
        await apiFetch("/api/notifications/web-push/subscribe", { method: "DELETE", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ endpoint: subscription.endpoint }) });
        await subscription.unsubscribe();
      }
      setPushMessage(label(lang, "此设备的主动提醒已关闭。", "Notifications are disabled on this device."));
      await loadPushStatus();
    } finally {
      setPushBusy(false);
    }
  }

  async function savePushPreferences() {
    if (!preferences) return;
    setPushBusy(true);
    const response = await apiFetch("/api/notifications/preferences", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(preferences) });
    setPushMessage(response.ok ? label(lang, "提醒偏好已保存。", "Preferences saved.") : label(lang, "保存失败。", "Save failed."));
    await loadPushStatus();
    setPushBusy(false);
  }

  async function testPush() {
    setPushBusy(true);
    const response = await apiFetch("/api/notifications/web-push/test", { method: "POST" });
    const payload = await response.json() as { status?: string; reason?: string };
    setPushMessage(response.ok && payload.status === "sent" ? label(lang, "测试通知已发送。", "Test notification sent.") : `${label(lang, "未发送", "Not sent")}: ${payload.reason ?? payload.status ?? "unknown"}`);
    setPushBusy(false);
  }

  const settingText = (key: string, fallback: string) => text[key] || fallback;
  return (
    <section className="panel settings-panel" id="settings-workspace">
      <div className="settings-head"><div><span>{settingText("settingsNav", "Settings")}</span><h2>{settingText("settingsTitle", "Terminal settings")}</h2><p>{settingText("settingsDescription", "Read-only research and data diagnostics.")}</p></div><span className="pill neutral"><ShieldCheck size={14} />{settingText("researchSignalOnly", "Research only")}</span></div>
      <div className="settings-grid">
        <div className="settings-card"><strong>{settingText("currentLocalMode", "Current local mode")}</strong><p>Local backend: {apiHealth?.backend ?? "127.0.0.1:8001"} / SQLite: work/kquant_us.sqlite3</p><p>Status: {apiConnection === "connected" ? "live API connected" : "live API offline"}</p></div>
        <div className="settings-card"><strong>{settingText("futureSaasTarget", "Future hosted target")}</strong><p>{settingText("futureSaasCopy", "Hosted deployment remains separate from the local research runtime.")}</p><p>{settingText("paymentDisabled", "Payments disabled")}</p></div>
        <div className="settings-card"><strong>{settingText("dataSourceTitle", "Data source")}</strong><p>{settingText("dataSourceCopy", "Longbridge is the primary read-only market source; reference data stays quarantined.")}</p><p>{settingText("remoteApi", "Remote API")}: {apiBaseUrl || "not configured"}</p></div>
        <div className="settings-card"><strong>{settingText("aiStatusTitle", "Research service")}</strong><p>{aiStatus?.status === "available" ? `Connected: ${aiStatus.models?.review ?? "review model"}` : "Research service unavailable"}</p><p>{settingText("aiStatusCopy", "Research output never overrides deterministic safeguards.")}</p></div>
        <div className="settings-card wide"><strong>{label(lang, "数据可信度", "Data trust")}</strong><p>{coverage ? `${coverage.universe_symbols} symbols / registry ${coverage.universe_registry?.registry_id ?? "pending"}` : "Loading coverage report..."}</p>{coverage ? <p>{Object.entries(coverage.interval_summary).map(([interval, item]) => `${interval}: ${item.longbridge_eligible_symbols}/${coverage.universe_symbols} (${item.coverage_pct}% / target ${item.target_pct}%)`).join(" · ")}</p> : null}{coverage?.historical_validation?.eligible_symbols !== undefined && coverage.historical_validation.eligible_symbols !== null ? <p>{label(lang, `历史验证窗口：${coverage.historical_validation.eligible_symbols}/${coverage.historical_validation.universe_symbols ?? coverage.universe_symbols}（${coverage.historical_validation.coverage_pct ?? 0}% / 目标 ${coverage.historical_validation.target_pct ?? 90}%）；仍需 ${coverage.historical_validation.additional_symbols_required ?? 0} 只。`, `Historical validation window: ${coverage.historical_validation.eligible_symbols}/${coverage.historical_validation.universe_symbols ?? coverage.universe_symbols} (${coverage.historical_validation.coverage_pct ?? 0}% / target ${coverage.historical_validation.target_pct ?? 90}%); ${coverage.historical_validation.additional_symbols_required ?? 0} more symbols needed.`)}</p> : null}{coverage?.backfill_quota?.provider_quota_lock ? <p>{label(lang, `历史回填已因 Longbridge 本月额度限制暂停（${coverage.backfill_quota.provider_error_code ?? "provider response"}）。请在 ${localTime(coverage.backfill_quota.next_recheck_at)} 后重新预检；系统不会自动发起请求。`, `Historical backfill is paused by the Longbridge monthly quota (${coverage.backfill_quota.provider_error_code ?? "provider response"}). Recheck after ${localTime(coverage.backfill_quota.next_recheck_at)}; KQUANT will not send requests automatically.`)}</p> : null}</div>
        <div className="settings-card wide"><strong>{label(lang, "主题分类审计", "Theme taxonomy audit")}</strong><p>{taxonomy?.status === "materialized" ? `${taxonomy.taxonomy_version} / as of ${taxonomy.as_of_date} / ${taxonomy.summary?.registry_symbol_count ?? 0} symbols` : "Theme taxonomy snapshot not materialized"}</p>{taxonomy?.summary ? <p>Mapped {taxonomy.summary.mapped_coverage_pct ?? 0}% · explicit review {taxonomy.summary.unmapped_theme_symbols ?? 0} · gate {taxonomy.summary.target_met ? "PASS" : "REVIEW"}</p> : null}{taxonomy?.definitions ? <p>{taxonomy.definitions.slice(0, 8).map((item) => `${item.display_name}: ${item.membership_count}`).join(" · ")}</p> : null}</div>
        <div className="settings-card wide"><strong>{label(lang, "主题轮动基线", "Capital Rotation baseline")}</strong><p>{rotation?.status === "materialized" ? `${rotation.summary?.ranked_theme_count ?? 0} ranked themes / as of ${rotation.as_of_time ?? "-"}` : "Capital Rotation snapshot not materialized"}</p>{rotation?.summary ? <p>Source {rotation.summary.data_source ?? "-"} · stress flips {rotation.summary.stress_direction_flips ?? 0} · unreasonable {rotation.summary.stress_unreasonable_flips ?? 0}</p> : null}{rotation?.scores?.filter((item) => item.score !== null && item.score !== undefined).slice(0, 5).map((item) => <p key={item.definition_id}>{`${item.rank_value ?? "-"}. ${item.definition_id} ${Number(item.score).toFixed(1)} / ${item.eligible_member_count} members`}</p>)}</div>
        <div className="settings-card wide"><strong>Theme Prediction evidence</strong><p>{themePrediction?.status === "materialized" ? `${themePrediction.prediction_version ?? "v1"} / ${themePrediction.gate_status ?? "review"}` : "Theme prediction evidence not materialized"}</p><p>{themePrediction?.summary?.calibration_gate ? `OOS folds ${themePrediction.summary.calibration_gate.observed_oos_folds ?? 0}/${themePrediction.summary.calibration_gate.minimum_oos_folds ?? 3} / probabilities ${themePrediction.summary.display_probability ? "enabled" : "blocked"}` : "Calibration evidence is required before probability display."}</p></div>
        <div className="settings-card wide"><strong>{label(lang, "主题领导力", "Theme leadership")}</strong><p>{leadership?.status === "materialized" ? `${leadership.summary?.unique_symbol_count ?? 0} stocks / ${leadership.summary?.theme_membership_count ?? 0} memberships / as of ${leadership.as_of_time ?? "-"}` : "Leadership snapshot not materialized"}</p>{leadership?.summary?.state_counts ? <p>{Object.entries(leadership.summary.state_counts).map(([state, count]) => `${state}: ${count}`).join(" · ")}</p> : null}<p>{leadership?.summary?.future_prediction_used ? "Blocked: future theme prediction detected." : "Uses only the same-timestamp rotation snapshot."}</p></div>
        <div className="settings-card wide"><strong>{settingText("consumerSafetyCopy", "Safety boundary")}</strong><p>{settingText("consumerSafetyText", "KQUANT is a read-only research terminal. It does not read accounts or submit orders.")}</p></div>
        <div className="settings-card wide"><strong>{settingText("journalDesign", "Journal")}</strong><p>{settingText("journalDesignText", "Manual notes and review evidence stay local to this research workspace.")}</p></div>
        <section className="notification-settings-band">
          <div className="notification-settings-head"><div><BellRing size={18} /><strong>{label(lang, "iPhone 主动提醒", "iPhone notifications")}</strong><p>{label(lang, "将 KQUANT 添加到 iPhone 主屏幕后，可在锁屏和通知中心收到提醒。", "Add KQUANT to the iPhone Home Screen to receive lock-screen alerts.")}</p></div><span className={pushStatus?.active_subscriptions ? "push-status active" : "push-status"}>{pushStatus?.active_subscriptions ? label(lang, "已连接", "Connected") : label(lang, "未连接", "Not connected")}</span></div>
          <div className="notification-preferences"><label>{label(lang, "静默开始", "Quiet from")}<input type="time" value={preferences?.quiet_start ?? "22:30"} onChange={(event) => setPreferences((current) => current ? { ...current, quiet_start: event.target.value } : current)} /></label><label>{label(lang, "静默结束", "Quiet until")}<input type="time" value={preferences?.quiet_end ?? "08:00"} onChange={(event) => setPreferences((current) => current ? { ...current, quiet_end: event.target.value } : current)} /></label><label>{label(lang, "每日普通提醒上限", "Daily routine limit")}<input type="number" min="1" max="20" value={preferences?.daily_routine_limit ?? 5} onChange={(event) => setPreferences((current) => current ? { ...current, daily_routine_limit: Number(event.target.value) } : current)} /></label></div>
          <div className="notification-actions"><button type="button" className="primary-action" disabled={pushBusy || !pushStatus?.configured} onClick={() => void enablePush()}><BellRing size={15} />{label(lang, "在此设备启用", "Enable here")}</button><button type="button" className="secondary-action" disabled={pushBusy || !pushStatus?.active_subscriptions} onClick={() => void testPush()}>{label(lang, "发送测试", "Send test")}</button><button type="button" className="secondary-action" disabled={pushBusy || !preferences} onClick={() => void savePushPreferences()}>{label(lang, "保存偏好", "Save")}</button><button type="button" className="icon-action" title={label(lang, "关闭此设备提醒", "Disable notifications")} disabled={pushBusy || !pushStatus?.active_subscriptions} onClick={() => void disablePush()}><Trash2 size={15} /></button></div>
          {!pushStatus?.configured ? <p className="notification-note">{label(lang, "本机尚未配置 VAPID 密钥，暂时只能使用网页预警。", "VAPID keys are not configured; web alerts remain available.")}</p> : null}{pushMessage ? <p className="notification-note">{pushMessage}</p> : null}
        </section>
      </div>
    </section>
  );
}
