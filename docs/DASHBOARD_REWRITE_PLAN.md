# Dashboard Rewrite Plan

Replace the 2,915-line monolithic `dashboard/index.html` with a componentized React + TypeScript
app while keeping the FastAPI backend untouched. Reach full feature parity, then cut over.
The legacy Alpine dashboard continues serving at `:8000` until the new app at `:5173` is
feature-complete and signed off.

---

## Stack

| Layer | Choice |
|---|---|
| Framework | React 18 + Vite 5 |
| Language | TypeScript 5 |
| Styling | Tailwind CSS 3 (PostCSS, not Play CDN) |
| Data fetching | TanStack Query v5 |
| Charts | Recharts 2 + 1 custom SVG component (DayRing) |
| Web Bluetooth | Custom `useRingSync` hook (port of existing logic, typed) |
| Tooling | ESLint + Prettier + Vitest |

---

## Dev topology

```
Browser
  ├── http://localhost:5173  (new React, Vite HMR)
  │       │
  │       └── /api/* proxied ──▶ http://localhost:8000  (FastAPI, untouched)
  │
  └── http://localhost:8000  (legacy Alpine, untouched)
```

Three tiers:

| Tier | Port | Command | Purpose |
|---|---|---|---|
| Dev (HMR) | 5173 | `npm run dev` | Active development |
| Preview | 4173 | `npm run build && npm run preview` | Verify production build |
| Prod cutover | 8000 | Vite builds `dist/`, FastAPI serves it | Final state |

Phone-BLE testing happens on the legacy `:8000` dashboard until cutover (see Risks).

---

## Project structure

```
dashboard/
├── package.json
├── vite.config.ts            ← proxy /api → :8000 in dev
├── tsconfig.json
├── tsconfig.node.json
├── tailwind.config.ts
├── postcss.config.js
├── .env.development          ← VITE_API_BASE=''
├── .env.production
├── .eslintrc.cjs
├── .prettierrc
├── index.html                ← Vite entry
├── index.legacy.html         ← archived current file (deleted at cutover)
└── src/
    ├── main.tsx
    ├── App.tsx               ← tab router + providers
    ├── index.css             ← Tailwind + chart polish
    ├── api/
    │   ├── client.ts         ← typed fetch wrapper
    │   ├── types.ts          ← response interfaces
    │   ├── hooks.ts          ← TanStack Query hooks per endpoint
    │   └── useSyncPolling.ts ← polling replaces setInterval
    ├── components/
    │   ├── layout/
    │   │   ├── Nav.tsx
    │   │   ├── Tabs.tsx
    │   │   ├── BatteryIndicator.tsx
    │   │   └── DateNav.tsx
    │   ├── charts/
    │   │   ├── VitalsChart.tsx       ← Recharts ComposedChart, 2 YAxis
    │   │   ├── CircadianChart.tsx    ← Recharts Line + Area
    │   │   ├── SleepDonut.tsx        ← Recharts Pie
    │   │   ├── TrendChart.tsx        ← Recharts Line (analytics tab)
    │   │   ├── MiniTrend.tsx         ← Recharts Bar (sparkline)
    │   │   ├── RecoveryBars.tsx      ← Recharts Bar
    │   │   └── DayRing.tsx           ← custom SVG (radial bars + sleep overlay)
    │   ├── cards/
    │   │   ├── ReadinessHero.tsx     ← big ring + sub-scores + contributors
    │   │   ├── RecoveryCard.tsx
    │   │   ├── HrvCard.tsx
    │   │   ├── StressCard.tsx
    │   │   ├── SleepCard.tsx
    │   │   ├── VitalsCard.tsx
    │   │   └── CircadianCard.tsx
    │   ├── sync/
    │   │   ├── SyncButton.tsx        ← spinner + elapsed + progress badge
    │   │   └── ErrorBanner.tsx
    │   ├── ble/
    │   │   ├── useRingSync.ts        ← Web Bluetooth hook
    │   │   ├── ringProtocol.ts       ← UUIDs, make16, makeBig (typed)
    │   │   ├── SyncProgressDialog.tsx
    │   │   └── toasts.ts
    │   └── ui/
    │       ├── Card.tsx
    │       ├── Skeleton.tsx
    │       └── EmptyState.tsx
    ├── tabs/
    │   ├── DashboardTab.tsx
    │   ├── AnalyticsTab.tsx
    │   └── AdminTab.tsx
    ├── hooks/
    │   ├── useTheme.ts
    │   ├── useSelectedDate.ts
    │   └── useElapsedTimer.ts
    ├── utils/
    │   ├── date.ts
    │   ├── format.ts
    │   ├── smoothPath.ts
    │   └── clipFuture.ts
    └── types/
        ├── api.ts
        └── ble.ts
```

---

## Phases

### Phase 0 — Build infrastructure (reversible, low risk)
1. Branch `dashboard-react-rewrite`.
2. `npm create vite@latest` with React+TS template.
3. Install deps: Tailwind 3, @tanstack/react-query, recharts, clsx, date-fns, eslint, prettier, vitest.
4. `vite.config.ts`: `server.port: 5173`, proxy `/api` and `/health` → `http://localhost:8000`.
5. Archive current `index.html` → `index.legacy.html`.
6. Verify `npm run dev` boots and `/api/health` returns `{"status":"ok"}`.
7. Update `api/main.py` to serve `dashboard/dist/index.html` when built.

**Checkpoint:** blank app at `:5173`, legacy still works at `:8000`.

### Phase 1 — Type the API contract (the foundation)
1. Read every `@app.get/post` in `api/main.py` (17 routes).
2. Write `src/api/types.ts` with one interface per response.
3. Write typed `src/api/client.ts`.
4. Write `src/api/hooks.ts` — one TanStack Query hook per endpoint.
5. Wire `QueryClientProvider` in `App.tsx`.

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
- `DayRing.tsx` — port `renderDayRing` + `_wireRingTooltip` verbatim. Tooltips via local state + refs.

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
- Ring status, last sync summary, health checks.
- Sync log table with pagination.
- Sync requests queue.

### Phase 6 — Sync UX
- `SyncButton.tsx` — POST `/api/admin/sync`, then `useSyncPolling()`.
- `useSyncPolling` — TanStack Query `refetchInterval: 5000` while pending/running.
- `ErrorBanner.tsx`.
- `useElapsedTimer`.
- On completion: `queryClient.invalidateQueries(['dashboard'])` auto-refreshes.

### Phase 7 — Web Bluetooth phone sync (~400 LOC)
- `ringProtocol.ts` — UUIDs, `make16`, `makeBig`, typed.
- `useRingSync.ts` — port the IIFE verbatim. Exposes `syncFromPhone()` + progress state.
- `SyncProgressDialog.tsx` — 12-phase progress UI.

### Phase 8 — Polish
- Loading skeletons for every async card.
- Empty states.
- `prefers-reduced-motion` respect.
- Verify dark mode across every component.

### Phase 9 — Cutover
1. Run new app as primary for several days; confirm ring data, sync, BLE.
2. Update `api/Dockerfile` to multi-stage (node:20-alpine build → python:3.12-slim serve).
3. Update `api/main.py` `DASHBOARD_DIR` → `dashboard/dist`.
4. Rebuild container, restart `smart-ring-api.service`.
5. Smoke test at `:8000`.
6. Delete `dashboard/index.legacy.html`.
7. Update `AGENTS.md` dashboard row + deploy notes.

---

## Risks & mitigations

| Risk | Likelihood | Mitigation |
|---|---|---|
| Recharts can't replicate a specific chart look | Medium | DayRing stays custom SVG. Others fall back to port-verbatim SVG if needed. |
| TanStack Query caching hides stale data | Low | Sensible `staleTime` per endpoint; explicit invalidation on sync complete. |
| Web Bluetooth regressions | Medium | Port logic verbatim first, test on desktop Chrome. Phone testing on legacy until cutover. |
| Build step breaks Podman workflow | Low | Multi-stage Dockerfile. Local dev unaffected. |
| Tailwind Play CDN → real Tailwind color drift | Low | Tailwind v3 default palette matches Play CDN. One visual review pass. |
| Scope creep | Medium | Strict "feature parity, not enhancement" rule. New ideas go to `TASKS.md`. |

---

## Definition of done

- [ ] All 3 tabs render with real data from `:8000`.
- [ ] All 8 chart types match or exceed current visuals.
- [ ] Sync button end-to-end: queue → poll → progress → complete → auto-refresh.
- [ ] Desktop Web Bluetooth sync works (tested on Chrome).
- [ ] Dark mode, date nav, battery indicator all functional.
- [ ] Legacy `dashboard/index.legacy.html` archived and deletable.
- [ ] `AGENTS.md` updated to reflect new stack.

---

## Effort estimate

| Phase | Days |
|---|---|
| 0 — Build infra | 0.5 |
| 1 — API types | 0.5 |
| 2 — Shell | 0.5 |
| 3 — Dashboard tab | 2–3 |
| 4 — Analytics tab | 0.5 |
| 5 — Admin tab | 0.5 |
| 6 — Sync UX | 0.5 |
| 7 — Web Bluetooth | 1 |
| 8 — Polish | 0.5 |
| 9 — Cutover | 0.5 |
| **Total** | **~7 days** |
