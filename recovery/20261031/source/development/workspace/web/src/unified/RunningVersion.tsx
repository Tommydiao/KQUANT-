import { useRef } from "react";
import { useOperationalResource } from "./useOperationalResource";

export default function RunningVersion({ language }: { language: string }) {
  const resource = useOperationalResource("/api/workspace/version", 0, true);
  const initial = useRef<string | null>(null);
  const id = resource.data?.release_id;
  if (id && !initial.current) initial.current = id;
  return <span className="running-version" title={resource.data?.build_sha256}>
    {initial.current ?? (language === "zh" ? "版本待读取" : "Version pending")}
    {id && initial.current !== id ? <button onClick={() => window.location.reload()}>{language === "zh" ? "新版本可用，完成当前操作后刷新" : "Update available; refresh after finishing this action"}</button> : null}
  </span>;
}
