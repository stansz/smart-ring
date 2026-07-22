# PWA Plan — Stan's Ring Dashboard

> Turn the dashboard into an installable, offline-capable Progressive Web App.
> **Status:** shipped on `feature/pwa-offline-shell` (2026-07-21).

## Why

The dashboard is already mobile-friendly and served over HTTPS via Tailscale.
Wrapping it as a PWA gives:

- **Install to home screen** on iOS/Android/desktop — opens in its own window,
  no browser chrome, custom icon.
- **Offline shell** — UI loads without network (Alpine + Tailwind + HTML
  precached). Data goes stale but the dashboard never goes white.
- **No build step** — pure static files, matches the existing no-build
  philosophy (Alpine + Tailwind via CDN).

## What was added

### Files
| File | Purpose |
|------|---------|
| `dashboard/manifest.webmanifest` | Name, theme colors, display mode, icon refs |
| `dashboard/sw.js` | Service worker — install/activate/fetch handlers |
| `dashboard/icon-192.png`, `icon-512.png` | Regular icons (transparent bg) |
| `dashboard/icon-maskable-192.png`, `icon-maskable-512.png` | Android adaptive icons (full-bleed bg, ring in 80% safe zone) |
| `dashboard/icon-apple-180.png` | iOS home-screen + splash icon (solid bg, no alpha) |
| `scripts/gen_icons.py` | One-shot Pillow script that regenerates all five PNGs |

### Edits
- `dashboard/index.html` — `<head>` got `<link rel="manifest">`, `theme-color`,
  `apple-touch-icon`, `apple-mobile-web-app-*` meta tags; `<body>` got a small
  SW registration block before `</body>`.
- `api/main.py` — two new routes alongside `/`:
  - `GET /sw.js` — served with `Service-Worker-Allowed: /` so it can claim root
    scope (a SW at `/static/sw.js` would only control `/static/`).
  - `GET /manifest.webmanifest` — served with the correct media type.

## Service worker strategies

| Request | Strategy |
|---------|----------|
| Navigation (`mode: navigate`) | Network-first → cached `/` |
| `/api/*` GET | Network-first → last-good cached response |
| `/api/mobile/sync` POST | Network-only (never cached — errors surface to UI banner) |
| Cross-origin CDN (Alpine, Tailwind) | Stale-while-revalidate |
| Same-origin `/static/*` | Cache-first |

Bump `CACHE_VERSION` in `sw.js` (`v1` → `v2`) on any precache change; the
activate handler auto-purges old caches. `self.skipWaiting()` +
`clients.claim()` mean the new SW takes over on next navigation.

## Verification checklist

- [x] 132/132 pytest suite passes (no Python logic changes)
- [x] `GET /manifest.webmanifest` returns `200 application/manifest+json`
- [x] `GET /sw.js` returns `200 text/javascript` with `Service-Worker-Allowed: /`
- [x] All five icons return `200 image/png` via `/static/*`
- [x] Service active after restart

### Manual checks (on phone via Tailscale URL)
- [ ] **iOS Safari** → Share → Add to Home Screen → icon appears, launches
      standalone (no Safari chrome), status bar styled.
- [ ] **Chrome desktop / Android** → visit → install prompt appears in
      address bar → app installs to launcher.
- [ ] **Offline** → DevTools → Network → Offline → reload → UI still renders
      with last-cached data, no white screen.
- [ ] **Chrome DevTools → Application → Manifest** shows zero installability
      blockers; **Service Workers** panel shows the SW registered and running.

## Icon regeneration

```bash
venv/bin/python3 scripts/gen_icons.py
```

Pillow is required (`venv/bin/pip install pillow`). The script draws a ring
(two concentric circles in `#2563eb`) on the appropriate background per
variant. To retheme, edit the `THEME`, `BG_DARK`, `RING_HIGHLIGHT` constants
at the top of `scripts/gen_icons.py` and rerun.

## Out of scope (future work)

- **Tier C (full offline)** — IndexedDB-cached API responses with TTLs +
  background sync queue for `/api/mobile/sync` retries. Useful if Tailscale
  drops mid-phone-sync.
- **Push notifications** — would need a push service + VAPID keys + UI for
  opt-in. Probably never needed for a single-user system.
- **Self-hosted CDN assets** — currently precache Alpine/Tailwind via the CDN
  URLs (both send `Access-Control-Allow-Origin: *`). If you want to drop the
  CDN entirely, that's a separate change.

## iOS quirks (worth knowing)

iOS does **not** support the Web Install API. Users must manually:
**Share → Add to Home Screen**. There's no install prompt.

iOS PWAs get separate storage from Safari — currently no auth flow exists, so
this is invisible, but if auth is added later the PWA will need to sign in
independently.

`apple-mobile-web-app-status-bar-style: black-translucent` makes the iOS
status bar overlay the gray header — looks correct in both light and dark
themes.
