import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

const apiGatewayTarget = process.env.KAIMS_DEV_API_GATEWAY || "http://localhost:8010";
const monitoringTarget = process.env.KAIMS_DEV_MONITORING_ADAPTER || "http://localhost:8001";
const approvalTarget = process.env.KAIMS_DEV_APPROVAL_SERVICE || "http://localhost:8007";

export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      output: {
        // Keep every React-dependent transitive package with its UI family.
        // Misplacing scheduler/react-remove-scroll in a generic chunk creates
        // mutual ESM imports and prevents React from mounting in production.
        manualChunks(id) {
          if (!id.includes("node_modules")) return undefined;
          if (id.includes("@tanstack") || id.includes("use-sync-external-store")) return "vendor-tanstack";
          if (id.includes("lucide-react")) return "vendor-icons";
          if (
            id.includes("react-aria")
            || id.includes("@react-aria")
            || id.includes("@react-stately")
            || id.includes("@react-types")
            || id.includes("@internationalized")
            || id.includes("react-remove-scroll")
            || id.includes("react-style-singleton")
          ) return "vendor-accessibility";
          if (
            id.includes("react-dom")
            || id.includes("react-router")
            || id.includes("scheduler")
            || /node_modules[\\/]react[\\/]/.test(id)
          ) return "vendor-react";
          return "vendor-react";
        },
      },
    },
  },
  server: {
    proxy: {
      "/api-gateway": {
        target: apiGatewayTarget,
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api-gateway/, ""),
      },
      "/monitoring-adapter": {
        target: monitoringTarget,
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/monitoring-adapter/, ""),
      },
      "/approval-service": {
        target: approvalTarget,
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/approval-service/, ""),
      },
    },
  },
});
