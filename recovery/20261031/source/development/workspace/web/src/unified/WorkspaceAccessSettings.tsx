import { useState } from "react";
import { RefreshCw } from "lucide-react";
import { useOperationalResource } from "./useOperationalResource";

export default function WorkspaceAccessSettings({ language }: { language: string }) {
  const zh = language === "zh";
  const [refresh, setRefresh] = useState(0);
  const result = useOperationalResource("/api/auth/session", refresh);
  const session = result.data;
  const state = session?.restart_required ? "RESTART_REQUIRED" : session?.authentication_required
    ? session.configured ? session.authenticated ? "ACTIVE" : "SIGN_IN_REQUIRED" : "SETUP_REQUIRED"
    : "NOT_CONFIGURED";
  return <section className="option-section" aria-label={zh ? "工作台登录" : "Workspace login"}>
    <div className="section-title"><h2>{zh ? "工作台登录" : "Workspace login"}</h2><button className="quiet-button" title={zh ? "刷新登录状态" : "Refresh login state"} onClick={() => setRefresh(value => value + 1)}><RefreshCw size={16} /></button></div>
    {result.error ? <p role="alert">{zh ? "登录状态不可用" : "Login status unavailable"}: {result.error}</p> : null}
    <dl className="settings-lines"><div><dt>{zh ? "当前状态" : "Current status"}</dt><dd>{result.loading && !session ? (zh ? "正在检查" : "Checking") : state}</dd></div>
      <div><dt>{zh ? "登录账号" : "Login account"}</dt><dd>{session?.email ?? (zh ? "仅在本机设置后显示" : "Shown after local setup")}</dd></div></dl>
    <p>{zh ? "在运行主机双击 Setup-KQUANT-Login.cmd，自行设置或重设邮箱和至少12位密码。通过原启动器重启后生效；重设会使旧会话失效。" : "On the host, run Setup-KQUANT-Login.cmd to set or reset your email and a 12+ character password. Restart with the existing launcher; resetting invalidates previous sessions."}</p>
  </section>;
}
