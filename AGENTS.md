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
| `api/main.py` | FastAPI endpoints | `/api/raw/*` (8 types), `/api/goals`, `/api/recovery`, `/api/sleep`, `/api/circadian-hr`, `/api/stress`, `/api/resting-hr`, `/api/admin/{ring-status,health,sync-log,sync,sync-requests,sync-progress,clock-alert}` |
| `dashboard/index.html` | Single-page UI (3 tabs) | Pure SVG charts (no Chart.js); Catmull-Rom smoothing + hover tooltips + entrance animations; Vitals chart (HR+SpO2+Temp triple-axis); sleep donut; 4 activity dials; Analytics tab (pipeline ref + trend charts); sync button (spinner + elapsed timer + progress badge + auto-refresh + error banner); battery indicator; circadian inline explainer; dark mode; `clipFuture` filter |
| `db/init.sql` | Postgres schema | ~15 tables (8 raw + 5 computed + sync_log + sync_requests + ring_status + ring_goals) |
| `RESEARCH.md` | Reference knowledge | BLE quirks & reconnect bug; protocol command mapping; validated score formulas; value-add analysis (our analytics vs ring/Gadgetbridge raw data) |
| `ROADMAP.md` | Planned future work | Mobile sync design (WebBluetooth PWA + Gadgetbridge fork options); not yet implemented |

---

## Current State

**Working (green):**
- All 8 data types collecting: HR, steps, HRV, sleep, SpO2, temperature, stress, goals
- All 5 health scores computing: sleep quality, HRV recovery, stress classification, circadian HR, resting HR
- Sync button: spinner + elapsed timer + 12-phase progress badge + auto-refresh on completion + inline error banner
- Clock sync: Gadgetbridge-compatible BCD local (6 data bytes, no language flag). Ack-based verification — ring responds to set_time cmd, response confirms command was processed
- Analytics tab: pipeline reference, score cards, 4 trend charts (7d/14d/30d/90d)
- Battery indicator in nav bar (green/amber/red)

**Known gaps:**
- 0x80-bit async packets not investigated (probably sleep/HRV/temp historical push)
- No auto-sync via systemd timer yet (manual + poller only)
- No phone sync path (Gadgetbridge → FastAPI) yet
- HRV is composite single-byte (not true RR intervals) — z-score still works, RMSSD/pNN50 unavailable

**See RESEARCH.md for:** BLE quirks & reconnect bug, full protocol command table, validated score formulas (with citations), value-add analysis (our analytics vs ring/Gadgetbridge data), deployment topology, CFW roadmap.

---

## Recent Work Log (Jul 2026)

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
