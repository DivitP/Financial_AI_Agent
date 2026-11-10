import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import { randomBytes } from "node:crypto";

export default defineConfig(({ command }) => {
  const nonce = randomBytes(24).toString("base64");
  const policy = (dev: boolean) =>
    `default-src 'self'; script-src 'self'${dev ? " 'nonce-" + nonce + "'" : ""}; style-src 'self'${dev ? " 'nonce-" + nonce + "'" : ""}; img-src 'self' data:; connect-src 'self'${dev ? " ws://localhost:5173 ws://127.0.0.1:5173" : ""}; object-src 'none'; base-uri 'none'; form-action 'self'`;
  const headers = {
    "Content-Security-Policy": policy(command === "serve") + "; frame-ancestors 'none'",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
  };
  return {
    html: { cspNonce: command === "serve" ? nonce : undefined },
    plugins: [
      react(),
      {
        name: "production-csp",
        apply: "build",
        transformIndexHtml() {
          return [
            {
              tag: "meta",
              attrs: { "http-equiv": "Content-Security-Policy", content: policy(false) },
              injectTo: "head",
            },
          ];
        },
      },
    ],
    server: { headers, cors: false, port: 5173, proxy: { "/api": "http://127.0.0.1:8000" } },
    preview: { headers, cors: false },
    test: {
      environment: "jsdom",
      setupFiles: ["./src/test/setup.ts"],
      exclude: ["e2e/**", "node_modules/**"],
    },
  };
});
