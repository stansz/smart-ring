# Dashboard Rewrite Plan

Replace the 3,230-line monolithic `dashboard/index.html` with a componentized React + TypeScript
app while keeping the FastAPI backend untouched. Reach full feature parity, then cut over.
The legacy Alpine dashboard continues serving at `:8000` until the new app is feature-complete
and signed off.

> **Active-file warning:** `dashboard/index.html` is the most-changed file in the repo
> (5+ commits in recent history, latest days ago). The transition rules below (feature freeze,
> same-day mirroring) exist because of this — a 7-day rewrite against a moving target drifts.

---

## Process rules (read before starting)

1. **Legacy feature freeze.** From branch creation to cutover, `dashboard/index.html` is frozen
   except critical fixes. Any legacy change during the window is mirrored into the React app the
   same day, or the parity guarantee breaks.
2. **Parity, not enhancement.** New ideas go to `TASKS.md`. No net-new UI in this arc.
3. **Don't touch `dashboard/` until cutover.** The new app lives in a sibling `web/` dir and
   builds into `dashboard/dist/`. This sidesteps renaming `index.html` (which would break the
   existing service worker's `/static/index.html` precache for anyone installing mid-transition)
   and leaves FastAPI's `root()` / `/sw.js` / `/manifest.webmanifest` routes untouched until Phase 10.
4. **Pre-cutover phone test is mandatory.** The riskiest surface (Web Bluetooth, ~400 LOC)
   gets its first real-device test *before* cutover, via a Tailscale beta path — not after.

---

## Stack

| Layer | Choice | Note |
|---|---|---|
| Framework | React 19 + Vite 7 | `npm create vite@latest` scaffolds current majors; the earlier React 18 / Vite 5 pins were a generation behind and contradicted step 2 of Phase 0 |
| Language | TypeScript 5 | |
| Styling | Tailwind CSS 3 (PostCSS, not Play CDN) | Deliberately v3 not v4: v3's `tailwind.config.ts` palette matches the current Play CDN exactly (see Risks). v4's CSS-first `@theme` is a separate migration not worth bundling here |
| Data fetching | TanStack Query v5 | Replaces hand-rolled `setInterval` polling + manual refresh — the structural fix for the `da326d8` "refresh UI after mobile sync" bug class |
| Charts | Recharts 3 + 1 custom SVG (DayRing) | |
| Web Bluetooth | Custom `useRingSync` hook (port of existing logic, typed) | ~400 LOC, currently **100% untested** — the TS port is the moment to add unit tests (Phase 7) |
| PWA | `vite-plugin-pwa` (`injectManifest`) | Ports the existing `sw.js` strategies verbatim; preserves installability + offline shell (see Phase 8) |
| Tooling | ESLint + Prettier + Vitest | Vitest is mandatory, not optional — see Phase 7 |

---

## Dev topology

```
Phone (Android Chrome, via Tailscale HTTPS)        ← the real target
   │
   ├── https://mint.tail1b421.ts.net        (prod, legacy until cutover)
   │     └─ tailscale serve → 127.0.0.1:8000  (FastAPI → dashboard/index.html)
   │
   └── https://mint.tail1b421.ts.net/beta   (NEW: pre-cutover phone test)
         └─ tailscale serve → 127.0.0.1:4173  (Vite preview build)

Dev machine (browser)
   └── http://localhost:5173  (Vite HMR)
         └── /api/* proxied ──▶ http://localhost:8000  (FastAPI, untouched)
```

Tailscale is how the phone reaches the box and obtains the **secure context** that Web Bluetooth
and PWA install require — plain LAN HTTP works for neither. The dev proxy is for the dev browser
only; phone testing needs the beta path above.

| Tier | Port | Command | Purpose |
|---|---|---|---|
| Dev (HMR) | 5173 | `npm run dev` (in `web/`) | Active development, browser only |
| Preview | 4173 | `npm run build && npm run preview` | Verify production build + pre-cutover phone test via Tailscale `/beta` |
| Prod cutover | 8000 | Build → `dashboard/dist/`, FastAPI serves it | Final state |

---

## Project structure

New app lives in `web/`; `dashboard/` keeps legacy + receives build output.

```
web/                                ← NEW: the React app (Vite root)
├── package.json
├── vite.config.ts                  ← proxy /api → :8000; vite-plugin-pwa injectManifest;
│                                     build.outDir: '../dashboard/dist', emptyOutDir: true
├── tsconfig.json
├── tailwind.config.ts
├── postcss.config.js
├── .env.development                ← VITE_API_BASE=''
├── .env.production
├── public/
│   ├── manifest.webmanifest        ← ported from dashboard/ at Phase 8
│   └── icon-{192,512,apple-180,maskable-192,maskable-512}.png   ← moved at Phase 8
├── index.html                      ← Vite entry
└── src/
    ├── main.tsx
    ├── App.tsx                     ← tab router + providers
    ├── index.css                   ← Tailwind + chart polish
    ├── api/
    │   ├── client.ts               ← typed fetch wrapper
    │   ├── types.ts                ← response interfaces
    │   ├── hooks.ts                ← TanStack Query hooks per endpoint
    │   └── useSyncPolling.ts       ← refetchInterval replaces setInterval
    ├── components/
    │   ├── layout/   (Nav, Tabs, BatteryIndicator, DateNav)
    │   ├── charts/   (VitalsChart, CircadianChart, SleepDonut, TrendChart,
    │   │             MiniTrend, RecoveryBars, DayRing ← custom SVG)
    │   ├── cards/    (ReadinessHero, RecoveryCard, HrvCard, StressCard,
    │   │             SleepCard, VitalsCard, CircadianCard)
    │   ├── sync/     (SyncButton, ErrorBanner)
    │   ├── ble/      (useRingSync, ringProtocol, SyncProgressDialog, toasts)
    │   └── ui/       (Card, Skeleton, EmptyState)
    ├── tabs/        (DashboardTab, AnalyticsTab, AdminTab)
    ├── hooks/       (useTheme, useSelectedDate, useElapsedTimer)
    ├── utils/       (date, format, smoothPath, clipFuture)
    ├── types/       (api, ble)
    └── sw/
        └── custom-sw.ts            ← ported from dashboard/sw.js (Phase 8)

dashboard/                          ← unchanged until cutover
├── index.html                      ← LEGACY (frozen; untouched until Phase 10)
├── sw.js, manifest.webmanifest, *.png   ← legacy PWA assets (untouched until Phase 10)
└── dist/                           ← NEW: Vite build output (created on first build)
```

---

## Parity checklist

Generate the exhaustive per-feature list at Phase 1 start by walking `dashboard/index.html`.
The DoD items are the gates; this checklist is the working tracker. Features easy to drop:

- Stale-data banner (`staleTypes`), partial-confidence badges (readiness + current-status)
- Current Status vibe ladder + stress history + HRV slope
- Sync-log pagination, cancel-sync button, `clock_drift_ms` OK / No-ack display
- Analytics range toggles (7/14/30/90d), raw HR/Steps tables
- Toasts, screen wake-lock during phone sync
- 8 chart types incl. DayRing (radial bars + sleep overlay + click-to-navigate)

---

## Phases

### Phase 0 — Build infrastructure (reversible, low risk)
1. Branch `dashboard-react-rewrite`.
2. `npm create vite@latest web -- --template react-ts` (sibling dir — see Process rule 3).
3. Install deps: Tailwind 3 + PostCSS, @tanstack/react-query, recharts, vite-plugin-pwa, clsx,
   date-fns, eslint, prettier, vitest.
4. `vite.config.ts`: `server.port: 5173`, proxy `/api` + `/health` → `http://localhost:8000`;
   `build.outDir: '../dashboard/dist'`, `emptyOutDir: true`.
5. `npm run build` produces `dashboard/dist/`; verify `npm run dev` boots and `/api/health` proxied.
6. **Do NOT touch `api/main.py` yet.** Legacy keeps serving at `:8000` as-is.

**Checkpoint:** blank app at `:5173`, legacy untouched at `:8000`, build outputs to `dashboard/dist/`.

### Phase 1 — Type the API contract (the foundation)
1. Read every route in `api/main.py` — there are **32 handlers** (28 API + `/`, `/sw.js`,
   `/manifest.webmanifest`, `/health`), not 17.
2. Write `src/api/types.ts` with one interface per response.
3. Write typed `src/api/client.ts`.
4. Write `src/api/hooks.ts` — one TanStack Query hook per endpoint.
5. Wire `QueryClientProvider` in `App.tsx`. Generate the parity checklist here.

**Checkpoint:** typed fetches confirmed in React DevTools.

### Phase 2 — Layout shell + theme + date nav
1. `App.tsx`: tab state, renders one of three tab components.
2. `Nav.tsx`, `Tabs.tsx`, `BatteryIndicator.tsx`, `DateNav.tsx`.
3. `useTheme` hook (dark mode + localStorage).
4. `useSelectedDate` hook (prev/today/next).

**Checkpoint:** app shell renders, tabs switch, dark mode and date nav work.

### Phase 3 — Dashboard tab

**3a. Hero panel**
- `ReadinessHero.tsx` (uses `useReadiness(30)` filtered by selected date).
- `DayRing.tsx` — port `renderDayRing` + `_wireRingTooltip` verbatim, incl. click-to-navigate.
  Tooltips via local state + refs.

**3b. Stat cards** — Recovery, HRV, Stress, Sleep (one component each, mini-trends).

**3c. Charts**
- `VitalsChart.tsx` — Recharts ComposedChart, 2 YAxis (HR blue / SpO₂ teal), built-in crosshair.
- `CircadianChart.tsx` — AreaChart with gradient fill.
- `SleepDonut.tsx` — PieChart (deep/rem/light/awake).
- `MiniTrend.tsx` — BarChart for stat cards.

**3d. Raw tables** — HR + Steps, plain `<table>`, typed rows.

### Phase 4 — Analytics tab
- Static data-pipeline reference table.
- 4 score cards (Recovery/Sleep/Stress/RestingHR).
- `TrendChart.tsx` — 4 instances, range toggle (7/14/30/90d) drives query hook.

### Phase 5 — Admin tab
- Ring status, last sync summary, health checks, `clock_drift_ms` display.
- Sync log table with pagination.
- Sync requests queue.

### Phase 6 — Sync UX
- `SyncButton.tsx` — POST `/api/admin/sync`, then `useSyncPolling()`.
- `useSyncPolling` — TanStack Query `refetchInterval: 5000` (matches current) while pending/running.
- `ErrorBanner.tsx`, `useElapsedTimer`, **cancel button** → `/api/admin/cancel-sync`.
- On completion: `queryClient.invalidateQueries(['dashboard'])` auto-refreshes (the structural
  fix for the `da326d8` "refresh UI after mobile sync" bug class).

### Phase 7 — Web Bluetooth phone sync (~400 LOC) + protocol tests
1. `ringProtocol.ts` — UUIDs, `make16`, `makeBig`, packet parsers, typed.
2. **Write Vitest protocol tests first** — byte-level fixtures for `make16` / `makeBig` / parser
   framing. The JS BLE code is currently untested; mirror the philosophy of
   `tests/test_time_sync_bcd.py` (which pins the Python side byte-for-byte). This converts the
   scariest port into a verified one.
3. `useRingSync.ts` — port the IIFE verbatim. Exposes `syncFromPhone()` + progress state.
4. `SyncProgressDialog.tsx` — 12-phase progress UI, wake-lock, toasts.

### Phase 8 — PWA (port installability + offline shell)
1. Move `dashboard/manifest.webmanifest` + the 5 icons into `web/public/`.
2. Port `dashboard/sw.js` strategies into `web/src/sw/custom-sw.ts` (network-first `/api/*` +
   navigations, SWR for CDN, cache-first static, network-only for `/api/mobile/sync` POST).
   Wire via `vite-plugin-pwa` `injectManifest` — keeps your exact strategy table (`generateSW`
   would rewrite it).
3. **Bump the cache version** so installed PWAs drop the old precache on next visit (the legacy
   `/static/index.html` entry disappears at cutover; the `activate` purge handles old caches
   only if the new SW actually ships with a new version).
4. Verify: installs on Android Chrome, loads offline, `/api/mobile/sync` POST stays network-only.

### Phase 9 — Polish
- Loading skeletons for every async card.
- Empty states.
- `prefers-reduced-motion` respect.
- Verify dark mode across every component.

### Phase 10 — Cutover

**Pre-cutover gate (mandatory):** serve the preview build through Tailscale
(`tailscale serve --bg --set-path /beta http://127.0.0.1:4173`), install on the phone, run a real
BLE sync end-to-end. Do not proceed until green.

Then:
1. Run new app as primary for several days via the beta path; confirm ring data, sync, BLE.
2. **Pick a cutover mechanism** — the systemd unit bind-mounts `dashboard/` into the container
   (`--volume /opt/smart-ring/code/dashboard:/dashboard`), which **shadows** anything a
   multi-stage Dockerfile bakes into the image. So the Dockerfile change alone is a no-op:
   - **(a) Host build (recommended):** `npm run build` → `dashboard/dist/` (node 22 is already on
     the host). Flip `DASHBOARD_DIR` → `dashboard/dist` in `api/main.py`. The existing bind mount
     already exposes `dist/` — **no Dockerfile change, no image rebuild.** Restart
     `smart-ring-api.service`.
   - **(b) Multi-stage Dockerfile:** valid, but you must *also* drop the dashboard bind mount
     from the unit, and every future dashboard tweak becomes an image rebuild. Heavier for a
     solo project.
3. With either path, the `/`, `/sw.js`, `/manifest.webmanifest` routes in `api/main.py` already
   read from `DASHBOARD_DIR`, so flipping the dir serves the new shell + new SW + new manifest
   together.
4. Smoke test at `:8000` and via the Tailscale URL on the phone.
5. Delete `dashboard/index.html`, `sw.js`, `manifest.webmanifest`, old icons.
6. Update `AGENTS.md`: the dashboard row now reflects the build step (the old "no build" claim is
   retired). Note `docker-compose.yml` is stale vs the systemd units (compose binds `127.0.0.1`,
   units bind `0.0.0.0`) — **the units are canonical**; update compose or mark it stale.
7. Remove the Tailscale `/beta` path.

---

## Risks & mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| Recharts can't replicate a specific chart look | Medium | DayRing stays custom SVG. Others fall back to port-verbatim SVG if needed. |
| TanStack Query caching hides stale data | Low | Sensible `staleTime` per endpoint; explicit invalidation on sync complete. |
| Web Bluetooth regressions | Medium | Port verbatim; **protocol tests first (Phase 7)**; pre-cutover phone test via Tailscale beta. |
| Build step breaks Podman workflow | Low | Host-build option (a) needs no Dockerfile/unit change. |
| Tailwind Play CDN → real Tailwind color drift | Low | Tailwind v3 default palette matches Play CDN. One visual review pass. |
| Scope creep | Medium | "Parity, not enhancement" rule (Process rule 2). |
| **Legacy dashboard keeps changing during rewrite** | **High** | **Feature freeze (Process rule 1); same-day mirroring.** |
| **Installed PWA serves stale shell after cutover** | **Medium** | **Bump cache version (Phase 8); new SW activate handler purges old caches.** |
| **Multi-stage Dockerfile silently shadowed by bind mount** | Medium | Use host-build option (a), or drop the unit volume if using (b). |

---

## Definition of done

- [ ] All 3 tabs render with real data from `:8000`.
- [ ] All 8 chart types match or exceed current visuals.
- [ ] Sync button end-to-end: queue → poll → progress → cancel → complete → auto-refresh.
- [ ] **Vitest protocol tests pass** for `make16` / `makeBig` / parsers.
- [ ] **Phone BLE sync verified pre-cutover** via Tailscale beta path (Android Chrome).
- [ ] **PWA: installs on phone, loads offline, mobile-sync POST stays network-only.**
- [ ] Dark mode, date nav, battery indicator functional; full parity checklist complete.
- [ ] Legacy `dashboard/index.html` + old SW / manifest / icons deleted.
- [ ] `AGENTS.md` updated (new stack, build step, compose-stale note).

---

## Effort estimate

| Phase | Days |
|---|---|
| 0 — Build infra | 0.5 |
| 1 — API types (32 routes) + parity checklist | 0.5 |
| 2 — Shell | 0.5 |
| 3 — Dashboard tab | 2–3 |
| 4 — Analytics tab | 0.5 |
| 5 — Admin tab | 0.5 |
| 6 — Sync UX | 0.5 |
| 7 — Web Bluetooth + protocol tests | 1.5 |
| 8 — PWA port | 0.5–1 |
| 9 — Polish | 0.5 |
| 10 — Cutover (incl. pre-cutover phone test) | 0.5 |
| **Total** | **~8–10 days** |

Previous estimate was ~7 days; +1–3 for the PWA port, BLE protocol tests, Tailscale beta wiring,
and SW migration debugging. Tight but realistic with AI assistance given the active churn on the
legacy file.
