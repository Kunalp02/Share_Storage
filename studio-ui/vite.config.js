import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  const proxy = (prefix, target) => ({
    target,
    changeOrigin: true,
    rewrite: (path) => path.replace(new RegExp(`^${prefix}`), ""),
    configure: (server) => {
      server.on("error", (error, _req, res) => {
        if (!res || res.headersSent || typeof res.writeHead !== "function") return;
        res.writeHead(502, { "Content-Type": "application/json" });
        res.end(JSON.stringify({
          code: "UPSTREAM_UNREACHABLE",
          message: `Could not reach ${target}. Set that service URL in studio-ui/.env and restart npm run dev. ${error.message}`,
        }));
      });
    },
  });
  return {
    plugins: [react()],
    server: {
      host: "0.0.0.0",
      port: 5173,
      proxy: {
        "/platform/auth": proxy("/platform/auth", env.AUTH_SERVICE_URL || "http://127.0.0.1:8500"),
        "/platform/agents": proxy("/platform/agents", env.AGENT_CONFIG_URL || "http://127.0.0.1:8504"),
        "/platform/execution": proxy("/platform/execution", env.EXECUTION_SERVICE_URL || "http://127.0.0.1:8765"),
        "/platform/storage": proxy("/platform/storage", env.STORAGE_SERVICE_URL || "http://127.0.0.1:8770"),
      },
    },
  };
});
