// Smart Ring service worker — Tier B (offline shell).
//
// Strategies:
//   - Navigation (mode: navigate) → network-first, fallback to cached "/"
//   - /api/* GET                  → network-first, fallback to last-good cached
//   - /api/mobile/sync POST       → network-only (never cache; surface errors to UI)
//   - Cross-origin CDN (Alpine/Tailwind) → stale-while-revalidate
//   - Same-origin static          → cache-first
//
// Bump CACHE_VERSION on any change to precache assets or strategy. The activate
// handler purges all caches not in KEEP_CACHES.

const CACHE_VERSION = "v1";
const STATIC_CACHE = `stan-ring-static-${CACHE_VERSION}`;
const RUNTIME_CACHE = `stan-ring-runtime-${CACHE_VERSION}`;
const KEEP_CACHES = new Set([STATIC_CACHE, RUNTIME_CACHE]);

// Shell assets that must be available offline. Alpine + Tailwind are CDN
// (both send Access-Control-Allow-Origin: *), so mode: 'cors' precache works.
const PRECACHE_URLS = [
  "/",
  "/manifest.webmanifest",
  "/static/index.html",
  "/static/icon-192.png",
  "/static/icon-512.png",
  "/static/icon-apple-180.png",
  "https://cdn.jsdelivr.net/npm/alpinejs@3.14.1/dist/cdn.min.js",
  "https://cdn.tailwindcss.com",
];

self.addEventListener("install", (event) => {
  event.waitUntil(
    (async () => {
      const cache = await caches.open(STATIC_CACHE);
      // Best-effort precache: if a single asset fails, the SW still installs.
      // Each add() is its own atomic request so partial success is preserved.
      await Promise.allSettled(
        PRECACHE_URLS.map(async (url) => {
          // Use no-cache so we don't pin stale Alpine/Tailwind at install time.
          const res = await fetch(url, {
            mode: url.startsWith("http") ? "cors" : "same-origin",
            cache: "no-cache",
          });
          if (res.ok) await cache.put(url, res);
        })
      );
      await self.skipWaiting();
    })()
  );
});

self.addEventListener("activate", (event) => {
  event.waitUntil(
    (async () => {
      const keys = await caches.keys();
      await Promise.all(
        keys.filter((k) => !KEEP_CACHES.has(k)).map((k) => caches.delete(k))
      );
      await self.clients.claim();
    })()
  );
});

self.addEventListener("fetch", (event) => {
  const req = event.request;
  const url = new URL(req.url);

  // Never touch non-GET/HEAD (other than letting POSTs pass through to network).
  // The mobile sync POST must hit the real API — never cached, never faked.
  if (req.method !== "GET") return;

  // Same-origin /api/* → network-first, fall back to last-good cached response.
  if (url.origin === self.location.origin && url.pathname.startsWith("/api/")) {
    event.respondWith(networkFirst(req));
    return;
  }

  // Navigations → network-first for fresh HTML, fall back to cached shell.
  if (req.mode === "navigate") {
    event.respondWith(networkFirst(req, "/"));
    return;
  }

  // Cross-origin CDN (Alpine/Tailwind) → stale-while-revalidate.
  if (url.origin !== self.location.origin) {
    event.respondWith(staleWhileRevalidate(req));
    return;
  }

  // Everything else same-origin (static, icons) → cache-first.
  event.respondWith(cacheFirst(req));
});

async function cacheFirst(req) {
  const cached = await caches.match(req);
  if (cached) return cached;
  try {
    const res = await fetch(req);
    if (res.ok) {
      const cache = await caches.open(RUNTIME_CACHE);
      cache.put(req, res.clone());
    }
    return res;
  } catch (e) {
    // No cache, no network. Return an empty Response so the caller doesn't crash.
    return new Response("", { status: 504, statusText: "Offline" });
  }
}

async function networkFirst(req, fallbackUrl) {
  try {
    const res = await fetch(req);
    if (res && res.ok) {
      const cache = await caches.open(RUNTIME_CACHE);
      cache.put(req, res.clone());
    }
    return res;
  } catch (e) {
    const cached = await caches.match(req);
    if (cached) return cached;
    if (fallbackUrl) {
      const fallback = await caches.match(fallbackUrl);
      if (fallback) return fallback;
    }
    return new Response("", { status: 504, statusText: "Offline" });
  }
}

async function staleWhileRevalidate(req) {
  const cache = await caches.open(RUNTIME_CACHE);
  const cached = await cache.match(req);
  const network = fetch(req)
    .then((res) => {
      if (res && res.ok) cache.put(req, res.clone());
      return res;
    })
    .catch(() => cached || new Response("", { status: 504, statusText: "Offline" }));
  return cached || network;
}

// Allow page to trigger immediate SW takeover after a new version activates.
self.addEventListener("message", (event) => {
  if (event.data === "skipWaiting") self.skipWaiting();
});
