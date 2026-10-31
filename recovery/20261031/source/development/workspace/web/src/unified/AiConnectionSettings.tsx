import { useState } from "react";
import { RefreshCw } from "lucide-react";
import { useOperationalResource } from "./useOperationalResource";

export default function AiConnectionSettings({ language }: { language: string }) {
  const zh = language === "zh";
  const [refresh, setRefresh] = useState(0);
  const result = useOperationalResource("/api/options/model-router/status", refresh);
  const status = result.data;
  const auth = status?.authentication;
  const test = status?.test_only;
  return <section className="option-section" aria-label={zh ? "AI接入" : "AI connection"}>
    <div className="section-title"><h2>{zh ? "AI接入" : "AI connection"}</h2><button className="quiet-button" title={zh ? "刷新本地状态" : "Refresh local status"} onClick={() => setRefresh(value => value + 1)}><RefreshCw size={16} /></button></div>
    {result.loading && !status ? <p role="status">{zh ? "正在读取本机配置" : "Reading local configuration"}</p> : null}
    {result.error ? <p role="alert">{zh ? "配置状态不可用" : "Configuration unavailable"}: {result.error}</p> : null}
    {status ? <><dl className="settings-lines">
      <div><dt>{zh ? "凭据" : "Credential"}</dt><dd>{auth?.credential_present ? (zh ? "已配置，尚不代表认证通过" : "Configured, authentication not implied") : (zh ? "未配置或不可读取" : "Missing or unreadable")} · {auth?.credential_source}</dd></div>
      <div><dt>{zh ? "端点" : "Endpoint"}</dt><dd>{auth?.effective_endpoint} · {auth?.endpoint_match ? (zh ? "官方端点" : "Official endpoint") : (zh ? "配置不一致，调用阻断" : "Mismatch; calls blocked")}</dd></div>
      <div><dt>{zh ? "共享预算" : "Shared budget"}</dt><dd>{status.budget_approved ? (zh ? "已批准" : "Approved") : (zh ? "未批准，付费调用关闭" : "Not approved; paid calls disabled")}</dd></div>
      <div><dt>{zh ? "运行身份" : "Runtime identity"}</dt><dd>{status.runtime_identity ?? "—"}</dd></div>
    </dl><h3>{zh ? "本次隔离验收" : "Isolated acceptance test"}</h3>
    <p>{zh ? "密钥请在运行主机使用 Setup-KQUANT-AI.cmd 输入；此页面不接收密钥。正式自动调用保持关闭。" : "Enter the key locally with Setup-KQUANT-AI.cmd on the host. This page never accepts secrets. Production automatic calls remain disabled."}</p>
    <dl className="settings-lines">
      <div><dt>{zh ? "授权状态" : "Approval status"}</dt><dd>{test?.status ?? "UNAVAILABLE"} · {test?.expires_at ?? "—"}</dd></div>
      <div><dt>{zh ? "跨模型总额 / 单次" : "Combined / per assessment"}</dt><dd>${test?.total_usd ?? "—"} / ${test?.per_assessment_usd ?? "—"} · {zh ? "已结算或保留" : "Settled or reserved"} ${test?.committed_usd ?? "—"}</dd></div>
      <div><dt>{zh ? "凭据绑定" : "Credential binding"}</dt><dd>{test?.credential_binding ?? "NOT_BOUND"}</dd></div>
    </dl><div className="copilot-status-grid">{["SOL", "ASTRA"].map(role => {
      const row = status.roles?.[role] ?? {};
      const isolated = test?.roles?.[role] ?? {};
      return <div key={role}><strong>{role} · {row.requested_model_id}</strong><dl className="settings-lines">
        <div><dt>{zh ? "模型访问" : "Model access"}</dt><dd>{row.capability?.status ?? "NOT_CHECKED"}</dd></div>
        <div><dt>{zh ? "核验时间" : "Checked at"}</dt><dd>{row.capability?.checked_at ?? "—"}</dd></div>
        <div><dt>{zh ? "访问证据端点" : "Evidence endpoint"}</dt><dd>{row.capability?.endpoint ?? "—"}</dd></div>
        <div><dt>{zh ? "配置指纹" : "Configuration fingerprint"}</dt><dd>{row.capability?.configuration_hash?.slice(0, 16) ?? (zh ? "旧记录未绑定配置" : "Legacy record not bound")}</dd></div>
        <div><dt>{zh ? "真实响应" : "Real response"}</dt><dd>{row.real_response_status ?? "NOT_VERIFIED"}</dd></div>
        <div><dt>{zh ? "工具往返" : "Tool round trip"}</dt><dd>{row.tool_roundtrip_status ?? "NOT_VERIFIED"}</dd></div>
        <div><dt>{zh ? "付费调用" : "Paid calls"}</dt><dd>{row.paid_call_ready ? "READY" : "DISABLED"}</dd></div>
        <div><dt>{zh ? "隔离真实响应" : "Isolated real response"}</dt><dd>{isolated.assessment_state ?? "NOT_RUN"} · {isolated.actual_model ?? "—"}</dd></div>
        <div><dt>{zh ? "隔离工具往返" : "Isolated tool round trip"}</dt><dd>{isolated.tool_roundtrip ?? "NOT_VERIFIED"}</dd></div>
      </dl></div>;
    })}</div></> : null}
  </section>;
}
