// TEST_ONLY recovery config; the archived unified tsconfig is not auto-discovered.
import { defineConfig } from "vitest/config";

export default defineConfig({
  esbuild: { jsx: "automatic" },
  test: { include: ["src/**/*.test.{ts,tsx}"] },
});
