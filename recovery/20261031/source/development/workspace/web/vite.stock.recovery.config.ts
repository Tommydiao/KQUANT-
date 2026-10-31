// TEST_ONLY reconstruction; the original stock build config remains missing.
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  publicDir: "stock-public",
  build: {
    outDir: "dist-stock",
    emptyOutDir: true,
    rollupOptions: { input: "index.html" },
  },
});
