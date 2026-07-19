# AGENTS.md — Smart Ring Project

> Agent-facing context. This file is **lean** — details go in `docs/` (research, device behavior, roadmap) or git history.
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
                ├─ smart-ring-poller.service  (system systemd, User=sz, 30s poll)
                │    └─ watches sync_requests → runs sync_ring.py
                ├─ smart-ring-db.service      (system systemd, User=sz, rootless Podman)
                └─ smart-ring-api.service     (system systemd, User=sz, rootless Podman)
                     └─ serves dashboard, all API endpoints

Source files: ~/.config/systemd/user/smart-ring-*.service (edit here)
Active:       /etc/systemd/system/smart-ring-*.service (sudo cp to deploy)
```

**Key facts:**
- **Services are SYSTEM-LEVEL, not user-level.** User systemd on this distro (systemd 255.4 + podman 4.9.3, Linux Mint) does NOT scan `~/.config/systemd/user/` at boot. Services live in `/etc/systemd/system/` with `User=sz`. Deploy with `sudo cp` + `sudo systemctl daemon-reload`. Source files in `~/.config/systemd/user/` for editing only.
- **DO NOT use `systemctl --user` for autostart.** It fails silently at boot. Use `sudo systemctl` for status, restart, enable, everything.
- **DO NOT use podman quadlet for user containers.** User quadlet generates transient units in `/run/` that conflict with persistent units. Use plain `.service` files with `ExecStart=podman run`.
- **Collector is bare metal only** — needs BlueZ/DBus for BLE. The ring's `forget_ring()` frees it for phone pairing after each sync.
- **R09 single-connection limit:** Linux box holds BLE during sync, then `forget_ring()` frees it for phone pairing.
- **Poller** (`smart-ring-poller.service`): DB-only poll at 30s interval, zero BLE between syncs. Runs `python -m collector.sync_ring` directly.
- **Cancel stuck syncs:** Dashboard Cancel button → `POST /api/admin/cancel-sync`. Clears both sync_requests AND sync_log stuck rows.
- **Sync log is the real culprit for stuck status.** When dashboard shows "running" but sync_requests looks clean, check `SELECT * FROM sync_log WHERE status='running'` — the poller being killed mid-sync leaves orphaned sync_log rows.

### Service Commands
```bash
sudo systemctl status smart-ring-db smart-ring-api smart-ring-poller
sudo systemctl restart smart-ring-api              # after code change in api/
sudo systemctl restart smart-ring-poller           # after code change in collector/
sudo journalctl -u smart-ring-db -f                # container logs
podman exec smart-ring-db psql -U smart_ring -d smart_ring   # DB shell
podman build -t smart-ring-api:latest /home/sz/code/smart-ring/api
venv/bin/python3 collector/sync_ring.py --forget     # manual sync
venv/bin/python3 collector/first_contact.py          # diagnostic
sudo cp ~/.config/systemd/user/smart-ring-*.service /etc/systemd/system/  # deploy after edits
sudo systemctl daemon-reload                         # after any .service edit
```

---

## Key Source Files

| File | Purpose | Key Details |
|------|---------|-------------|
| `collector/ring_client.py` | BLE client wrapper | Timeout on BleakClient; V2 big-data service (sleep/SpO2/temp: types 0x23–0x2B, skip 0x2A); `set_time_local()` (6 BCD bytes, no language byte, matches Gadgetbridge); forget/pair/disconnect BlueZ helpers; `_handle_tx` unmasks bit-7 for cmd 115 device-notify routing |
| `collector/sync_ring.py` | BLE collector, syncs ring → Postgres | Thin orchestrator; delegates BLE + parsers + upserts to `collector/protocol/`; CLI: `python -m collector.sync_ring [--no-forget] [--attempts N] [--no-retry] [scan]` |
| `collector/protocol/` | BLE protocol layer | `db.py` (sync state, packet framing, upserts), `connect.py` (retry + forget+repair), `time_sync.py` (SACRED — see Locked Constraints), `parsers/` (8 per-type parsers: hr/hrv/sleep/spo2/temp/stress/steps/goals) |
| `collector/analytics/` | Health score computation | Per-scorer modules (hrv, sleep, stress, circadian, rhr, daily_activity, readiness, data_quality, dedupe); `helpers.py` (trap_score, readiness_text); `db.py` (session TZ setup); `main.py` orchestrator. CLI: `python -m collector.analytics` |
| `collector/jobs/` | Poller job types | `SyncJob` abstract + `RingSyncJob` + `AnalyticsJob`. Replaces the old magic-string DISPATCH dict |
| `collector/sync_request_poller.py` | Host-side poller | Watches `sync_requests` every 30s, claims with `FOR UPDATE SKIP LOCKED`, dispatches to the right `SyncJob`, marks complete/failed, runs analytics after sync; `reap_stuck_rows()` auto-cleans orphaned sync_log rows; `set_session_timezone()` from `$TZ` at startup |
| `collector/first_contact.py` | Read-only diagnostics | Battery, firmware, device info, `set_time_local()` — NO data sync |
| `api/main.py` | FastAPI endpoints | `/api/raw/*` (8 types), `/api/readiness`, `/api/daily-activity`, `/api/goals`, `/api/recovery`, `/api/sleep`, `/api/circadian-hr`, `/api/stress`, `/api/resting-hr`, `/api/mobile/sync` (phone Web Bluetooth), `/api/admin/{ring-status,health,sync-log,sync,sync-requests,sync-progress}` |
| `dashboard/index.html` | Single-page UI (3 tabs) | Pure SVG charts (no Chart.js); Catmull-Rom smoothing + hover tooltips; Hero panel (24h activity ring with radial step bars + sleep overlay + tap tooltips + Readiness Score 0–100 with 4 sub-scores + contributors); Web Bluetooth phone sync (multi-packet HR/HRV handlers, write-without-response, 12-phase progress); Vitals chart (HR+SpO2+Temp triple-axis); sleep donut + empty state; Analytics tab (pipeline ref + trend charts); sync button (spinner + elapsed timer + progress badge + auto-refresh + error banner); battery indicator; dark mode; date navigation; server-computed dials (daily_activity table) |
| `db/init.sql` | Postgres schema | ~20 tables (8 raw + daily_activity + readiness_score + sleep_quality + daily_recovery + hrv_trends + circadian_hr + stress_classification + sync_log + sync_requests + ring_status + ring_goals) |
| `docs/RING_BEHAVIOR.md` | Device behavior | Empirical R09 firmware behavior: connection quirks, per-data-type reference (interval/buffer/publish cadence), logger stall, time-sync protocol |
| `docs/RESEARCH.md` | Reference knowledge | Validated score formulas (with citations); readiness gap analysis (Oura vs WHOOP vs Garmin); value-add analysis; hardware specs |
| `docs/ROADMAP.md` | Planned future work | Mobile sync design (WebBluetooth PWA + Gadgetbridge fork options) |

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
- Temp big-data range fixed: queries **0x22–0x2C** (skip 0x2A) with response dataId=0x25 check — catches all 8 rotating temp slots after discovering 0x23/0x24/0x2B held the current-day data that 0x25–0x29 missed
- Big-data queue drain between requests prevents shared-queue race (was causing 15/0/15/0 flakiness)
- Dashboard data-gap banner only reflects *today's* stale types (dropped yesterday-union false positive)
- Poller auto-reaps orphaned `sync_log` rows (stuck `running` >10 min → errored)

**Known gaps:**
- **R09 firmware logger can hang silently** — background HR-log (cmd 0x15) runs as a separate firmware task from live PPG. When it hangs, HRV/SpO2/stress keep flowing but HR buffer goes empty. Detection (HRV present + HR empty) implemented but auto-recovery is DISABLED (was unreliable). Data-quality staleness check + banner in dashboard. Manual toggle (via Gadgetbridge) or full power-cycle (discharge→recharge) needed if stall occurs. *Note: temp logger is part of the same background task — HR and temp stall together.*
- 0x80-bit async packets partially handled — cmd 115 device-notify frames (type 5 = temperature) now routed to queue for live-temp capture during sync windows.
- No auto-sync via systemd timer yet (manual + poller only)
- HRV is composite single-byte (not true RR intervals) — z-score still works, RMSSD/pNN50 unavailable
- Steps undercount vs wrist devices (rings inherently register fewer steps)
- Phone steps not fetched (Web Bluetooth sync doesn't query step data — only HR/SpO2/temp/sleep/HRV)
- Temp sync: R09 stores ~8 days of temp across big-data types **0x23–0x2B** (skip 0x2A = SpO2). The slot→day mapping rotates daily — fetch queries 0x22–0x2C with a response-dataId check for 0x25. **Publish cadence:** the history buffer only exposes *completed* days (`daysAgo` 1–7); today's temp (`daysAgo=0`) is absent until the ring commits it (late evening / day rollover). So "today" temp usually isn't fetchable until tonight or tomorrow — this is firmware behavior, not a fetch bug. See `docs/RING_BEHAVIOR.md`.

**See `docs/RING_BEHAVIOR.md` for:** connection quirks, read-only sync, per-data-type reference (commands · interval · buffer · publish cadence · format), V2 big-data protocol, background-logger stall, time-sync protocol.

**See `docs/RESEARCH.md` for:** validated score formulas (with citations), readiness score gap analysis (Oura vs WHOOP vs Garmin), value-add analysis (our analytics vs raw ring data), timezone design rationale, source dedup design.

**See TASKS.md for:** CFW roadmap, readiness score improvement backlog, future feature plans.

---

## Recent Work Log (Jul 2026)

### 2026-07-18 — Readiness overhaul: 3-pillar WHOOP-style, sleep/RHR/temp fixes
- **Readiness — drop activity, switch to 3-pillar:** activity (same-day steps) removed as circular — "readiness for today" shouldn't use today's activity. Reweighted: HRV 44% / Sleep 37% / RHR 19%. Dropped `activity_score` and `steps` columns from `readiness_score` table + schema. Updated `/api/readiness` and dashboard readiness ring.
- **RHR fix:** readiness was using `daily_activity.hr_avg` (24h average, ~70-82 bpm) as "resting HR." Switched to `hr_min` (overnight minimum, ~52-57 bpm) — a 25 bpm correction. Baseline dropped from 82→57 bpm.
- **Sleep scoring fix:** sleep stages from `raw_sleep` were grouped by calendar day, splitting midnight-spanning sessions and mixing two different nights' stages into one Frankenstein score. Now clusters stages by temporal gaps (4h+) into sessions, assigns to wake date. Fixes 07-11 (score 43→59) and other fragmented days.
- **Temp warning fix:** `sync_ring.py:1040` warning ("no temp for today, firmware may not have flushed") fired every sync on a normal state (today-pending is expected cadence). Now silent on normal; only warns if yesterday's temp is also missing.
- **Data-quality fix:** `data_quality` table flagged temperature "stale" every day (today-empty is normal). Now marks temp `ok` on the current day — only past days check for actual staleness.
- **Dashboard:** removed temp axis from vitals chart (always blank for today), added skin temp trend chart to Analytics tab.
- **Battery investigation:** confirmed syncs use proper `--forget` flow and tear down cleanly. HR interval changed from 30→15 min at some point (doubles PPG uptime). Average drain ~12%/day projects to ~8 days — consistent with 5-6 day reports at 10-min intervals. Overnight cliff drops likely gauge noise, not real capacity loss.
- **New `docs/` folder.** Moved `RESEARCH.md`, `ROADMAP.md`, `research/HRV-RECOVERY-SCORING-DEEP-DIVE.md` into `docs/`. Created `docs/RING_BEHAVIOR.md` as the canonical home for empirical R09 firmware behavior (connection quirks, per-data-type reference, logger stall, time-sync). Trimmed RESEARCH.md to methodology/formulas + pointers.
- **Temp publish cadence (finding, no code change):** investigated why today's temp was empty. Confirmed via collector.log that the fetch is healthy — the ring returns 7 completed day-blocks (`daysAgo` 1–7) but no `daysAgo=0` block. The history buffer only exposes completed days; today's temp isn't committed until late evening / day rollover. Documented in `docs/RING_BEHAVIOR.md`. Action: re-check tomorrow to confirm it lands.
- **Gadgetbridge worn/not-worn:** confirmed from GB source (`ColmiActivitySampleProvider` + `fillGaps`) that the R09 has no wear sensor — GB renders hourly step samples + gap-filled `UNKNOWN/NOT_MEASURED` dummies, producing the on/off cycling. Not a ring defect.

### 2026-07-19 — Live verification + poller analytics job fix (post-refactor)
- User triggered dashboard sync #132 (~14:16). Confirmed in DB: `clock_drift_ms=1`, 117 records, battery 52%, completed cleanly.
- Post-sync check: poller `AnalyticsJob` still targeted deleted `collector/analytics.py` (rc=2, "analytics failed" warnings).
- Fixed `collector/jobs/analytics.py` to invoke `python -m collector.analytics` (the supported entrypoint after Phase 4 split). Verified rc=0.
- Re-ran analytics; today's readiness recomputed fresh (40 → 53 full).
- Docs pass: work log + stale current-state references cleaned.

### 2026-07-19 — Post-cleanup hotfix: `set_time_local` regression + dead HR-log removal
- Phase 0 refactor `89be367` accidentally deleted both `set_time` **and** the `async def set_time_local(self, ts)` signature while removing dead code. The carefully-tuned BCD body remained as dead unreachable statements inside `get_realtime_reading`. `sync_time_to_ring()` (and first_contact) hit `AttributeError`. Time-sync silently "failed" (caught) on every collector run since the cleanup; `clock_drift_ms` was NULL for affected syncs.
- Hotfix: restored `async def set_time_local(self, ts: datetime) -> None:` before the preserved docstring+body. Removed the three leftover HR-log wrapper methods (`get_heart_rate_log*` + `set_*`) that still referenced the removed `date_utils` import (no callers in collector path).
- Verification: BCD encoding roundtrip correct (matches Gadgetbridge reference bytes); full `sync_time_to_ring` ack path now succeeds under test harness; all `python -m collector.*` entrypoints and `py_compile` clean; no more `date_utils` or HR-log references in our files.
- Operational: next sync that reaches a live ring connection (via poller or manual `--forget`) will now set `clock_drift_ms=1` on ack. Test attempts (#130/#131) cleaned as errored.

### 2026-07-18 — Dashboard rewrite plan: React + Vite + TypeScript
- **Stack decision:** replace Alpine.js + Tailwind Play CDN with React + Vite + TypeScript + Recharts + TanStack Query. Dev server on :5173 proxies /api → :8000. Legacy dashboard untouched until full feature parity. Full plan: `docs/DASHBOARD_REWRITE_PLAN.md`.

### 2026-07-16 — Temp fetch fix: broadened type range + queue drain + banner + orphan cleanup
- **Temp big-data range:** was querying 0x25–0x29 only (stale days). Ring stores ~8 days at types 0x23–0x2B (skipping 0x2A = SpO2). Widened fetch to 0x22–0x2C with response dataId check, unlocking backfill of the prior days' temp. (Note: the current day is still subject to the publish cadence above.)
- **Queue drain:** added `_bd_buf` reset + `big_data_queue` drain before each `_big_data_request`. Eliminated 15/0/15/0 flakiness from shared-queue race with sleep type 0x27 collision.
- **Dashboard banner:** dropped `|| yesterday` union — HRV/SpO2 falsly accused when yesterday had gaps.
- **Ghost sync cleanup:** marked orphaned `sync_log` #89; added `reap_stuck_rows()` sweep to poller (auto-marks stuck `running` rows >10 min).
- **Live temp:** cmd 115 device-notify routing fixed — `_handle_tx` now unmasks bit-7 for queue dispatch; dedicated `queues[115]` added.

### 2026-07-14 — Docs cleanup
- Split bloated RESEARCH.md into focused files: pure research in RESEARCH.md, CFW/readiness backlog in TASKS.md, hardware specs in AGENTS.md. Net: -522 lines.

### 2026-07-13 — Dashboard Overhaul: Readiness Score + Activity Ring + Source Dedup + Timezone Fix

Unified hero panel: 24h activity ring (radial step bars + sleep overlay) alongside Readiness Score 0-100 (4 sub-scores + contributors). `daily_activity` table (server-computed, Pacific tz, hourly JSONB). Source dedup (ring canonical, phone fills gaps). Postgres + container timezone fix. Sleep card empty state. Phone sync PWA.

**Earlier work (see `git log --oneline` for details):** Ring time sync fix (BCD local), phone sync multi-packet, temperature 5-day history, analytics rewrite (Ohayon 2004/Altini 2021/Firstbeat), big-data V2 protocol, poller architecture, initial collector + dashboard.

---

## Agent Notes

- **When editing:** Update the work log above. Keep it lean — details in `docs/` or commit messages.
- **Secrets:** Never commit. Update `.env.example` for new env vars.
- **BLE protocol:** Cross-reference `colmi.puxtril.com` and Gadgetbridge source (`yawell/ring` namespace).
- **Runtime:** Collector = bare metal venv (`venv/bin/python3`). API + DB = Podman containers (restart with `sudo systemctl`).
- **Services are SYSTEM-LEVEL, not user-level. User systemd on this distro (systemd 255.4 + podman 4.9.3, Linux Mint) does NOT scan `~/.config/systemd/user/` at boot. Services live in `/etc/systemd/system/` with `User=sz`. Deploy with `sudo cp` + `sudo systemctl daemon-reload`. Source files in `~/.config/systemd/user/` for editing only.
- **DO NOT use `systemctl --user` for autostart.** It fails silently at boot. Use `sudo systemctl` for status, restart, enable, everything.
- **DO NOT use podman quadlet for user containers.** User quadlet generates transient units in `/run/` that silently conflict with persistent units of the same name. Write plain `.service` files with `ExecStart=/usr/bin/podman run`.
- **DO NOT write wrapper services or startup shims.** If something doesn't autostart, find the missing dependency — don't write a `.service` that `daemon-reload && systemctl start`s things. No `smart-ring-startup.service`, no `WantedBy=graphical-session.target`.
- **NEVER run raw ad-hoc Python one-liners to talk to the ring.** The R09 is BLE-flaky and needs the proper forget+repair+wake-ping flow that only `sync_ring.py --forget` handles. Raw `bluetoothctl` or ad-hoc `Client()` attempts will fail with EOFError/connect errors and waste time. For diagnostics use `first_contact.py`. For sync use `sync_ring.py --forget`. For any settings reads/writes, either extend those scripts or run them inside an active sync_ring.py connection.**
