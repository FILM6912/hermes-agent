import path from "path";
import type { Plugin } from "vite";
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

/** Dev-only: valid JS in index.html; production build keeps FastAPI placeholders. */
function hermesIndexHtmlPlaceholders(): Plugin {
  return {
    name: "hermes-index-html-placeholders",
    apply: "serve",
    transformIndexHtml(html) {
      const csrf = JSON.stringify(
        process.env.VITE_HERMES_CSRF_TOKEN?.trim() ||
          process.env.HERMES_CSRF_TOKEN?.trim() ||
          "",
      );
      const maxBytes = process.env.VITE_MAX_UPLOAD_BYTES?.trim() || "20971520";
      return html
        .replace(/__CSRF_TOKEN_JSON__/g, csrf)
        .replace(/__MAX_UPLOAD_BYTES__/g, maxBytes);
    },
  };
}

export default defineConfig(() => {
  const hermesPort = process.env.HERMES_WEBUI_PORT || "8789";
  const hermesTarget = `http://localhost:${hermesPort}`;

  return {
    test: {
      environment: "node",
      include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
    },
    server: {
      port: 5173,
      host: "0.0.0.0",
      proxy: {
        "/api": {
          target: hermesTarget,
          changeOrigin: true,
          secure: false,
        },
      },
    },
    plugins: [react(), tailwindcss(), hermesIndexHtmlPlaceholders()],
    resolve: {
      alias: {
        "@": path.resolve(__dirname, "./src"),
      },
    },
    base: "/",
    worker: {
      format: "es" as const,
      rollupOptions: {
        output: {
          format: "es" as const,
        },
      },
    },
    optimizeDeps: {
      exclude: ["@extend-ai/react-xlsx"],
    },
    build: {
      outDir: path.resolve(__dirname, "../static/dist"),
      emptyOutDir: true,
    },
  };
});
