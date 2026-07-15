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

### Hardware

- **Host:** Linux Mint HTPC (AMD 3800x, 64GB RAM, GTX 1070) — on 24/7
- **Bluetooth:** Built-in (combo WiFi+BT on motherboard PCIe)
- **Ring:** Colmi R09, size 11, FW RT09_3.10.21_251107, HW RT09_V3.1
- **BLE address:** stored in `.env` as `RING_ADDRESS`

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

**See RESEARCH.md for:** BLE protocol command table, validated score formulas (with citations), readiness score gap analysis (Oura vs WHOOP vs Garmin), value-add analysis (our analytics vs raw ring data), timezone design rationale, source dedup design.

**See TASKS.md for:** CFW roadmap, readiness score improvement backlog, future feature plans.

---

## Recent Work Log (Jul 2026)

### 2026-07-14 — Docs cleanup
- Split bloated RESEARCH.md into focused files: pure research in RESEARCH.md, CFW/readiness backlog in TASKS.md, hardware specs in AGENTS.md. Net: -522 lines.

### 2026-07-13 — Dashboard Overhaul: Readiness Score + Activity Ring + Source Dedup + Timezone Fix

Unified hero panel: 24h activity ring (radial step bars + sleep overlay) alongside Readiness Score 0-100 (4 sub-scores + contributors). `daily_activity` table (server-computed, Pacific tz, hourly JSONB). Source dedup (ring canonical, phone fills gaps). Postgres + container timezone fix. Sleep card empty state. Phone sync PWA.

**Earlier work (see `git log --oneline` for details):** Ring time sync fix (BCD local), phone sync multi-packet, temperature 5-day history, analytics rewrite (Ohayon 2004/Altini 2021/Firstbeat), big-data V2 protocol, poller architecture, initial collector + dashboard.

---

## Agent Notes

- **When editing:** Update the work log above. Keep it lean — details in RESEARCH.md or commit messages.
- **Secrets:** Never commit. Update `.env.example` for new env vars.
- **BLE protocol:** Cross-reference `colmi.puxtril.com` and Gadgetbridge source (`yawell/ring` namespace).
- **Runtime:** Collector = bare metal venv (`venv/bin/python3`). API + DB = Podman containers (restart with `systemctl --user`).
