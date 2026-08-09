# AGENTS.md — Smart Ring Project

> Agent-facing context. This file is **lean** — details go in `docs/` (research, device behavior, roadmap) or git history.
> Update this when architecture, key files, or current state changes.

---

## Project Overview

Private, self-hosted health tracking around the **Colmi R09** (~$45 CAD).

- **Hardware:** Colmi R09 (FW RT09_3.10.21_251107), BLE → Postgres → health metrics → React dashboard
- **Stack:** Python (bleak), FastAPI, Postgres 16, React 19 + TypeScript 5 + Vite (build → `dashboard/dist/`)
- **Deployment:** Linux Mint HTPC (AMD 3800x / 64 GB) — bare metal for collector

**BLE address** is in `.env` as `RING_ADDRESS` (local only — never commit). Host on 24/7.

**Target device is Android.** The dashboard's phone sync uses Web Bluetooth, which iOS doesn't support (and never will — WebKit has no implementation). Don't propose iOS workarounds (Bluefy, WebBLE, native apps), don't flag iOS as a limitation in plans, and don't bend designs to accommodate iOS. The PWA installs fine on iOS as a read-only dashboard; that's a side-effect, not a target.

---

## Runtime (read before any podman/systemctl)

**Full ops contract: [`docs/RUNTIME.md`](docs/RUNTIME.md).** Do not skip it.

**Dual Podman store trap:** bare `podman ps` uses `$HOME/.local/share/containers` and is
often **empty** even when the stack is up. Production storage is only visible when
`XDG_DATA_HOME=/opt/smart-ring/.local/share` is set (units set this; interactive shells do not).

```bash
# Wrong store (often empty) ≠ stack down:
podman ps -a
# Production store (must show smart-ring-db + smart-ring-api when healthy):
export XDG_DATA_HOME=/opt/smart-ring/.local/share
podman ps -a
```

---

## Current Architecture

```
Ring ──BLE──> Linux Box (bare metal, forget+repair each sync)
                ├─ smart-ring-poller.service  (system systemd, bare metal, 30s poll)
                │    └─ watches sync_requests → sync_ring / analytics
                ├─ smart-ring-db.service      (system systemd, rootless podman run)
                └─ smart-ring-api.service     (system systemd, rootless podman run)
                     └─ serves dashboard + API

Code:          /opt/smart-ring/code
Podman store:  /opt/smart-ring/.local/share/containers   (ONLY via XDG_DATA_HOME in units)
Units:         /etc/systemd/system/smart-ring-*.service  (canonical — no user-unit, no quadlets, no compose)
```

**Critical facts (do not violate):**

- **Every smart-ring `podman` command needs** `export XDG_DATA_HOME=/opt/smart-ring/.local/share` (or the same prefix). Bare podman is a different graph root.
- Collector is **bare metal only** (BlueZ/DBus) — `python -m collector.sync_ring`. Phone pairing needs `forget_ring()` after each sync.
- **R09 single-connection:** box holds BLE; forget releases the ring for the phone.
- **Poller** (`smart-ring-poller.service`): bare-metal 30s loop; not a container.
- **Services are system units** (`/etc/systemd/system/`). Lifecycle = `sudo systemctl` / `sudo journalctl`. Never `systemctl --user` for production.
- **Code + Podman storage live at `/opt/smart-ring`, never under an encrypted home.** Encrypted homes (e.g. ecryptfs) only decrypt on login — paths there kill boot autostart. Same pattern as ollama / data under `/opt`.
- **No docker-compose, no Podman quadlets, no user systemd units** for this stack.

### Key commands

```bash
cd /opt/smart-ring/code
export XDG_DATA_HOME=/opt/smart-ring/.local/share   # required for all podman below

sudo systemctl status smart-ring-db smart-ring-api smart-ring-poller
sudo systemctl restart smart-ring-api smart-ring-poller
sudo journalctl -u smart-ring-poller -f

podman ps -a
podman exec -it smart-ring-db psql -U smart_ring -d smart_ring

venv/bin/python3 -m collector.sync_ring --forget
venv/bin/python3 -m collector.first_contact
venv/bin/python3 -m pytest tests/          # use python3 -m; venv shebangs may be stale
```

After editing a unit: `sudo systemctl daemon-reload && sudo systemctl restart smart-ring-db smart-ring-api smart-ring-poller`.

---

## Key Source Files

| File | Purpose |
|------|---------|
| `docs/RUNTIME.md` | **Ops truth:** dual Podman store, units, ports, volumes, commands that work |
| `collector/ring_client.py` | BLE wrapper (timeout, `set_time_local`, forget/repair helpers, `_encode_time_bcd` pure helper) |
| `collector/sync_ring.py` + `protocol/` | Thin orchestrator + all BLE protocol, parsers, upserts |
| `collector/garmin/` | Garmin 745 FIT file parser + ingest. `parser.py` handles Activity/ + Summary/ files (Phase 1, 40 activities ingested). `monitoring.py` handles Metrics/ + Sleep/ files (Phase 1.5, DEFERRED — needs FIT SDK profile upgrade; framework + 15 tests ship, extractors stubbed) |
| `collector/garmin/ingest.py` | CLI: `python -m collector.garmin.ingest --fit-dir <path>`. Idempotent by file path + SHA-256 hash. Maps parsed activity → `activities` + `activity_laps` + `activity_trackpoints` + `activity_hr` tables. Phase 0 dedupe unaffected (Garmin-only tables). |
| `collector/analytics/` | Package of per-scorer modules; `python -m collector.analytics` |
| `collector/analytics/source_priority.py` | N-source priority resolver — `DEFAULT_PRIORITY = (ring, garmin, phone)` per metric. Single source of truth for which source wins |
| `collector/analytics/readiness.py` | Morning Readiness scorer (frozen at 6 AM) + `should_freeze` pure helper |
| `collector/analytics/current_status.py` | Live intra-day scorer (Current Status) + pure component helpers |
| `collector/jobs/` | `SyncJob` / `RingSyncJob` / `AnalyticsJob` for the poller |
| `collector/sync_request_poller.py` | Host poller watching `sync_requests` |
| `api/main.py` | FastAPI app + all endpoints (mobile_sync uses dispatch loop) |
| `api/upsert.py` | `upsert_many` generic dispatcher for simple point tables |
| `dashboard/index.html` | ~~Pure client-side UI (Alpine.js + Tailwind, no build)~~ **retired 2026-07-26** — replaced by React app |
| `web/` | React + TypeScript dashboard (Vite build → `dashboard/dist/`). TanStack Query, Recharts, Tailwind 3, vite-plugin-pwa. See `docs/done/DASHBOARD_REWRITE_PLAN.md`. |
| `web/src/api/` | Typed API client: `types.ts` (25+ interfaces), `hooks.ts` (25+ TanStack Query hooks per endpoint), `client.ts` (fetch wrapper) |
| `web/src/components/ble/ringProtocol.ts` | Colmi R09 Web Bluetooth protocol + 9/9 Vitest byte-level tests |
| `web/src/components/garmin/` | Garmin dashboard components: `ActivitiesList` (sport filter), `ActivityDetail` (stats + HR chart + laps), `ActivityHrChart` (zone bands), `ActivityLaps` (splits), `ActivityMap` (Leaflet GPS route), `GarminUpload` (drag-and-drop FIT zip) |
| `web/src/components/analytics/` | Analytics rework: `TrendChart` (click-to-zoom), `TimeScaleControls` (presets + custom range), `HelpPopover` (methodology per chart) |
| `web/src/components/layout/SensorFreshnessNav.tsx` | Always-visible sensor freshness chips in nav (HR/HRV/Steps/SpO₂/Stress/Temp) |
| `web/src/tabs/AnalyticsTab.tsx` | Shared time window state, click-to-zoom orchestration, hourly resolution switch |
| `dashboard/dist/` | Built React app (served by FastAPI at `/static/`). `npm run build` in `web/` to rebuild. |
| `scripts/gen_icons.py` | One-shot Pillow icon generator (192/512/maskable/apple-180) |
| `tests/` + `pytest.ini` | 279-test regression net (trap_score, BCD, dedupe, source_priority, mobile_sync, current_status, readiness_freeze, data_quality, steps_drain, strain_trend, heart_rate_zones, garmin_parser, garmin_ingest, garmin_monitoring, garmin_api) |
| `docs/RING_BEHAVIOR.md` | Firmware quirks, data publish cadence, logger stall |
| `docs/RESEARCH.md` | Scoring formulas & methodology (Morning Readiness + Current Status) |
| `docs/GARMIN_INTEGRATION_RESEARCH.md` | Garmin 745 integration design (privacy, sync options, schema, Rust ecosystem, phases) |
| `docs/done/CLEANUP_PLAN.md` | Cleanup arc history + Step 4 details |
| `docs/done/PWA_PLAN.md` | PWA strategies, manifest, service worker design |

---

## Current State

All 8 raw data types and the 5 health scores (including Morning Readiness frozen + Current Status live) are collecting and computing successfully. Phone sync + dashboard + poller are stable. Dashboard is now a React + TypeScript app (replaced Alpine.js monolith on 2026-07-26) served at `/static/` from `dashboard/dist/`. The legacy `dashboard/index.html`, `sw.js`, `manifest.webmanifest`, and icons are deleted. Dashboard ships as an installable PWA (offline shell + manifest + icons).

**Test suite:** 279 tests across 15 files (`tests/test_{trap_score,time_sync_bcd,dedupe,source_priority,mobile_sync,current_status,readiness_freeze,data_quality,steps_drain,strain_trend,heart_rate_zones,garmin_parser,garmin_ingest,garmin_monitoring,garmin_api}.py`). Run with `venv/bin/python3 -m pytest tests/` — ~25s total. DB-backed tests use an ephemeral `smart_ring_test_<pid>` database created from `db/init.sql`; pure-function tests need no fixtures. Garmin parser/ingest/monitoring/API tests use real FIT files from `/opt/smart-ring/code/temp/GARMIN/` (skipped if not present).

**Readiness model (split July 2026):**
- **Morning Readiness** (frozen, WHOOP-style): locks at first analytics pass at/after 6 AM local. `frozen_at` column on `readiness_score`. Subsequent passes skip today's row entirely (preserves original timestamp via COALESCE).
- **Current Status** (live intra-day): new `current_status` table, one row per analytics pass. 4 components (HRV 40% / HR 25% / Stress 20% / Trend 15%), renormalizes over available. Vibe labels: Locked In / Solid / Vibing / Winded / Gassed. See `docs/RESEARCH.md` for methodology.

**API cleanup arc complete** (2026-07-20): dead ORM code dropped, redundant `_dedupe_sources` dropped, generic `upsert_many` dispatcher shipped. Step 3 (extract raw SQL to `queries.py`) skipped indefinitely as "rearranging deck chairs." See `docs/CLEANUP_PLAN.md` for full history.

**See `docs/RING_BEHAVIOR.md`** for:
- Firmware quirks, per-data-type reference (command, publish cadence, etc.)
- Critical details: background logger stall behavior, temp history only publishing *completed* days (`daysAgo` >= 1), R09 single-connection limit

**See `docs/RESEARCH.md`** for validated scoring formulas and methodology.

**See `TASKS.md`** for CFW ideas, readiness improvements, and open backlog.

**High-signal recent facts (verify via DB + source):**
- Clock sync uses the sacred local BCD `set_time_local()` + ack path (clock_drift_ms=1 means success). `_encode_time_bcd` is the pure helper, pinned byte-for-byte by `tests/test_time_sync_bcd.py`.
- Poller auto-reaps stuck `sync_log` rows.
- Source dedup runs in analytics (`collector/analytics/dedupe.py:dedupe_sources()`) — single source of truth, runs before scorers every analytics pass. API-side `_dedupe_sources` removed (was redundant). Priority driven by `collector/analytics/source_priority.py:DEFAULT_PRIORITY` (N-source resolver).

---

## Recent Work Log (Jul 2026)

For full history: `git log --oneline` and `docs/CLEANUP_PLAN.md`.

### 2026-08-08 — README screenshots via one-time demo data
- **Goal:** publishable dashboard screenshots for the README with zero real
  health data or GPS exposure.
- **`scripts/seed_demo_data.py`:** generates 30 days of synthetic Colmi R09 data
  (HR/HRV/SpO2/temp/stress/steps/sleep + 6 fake Garmin activities with generic
  arbitrary GPS coords) into the `DATABASE_URL` DB. `seed(conn, days, rng_seed)`
  is the testable entry point; all inserts are `ON CONFLICT DO NOTHING`
  (idempotent). Raw rows tagged `source='ring'` (NOT 'demo') — scorers filter to
  known sources only, so a synthetic tag would make demo data invisible.
  Analytics engine then computes all scores from the fake raw data (nothing
  hand-faked at the score layer).
- **`scripts/capture_screenshots.py`:** Python Playwright; loads 4 tabs
  (`#dashboard/#analytics/#garmin/#admin`), forces dark (localStorage
  `darkMode=true` + reload — hash-only navigations don't remount the app, so it
  reloads after each `#tab`), full-page PNGs → `docs/screenshots/`.
  **PWA-shell pitfall:** the app's `html {overflow:hidden}` + `body
  {height:100vh; overflow-y:auto}` scroll shell makes full-page captures
  rasterize everything below the initial viewport as **pure black** (both
  Chromium and Firefox headless). Fix: `neutralize_pwa_scroll()` temporarily
  sets `html/body {overflow:visible}` + `body {height:auto}` so the page flows
  normally before capture. The script asserts captured height ==
  `body.scrollHeight` AND that every h2 section has painted pixels (verified:
  dashboard 2022px, analytics 2160px).
- **Workflow:** create throwaway DB → seed → run `python -m collector.analytics`
  **several times** (each pass appends a `current_status` row; the Current
  Status stress sparkline needs ≥2 rows/day to render — the prod poller does
  this every 30s) with `DATABASE_URL` → run API from `api/` dir on :8001 (must
  run as `main:app` from api/ — sibling imports, same as container) → capture →
  drop DB. Production never touched.
- **`tests/test_demo_data.py`:** 25 tests (pure generators: ranges, Ohayon
  sleep norms, FIT semicircle round-trip, polyline smoothing; DB-backed:
  seed populates raw tables, idempotency, seed→analytics populates all score
  tables, Garmin children wired). Suite total 279 → 304.
- **README:** 2x2 dark-mode screenshot gallery after intro (demo data, safe to
  publish). `pyproject.toml` gains `[project.optional-dependencies] screenshots
  = ["playwright>=1.40"]`.

### 2026-08-06 — PWA refresh button now does a real page reload
- **Problem:** the PWA refresh button (and the pull-to-refresh gesture) only
  called `queryClient.invalidateQueries()` — refetched API data but never
  reloaded the page, updated the service worker, or cleared the SW cache.
  Felt like "nothing happened", especially when server data was unchanged.
- **Fix (`web/src/components/layout/Nav.tsx`):** `handleRefresh` now checks for
  service worker updates (`reg.update()` with a 2 s timeout, never blocks the
  reload), shows a brief spinner, then does `window.location.reload()` — a
  true browser-style refresh. Tooltip/aria-label changed to "Refresh page".
  `queryClient`/`useQueryClient` no longer needed in Nav.
- **Removed pull-to-refresh entirely:** deleted
  `web/src/components/ui/PullToRefresh.tsx` (167 lines) + unwrapped
  `<PullToRefresh>` in `web/src/App.tsx`. The gesture was flaky on some
  Android builds and the nav button is now the reliable path.
- **Verified:** oxlint clean, `tsc -b && vite build` clean (new
  `index-BgcrxFLq.js` in `dashboard/dist/`), 9/9 vitest.
- **Note:** the refresh button remains PWA-only (`display-mode: standalone`);
  desktop users already have the browser refresh.

### 2026-08-01 — Analytics tab rework (Phases 1-3: click-to-zoom + hourly resolution)
- **Goal:** make trends explorable without switching tabs or losing alignment
  across metrics.
- **Phase 1 (trends-only page):** replaced the old Analytics tab (data pipeline
  table + score cards + 5 charts) with 8 trend charts (Recovery, Sleep, Stress,
  RHR, Strain, Steps, Temp, SpO2) driven by a shared `{start, end}` window.
  Time-scale presets (3/7/14/30/90/180d). Score cards removed — they duplicated
  the Dashboard + the rightmost point of each trend. Methodology content moved
  into `HelpPopover` (expandable, per-chart).
- **Phase 2 (click-to-zoom + breadcrumb):** click any point on any chart →
  narrows the shared window to 1/3 its current width, centered on the clicked
  day. All 8 charts re-render together. Breadcrumb + Reset button appear
  whenever the window isn't a recognized preset.
- **Phase 3 (hourly resolution):** when the window narrows to a single day,
  7 of 8 trends automatically switch from daily aggregates to hourly raw
  sensor data (Recovery → raw_hrv, RHR → raw_heart_rate, Stress → raw_stress,
  Strain → raw_heart_rate, Steps → raw_steps, Temp → raw_temperature,
  SpO2 → raw_spo2). Sleep stays daily-only (no hourly version — composite).
- **Backend (`api/main.py`):** raw data endpoints (`/api/raw/heart-rate`,
  `/api/raw/hrv`, etc.) gained optional `start`/`end` date params so the
  frontend can fetch the exact window it needs. Daily-aggregate endpoints
  still fetch max span (180d) once; client-side filtering keeps TanStack
  Query cache stable.
- **Frontend (`web/src/`):** new `TimeScaleControls` (presets + custom range
  picker), `TrendChart` (click handler + x-position mapping), `HelpPopover`
  (methodology per chart). `AnalyticsTab` owns the shared window state.
  New `web/src/utils/date.ts` helpers (`aggregateByDay`, `aggregateByHour`,
  `todayKey`, `dateKey`) handle local-time bucketing so rows near midnight
  land on the correct day/hour.
- **Verified:** 279 pytest, 9/9 vitest, `npm run lint` + `npm run build`
  clean. Live against production DB — zoom works end-to-end.

### 2026-08-01 — Sensor freshness moved to nav bar
- **Problem:** the old `DataQualityBanner` was a surprise amber bar that
  appeared/disappeared based on stale data. Felt random, broke flow.
- **Fix:** replaced with `SensorFreshnessNav` — always-visible chips in the
  top nav (HR/HRV/Steps/SpO₂/Stress/Temp). Each chip shows current status
  (ok/stale/pending) for the ring source. No more surprise banners.
- **Data quality logic rewrite:** `collector/analytics/data_quality.py`
  rewritten to use peer-lag (not wall-clock age). Steps/stress peer-lag
  vs HR (evening stops are normal). HR logger stall vs HRV/SpO2/stress.
  No phone rows unless phone has data. `reason` column added. Calendar
  today check. Thresholds calibrated in `docs/DATA_QUALITY.md`.
- **Backend:** `DataQualityBanner` component deleted. `SensorFreshnessNav`
  component added. API `/api/data-quality` unchanged (already returned
  per-type status).
- **Verified:** 279 pytest, lint+build clean.

### 2026-07-30 — Garmin FIT upload via web UI
- **Goal:** replace `ssh + python -m collector.garmin.ingest --fit-dir <path>`
  with a drag-and-drop zone in the browser.
- **Backend (`api/main.py`):** new `POST /api/admin/garmin/upload` endpoint
  accepts a zip file containing the `Garmin/` folder tree. Extracts to
  temp dir, runs the same ingest pipeline as the CLI. Returns summary
  (found/inserted/skipped counts).
- **Frontend (`web/src/components/garmin/GarminUpload.tsx`):** drag-and-drop
  zone in the Admin tab. Accepts `.zip` files. Shows progress + result
  summary. Empty state in GarminTab still shows the CLI command for users
  who prefer it.
- **Verified:** 279 pytest, lint+build clean. Live against production DB —
  uploaded a zip of the `Garmin/` folder, 40 activities ingested.

### 2026-07-30 — Leaflet map for Garmin GPS routes
- **Goal:** visualize the GPS track from Garmin activities on a map.
- **Frontend (`web/src/components/garmin/ActivityMap.tsx`):** ~130 lines of
  vanilla Leaflet (no react-leaflet wrapper). Renders the route polyline
  with start/finish markers. Auto-fits bounds. Handles dark mode (CARTO
  Voyager tiles for light, Dark Matter for dark). Filters GPS dropouts
  (null lat/lon). Integrated into `ActivityDetail` component.
- **Tiles:** CARTO Voyager (light) / Dark Matter (dark). No geo-api needed
  for the base map. Elevation profile overlay blocked on geo-api CORS/auth
  (separate follow-up).
- **Verified:** 279 pytest, lint+build clean. Live against production DB —
  40 activities have GPS tracks, all render correctly.

### 2026-07-30 — Data quality banner source-agnostic
- **Problem:** the old `DataQualityBanner` hardcoded `ring > phone` logic.
  With N-source resolver (Phase 0), we can have garmin data too. Banner
  should flag stale only when *no* source is fresh.
- **Fix:** `collector/analytics/data_quality.py` rewritten. `classify_status()`
  is now pure. Checks all sources for a given data type. If any source is
  fresh within the peer-lag threshold, status is "ok". Only flags "stale"
  when all sources are stale. `reason` column explains which sources are
  stale and why.
- **Verified:** 279 pytest, lint+build clean.

### 2026-08-01 — Data quality freshness rethink (kill false alarms)
- **Problem:** banner felt random — phone phantoms, peer-fresh 30m decay,
  steps/stress peer-lag vs HR (evening stops are normal), wrong cadence
  assumptions (docs said HR 5m / HRV 30m; prod is HR 15m / HRV 60m).
- **Audit:** 5 days prod gaps → calibrated thresholds in `docs/DATA_QUALITY.md`.
- **Backend:** rewrite `collector/analytics/data_quality.py` — pure
  `classify_status()`, peer-lag (not wall-clock age), steps waking-only
  5h stall, stress no peer-lag, HR logger stall vs HRV/SpO₂/stress,
  no phone rows unless phone has data, `reason` column, calendar today.
- **UI:** always-visible `SensorFreshnessStrip` (ring only) replaces
  surprise amber banner. Chips HR/HRV/Steps/SpO₂/Stress/Temp.
- **Tests:** 22 in `test_data_quality.py` pin real false-alarm cases.
- **Verified:** 279 pytest, lint+build clean; today all ring ok +
  temp_pending after live analytics pass.

### 2026-07-30 — Garmin activity dashboard tab (list + HR chart + laps)
- **Goal:** make the 40 activities ingested in Phase 1 visible in the
  browser. New "Garmin" tab, pure read-side, no scoring logic touched.
- **Branch:** `garmin-integration`. 16 files, +~1200 LOC, 254→268 tests.
- **Backend (`api/main.py`):** 5 new read-only endpoints:
  - `GET /api/activities?days=365&sport=walking&limit=30` — list with
    sport filter, returns 30 most recent by default. Joins
    `activity_laps` for `lap_count`.
  - `GET /api/activities/{id}` — session detail (training effect,
    running dynamics, `fit_file_path`).
  - `GET /api/activities/{id}/trackpoints` — 1-Hz GPS+HR+cadence,
    auto-downsamples to `max_points` (default 5000) for long
    activities (multi-hour walks = 10,000+ points). GPS coordinates
    converted from FIT semicircles to degrees at the API boundary.
  - `GET /api/activities/{id}/hr` — 1-Hz HR-only projection (lighter
    than trackpoints, separate table for the chart).
  - `GET /api/activities/{id}/laps` — lap splits.
- **Frontend (`web/src/`):** new `GarminTab` + 4 components:
  - `ActivitiesList` — table with sport filter (all/walking/running/
    cycling/other). Click a row → opens detail. Empty state shows
    the ingest CLI command (`python -m collector.garmin.ingest
    --fit-dir <path>`).
  - `ActivityDetail` — headline stats grid (distance, duration,
    avg/max HR, elevation, calories, training effect, cadence,
    strides) + HR chart + lap splits. Dark mode + mobile responsive.
  - `ActivityHrChart` — Recharts area chart with HR zone reference
    bands (Z1-Z5 tinted backgrounds, Garmin 5-zone defaults).
  - `ActivityLaps` — splits table (duration, distance, pace, avg/max
    HR, calories, elevation).
  - `types.ts`: 4 new interfaces (`ActivityRow`, `ActivityDetail`,
    `TrackpointRow`, `ActivityHrRow`, `ActivityLapRow`).
  - `hooks.ts`: 5 new TanStack Query hooks (`useActivities`,
    `useActivityDetail`, `useActivityTrackpoints`, `useActivityHr`,
    `useActivityLaps`).
  - Tab wiring: new `garmin` option in `App.tsx` + `Nav.tsx` +
    `Tabs.tsx` (URL hash `#garmin` works for PWA shortcuts).
- **Tests:** +14 in `tests/test_garmin_api.py`. Real-activity
  fixture (one walk from 2026-07-29 ingested via the same code path
  as the CLI). Covers list happy path, sport filter, limit, 404,
  downsampling, laps empty case, field shapes. Skip if
  `/opt/smart-ring/code/temp/GARMIN/` absent.
- **Verified:** 268/268 pytest in 25 s, 9/9 vitest, `npm run lint`
  + `npm run build` clean. API live against production DB — 40
  activities queryable from the new Garmin tab.
- **Deferred to follow-up PRs:**
  - Leaflet map for GPS trackpoints (with OSM or geo-api tiles).
  - Upload UI in the Admin tab (drag-and-drop `.fit` files instead
    of `ssh + python -m collector.garmin.ingest`).
  - Daily monitoring files (Phase 1.5) — still blocked on
    undocumented Garmin-specific FIT global_ids. Path forward is
    Garmin Connect export → match values → write extractors.

### 2026-07-30 — Phase 1.5: Garmin Monitoring files (DEFERRED)
- **Goal:** ingest the daily Metrics/ + Sleep/ FIT files (per-day
  HR, HRV, SpO2, body battery, overnight skin temp, sometimes
  step totals) into `raw_*` with `source='garmin'`. These are
  the files the 745 writes between activity syncs — the most
  valuable non-activity data the watch captures.
- **Branch:** `garmin-integration`. 3 files, +~700 LOC, 239→254 tests.
- **Blocker discovered:** the monitoring files use FIT SDK
  message types (global_id 229, 232, 281, 294, 339, 356) that
  post-date the public FIT SDK profile bundled with `fitparse`
  (21.60). The binary format is stable and we can read raw
  field IDs (via `fit_tool`), but the *semantics* of each field
  aren't documented anywhere we have access to:
  - 232 (Hr): fids 5,6,7,8 are HR values (67, 218, 263 — could be
    daily min/avg/max, or 5-min samples, unclear)
  - 281 (Hrv): all UINT32Z nulls in our sample (no HRV captured?)
  - 339 (HsaSpo2Data): fids 1,2,3,4 are 1785, 3964, 9636, 22995 —
    too large for SpO2% (90-100), may be seconds-in-zone
  - 356 (SkinTempOvernight): fids 2,3 are 1268600, 4380400 —
    too large for centi-degrees, may be time-weighted temps
  Writing these to `raw_*` without understanding the scale would
  silently corrupt the analytics pipeline (Phase 0 dedupe would
  not catch a wrong-unit value).
- **What ships in this commit:** the framework + 15 tests, not
  the extractors.
  - `collector/garmin/monitoring.py` (~280 lines): file
    discovery, fit_tool-based record reader that exposes
    `(global_id, {field_id: encoded_values})` tuples, and the
    `ParsedMonitoring` dataclass with per-metric lists.
  - Per-message extractors (`_extract_hr`, `_extract_hrv`, etc.)
    are wired up but currently return empty lists — the
    comment in each one notes which field IDs are unverified.
  - `EXTRACTED_GIDS` + `PENDING_DECODE_GIDS` constants
    document the status so a future contributor can pick
    up where this leaves off.
- **Tests (15 in `test_garmin_monitoring.py`):** file
  discovery, file_hash determinism, parse_monitoring_file
  returns a valid `ParsedMonitoring` with correct metadata,
  the framework tracks unknown global_ids for future
  expansion, the step file and sleep file parse without
  error. Skip if `/opt/smart-ring/code/temp/GARMIN/` absent.
- **Verified:** 254/254 pytest in 18.8s, 9/9 vitest, `npm
  run lint` + `npm run build` clean. No production DB
  changes (nothing was ingested — the extractors are
  stubs).
- **Path to unblock** (in `docs/GARMIN_INTEGRATION_RESEARCH.md`
  §Phase 1.5):
  - **Option 1 (recommended):** drop in a newer FIT SDK
    profile (21.202+ has full definitions). Phase 2 is
    heading to Rust anyway, and the Rust `fitparser`
    crate already uses 21.202. The Python monitoring.py
    becomes the spec.
  - **Option 2:** decode against reference data — pull a
    known day's values from Garmin Connect (or compare
    against the user's ring's overnight readings for the
    same night) and hand-decode the field IDs. ~1 day of
    work but produces a permanent local mapping.
  - **Option 3:** port Gadgetbridge's reverse-engineered
    field mappings for the 745 (free, but requires
    reading their Java source).

### 2026-07-30 — Phase 1: Garmin 745 USB/FIT backfill
- **Goal:** get all historical Garmin activity data into Postgres via
  USB dump. Per the user's earlier decision, USB+ FIT first (no
  cloud dependency, no 2FA, fully aligned with the project's
  privacy ethos). Rust re-port deferred to Phase 2.
- **Branch:** `garmin-integration` (renamed from
  `feature/n-source-resolver`). 8 files, +~900 LOC, 204→239 tests.
- **Schema (5 new tables in `db/init.sql`):**
  - `activities` — one row per FIT file (UNIQUE source+start_ts)
  - `activity_laps` — per-lap splits (FK to activities)
  - `activity_trackpoints` — 1-Hz GPS/HR/cadence/altitude/temp
  - `activity_hr` — 1-Hz HR-only projection (lighter for charts)
  - `garmin_fit_ingest` — idempotency log (file_path + sha256)
  - All tables `source` default to `'garmin'`; schema future-proofs
    multi-source activity (colmi-activities, etc.) without migration.
- **Parser (`collector/garmin/parser.py`):** uses `fitparse` (Python
  FIT SDK binding). `discover_fit_files()` walks Activity/ + Summary/
  subdirs, skips Settings/Sports/Workouts/Metrics/Sleep. Sport enum
  → activity_type translation table (running, walking, cycling,
  hiking, swimming, etc.). GPS coordinates stored as FIT
  semicircles (sint32) for fidelity; converted at API boundary.
- **Ingest (`collector/garmin/ingest.py`):** CLI `python -m
  collector.garmin.ingest --fit-dir <path>`. ON CONFLICT for both
  activities (by source+start_ts) and garmin_fit_ingest (by
  file_path). Laps + trackpoints wiped-and-rewritten on conflict
  (cheap; <100 rows per activity). Idempotency verified: re-running
  on a fully-ingested directory is a no-op (`found=40 inserted=0
  skipped=40`).
- **Tests:** +35 (26 in `test_garmin_parser` for file discovery,
  session/lap/trackpoint parsing, sport translation, hashing; 9 in
  `test_garmin_ingest` for end-to-end ingest, idempotency-by-path,
  idempotency-by-hash-after-move, conflict resolution, directory
  walk). All tests skip if `/opt/smart-ring/code/temp/GARMIN/` is
  not present (CI may not have the data).
- **Verified live:** ran the full backfill against the production
  DB. 40 activities, 80 laps, 25,950 trackpoints, 25,943
  activity_hr rows. Activities include 2023-10-12 (earliest
  walk) through 2026-07-29. Spotted activity 1 (a 77-min walk on
  2026-07-29): 1.2 km elevation gain, 1239 trackpoints, HR
  84→75bpm cooldown, training_effect_aerobic=2.0.
- **Phase 1 deferred:** Metrics/Sleep files (daily summaries) use
  newer FIT SDK message types (global_id 229, 232, 281, etc.) that
  `fitparse` doesn't have profiles for. The pure-file-id-44 ingest
  path is identical (just the field-id→semantic mapping differs);
  ~1-2 days of work to ship. Will tackle in Phase 1.5 after the
  dashboard has a place to display daily Garmin metrics.

### 2026-07-30 — Phase 0: N-source resolver (Garmin integration prerequisite)
- **Goal:** unblock Garmin integration by teaching the analytics pipeline to
  handle N overlapping sources, not just ring + phone. Per
  `docs/GARMIN_INTEGRATION_RESEARCH.md` §10, this is the prerequisite before
  any overlapping Garmin data lands in `raw_*` (today's hardcoded `ring > phone`
  dedupe would silently double-count a third source).
- **Branch:** `feature/n-source-resolver` (off dev). 15 files, +988/-137, 132→204 tests.
- **New module — `collector/analytics/source_priority.py`:** single source of
  truth for "which source wins" per metric. `DEFAULT_PRIORITY` = `(ring, garmin,
  phone)` for every metric; `select_preferred_source()` and `sources_to_drop()`
  are pure functions, fully testable without a DB. Adding a fourth source (e.g.
  `oura`) is a one-line change.
- **`dedupe.py`:** replaced the hardcoded `ring > phone` SQL with a generic
  resolver driven by `source_priority`. The point-table and sleep dedupe were
  unified into a single `_drop_non_preferred` helper (table + slot keys + priority
  chain are the inputs). Backwards compatible: with only ring+phone data, the
  result is byte-identical to the old behaviour.
- **`sleep.py`:** replaced the hardcoded `ring`-first `CASE` with the same
  priority chain, so day-level sleep source selection is now consistent with
  point-table dedupe.
- **`data_quality`:** `source` is now part of the PK `(day, data_type, source)`.
  Each source gets its own freshness row — "ring HR ok / garmin HR stale" is now
  a first-class signal. Migration block in `db/init.sql` adds the source column
  + rebuilds the PK safely on a live DB (verified via psql on the production
  container). Intra-day freshness gap now fires for any source, not just ring.
- **API + React:** `/api/data-quality` optional `?source=` filter.
  Dashboard `SensorFreshnessStrip` uses `?source=ring` (always-visible chips).
  Freshness rules recalibrated 2026-08 against prod cadences — see `docs/DATA_QUALITY.md`.
- **Tests:** +72 (8 in `test_source_priority` for pure helpers, 8 in `test_dedupe`
  for 3-source overlap + custom priority + unknown-source preservation, 4 in
  `test_data_quality` for per-source semantics). 204/204 pytest in 8.6 s, 9/9
  vitest, `npm run lint` + `npm run build` clean.
- **Verified live:** ran `python -m collector.analytics` against the production
  DB after the migration; ring rows = ok, phone rows = stale (no phone data but
  ring has data → stale for that source). Dashboard banner correctly silent
  (filters to ring, all ok).

### 2026-07-30 — PWA pull-to-refresh + last-sync on mobile + PWA plumbing cleanup
- **Symptom 1:** once the dashboard was opened as an installed PWA (standalone
  display mode), pull-to-refresh stopped working. The desktop browser was fine.
- **Symptom 2:** "Last sync: …" was visible on the desktop browser but not on
  the phone PWA. No last-sync info at all in the mobile nav.
- **Root cause 1 (PTR):** the app had no custom pull-to-refresh — it relied on
  Chrome's *native* pull-to-reload. Once `display: "standalone"` takes over
  (vite.config.ts:29), the browser chrome and its reload gesture are gone, so
  the gesture does nothing. Only the existing TanStack auto-refetch on focus +
  the 3 s sync-progress poll were keeping data live.
- **Root cause 2 (last-sync):** `Nav.tsx:34` was `hidden sm:inline` — the full
  timestamp was hidden below Tailwind's 640 px breakpoint. On a phone
  (PWA *or* mobile browser) it was `display:none`. No PWA-vs-browser branching
  existed; the difference was pure viewport width (desktop vs phone).
- **Fix 1 — `web/src/components/ui/PullToRefresh.tsx` (new, 122 lines):** in-app
  touch gesture that activates only at `window.scrollY <= 0`, ignores
  horizontal swipes, and on release past 70 px calls
  `queryClient.invalidateQueries()` (refetch all, matching the post-sync
  blanket invalidate in `useSyncPolling.ts`). Wrap the app in `App.tsx`.
  Touch-only — mouse/trackpad keeps native browser refresh.
- **Fix 2 — `web/src/hooks/useRelativeTime.ts` (new) + `Nav.tsx`:** add a
  compact "Synced 2m ago" / "Yesterday 3:45 PM" line in the always-visible
  second nav row, mobile-only (`sm:hidden`), next to `BatteryIndicator`.
  Desktop row keeps the full timestamp. The hook self-ticks (10s < 1h,
  30s < 3h, 60s < 24h, 5min beyond) so the relative label never lies.
- **Fix 3 (plumbing cleanup, secondary):** deleted the stale
  `web/public/manifest.webmanifest` (overwritten at build by the inline one
  in `vite.config.ts`; had the old "Stan's Ring" name + root-scope) and the
  vestigial `/sw.js` + `/manifest.webmanifest` root routes in `api/main.py`
  (React build self-registers `/static/sw.js` at `/static/` scope; the
  `Service-Worker-Allowed: /` header no longer matched reality). Verified
  live: `/sw.js` and `/manifest.webmanifest` → 404, `/static/sw.js` and
  `/static/manifest.webmanifest` → 200, `/` and `/api/admin/ring-status` → 200.
- **Verified:** `npm run lint` clean, `npm run build` clean (ttypescript + vite),
  9/9 vitest, 173/173 pytest in 6.95 s. Uvicorn `--reload` picked up the
  `api/main.py` change automatically; no container restart needed. Dashboard
  rebuild landed in `dashboard/dist/` (new `index-BZkLysa5.js`,
  `index-AKSdjBo_.css`).
- **PWA update dance:** installed PWA on the phone will pick up the new SW
  on next launch via `main.tsx`'s `reg.update()`. No user action required
  beyond a normal reopen.
- **Follow-up — pull-to-refresh "works once, then never":** user reported the
  gesture only worked on the first attempt. Root cause: the original
  `PullToRefresh` used `passive: true` on touchmove, so `e.preventDefault()`
  was a no-op and the browser's overscroll kept claiming the gesture on
  subsequent pulls. Secondary issue: `pull`/`refreshing` were React state, so
  the effect re-attached all four window listeners on every pixel of drag,
  risking lost events mid-gesture. Fix in `PullToRefresh.tsx`: refactored
  `pull`/`refreshing`/`startY`/`startX`/`triggered` to refs, single effect
  attach (deps `[queryClient]`), `tick` counter for re-renders (throttled to
  >=1px changes), `passive: false` on touchmove + `e.preventDefault()` when
  engaging. `overscroll-behavior: none` was already on body so the CSS side
  needed no change.
- **Follow-up 2 — PTR "scrolls a bit then can't scroll":** the refactor above
  introduced a regression: my "are we at the top?" check used `window.scrollY`,
  but the page layout is `html { overflow: hidden }` + `body { overflow-y: auto }`
  (`index.css`), so `window.scrollY` is *always 0* regardless of the body's
  actual scroll position. Once the user scrolled down even a few pixels, my
  touchmove handler thought they were "at the top" and called
  `e.preventDefault()` on every move, silently killing all subsequent
  scrolling. Fix: new `isAtScrollTop()` helper reads `body.scrollTop` and
  `documentElement.scrollTop` (the real scroll container is the body), and
  only `preventDefault()`s when truly at the top. The check is now strictly
  conservative — if the body has scrolled even 1px, we never touch the
  default scroll behavior.
- **Follow-up 3 — PWA refresh button (PTR gesture still flaky on some
  Android builds):** the user reported the pull-to-refresh gesture remained
  inconsistent even after the scroll-check fix. Added a dedicated refresh
  button to the nav, **visible only when the app is running as an installed
  PWA** (detected via `matchMedia("(display-mode: standalone)")` and
  `navigator.standalone` for iOS). Sits to the left of the dark-mode toggle,
  calls `queryClient.invalidateQueries()` (same blanket invalidate the PTR
  gesture uses), uses TanStack's `useIsFetching` to spin + disable itself
  while a refetch is in flight. The gesture is still wired in as a
  convenience, but the button is the reliable path.
- **Follow-up 4 — refresh button "doesn't seem to do anything":** user
  reported tapping the button had no visible effect. Root cause: a local-API
  refetch often completes in <50ms, and the server data is usually identical
  (no new sync happened on the server), so the only feedback the user got
  was a 50ms spinner flash that's not perceptible. Fix in `Nav.tsx`: added
  a local `refreshing` state that holds the spinner for a minimum of 600ms
  (same pattern the pull-to-refresh uses) so the action is visibly
  acknowledged. `showSpinner = refreshing || isFetching > 0` — either an
  explicit refresh OR any background refetch triggers the spin. Refresh
  timer cleared on rapid repeat clicks so a second tap doesn't get stuck.

### 2026-07-26 — Runtime docs truth-up (dual Podman store)
- Added `docs/RUNTIME.md` as the ops contract. Fixed AGENTS/README/TASKS/RESEARCH so
  commands never imply bare `podman` or quadlets/compose/user units. Deleted
  `docker-compose.yml`. Host opencode AGENTS got the dual-store line. Root cause of
  “no containers” agent failures: interactive Podman ≠ unit `XDG_DATA_HOME` store.

### 2026-07-27 — Steps queue-pollution fix + intra-day freshness alert
- **Symptom:** user reported steps not pulling in; dashboard freshness banner
  silent. DB showed sync #182 completed cleanly (HR/HRV/stress fresh) but
  `raw_steps` had zero new rows after 16:00 — the ring had the data
  (Gadgetbridge confirmed), our collector silently dropped it.
- **Root cause 1 (steps):** stale packets in `client.queues[67]` from a prior
  per-day request were consumed by `get_steps()`'s single `.get()` before the
  new response arrived → `fetch_steps` returned `[]` for today, no exception
  raised. Same class of bug as the V2 big-data path documented in
  `docs/RING_BEHAVIOR.md`. Fix in `collector/protocol/parsers/steps.py`:
  added `_drain_steps_queue()` + `_reset_steps_parser()` prologue before each
  per-day request, plus per-day `log.info` with parsed `time_index` ranges.
  Also bumped `get_steps` timeout 2 s → 4 s (`collector/ring_client.py:430`)
  for busy R09 days (up to 96 slot packets).
- **Root cause 2 (alert):** `collector/analytics/data_quality.py` only flagged
  "stale" when `cnt == 0` for the day — totally missed the intra-day gap
  (steps has 9 samples today, just none past 16:00 while HR is current).
  Added peer-relative freshness check: per-type thresholds (HR 30 m · HRV 90 m
  · Steps 90 m · SpO₂ 3 h · Stress 90 m; temp exempt), gated on a peer being
  fresh within 30 m (ring is actively worn). Catches the steps-stall case
  without false-alarming overnight when the ring is off.
- **Verified live:** triggered sync #173 via `sync_requests` → pulled the 3
  missing hours (17:00/18:00/19:00). All types fresh post-sync, banner
  correctly silent. Reproducible via `INSERT INTO sync_requests(requested_by)
  VALUES ('admin-ui')` and watching `journalctl -u smart-ring-poller`.
- **Tests:** +13 (6 in `tests/test_steps_drain.py`, 7 in
  `tests/test_data_quality.py`). Suite total: 173 passing in 6.76 s.
  New data_quality tests cover both the original `cnt==0` rule and the
  new intra-day peer-relative rule (stale flag, threshold boundary,
  ring-off no-false-alarm, historical-day skip, temp exemption).

### 2026-07-26 — Activity detection plan (research → concrete Phases 1–2)
- Rewrote `docs/ACTIVITY_DETECTION_RESEARCH.md` from sketch into a build contract:
  Phase 1 = Edwards TRIMP→strain 0–21 + zone minutes; Phase 2 = 15-min step+HR
  segments (`walking`/`running`/`general_activity` only). Fixes from review:
  schema stores minutes (not thresholds), 7d prior RHR baseline, per-slot wear,
  idempotent segments, `USER_AGE`, no fake cycling, readiness unchanged until
  prior-day strain later. Not implemented yet — design only.

### 2026-07-26 — Recovery card label/value tightening + hero HRV bug fix
- **RecoveryCard** (`web/src/components/cards/RecoveryCard.tsx`): the `flex
  justify-between` rows stretched labels to the left edge and values to the far
  right of a ~450px column, leaving a big gap between them. Reworked into a
  hero HRV (left) + 2-column stat grid (right, two tight label:value pairs per
  row) + a description line grounded in the Plews/Altini z-score framework.
  Fills the card width without boxes or far-edge stretching.
- **Removed the Stress row** (redundant — stress is shown in Current Status).
  Dropped the now-dead `useStress` fetch + `stressDailyAvg`/trend computation.
- **Bug fix:** "latest HRV" was `hrvToday[0]` (insertion order = first sample of
  the day, not latest). Now sorts by `ts` desc before picking. Label is truthful.
- **Tiny polish:** added `dark:` color variants to the hero HRV number, bumped
  stat text to `text-base` with `gap-10` separation from the hero.
- Presentational only; `npm run build` + `npm run lint` clean. No pytest/vitest impact.

### 2026-07-26 — Dashboard React rewrite (cutover complete)
- **Replaced** the 3,230-line Alpine.js monolithic `dashboard/index.html` with a
  componentized React + TypeScript app in `web/`. Vite builds to `dashboard/dist/`;
  `DASHBOARD_DIR` flipped from `dashboard` to `dashboard/dist` in `api/main.py`.
- **Stack:** React 19, TypeScript 5, Vite 8, Tailwind CSS 3, TanStack Query 5,
  Recharts 3, vite-plugin-pwa. 9/9 Vitest protocol tests for Web Bluetooth.
- **Legacy files deleted:** `dashboard/index.html`, `sw.js`, `manifest.webmanifest`,
  5 icon PNGs (now served from `dashboard/dist/` via Vite build).
- **Branch:** `dashboard-react-rewrite` → merged/PR pending.
- **Next:** packaged-app fork (`docs/PACKAGED_APP.md`).

### 2026-07-25 — Phase 1: dialect-neutral SQL (packaged-app prep)
- **Goal:** replace Postgres-only query constructs so the same code runs on both PG
  and SQLite. Unblocks the packaged-app fork planned in `docs/PACKAGED_APP.md`.
- **Changes:** `api/main.py` (15 sites) + 7 analytics scorers (20 sites): all
  `NOW()`/`CURRENT_DATE - INTERVAL` → Python-computed cutoff params passed as bind
  parameters. `REGR_SLOPE` → `statistics.linear_regression`, `PERCENTILE_CONT` →
  `statistics.median`. All changes PG-compatible — no behavior change.
- **Dialect surface:** shrank from ~35 PG-only constructs to 2 (both in the poller,
  which the packaged fork drops).
- **Test suite:** 132/132 green (4.84s). No scoring change expected — README_REGR
  + median parity pinned against production data.
- **Commit:** `eba7848` on `dev`.
- **Next:** dashboard React rewrite (`docs/DASHBOARD_REWRITE_PLAN.md`), then fork.

### 2026-07-24 — Moved project out of encrypted home (the real autostart fix)
- **Root cause of the recurring autostart failure:** project data + code lived in an encrypted home path (ecryptfs encrypted home), which only decrypts on login → boot-time services failed with `mkdir ~/.local: permission denied` until someone logged in. This is why "autostart" never worked headless across prior sessions.
- **Fix:** relocated everything to `/opt/smart-ring` (outside the encrypted home): code → `/opt/smart-ring/code`, Podman storage → `/opt/smart-ring/.local/share/containers` (via `XDG_DATA_HOME=` in the units). System units set `WantedBy=multi-user.target` + `After=user@1000.service network-online.target`.
- **Rebuild, not move:** naive `mv` of podman storage broke (libpod DB hardcodes its path) and the venv's editable-install + script shebangs pointed at the old path. So: storage reset + image rebuilt from `api/Dockerfile`, DB restored from a `pg_dump`, editable install re-run (`venv/bin/python3 -m pip install -e . --no-deps`). Direct `venv/bin/pip`/`pytest` shebangs are still stale — use `python3 -m`.
- **Verified by a real cold reboot (no login):** all 3 services came up at boot, zero encrypted-home errors. (Poller has a harmless ~10s DB-not-ready blip on first boot; self-heals via `Restart=on-failure`.)
- **Also deleted** the 142 GB stale Win10 VM dupe in `~/vmware` (live VM is at `/opt/vmware`); cleaned VMware inventory + preferences.
- **Lesson (do not repeat):** stale `~/.config/systemd/user/` unit mirrors and `~` paths in docs misled multiple sessions into chasing the wrong layer (linger, user-vs-system). Canonical units = `/etc/systemd/system/`; canonical code = `/opt/smart-ring/code`. **Always verify autostart with a cold-reboot + boot-log check, never an "is it running now" check.**

### 2026-07-21 — PWA (installable + offline shell)
- Dashboard is now an installable PWA. Manifest + service worker + 5 PNG icons
  (regular/maskable/192/512/apple-180) generated via `scripts/gen_icons.py`
  (Pillow, one-shot). Verified live on Android Chrome.
- SW strategies: network-first for `/api/*` + navigations, cache-first for `/static/*`. Mobile sync
  POST stays network-only — errors surface via existing banner.
- `api/main.py` got two new root-scope routes (`/sw.js`, `/manifest.webmanifest`)
  because the existing `/static` mount would only give the SW `/static/` scope.
  SW response carries `Service-Worker-Allowed: /`.
- No build step added; no Python logic touched; 132/132 tests still pass.
- See `docs/PWA_PLAN.md`.

### 2026-07-20 — Morning Readiness (frozen) + Current Status (live)
- Replaced the dynamic-readiness model (where today's score drifted during
  the day as data accumulated) with two distinct concepts on a feature branch:
  - **Morning Readiness**: locks at first analytics pass at/after 6 AM local.
    `frozen_at` column on `readiness_score`; subsequent passes skip today.
  - **Current Status**: new `current_status` table, one row per analytics pass.
    4 components (HRV 40% / HR 25% / Stress 20% / Trend 15%); vibe labels
    Locked In / Solid / Vibing / Winded / Gassed.
- Pure helpers (`should_freeze`, component scorers, `weighted_score`) are
  unit-tested at boundaries. DB-backed tests verify the freeze gate.
- Suite total: 132 tests pass in 5.35s (+67 from baseline 65).
- Branch: `feature/morning-readiness-and-current-status` (commit `8c66496`).

### 2026-07-20 — API cleanup arc + Tier 1 test suite
- **API cleanup Steps 1, 2, 4** shipped + verified live (`4032415`, `0b14cae`): dropped
  dead ORM code, dropped redundant `_dedupe_sources` (analytics owns dedup), shipped
  `api/upsert.py` generic dispatcher for the 5 simple point tables. Step 3 skipped
  indefinitely as "deck chairs" — see CLEANUP_PLAN.md for rationale.
- **Test suite** (`tests/`, 65 tests, ~4s): `test_trap_score.py` (20),
  `test_time_sync_bcd.py` (16), `test_dedupe.py` (13), `test_mobile_sync.py` (16).
  Ephemeral DB fixture in `conftest.py` creates `smart_ring_test_<pid>` from
  `db/init.sql` — never touches production data.
- **Sacred-code refactor**: extracted `_encode_time_bcd` pure helper from
  `set_time_local` (`4c12e06`). Pinned byte-for-byte by `tests/test_time_sync_bcd.py`.
  No rebuild/restart needed (in `collector/`, not `api/`); next ring sync exercises
  the new path — `clock_drift_ms=1` is the live success signal.
- **Quirk pinned** (not yet fixed): per-attempt `accepted` counting in
  `/api/mobile/sync` — ON CONFLICT DO NOTHING doesn't raise, so duplicate ts in one
  payload counts both. May be fixed in a follow-up using `cursor.rowcount`.

### 2026-07-21 — Historical freeze-timestamp cascade cleanup + badge simplification
- **Investigation**: user reported the readiness 🔒 lock timestamp showed the first sync of the day (e.g., 12:33 PM) rather than 6 AM. Root cause: the freeze fires on the first **analytics pass** at/after 6 AM, and analytics only runs after a sync. So the freeze timestamp = first sync time.
- **Considered and rejected**: a 6 AM self-trigger on the poller. Tried it, reverted it. At 6 AM the ring hasn't synced yet → DB has stale (yesterday's last) data. The user's first sync post-6 AM brings in the overnight sleep + morning HRV (the data we actually want to lock in), so freeze-on-first-sync is the correct semantic. The Colmi buffers data on-device between syncs, so "first sync" captures the full overnight window.
- **Dashboard simplification**: removed the 🔒 "Locked at HH:MM" badge entirely. Showing the freeze timestamp misled users into reading it as "snapshot through HH:MM" (it's actually overnight data from the morning sync). The `Preliminary` badge already conveys the unfrozen state; its absence now conveys "final for the day".
- **Historical cascade cleanup**: 13 rows (7-07 through 7-19) all shared `frozen_at = 2026-07-20 20:02:58` — a backfill artifact from the freeze feature's first deploy. One-shot `UPDATE readiness_score SET frozen_at = NULL WHERE day < CURRENT_DATE - INTERVAL '1 day'`. Historical rows don't need freeze stamps (immutable).

### 2026-07-20 — Sync retry + battery noise documentation
- Sync #138–141 took 4 attempts (R09 cold-start + overlap artifact).
- R09 battery readings are noisy instantaneous ADC samples (no smoothing;
  Gadgetbridge does identical `value[1]` parsing). Documented in
  `docs/RING_BEHAVIOR.md`. Tracking raw values in `sync_log` + `ring_status`.

### 2026-07-19 — Live verification + poller analytics job fix
- Fixed `collector/jobs/analytics.py` (was referencing deleted
  `collector/analytics.py` causing rc=2 — now uses `python -m collector.analytics`).
- `set_time_local` Phase 0 hotfix proven in production.

### 2026-07-18 — Readiness overhaul + collector refactor
- 3-pillar readiness (HRV 44% / Sleep 37% / RHR 19%).
- Major collector refactor: split into `protocol/` + `analytics/` packages + `jobs/`.

**July 13–17:** Dashboard overhaul, temp big-data fix, docs reorganization. Details in git.

---

## Agent Notes

- **When editing:** Update the work log above. Keep it lean — details go in `docs/` or git history.
- **Secrets:** Never commit. Update `.env.example` for new env vars.
- **Runtime:** Follow `docs/RUNTIME.md`. Empty bare `podman ps` is not “stack down.” Never `systemctl --user`. Never compose/quadlets.
- **BLE protocol:** Cross-reference Gadgetbridge `yawell/ring` + `colmi.puxtril.com`.
- **Never raw Python to the ring.** Always `python -m collector.sync_ring --forget` (or `first_contact`). R09 needs forget+repair+wake.
- **No wrapper services or shims.** If autostart is broken, fix real unit deps — do not add startup wrapper units.
