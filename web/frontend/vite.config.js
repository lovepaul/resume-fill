import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

function statsPagePlugin() {
  const rewriteEntryPaths = (req, _res, next) => {
    if (!req.url) {
      next();
      return;
    }
    if (req.url === "/stats" || req.url === "/stats/") {
      req.url = "/stats/index.html";
    }
    if (req.url === "/nvwa" || req.url === "/nvwa/") {
      req.url = "/nvwa/index.html";
    }
    next();
  };

  return {
    name: "stats-page-rewrite",
    configureServer(server) {
      server.middlewares.use(rewriteEntryPaths);
    },
    configurePreviewServer(server) {
      server.middlewares.use(rewriteEntryPaths);
    }
  };
}

export default defineConfig({
  plugins: [react(), statsPagePlugin()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://127.0.0.1:8000",
        changeOrigin: true
      }
    }
  }
});
