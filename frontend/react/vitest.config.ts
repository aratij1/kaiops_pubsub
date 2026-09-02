import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    include: ["src/**/*.test.{ts,tsx}"],
    exclude: ["tests/e2e/**", "node_modules/**", "dist/**"],
    // The development stack commonly runs beside this suite. Bounding workers
    // prevents process-start timeouts that otherwise skip test files silently.
    maxWorkers: 1,
  },
});
