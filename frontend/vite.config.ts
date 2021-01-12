import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { readdirSync, readFileSync, writeFileSync } from "node:fs";
import { createHash } from "node:crypto";

export default defineConfig({
  plugins: [
    react(),
    {
      name: "gridsense-offline-shell",
      closeBundle() {
        const assets = readdirSync("dist/assets").map(
          (file) => `/assets/${file}`,
        );
        const hash = createHash("sha256")
          .update(readFileSync("dist/index.html"))
          .digest("hex")
          .slice(0, 12);
        const precache = JSON.stringify(["/", "/favicon.svg", ...assets]);
        writeFileSync(
          "dist/sw.js",
          `
const CACHE = 'gridsense-${hash}';
const FILES = ${precache};
self.addEventListener('install', event => {
  event.waitUntil(caches.open(CACHE).then(cache => cache.addAll(FILES)).then(() => self.skipWaiting()));
});
self.addEventListener('activate', event => {
  event.waitUntil(caches.keys().then(keys => Promise.all(keys.filter(key => key.startsWith('gridsense-') && key !== CACHE).map(key => caches.delete(key)))).then(() => self.clients.claim()));
});
self.addEventListener('fetch', event => {
  const url = new URL(event.request.url);
  if (event.request.method !== 'GET' || url.origin !== location.origin || url.pathname.startsWith('/api/')) return;
  event.respondWith(caches.match(event.request).then(cached => cached || fetch(event.request)));
});
`,
        );
      },
    },
  ],
  server: {
    proxy: { "/api": process.env.VITE_API_TARGET || "http://127.0.0.1:8788" },
  },
});
