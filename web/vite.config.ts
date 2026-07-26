import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { VitePWA } from "vite-plugin-pwa";

export default defineConfig({
  plugins: [
    react(),
    VitePWA({
      registerType: "autoUpdate",
      workbox: {
        runtimeCaching: [
          {
            urlPattern: /^\/api\//,
            handler: "NetworkFirst",
            options: {
              cacheName: "api-cache",
              networkTimeoutSeconds: 5,
              expiration: { maxEntries: 200, maxAgeSeconds: 3600 },
            },
          },
        ],
      },
      manifest: {
        name: "Smart Ring",
        short_name: "Smart Ring",
        description: "Private health tracking with Colmi R09",
        theme_color: "#1e293b",
        background_color: "#f9fafb",
        display: "standalone",
        orientation: "portrait-primary",
        icons: [
          { src: "/icon-192.png", sizes: "192x192", type: "image/png" },
          { src: "/icon-512.png", sizes: "512x512", type: "image/png" },
          { src: "/icon-maskable-192.png", sizes: "192x192", type: "image/png", purpose: "maskable" },
          { src: "/icon-maskable-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
          { src: "/icon-apple-180.png", sizes: "180x180", type: "image/png" },
        ],
        shortcuts: [
          { name: "Dashboard", short_name: "Dashboard", url: "/static/" },
          { name: "Analytics", short_name: "Analytics", url: "/static/#analytics" },
        ],
      },
    }),
  ],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://localhost:8000",
      "/health": "http://localhost:8000",
    },
  },
  build: {
    outDir: "../dashboard/dist",
    emptyOutDir: true,
  },
  base: "/static/",
});
