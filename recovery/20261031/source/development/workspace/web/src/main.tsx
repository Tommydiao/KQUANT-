import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import { canonicalWorkspaceUrl, symbolFromSearch, viewFromSearch, workspaceFromSearch } from "./unified/workspace";
import "./styles.css";

const legacyPorts = new Set(["8001", "8002"]);
const shouldRedirect = import.meta.env.PROD && legacyPorts.has(window.location.port);

if (shouldRedirect) {
  const workspace = workspaceFromSearch(window.location.search);
  const view = viewFromSearch(window.location.search, workspace);
  const symbol = symbolFromSearch(window.location.search, workspace);
  const destination = new URL(window.location.href);
  destination.port = import.meta.env.VITE_KQUANT_GATEWAY_PORT || "8020";
  destination.pathname = "/";
  const canonical = canonicalWorkspaceUrl(destination.href, workspace, view, symbol);
  window.location.replace(`${destination.origin}${canonical}`);
} else {
  ReactDOM.createRoot(document.getElementById("root")!).render(
    <React.StrictMode>
      <App />
    </React.StrictMode>,
  );
}

if (import.meta.env.PROD && "serviceWorker" in navigator) {
  window.addEventListener("load", () => {
    void navigator.serviceWorker.register("/service-worker.js", { updateViaCache: "none" });
  });
}
