import { execFileSync } from "node:child_process";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

function gitValue(args: string[], fallback = "unknown") {
  try {
    return execFileSync("git", args, { encoding: "utf8" }).trim() || fallback;
  } catch {
    return fallback;
  }
}

const buildSha = process.env.KQUANT_BUILD_SHA || gitValue(["rev-parse", "HEAD"]);
const buildTime = process.env.KQUANT_BUILD_TIME || new Date().toISOString();
const buildEnvironment = process.env.KQUANT_ENVIRONMENT || process.env.VERCEL_ENV || "local";

export default defineConfig({
  plugins: [react()],
  define: {
    __KQUANT_BUILD_SHA__: JSON.stringify(buildSha),
    __KQUANT_BUILD_TIME__: JSON.stringify(buildTime),
    __KQUANT_BUILD_ENVIRONMENT__: JSON.stringify(buildEnvironment),
  },
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8000",
      "/stream": "http://127.0.0.1:8000"
    }
  }
});
