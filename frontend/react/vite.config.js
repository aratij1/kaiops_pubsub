import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  build: {
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (!id.includes("node_modules")) return undefined;
          if (id.includes("react-dom") || id.includes("react-router") || /node_modules[\\/]react[\\/]/.test(id)) return "vendor-react";
          if (id.includes("@tanstack")) return "vendor-tanstack";
          if (id.includes("lucide-react")) return "vendor-icons";
          if (id.includes("react-aria")) return "vendor-accessibility";
          return "vendor-shared";
        },
      },
    },
  },
  server: {
    proxy: {
      "/api-gateway": {
        target: "http://localhost:8010",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api-gateway/, ""),
      },
      "/monitoring-adapter": {
        target: "http://localhost:8001",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/monitoring-adapter/, ""),
      },
      "/approval-service": {
        target: "http://localhost:8007",
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/approval-service/, ""),
      },
    },
  },
});
