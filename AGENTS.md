# AGENTS.md — Smart Ring Project

> Agent-facing context. This file is **lean** — details go in RESEARCH.md or git history.
> Update this when architecture, key files, or current state changes.

---

## Project Overview

Private, self-hosted health tracking built around the **Colmi R09** (~$45 CAD). BLE → Postgres → health metrics → Alpine.js dashboard.

- **Hardware:** Colmi R09 (BlueX RF03, PPG + SpO2 + skin temp + accelerometer), FW RT09_3.10.21_251107
- **Stack:** Python (async BLE via bleak), FastAPI, Postgres 16, Alpine.js + Tailwind CSS (no build step)
- **Deployment:** Local-first on Linux Mint HTPC (AMD 3800x, 64GB RAM)
- **Status:** Green. Ring validated. All 8 data types collecting. All 5 health scores computing. Poller + auto-refresh working.

---

## Current Architecture

```
Ring ──BLE──> Linux Box (bare metal, forget+repair each sync)
                ├─ smart-ring-poller.service  (systemd user unit, 30s loop)
                │    └─ watches sync_requests → runs sync_ring.py --forget
                ├─ smart-ring-db.service      (rootless Podman, Postgres 16, port localhost:5432)
                └─ smart-ring-api.service     (rootless Podman, FastAPI, port localhost:8000)
                     └─ serves dashboard, all API endpoints
```

**Key facts:**
- **Collector is bare metal only** — needs BlueZ/DBus for BLE. Quadlets are host-specific (`~/.config/containers/systemd/`), NOT in repo.
- **R09 single-connection limit:** Linux box holds BLE during sync, then `forget_ring()` frees it for phone pairing.
- **Poller** (`smart-ring-poller.service`): DB-only poll at 30s interval, zero BLE between syncs. Runs `sync_ring.py --forget` via `collector-wrapper.py`.
- **`docker-compose.yml`** kept as fallback reference, not used locally.
- **Services start at boot** (lingering enabled).

### Service Commands
```bash
systemctl --user status smart-ring-db smart-ring-api smart-ring-poller
systemctl --user restart smart-ring-api              # after code change
podman exec smart-ring-db psql -U smart_ring -d smart_ring   # DB shell
podman build -t smart-ring-api:latest /home/sz/code/smart-ring/api
venv/bin/python3 collector/sync_ring.py --forget     # manual sync
venv/bin/python3 collector/first_contact.py          # diagnostic
```

---

## Key Source Files

| File | Purpose | Key Details |
|------|---------|-------------|
| `collector/ring_client.py` | BLE client wrapper | Timeout on BleakClient; V2 big-data service (sleep/SpO2/temp); `set_time_local()` (6 BCD bytes, no language byte, matches Gadgetbridge); forget/pair/disconnect BlueZ helpers |
| `collector/sync_ring.py` | BLE collector, syncs ring → Postgres | `connect_with_retry()` (exponential backoff); 12-phase `update_progress()` to `sync_log.current_step`; `_compute_clock_drift_ms()`; all 8 data types via correct Gadgetbridge commands; `.astimezone()` timestamps |
| `collector/analytics.py` | Health score computation | Sleep quality (5-component, Ohayon 2004 norms); HRV recovery (log-transform + 7-day z-score, Plews/Altini); Stress classification (Garmin/Firstbeat); Circadian HR; Resting HR |
| `collector/sync_request_poller.py` | Host-side poller | Watches `sync_requests` every 30s, claims with `FOR UPDATE SKIP LOCKED`, runs `collector-wrapper.py`, marks complete/failed, runs analytics after sync |
| `collector/collector-wrapper.py` | Shim for poller | Injects `--forget` into sys.argv for R09 reconnect-bug workaround |
| `collector/first_contact.py` | Read-only diagnostics | Battery, firmware, device info, `set_time_local()` — NO data sync |
| `api/main.py` | FastAPI endpoints | `/api/raw/*` (8 types), `/api/readiness`, `/api/daily-activity`, `/api/goals`, `/api/recovery`, `/api/sleep`, `/api/circadian-hr`, `/api/stress`, `/api/resting-hr`, `/api/mobile/sync` (phone Web Bluetooth), `/api/admin/{ring-status,health,sync-log,sync,sync-requests,sync-progress}` |
| `dashboard/index.html` | Single-page UI (3 tabs) | Pure SVG charts (no Chart.js); Catmull-Rom smoothing + hover tooltips; Hero panel (24h activity ring with radial step bars + sleep overlay + tap tooltips + Readiness Score 0–100 with 4 sub-scores + contributors); Web Bluetooth phone sync (multi-packet HR/HRV handlers, write-without-response, 12-phase progress); Vitals chart (HR+SpO2+Temp triple-axis); sleep donut + empty state; Analytics tab (pipeline ref + trend charts); sync button (spinner + elapsed timer + progress badge + auto-refresh + error banner); battery indicator; dark mode; date navigation; server-computed dials (daily_activity table) |
| `db/init.sql` | Postgres schema | ~20 tables (8 raw + daily_activity + readiness_score + sleep_quality + daily_recovery + hrv_trends + circadian_hr + stress_classification + sync_log + sync_requests + ring_status + ring_goals) |
| `RESEARCH.md` | Reference knowledge | BLE quirks & reconnect bug; protocol command mapping; validated score formulas; value-add analysis (our analytics vs ring/Gadgetbridge raw data) |
| `ROADMAP.md` | Planned future work | Mobile sync design (WebBluetooth PWA + Gadgetbridge fork options); not yet implemented |

---

## Current State

**Working (green):**
- All 8 data types collecting: HR, steps, HRV, sleep, SpO2, temperature, stress, goals
- All 5 health scores + unified Readiness Score (0-100 Oura-style)
- Web Bluetooth phone sync (Android Chrome → ring → `/api/mobile/sync` → dedup)
- 24h activity ring (radial step bars + sleep overlay + tap tooltips)
- Readiness Score hero (big ring, 4 sub-scores, contributors) + Activity Ring in unified panel
- Server-computed per-day activity + hourly arrays (daily_activity table) — no more flaky client-side calc
- Source dedup (ring canonical, phone fills gaps) in both container + host
- Timezone fix: Postgres `ALTER SYSTEM SET TimeZone='America/Vancouver'` + container `$TZ`
- Phone-sync analytics trigger via `sync_requests` queue (no more broken Popen)
- Sync button: spinner + elapsed timer + 12-phase progress badge + auto-refresh + inline error banner
- Clock sync: Gadgetbridge-compatible BCD local (6 data bytes, no language flag). Ack-based verification.
- Analytics tab: pipeline reference, score cards, 4 trend charts (7d/14d/30d/90d)
- Battery indicator in nav bar (green/amber/red)
- Sleep card: empty state when no data (no more stale fallback)
- Dashboard no-cache header (Cache-Control: no-cache, no-store, must-revalidate)

**Known gaps:**
- 0x80-bit async packets not investigated (probably sleep/HRV/temp historical push)
- No auto-sync via systemd timer yet (manual + poller only)
- HRV is composite single-byte (not true RR intervals) — z-score still works, RMSSD/pNN50 unavailable
- Steps undercount vs wrist devices (rings inherently register fewer steps)
- Phone steps not fetched (Web Bluetooth sync doesn't query step data — only HR/SpO2/temp/sleep/HRV)

**See RESEARCH.md for:** BLE quirks & reconnect bug, full protocol command table, validated score formulas (with citations), value-add analysis (our analytics vs ring/Gadgetbridge data), deployment topology, CFW roadmap.

---

## Recent Work Log (Jul 2026)

### 2026-07-13 — Dashboard Overhaul: Readiness Score + Activity Ring + Source Dedup + Timezone Fix

**Major dashboard revamp.** Replaced the client-side "Today's Activity" dials with server-computed data and a unified hero panel:

- **Readiness Score (Oura-style 0–100)**: New `daily_activity` and `readiness_score` tables (computed in analytics.py, Pacific tz). Weighted composite: 35% HRV (z-score→0-100) + 30% Sleep (sleep_quality.score) + 20% Activity (steps vs goal) + 15% RHR (vs 30-day baseline). `/api/readiness` endpoint. Hero panel shows big score ring with 4 sub-score cards (Sleep/HRV/Activity/RHR) and contributors (e.g. "+18 HRV · +9 Sleep · -6 Activity · +6 RHR"). Date-aware (toggles with day nav).
- **24h Activity Ring (Gadgetbridge-style)**: Radial bar chart where each of 24 hours shows wear/sleep/off status (colored baseline) + step count (bar height ∝ steps). Sleep stages (deep/REM/light/awake) overlay the ring. Tap/hover tooltips. Replaces the separate steps timeline graph.
- **Unified hero panel**: Activity Ring (left) + Readiness Score (right) in one seamless card.
- **`daily_activity` table**: Server-side per-day aggregates (steps, distance, calories, HR stats, wear time). Includes `hourly_steps` and `hourly_worn` JSONB arrays for the ring. `/api/daily-activity` endpoint. Replaces flaky client-side day filtering.
- **Timezone fix**: `ALTER SYSTEM SET TimeZone='America/Vancouver'` on Postgres + `TZ=America/Vancouver` on both quadlets. `CURRENT_DATE`/`ts::date` now Pacific. Ring time-setting unaffected (host collector's `set_time_local` still sends Pacific-local BCD).
- **Source dedup**: Ring canonical, phone fills gaps. `_dedupe_sources()` in `mobile_sync` (container) + `analytics.py` (host). Removes phone rows where ring has same key. Removed 356 duplicates; only 7 phone gap-fills remain. `source` column preserved on all surviving rows.
- **Sleep card improvement**: No more fallback to older nights (was showing 2-nights-ago data). Shows empty state ("No sleep recorded last night") when no data for selected day.
- **Phone sync built**: Web Bluetooth JS with multi-packet HR/HRV handlers, write-without-response, temp 0x27 skip (sleep type contamination), phone-analytics queue trigger. Status bar with phase progress.

**Files**: `db/init.sql`, `collector/analytics.py`, `api/main.py`, `dashboard/index.html`, `~/.config/containers/systemd/*.container`, `TASKS.md`

### 2026-07-12 (b) — Web Bluetooth Phone Sync: Multi-Packet Fix
- **Root cause of "only 6 records":** JS response queue resolved on the *first* 16-byte packet and dropped the rest. But HR (0x15) and HRV (0x39) are **multi-packet** responses. Plus an **extra `}`** in the sleep parser closed `connect()` early so the module only worked partially.
- **HR protocol** (matches lib `HeartRateLogParser`): pkt[sub0]=header(size@byte2), pkt[sub1]=ts+9 vals, pkts[sub2..N]=13 vals → 288 slots @5-min from local midnight.
- **HRV protocol** (matches stress 0x37): sub0=header, sub1=12 vals, sub2..4=13 vals @30-min.
- **Fix:** Replaced queue-of-resolvers with a `handlers` registry supporting `sendCmd` (single) + `sendCmdMulti(c, data, isLast)` (collect until terminal sub_type). Rewrote HR + HRV fetchers. Removed extra brace. Removed duplicate SpO2 insert in `mobile_sync`.
- **Files:** `dashboard/index.html` (phone-sync script), `api/main.py` (dedup SpO2), `TASKS.md`
- **Verified:** node --check OK (85/85 braces), `main.py` parses, service restarted, dashboard + `/api/mobile/sync` return 200. **Phone live test pending.**

### 2026-07-12 — Temperature Big-Data Fix + Time Sync Ack Verification
- **Temperature fix:** Ring stores 5 days of temperature across big-data types 0x25-0x29 (one type per day, oldest to newest). Previous code only queried 0x25 (4 days ago), missing 4 days of data. Fix: `fetch_temperature_history()` now loops 0x25-0x29. 142 records synced (5 nights, 30-min intervals, overnight skin temp).
- **Time sync:** Same as below — ack-based verification replaces drift metric.
- **Problem:** `_compute_clock_drift_ms()` measured `max(HR ts) - now()` from raw_heart_rate. With 30-min HR sampling, this always showed -10 to -30 min "drift" — just sampling lag, not clock error. False alarms on every sync. Couldn't distinguish ring-off-finger from genuine clock issues.
- **R09 time sync findings (Gadgetbridge source-verified):**
  - Gadgetbridge `setDateTime()`: 6 BCD data bytes, LOCAL time (GregorianCalendar.getInstance), no language flag. Our `set_time_local` matches byte-for-byte.
  - Library `set_time_packet()`: 7 bytes, UTC, language flag = 0x01. Wrong for R09 — firmware reads bytes as local wall-clock.
  - Library `client.py` registers `empty_parse` for CMD_SET_TIME (0x01) — silently discards the ring's capability response. Overrode with `_pass_through` so the ack reaches the queue.
- **Fix:** After `set_time_local()`, wait 3s for ring's response on `client.queues[0x01]`. Store `1` (acked) / `0` (no ack) in `sync_log.clock_drift_ms` (column reused). Dashboard sync log shows "OK" (green) / "No ack" (red). Removed drift alert banner (kept future_rows ring buffer warning).
- **Files:** `collector/ring_client.py` (override 0x01 handler), `collector/sync_ring.py` (ack wait, remove drift), `api/main.py` (simplify clock-alert), `dashboard/index.html` (Time Sync column)

### 2026-07-11 (c) — Sync Button: Spinner, Progress Stages, Auto-Refresh
- DB: `current_step TEXT` on `sync_log`. Collector writes 12 phases (Connected → … → Fetching goals).
- API: `GET /api/admin/sync-progress`. Dashboard: CSS spinner, elapsed timer `[M:SS]`, progress badge, auto-refresh on completion, inline error banner (replaces `alert()`), battery indicator in nav bar, circadian explainer moved inline.
- Files: `db/init.sql`, `collector/sync_ring.py`, `api/main.py`, `dashboard/index.html`

### 2026-07-11 (b) — Analytics Tab + Trend Charts
- Third tab (Dashboard/Analytics/Admin): data pipeline reference table, 4 score breakdown cards with expandable formulas, 4 trend charts (HRV, sleep, stress, resting HR) with date range selector.
- API: `GET /api/resting-hr?days=N`. Files: `dashboard/index.html`, `api/main.py`

### 2026-07-11 — Ring Time Sync Fix + Vitals Chart
- Root cause: library's `set_time_packet()` sent UTC BCD bytes; R09 reads as local. Fix: `set_time_local()` — 6 BCD bytes, no language byte, 2s delay. Clock drift tracking added.
- Dashboard: Vitals triple-axis SVG (HR+SpO2+Temp), Catmull-Rom smoothing on all charts, sync log consolidated to Admin tab only, clock alert banner.
- Files: `collector/ring_client.py`, `collector/sync_ring.py`, `api/main.py`, `dashboard/index.html`

### 2026-07-10 (d-e) — Big-Data Protocol + Analytics Rewrite
- Discovered V2 BLE service (`de5bf728`) for sleep/SpO2/temp via cmd 0xBC. Replaced broken cmd 68/105/115.
- Analytics full rewrite: peer-reviewed formulas (Ohayon 2004, Altini 2021, Garmin/Firstbeat). HRV z-score with 7-day baseline, sleep quality 5-component score.
- Dashboard redesign: sleep donut, circadian SVG, 4 activity dials, dark mode, stat cards.
- Files: `collector/ring_client.py` (V2 service), `collector/sync_ring.py` (big-data fetch/parse), `collector/analytics.py` (rewrite), `dashboard/index.html` (overhaul), `db/init.sql`

### Earlier (Jul 4-10 condensed)
- **2026-07-10 (c):** HRV protocol aligned to cmd 0x39 (Gadgetbridge `CMD_SYNC_HRV`) — 38 records across 3 days.
- **2026-07-10 (b):** Dashboard overhaul (Chart.js removed, CSS bars/dials, stress/goals/calories).
- **2026-07-10:** Poller restored at 30s interval (was retired Jul 9 due to sync_ring bugs, now fixed).
- **2026-07-09 (e):** Sync confirmed read-only; HR 49 records synced; step timestamps fixed (15-min slots).
- **2026-07-09 (d):** Poller retired (later reversed). `setup.sh` deleted.
- **2026-07-09 (c):** First Contact UI/API removed (ring already paired).
- **2026-07-09 (b):** Retry-on-sleep with exponential backoff (`connect_with_retry`).
- **2026-07-09:** Ring arrived — FW RT09_3.10.21, HW RT09_V3.1. First contact succeeds.
- **2026-07-08:** Sync poller first wired up.
- **2026-07-04:** Initial review + critical fixes (time sync, circadian PK, setup.sh). Docker→Podman+quadlets. Admin tab + DB job queue.

---

## Agent Notes

- **When editing:** Update the work log above. Keep it lean — details in RESEARCH.md or commit messages.
- **Secrets:** Never commit. Update `.env.example` for new env vars.
- **BLE protocol:** Cross-reference `colmi.puxtril.com` and Gadgetbridge source (`yawell/ring` namespace).
- **Runtime:** Collector = bare metal venv (`venv/bin/python3`). API + DB = Podman containers (restart with `systemctl --user`).
