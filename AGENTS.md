# AGENTS.md — Smart Ring Project

> Agent-facing context. This file is **lean** — details go in `docs/` (research, device behavior, roadmap) or git history.
> Update this when architecture, key files, or current state changes.

---

## Project Overview

Private, self-hosted health tracking around the **Colmi R09** (~$45 CAD).

- **Hardware:** Colmi R09 (FW RT09_3.10.21_251107), BLE → Postgres → health metrics → React dashboard
- **Stack:** Python (bleak), FastAPI, Postgres 16, React 19 + TypeScript 5 + Vite (build → `dashboard/dist/`)
- **Deployment:** Linux Mint HTPC (AMD 3800x / 64 GB) — bare metal for collector

**BLE address** is in `.env` as `RING_ADDRESS`. Ring size 11. Host on 24/7.

**Target device is Android.** The dashboard's phone sync uses Web Bluetooth, which iOS doesn't support (and never will — WebKit has no implementation). Don't propose iOS workarounds (Bluefy, WebBLE, native apps), don't flag iOS as a limitation in plans, and don't bend designs to accommodate iOS. The PWA installs fine on iOS as a read-only dashboard; that's a side-effect, not a target.

---

## Current Architecture

```
Ring ──BLE──> Linux Box (bare metal, forget+repair each sync)
                ├─ smart-ring-poller.service  (system systemd, User=<username>, 30s poll)
                │    └─ watches sync_requests → runs sync_ring.py
                ├─ smart-ring-db.service      (system systemd, User=<username>, rootless Podman)
                └─ smart-ring-api.service     (system systemd, User=<username>, rootless Podman)
                     └─ serves dashboard, all API endpoints

Project root:  /opt/smart-ring/code                          (code + venv — OUTSIDE the encrypted home; see note below)
Podman storage:/opt/smart-ring/.local/share/containers       (rootless; located via XDG_DATA_HOME in the units)
Unit files:    /etc/systemd/system/smart-ring-*.service      (CANONICAL — edit directly; no user-unit mirror)
```

**Critical facts (do not violate):**

- Collector is **bare metal only** (needs BlueZ/DBus) — runs `python -m collector.sync_ring`. Phone pairing requires `forget_ring()` after each sync.
- **R09 single-connection**: Linux box holds the BLE connection; `forget_ring()` releases the ring for phone use.
- **Poller** (`smart-ring-poller.service`): DB-only 30s loop. Watches `sync_requests`, dispatches jobs, then runs analytics. Auto-reaps stuck `sync_log` rows.
- **Services are system-level** (`/etc/systemd/system/`, `User=<username>`). Never use `systemctl --user` for production autostart. Use `sudo systemctl`.
- **Code + Podman storage live at `/opt/smart-ring`, NOT `~`.** Reason: the original home path was an **ecryptfs encrypted home** — it only decrypts on login, so anything stored in an encrypted home is unreachable at boot and boot-time services fail (`mkdir ... permission denied`) until someone logged in. That's why the project was relocated out of the home (2026-07-24). **Never move service data/code back into `~`.** This mirrors how `ollama` (dedicated system user) and the Win10 VM (`/opt/vmware`) already autostart reliably.

### Key commands
Run from the project root `/opt/smart-ring/code` (commands use relative paths). Note: the venv was relocated on 2026-07-24, so its `bin/pip` / `bin/pytest` shebangs are stale — always invoke via `venv/bin/python3 -m pip` / `venv/bin/python3 -m pytest`.
```bash
cd /opt/smart-ring/code
sudo systemctl restart smart-ring-api smart-ring-poller
sudo journalctl -u smart-ring-poller -f
venv/bin/python3 -m collector.sync_ring --forget
venv/bin/python3 -m collector.first_contact
venv/bin/python3 -m pytest tests/                # full regression net (65 tests, ~4s)
podman exec smart-ring-db psql -U smart_ring -d smart_ring
```

Unit files are canonical at `/etc/systemd/system/smart-ring-*.service` — edit them directly there. (The old `~/.config/systemd/user/` mirrors were removed on 2026-07-24.) After editing: `sudo systemctl daemon-reload && sudo systemctl restart smart-ring-db smart-ring-api smart-ring-poller`.

---

## Key Source Files

| File | Purpose |
|------|---------|
| `collector/ring_client.py` | BLE wrapper (timeout, `set_time_local`, forget/repair helpers, `_encode_time_bcd` pure helper) |
| `collector/sync_ring.py` + `protocol/` | Thin orchestrator + all BLE protocol, parsers, upserts |
| `collector/analytics/` | Package of per-scorer modules; `python -m collector.analytics` |
| `collector/analytics/readiness.py` | Morning Readiness scorer (frozen at 6 AM) + `should_freeze` pure helper |
| `collector/analytics/current_status.py` | Live intra-day scorer (Current Status) + pure component helpers |
| `collector/jobs/` | `SyncJob` / `RingSyncJob` / `AnalyticsJob` for the poller |
| `collector/sync_request_poller.py` | Host poller watching `sync_requests` |
| `api/main.py` | FastAPI app + all endpoints (mobile_sync uses dispatch loop) |
| `api/upsert.py` | `upsert_many` generic dispatcher for simple point tables |
| `dashboard/index.html` | ~~Pure client-side UI (Alpine.js + Tailwind, no build)~~ **retired 2026-07-26** — replaced by React app |
| `web/` | React + TypeScript dashboard (Vite build → `dashboard/dist/`). TanStack Query, Recharts, Tailwind 3, vite-plugin-pwa. See `docs/DASHBOARD_REWRITE_PLAN.md`. |
| `web/src/api/` | Typed API client: `types.ts` (25 interfaces), `hooks.ts` (25 TanStack Query hooks per endpoint), `client.ts` (fetch wrapper) |
| `web/src/components/ble/ringProtocol.ts` | Colmi R09 Web Bluetooth protocol + 9/9 Vitest byte-level tests |
| `dashboard/dist/` | Built React app (served by FastAPI at `/static/`). `npm run build` in `web/` to rebuild. |
| `scripts/gen_icons.py` | One-shot Pillow icon generator (192/512/maskable/apple-180) |
| `tests/` + `pytest.ini` | 132-test regression net (trap_score, BCD, dedupe, mobile_sync, current_status, readiness_freeze) |
| `docs/RING_BEHAVIOR.md` | Firmware quirks, data publish cadence, logger stall |
| `docs/RESEARCH.md` | Scoring formulas & methodology (Morning Readiness + Current Status) |
| `docs/CLEANUP_PLAN.md` | Cleanup arc history + Step 4 details |
| `docs/PWA_PLAN.md` | PWA strategies, manifest, service worker design |

---

## Current State

All 8 raw data types and the 5 health scores (including Morning Readiness frozen + Current Status live) are collecting and computing successfully. Phone sync + dashboard + poller are stable. Dashboard is now a React + TypeScript app (replaced Alpine.js monolith on 2026-07-26) served at `/static/` from `dashboard/dist/`. The legacy `dashboard/index.html`, `sw.js`, `manifest.webmanifest`, and icons are deleted. Dashboard ships as an installable PWA (offline shell + manifest + icons).

**Test suite:** 132 tests across 6 files (`tests/test_{trap_score,time_sync_bcd,dedupe,mobile_sync,current_status,readiness_freeze}.py`). Run with `venv/bin/python3 -m pytest tests/` — ~5s total. DB-backed tests use an ephemeral `smart_ring_test_<pid>` database created from `db/init.sql`; pure-function tests need no fixtures.

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
- Source dedup runs in analytics (`collector/analytics/dedupe.py:dedupe_sources()`) — single source of truth, runs before scorers every analytics pass. API-side `_dedupe_sources` removed (was redundant).

---

## Recent Work Log (Jul 2026)

For full history: `git log --oneline` and `docs/CLEANUP_PLAN.md`.

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
- **Runtime:** Collector = bare-metal venv; API + DB = Podman. Never `systemctl --user`; services are system-level. Project root is `/opt/smart-ring/code` (NOT `~` — encrypted home breaks boot autostart; see 2026-07-24 entry).
- **BLE protocol:** Cross-reference Gadgetbridge `yawell/ring` + `colmi.puxtril.com`.
- **Never raw Python to the ring.** Always use `python -m collector.sync_ring --forget` (or `python -m collector.first_contact`). The R09 needs the forget+repair+wake flow.
- **No wrapper services or shims.** If autostart is broken, find the real missing dependency instead of writing `smart-ring-startup.service`.
