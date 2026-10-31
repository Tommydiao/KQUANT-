import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  publicDir: "unified-public",
  build: {
    outDir: "dist-unified",
    emptyOutDir: true,
    rollupOptions: { input: "unified.html" },
  },
  server: {
    port: 5180,
    proxy: { "/api": "http://127.0.0.1:8020" },
  },
});
