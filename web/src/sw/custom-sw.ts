// @ts-nocheck — runs in WebWorker context, not DOM; types unavailable
// Smart Ring service worker — React port (vite-plugin-pwa injectManifest).
// Bump CACHE_VERSION on any change to precache or strategy.
// The activate handler purges old caches not in KEEP_CACHES.

const CACHE_VERSION = "v2"; // bumped from v1 (legacy Alpine)
const STATIC_CACHE = `stan-ring-static-${CACHE_VERSION}`;
const RUNTIME_CACHE = `stan-ring-runtime-${CACHE_VERSION}`;
const KEEP_CACHES = new Set([STATIC_CACHE, RUNTIME_CACHE]);

const sw = self as unknown as ServiceWorkerGlobalScope;

sw.addEventListener("activate", (event: ExtendableEvent) => {
  event.waitUntil(
    (async () => {
      const keys = await caches.keys();
      await Promise.all(
        keys.filter((k) => !KEEP_CACHES.has(k)).map((k) => caches.delete(k))
      );
      await sw.clients.claim();
    })()
  );
});

sw.addEventListener("fetch", (event: FetchEvent) => {
  const req = event.request;
  const url = new URL(req.url);

  if (req.method !== "GET") return;

  // Same-origin /api/* → network-first
  if (url.origin === sw.location.origin && url.pathname.startsWith("/api/")) {
    event.respondWith(networkFirst(req));
    return;
  }

  // Navigations → network-first, fall back to cached "/"
  if (req.mode === "navigate") {
    event.respondWith(networkFirst(req, "/"));
    return;
  }

  // Everything else → cache-first
  event.respondWith(cacheFirst(req));
});

async function cacheFirst(req: Request): Promise<Response> {
  const cached = await caches.match(req);
  if (cached) return cached;
  try {
    const res = await fetch(req);
    if (res.ok) {
      const cache = await caches.open(RUNTIME_CACHE);
      cache.put(req, res.clone());
    }
    return res;
  } catch {
    return new Response("", { status: 504, statusText: "Offline" });
  }
}

async function networkFirst(req: Request, fallbackUrl?: string): Promise<Response> {
  try {
    const res = await fetch(req);
    if (res && res.ok) {
      const cache = await caches.open(RUNTIME_CACHE);
      cache.put(req, res.clone());
    }
    return res;
  } catch {
    const cached = await caches.match(req);
    if (cached) return cached;
    if (fallbackUrl) {
      const fallback = await caches.match(fallbackUrl);
      if (fallback) return fallback;
    }
    return new Response("", { status: 504, statusText: "Offline" });
  }
}

sw.addEventListener("message", (event: ExtendableMessageEvent) => {
  if (event.data === "skipWaiting") sw.skipWaiting();
});
