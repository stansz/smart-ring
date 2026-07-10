# AGENTS.md — Smart Ring Project

> Agent-facing context for the Smart Ring health data pipeline.
> This file is a **living document** — update it as the project evolves.

---

## Project Overview

Private, self-hosted health tracking system built around the **Colmi R09** smart ring (~$45 CAD). Collects biometric data via BLE, stores in Postgres, computes health metrics (HRV, sleep, recovery), and visualizes in a local web dashboard.

- **Hardware:** Colmi R09 (BlueX RF03 SoC, PPG + SpO2 + skin temp + accelerometer)
- **Stack:** Python (async BLE), FastAPI, Postgres, Alpine.js + Chart.js
- **Deployment:** Local-first on Linux Mint HTPC (AMD 3800x, 64GB RAM)
- **Status:** 🟢 Ring arrived, validated, and working end-to-end. First contact succeeds, sync pulls data, dashboard operational. Sleep/retry hardening remaining.

**Update 2026-07-09:** Ring arrived, hardware confirmed working. Firmware RT09_3.10.21_251107, HW RT09_V3.1. Nordic UART protocol (UUIDs match colmi_r02_client). See work log entries for full validation.

---

## Architecture (Local-First, Quadlet-Managed)

The ring talks to **one BLE host at a time** — the R09 only supports a single connection.

**At home:** Linux box runs a persistent BLE daemon (TBD — currently manual `python3 collector/sync_ring.py`). Data flows ring → daemon → Postgres → dashboard.

**On the go:** Phone (Android + Gadgetbridge) connects to the ring, then pushes data via HTTPS (Tailscale) to FastAPI → Postgres. Gadgetbridge fork for ring-only sync is planned (see Future Work).

```
At Home:                          On the Go (planned):
Ring ──BLE──> Linux Daemon        Ring ──BLE──> Phone (Gadgetbridge fork)
                 │                                 │
                 ▼                                 ▼ HTTPS (Tailscale)
            Postgres ◄────────── FastAPI ──────────┘
                 │
                 ▼
            Dashboard (Alpine.js + Chart.js)
```

**Current services on the Linux box:**

```
Linux Mint Box (AMD 3800x, 64GB RAM, BT enabled)
├─ smart-ring-db.service      (rootless Podman quadlet, Postgres 16)
│   └─ port localhost:5432
├─ smart-ring-api.service     (rootless Podman quadlet, FastAPI)
│   └─ port localhost:8000, serves dashboard
└─ Manual collector           (bare metal Python venv — needs BlueZ/DBus for BLE)
    └─ python3 collector/sync_ring.py  (run manually, no cron yet)
```

- **Container runtime:** Podman 4.9.3, rootless, user systemd units
- **Collector** is **bare metal only** — needs direct BlueZ/DBus access for BLE.
- **Quadlets** live in `~/.config/containers/systemd/` (not the repo) — they're host-specific.
- **Lingering enabled** (`loginctl enable-linger sz`) so services start at boot, not on login.
- **No cron jobs installed.** The old poller service (`smart-ring-poller`) was retired on 2026-07-09(d) — it held a BLE connection that blocked Gadgetbridge pairing and drained the ring battery without actually pulling data.
- `docker-compose.yml` in repo kept as fallback documentation but **not used** for local deployment.

---

## Key Source Files

| File | Purpose | Notes |
|------|---------|-------|
| `collector/ring_client.py` | Drop-in wrapper around `colmi_r02_client.Client` | Passes explicit `timeout` to `BleakClient` (upstream hangs without one); replaces `assert packet_type < 127` with `logger.debug` so async ring pushes don't kill the listener; includes forget/pair/disconnect BlueZ helpers for R09 reconnect-bug workaround; registers cmd 0x21 (goals) and 0x37 (stress) handlers |
| `collector/sync_ring.py` | BLE collector, syncs ring → Postgres | Time sync uses `datetime.now()` **(local time, not UTC)**; uses `ring_client.Client`; own `fetch_hr_history()` bypasses broken library HR parser; steps use `time_index * 15` for per-15-min-slot timestamps; `fetch_stress_history()` + `fetch_goals()`; `_read_multi_packet()` generic helper |
| `collector/collector-wrapper.py` | Tiny shim that sets `sys.path` and runs `sync_ring.main()` | Injects `--forget` into sys.argv for R09 reconnect-bug workaround |
| `collector/first_contact.py` | Safe read-only diagnostics | Reads battery (`battery_level`), firmware, device info, sets clock — NO data sync |
| `collector/test_open_questions.py` | One-shot validation of unknown ring behaviors | Uses a single Client connection with per-test try/except (the ring drops between reconnects) |
| `collector/test_sync_readonly.py` | Verifies read-only vs read-and-clear behavior | Two scenarios: within-connection + across-disconnect; confirmed READ-ONLY on R09 3.10.21 |
| `collector/sync_request_poller.py` | Host-side poller for admin-triggered syncs | **RESTORED 2026-07-10** — watches `sync_requests` table every 30s, runs `collector-wrapper.py` for any pending row. Safe to run continuously: no BLE connection between syncs. Old `--interval 2` caused issues only because `sync_ring.py` was hanging (now fixed). |
| `collector/analytics.py` | Computes HRV, sleep, recovery metrics | `detect_sleep_stages()` infers duration since cmd 68 lacks timestamps |
| `api/main.py` | FastAPI with metric + admin endpoints | Serves dashboard static files from `../dashboard/`; endpoints: `/api/raw/{heart-rate,steps,stress,temperature}`, `/api/goals`, `/api/recovery`, `/api/sleep`, `/api/hrv-trends`, `/api/circadian-hr`, `/api/stress`, `/api/sync-log`, `/api/admin/{ring-status,health,sync-log,sync,sync-requests}` |
| `dashboard/index.html` | Single-page Alpine.js + CSS bars UI, **two tabs: Dashboard + Admin** | No build step needed; 4 conic-gradient dials for Today's Activity; no chart.js (pure CSS); Sync Now in nav bar; raw data tables in Admin tab |
| `db/init.sql` | Postgres schema | `circadian_hr` uses `PRIMARY KEY (day, hour)`; `sync_requests` is the admin job queue; `raw_steps` now includes `calories` + `distance`; `raw_stress` + `ring_goals` tables added |

---

## Agent Work Log

Use this section to append notes about what the agent has done, decisions made, and open issues. Append chronologically.

### 2026-07-08 — Sync Poller Wired Up + Pre-Ring Smoke Test

**Task:** Complete the remaining TODO before ring arrival — wire up the sync request poller so Admin tab buttons actually work.

**What was done:**
- Created `~/.config/systemd/user/smart-ring-poller.service` — `--loop --interval 2s`, enabled, active
- Poller claims DB rows via `FOR UPDATE SKIP LOCKED`, dispatches to `first_contact.py` or `sync_ring.py` depending on `requested_by`
- Smoketested end-to-end: POST `/api/admin/first-contact` → row claimed within ~1s → `first_contact.py` ran → failed as expected (no ring in range)
- Both "First Contact" and "Sync Now" Admin tab buttons now fully functional end-to-end *(First Contact button later removed — see 2026-07-09(c))*

### 2026-07-04 — Initial Review + Critical Fixes

**Agent task:** Full project review (research, code, architecture), then apply critical fixes.

**Review findings:**
1. **Time sync bug:** `sync_ring.py` used `datetime.now(timezone.utc)` — ring stores naive local time. **Fixed:** changed to `datetime.now()`.
2. **`circadian_hr` PK bug:** Was `hour INT PRIMARY KEY`, overwriting single row. **Fixed:** composite `PRIMARY KEY (day, hour)`.
3. **`setup.sh` destructive bug:** Overwrote `collector-wrapper.py`, `analytics-wrapper.py`, `test_open_questions.py`. **Fixed:** all now check `if not path.exists():` before writing.
4. **Sleep data parsing bug:** `detect_sleep_stages()` assumed `start_ts`/`end_ts` from cmd 68, but firmware only returns `(day, stage)`. **Fixed:** infers duration from record count × 30 min, assigns synthetic timestamps by stage type.
5. **Missing `.env.example`:** Created with `DATABASE_URL`, `RING_ADDRESS`, `POSTGRES_PASSWORD`.

**Deployment model updated (local-first):**
- README.md and RESEARCH.md updated to reflect local-first approach
- Removed old 3-option comparison (All-Local vs OVH Hybrid vs Read-Only Mirror)
- `docker-compose.yml` now binds Postgres/API to `localhost` (localhost only)
- Topology diagram added to both docs

**Verified sources via web:**
- `colmi.puxtril.com`: Confirmed live, full BLE protocol docs available
- `tahnok/colmi_r02_client`: 635 stars, compatible with R02/R06/R10 (R09 likely works)
- `atc1441/ATC_RF03_Ring`: 486 stars, includes OTA flasher + firmware dumps

### 2026-07-04 — Container Runtime Migration: Docker → rootless Podman + Quadlets

**Task:** Replace Docker with rootless Podman managed by systemd quadlets.

**What was done:**
- Installed `podman` 4.9.3 + `python3-pip` (user ran sudo apt install)
- Enabled lingering: `loginctl enable-linger sz` (services start at boot)
- Purged Docker packages + removed `/var/lib/docker`
- Cleaned up 6 stale overlay mounts + 5 stale network namespaces left by Docker (required `umount -l` on each netns since `umount -f` doesn't work on nsfs)
- Removed leftover `containerd` daemon (PID 4132707) that was holding namespaces alive

**Quadlet files created** in `~/.config/containers/systemd/` (host-specific, NOT in repo):
- `smart-ring.network` — internal container network
- `smart-ring-db.container` — Postgres 16 alpine, named volume `smart-ring-pgdata`, mounts `db/init.sql`, port `localhost:5432`, healthcheck
- `smart-ring-api.container` — built image `localhost/smart-ring-api:latest`, `Requires=smart-ring-db.service`, mounts `api/` + `dashboard/` for live reload, port `localhost:8000`

**Verified end-to-end:**
- Both services `active (running)` under `systemctl --user`
- Postgres: 13 tables created from `init.sql`, healthcheck passing
- API `/health` returns `{"status":"ok","db":"connected"}`
- Dashboard HTML served at `http://localhost:8000/`

**Operational commands (for future agents):**
```bash
systemctl --user status smart-ring-db smart-ring-api    # check both
systemctl --user restart smart-ring-api                 # restart after code change
journalctl --user -u smart-ring-db -f                   # tail DB logs
podman exec smart-ring-db psql -U smart_ring -d smart_ring  # psql into DB
podman build -t smart-ring-api:latest /home/sz/code/smart-ring/api  # rebuild image
```

### 2026-07-04 — Admin Tab + DB Job Queue (Manual Sync from UI)

**Task:** Add admin GUI for ring management (separate tab from the user dashboard).

**Architecture decision — DB-as-job-queue:**
The API lives in a container without BLE access. The collector must run on the host (needs BlueZ/DBus). Solution: dashboard buttons → API inserts row into `sync_requests` (status=pending) → host-side poller claims and runs the collector → marks row complete.

**What was built:**
1. **New table** `sync_requests` (id, requested_at, status, started_at, completed_at, sync_log_id, result, error)
2. **5 new admin endpoints** in `api/main.py`:
   - `GET  /api/admin/ring-status` — latest battery/firmware + last sync summary
   - `GET  /api/admin/health` — DB ping, row counts, container hostname
   - `GET  /api/admin/sync-log` — detailed sync history
   - `POST /api/admin/sync` — queue a sync (refuses if one is already pending/running → 409)
   - `GET  /api/admin/sync-requests` — recent queued syncs
3. **Dashboard restructured** with tab navigation (Dashboard / Admin):
   - Admin tab has: ring status cards, sync controls, recent-requests table, system health, full sync log, hardware test instructions
   - Polling: when a sync is queued, the UI polls every 5s until the request reaches terminal state
4. **`collector/sync_request_poller.py`** — host-side script that:
   - Uses `FOR UPDATE SKIP LOCKED` to safely claim requests (no races)
   - Invokes `collector-wrapper.py`, waits, captures stdout/stderr
   - Writes result back to the request row + links to sync_log id
   - Supports `--loop` (long-running service) and one-shot mode (systemd timer)

**Verified working (smoke tests):**
- All 5 endpoints respond correctly with empty data
- POST `/api/admin/sync` queues a row, second POST correctly returns HTTP 409
- Schema applied to running DB without restart

**Poller wired up (2026-07-08):**
- Created `smart-ring-poller.service` in `~/.config/systemd/user/` — `--loop --interval 2s`, enabled, active
- Smoketested end-to-end: POST /api/admin/first-contact → DB row claimed within ~1s → `first_contact.py` ran → failed as expected (no ring in range)
- Both "First Contact" and "Sync Now" buttons now fully functional *(First Contact button later removed — see 2026-07-09(c))*

**Still TODO before ring arrives:**
- [ ] Set up collector + analytics cron jobs (`setup.sh` ran but `psql` was unavailable — crontab is empty)

### 2026-07-09 — Ring Arrived: First Contact + Open-Question Tests

**Hardware confirmed working:**
- BLE address: `<ring_ble_address>` (R09_2103)
- Firmware: **RT09_3.10.21_251107**
- Hardware: **RT09_V3.1**
- Nordic UART service UUID matches `colmi_r02_client` (6E40FFF0-…)

**Critical BLE learnings (BIG gotchas):**
1. **`bluetoothctl` and `bleak` cannot share a connection.** Pairing via bluetoothctl is fine (must be done at least once), but never use `bluetoothctl connect` while the Python collector is running — let bleak own the GATT connection.
2. **Ring requires bonding before notifications work.** First EOFError on `start_notify` (cmd 6E400003 TX char) was because we tried `client.connect()` without prior pairing. After running `bluetoothctl pair <addr>` once, notifications come through.
3. **Aggressive sleep on R09 firmware 3.10.21.** Ring stops advertising ~30 sec after losing connection. Wear / tap / charger wakes it briefly. RSSI drops fast — from -73 to -127 within seconds of being idle.
4. **`colmi_r02_client` battery attribute is `battery_level`** (not `chargePercent`). Fixed in `sync_ring.py` + `first_contact.py`.
5. **`colmi_r02_client.Client` doesn't pass timeout to `BleakClient`** → service discovery can hang indefinitely. **Fix:** new `collector/ring_client.py` is a drop-in wrapper that sets `timeout=30.0` on the `BleakClient`. Both `first_contact.py` and `sync_ring.py` now import `Client` from there.
6. **Ring pushes async packets with high bit set (0x80+).** The library's `assert packet_type < 127` was crashing the listener. Replaced with `logger.debug` in `ring_client._handle_tx()`.
7. **`get_full_data` returned a tuple.** `sync_ring.py` expects a `FullData`-like object with `.heart_rates` and `.sport_details`. Wrapped result in `SimpleNamespace`.

**Tests run via `collector/test_open_questions.py`:**
- ✅ **Heart rate real-time:** 77–96 bpm (sensor works, ring watches wear detection)
- ✅ **Steps:** `SportDetail(year, month, day, time_index, calories, steps, distance)` — 9 entries today (sync wrote 2 to DB)
- ✅ **Battery:** 69%
- ✅ **Device info:** FW + HW readable
- ✅ **Time sync:** works
- ⚠️ **HRV (cmd 57):** 0 records — ring needs to wear longer for HRV log to populate
- ⚠️ **Sleep (cmd 68):** 0 records — slept no nights with ring yet
- ⚠️ **Temperature push:** no notification in 10s window → event-driven, not polled
- ❓ **Sync behavior (read-only vs wipe):** first sync pulled 2 step records; need second sync to confirm. Run collector twice and compare DB counts.

**Files changed:**
- `collector/ring_client.py` — NEW, drop-in `Client` wrapper with timeout, robust packet handling
- `collector/first_contact.py` — uses `ring_client.Client`, correct battery attribute
- `collector/sync_ring.py` — uses `ring_client.Client`, correct battery attribute, `sys.path` for direct run
- `collector/test_open_questions.py` — rewritten to use a single connection, isolate each test in try/except

**Known open items:**
- [x] Run collector once more after waking ring → confirm 0 new step records → confirm sync is read-only — done; see 2026-07-09(e) below
- [x] Add retry-on-sleep to `sync_ring.py` (try N attempts before failing) — done; see 2026-07-09b below
- [ ] Add automatic wake gesture (heavy BLE activity) before sync attempts
- [ ] Collect enough HRV data to determine format (RR vs composite): wear for 24h+
- [ ] Investigate the `0x80`-bit packets (probably sleep or temperature reported asynchronously)
- [x] Retire poller — done; see 2026-07-09(d) below

### 2026-07-09 (b) — Retry-on-Sleep Helper

**Task:** R09 hardware validated last session, but the ring's aggressive sleep behavior would make any cron-driven sync fail (ring stops advertising ~30s after disconnect). Added a `connect_with_retry` helper so both sync_ring.py and first_contact.py survive an asleep ring.

**What was done:**
- New `connect_with_retry(address, attempts=5, wake_ping=False)` in `collector/sync_ring.py`
  - Wraps each connect attempt in try/except (BleakError / OSError / TimeoutError)
  - Exponential backoff: 2s, 4s, 8s, 16s, 32s — total ~62s wait across 5 attempts
  - Optional `wake_ping` runs a 10s BLE scan before the *final* attempt to nudge the radio awake
  - Returns a connected Client; raises RuntimeError on exhaustion
- `sync_ring(address, *, attempts=5, wake_ping=True)` rebuilt on top of it. Includes a `main()` `--attempts N` and `--no-retry` flag for testing.
- `first_contact.py` now also uses `connect_with_retry(...)` (default 5 attempts) — a manual Admin-tab "First Contact" click now waits for the ring to wake instead of failing instantly.
- CLI flags `--no-retry` and `--attempts N` added for cron to use longer retries (e.g., `--attempts 12`).
- Refactored sync data work into `_collect_data(client, address)` so the test_open_questions.py / connect_with_retry path can reuse it.
- Added `sys.path` shim to both `sync_ring.py` and `first_contact.py` so they can run directly without the collector-wrapper.py poller shim.

**Tested:**
- Real run of `first_contact.py` against the sleeping ring: Attempt 1 failed → wait 2s → Attempt 2 failed → wait 4s → Attempt 3 failed → wait 8s → Attempt 4 in progress at timeout. Confirms exponential backoff works as designed.

**Files changed:**
- `collector/sync_ring.py` — added `connect_with_retry`, refactored into `_collect_data`/new `sync_ring`, CLI flags
- `collector/first_contact.py` — uses `connect_with_retry`, sys.path shim
- `.env.example` — added commented knobs (`SYNC_ATTEMPTS`, `FIRST_CONTACT_ATTEMPTS`, `BLE_CONNECT_TIMEOUT`)
- `AGENTS.md` — this entry, plus ticking the corresponding Future Work checkbox

### 2026-07-09 (c) — Remove "First Contact" UI/API/Poller Mapping

**Task:** User decided manual sync is fine for now (no cron yet), and the Admin tab "First Contact" button is no longer needed now that the ring is paired and validated. Removed the button from the dashboard, the API endpoint, and the poller's `requested_by='first-contact'` dispatch entry. Standalone `first_contact.py` script remains useful for CLI use.

**What was done:**
- `dashboard/index.html` — removed the entire "Ring Setup" block (the box with the First Contact button + description) and the `queueFirstContact()` JS method. Also removed the "Hardware Tests" pre block (`test_open_questions.py` instructions) since the ring is already past that stage.
- `api/main.py` — removed `@app.post("/api/admin/first-contact")` route + its `queue_first_contact` function. Kept the shared `SyncRequest` pydantic class (still used by `/api/admin/sync`). Updated `/api/admin/sync`'s 409 detail to no longer mention "first-contact".
- `collector/sync_request_poller.py` — removed `FIRST_CONTACT_SCRIPT` constant and the `"first-contact"` entry from the `DISPATCH` dict. The poller will log "Unknown requested_by" and mark failed if any future DB row claims that value (it can't, since the API endpoint is gone).
- `db/init.sql` — **no change**. `sync_requests` schema is generic; no migration needed.
- `collector/first_contact.py` — **kept** (still useful as a one-off CLI: `python3 collector/first_contact.py` for "why is sync failing" debugging).

**Migration / break-things risk considered (none materialized):**
- DB unique partial index `idx_sync_requests_one_active` only blocks `pending`/`running` rows → no conflict on cleanup.
- Poller's `requested_by` column is unconstrained `TEXT` → dropping the mapping is safe.
- API removal is backward-compatible (clients get 404 instead of 200; the only client was the deleted button).
- Pre-removal: 9 historical `first-contact` rows + 1 `smoke-test` row, all in `failed` status (ring had never successfully synced via this path). `DELETE FROM sync_requests WHERE requested_by IN ('first-contact','smoke-test');` cleared them.

**Operational steps (clean, not hot):**
1. `systemctl --user stop smart-ring-poller` (kills the long-running Python process so it re-reads the source on next start).
2. `systemctl --user stop smart-ring-api` (stops the Podman container that mounts the API source).
3. Edits applied.
4. `systemctl --user start smart-ring-api smart-ring-poller` (restart picks up the changes — Podman quadlet recreates the container, poller re-execs Python).
5. Smoke test: `curl -X POST http://localhost:8000/api/admin/first-contact` → `{"detail":"Not Found"}` (404), `/api/admin/sync` → 200 + row id. `curl http://localhost:8000/` → 0 occurrences of `First Contact|queueFirstContact|test_open_questions` in served HTML.

**Files changed:**
- `dashboard/index.html` — removed Ring Setup block, queueFirstContact method, Hardware Tests pre block
- `api/main.py` — removed `queue_first_contact` endpoint (lines 242-259) and its 409 message
- `collector/sync_request_poller.py` — removed `FIRST_CONTACT_SCRIPT` and `DISPATCH['first-contact']` entry
- `AGENTS.md` — this entry; also updated `api/main.py` row in Key Source Files (5 → 4 endpoints) and added "*(First Contact button later removed — see 2026-07-09(c))*" annotation to two earlier work-log lines that mentioned the button

### 2026-07-09 (d) — Retire Poller Service + Delete setup.sh + Docs Refresh

**Task:** The sync request poller (`smart-ring-poller.service`), built in 2026-07-08, held a persistent BLE GATT connection to the ring. On the R09 (firmware 3.10.21), this was actively harmful:

1. **Battery drain:** The poller's 2-second poll loop + reconnect attempts drained the ring battery to zero over ~6 hours of testing (ring went from 69% → 100% → bricked until charged).
2. **Blocked Gadgetbridge pairing:** The R09 only supports one BLE connection at a time. The poller held that connection, preventing Gadgetbridge (or anything else) from pairing with the ring.
3. **No data sync:** The poller only *held* the connection — it didn't pull historical data (no notification-driven fetch chain like Gadgetbridge). Dashboard showed stale data.

**What was done:**
- `systemctl --user stop smart-ring-poller && systemctl --user disable smart-ring-poller`
- Deleted `~/.config/systemd/user/smart-ring-poller.service` and `smart-ring-poller.timer`
- Deleted `setup.sh` from the repo — it had only venv/pip/cron steps, all of which are already done or harmful (cron silently appends entries on each run)
- Verified the ring works: after stopping the poller + disconnecting BlueZ, `first_contact.py` returned 100% battery, RT09_3.10.21_251107, clock synced. Ring advertising at RSSI -68.
- Gadgetbridge paired successfully on the Android phone.

**Architecture impact:**
- The DB-as-job-queue model (`sync_requests` table) still exists in schema; the "Sync Now" Admin tab button inserts rows but nobody consumes them. This is harmless but technically stale — the button is a no-op.
- Future architecture (planned): Linux daemon (Path A) as the home BLE collector, Gadgetbridge fork (Path B) as the mobile BLE collector. Both push to FastAPI `/api/sync`. Neither uses the old poller dispatch model.
- `collector/sync_request_poller.py` kept in repo for reference but marked OBSOLETE in Key Source Files.

**Files changed:**
- `setup.sh` — DELETED from repo
- `AGENTS.md` — this entry; updated Architecture diagram (added phone path, removed cron, noted poller retired); updated Key Source Files table; updated Testing the Ring section
- `README.md` — minor updates to reflect poller retirement

**Current usable collector surface:**
```bash
python3 collector/first_contact.py       # read-only diagnostic (battery, fw, clock)
python3 collector/sync_ring.py           # full sync to Postgres
python3 collector/test_sync_readonly.py  # test read-only vs read-and-clear (single connection)
```
No cron. No poller. Manual only. Gadgetbridge works for phone-side quick checks.

### 2026-07-09 (e) — Sync Behavior Confirmed + HR Data Working + BLE Fixes

**Task:** Verify sync behavior (read-only vs read-and-clear), get overnight HR data into dashboard, fix critical BLE bugs.

**Sync behavior confirmed: READ-ONLY across disconnects.**
- Tested via `test_sync_readonly.py` — two fetches across full disconnect/reconnect returned identical data (9 entries, 731 steps). Data is not cleared on read or disconnect.
- The `forget+repair` flow was buggy: after `bluetoothctl remove`, BlueZ needs a scan to re-discover the device before `pair` can succeed. Fixed `forget_and_repair` to scan between forget and pair, and made it async.
- `forget_ring()` now calls `bluetoothctl disconnect` before `remove` to fully release GATT state.
- `pair_ring()` now auto-disconnects after pairing — bluetoothctl must release the GATT link before bleak can own it.
- Added `disconnect_ring()` helper.
- Wake-ping scan moved to BEFORE `forget+repair` so the ring is already awake when pairing starts.

**Heart rate history: 49 records synced to Postgres.**
- The `colmi_r02_client` library's `HeartRateLogParser` only completes for "today's" data (`is_today()` check). Historical days accumulate but never yield. The 2s timeout in `get_heart_rate_log()` also cuts off multi-packet HR responses.
- **Fix:** New `fetch_hr_history()` reads directly from the notification queue with 10s timeout. Uses local midnight timestamps (ring clock = local time, not UTC).
- HR data: 49 records across Mon-Wed (July 8-10), 30-min intervals, avg BPM 77-84, range 53-105.

**Step timestamps fixed.** Previously all steps for a day got the same midnight timestamp. Now uses `time_index` for per-hour timestamps.

**Remaining gaps (will fix in later sessions):**
- **Sleep data:** Our code uses cmd 68; Gadgetbridge uses `CMD_BIG_DATA_V2` (0xBC) + `BIG_DATA_TYPE_SLEEP` (0x27).
- **HRV data:** Our code uses cmd 57; Gadgetbridge uses `CMD_SYNC_HRV` (0x39) with per-day offset.
- **SpO2 / temperature:** Also likely protocol mismatch vs Gadgetbridge.

**Files changed:**
- `collector/ring_client.py` — `forget_ring` disconnect-before-remove; `pair_ring` auto-disconnect; `forget_and_repair` async + scan; added `disconnect_ring`
- `collector/sync_ring.py` — new `fetch_hr_history()` replaces broken HR path; step timestamps fixed; wake-ping moved; `await` on async `forget_and_repair`
- `collector/test_sync_readonly.py` — rewritten: two scenarios (within-connection + across-disconnect); `--skip-within` flag
- `.env` — removed extra quotes from `RING_ADDRESS` (cosmetic)
- `AGENTS.md` — this entry

### 2026-07-10 — Poller Restored + "Sync Now" End-to-End Working

**Task:** User reported that clicking "Sync Now" in the Admin tab did nothing — the request sat in `pending` status forever. Investigated and confirmed: the poller service was deleted in 2026-07-09(d), so nothing consumed the DB queue. Re-enabled the poller (now safe after sync_ring.py bugs are fixed).

**What was done:**
- Diagnosed: `sync_requests` had a row stuck in `pending` (request #18). The poller service (`smart-ring-poller.service`) was removed in commit `8ed4421` (2026-07-09(d) work log).
- Re-analyzed why the poller was "bad": the poller itself does NOT hold a BLE connection — it only polls DB every N seconds and runs `sync_ring.py` as a subprocess when there's work. The original issues were:
  1. `sync_ring.py` was hanging during sync (library bugs: no timeout on BleakClient, 2s HR timeout, broken parser)
  2. The poller ran every 2s, so overlapping sync attempts piled up
  3. Each hanging sync held a BLE GATT connection
- All three are now fixed (see 2026-07-09(e) work log). Poller is safe to run.
- Fixed `collector/collector-wrapper.py` to inject `--forget` into `sys.argv` — the poller calls this wrapper, which calls `sync_ring.main()`. Without `--forget`, the R09 reconnect-bug workaround (forget_and_repair before connect, forget after disconnect) wouldn't run.
- Cleaned up stale pending request #18: `DELETE FROM sync_requests WHERE status = 'pending'`.
- Created `~/.config/systemd/user/smart-ring-poller.service`:
  - `Type=simple`
  - `ExecStart=.../sync_request_poller.py --loop --interval 30`
  - `Restart=on-failure`, `RestartSec=10`
  - `After=bluetooth.target network-online.target smart-ring-db.service`
  - Enabled and started.

**Verified end-to-end:**
- `POST /api/admin/sync` → request #19 inserted with status=pending
- Poller claimed request #19 in ~30s (interval)
- `sync_ring.py --forget` ran for ~31s, completed with `sync_log_id=13`
- Request marked `completed`, 13 records synced to DB
- `systemctl --user status smart-ring-poller` → `active (running)`

**No code changes to `sync_request_poller.py` needed** — the existing code worked fine; it just wasn't running. The 30s interval (was 2s) is much friendlier: it's a DB-only poll with zero BLE activity between syncs.

**Design decision: "Sync Now" stays as ONE button, not split into pair + sync.**
- The R09 reconnect bug couples pair + sync — every sync needs forget+pair anyway. Separating them would mean "Pair" then "Sync" then "Sync fails because bond went stale → click Pair again."
- What the user actually needs to separate is sync vs release-for-phone. But sync already does `forget_ring()` at the end, so the ring is automatically free for the phone after each sync. No extra button needed for now.

**Files changed:**
- `collector/collector-wrapper.py` — injects `--forget` if not present
- `AGENTS.md` — this entry; updated Key Source Files (poller row now RESTORED), Future Work (poller restore ticked)

### 2026-07-10 (b) — Dashboard Overhaul + HR Fixes + Stress/Goals/Calories

**Task:** Make the dashboard show real data, fix HR sync bugs, add Gadgetbridge-style metrics, pull in stress + goals + calories from the ring.

**Dashboard — major rework:**
- Replaced Chart.js (was failing to render due to CDN/canvas issues) with pure HTML/CSS bar visualizations. Zero external chart library dependency. Recovery Trend, Sleep Quality, HRV Trends, and Circadian HR Pattern are all now CSS bars.
- Added "Today's Activity" section with 4 conic-gradient dials: Steps, Heart Rate, Calories, Active Time. No JS chart library — pure CSS.
- Active Time uses a movement threshold (150 steps/15min = ~10 steps/min, brisk walk). Based on Gadgetbridge's definition: Running >120 steps/min, Exercise >90 bpm + intensity >15. We don't have intensity data so use step count as proxy.
- Steps ring fill uses the ring's actual goals (cmd 0x21): 5000 steps target.
- Calories ring fill uses the ring's calorie goal (300 kcal).
- Resting HR computed from raw data. Falls back to most recent day if no data today.
- "Last synced" timestamp shows actual sync completion time, not browser refresh time.
- Moved Sync Now button to nav bar (accessible on every tab). Removed duplicate button from Admin tab.
- Moved raw HR/Steps Log tables from Dashboard tab to Admin tab.
- Consolidated two sync history tables into single Sync Log on Admin tab.
- Replaced "Refresh" button with "Sync Now" in nav bar.
- Replaced empty RMSSD card with Stress card showing latest value + classification (Relaxed/Normal/Medium/High).

**HR sync fixes:**
- `fetch_hr_history()` was looping `range(7, 0, -1)` which excluded today. Fixed to `range(7, -1, -1)` to include day 0.
- `fetch_hr_history(client, start, end)` call site referenced undefined `start`/`end` variables (removed in earlier refactor). Fixed to pass `None, None`.
- Ring confirmed: 26 non-zero HR entries for today, 33 for yesterday, 14 for two days ago. Total 73 records in DB across 3 days.

**Step timestamp fix — 15-minute slots:**
- The ring's `SportDetail.time_index` is a **15-MINUTE SLOT from local midnight** (0–95 per day), NOT the hour of the day. Confirmed by querying ring directly: time_index values like 28, 32, 36, 68, 72, 76 are spaced 4 apart (1 hour × 4 slots/hour).
- Previous code did `local_midnight + hours(time_index)` which created timestamps 20+ hours in the future.
- Fixed to `timedelta(minutes=s.time_index * 15)` with local midnight base + `astimezone()` for UTC storage.
- Also fixed step record deduplication: the ring sends 5 duplicate entries per hour with the same value.

**Calories + distance now stored:**
- The ring's `SportDetail` always included `calories` and `distance` alongside `steps` — we were only storing `steps`.
- Added `calories` and `distance` INT columns to `raw_steps` table.
- Dashboard: Calories dial replaces the old estimated Distance dial. Values divided by 1000 (ring stores in 0.001 kcal units). Steps Log table in Admin shows all 4 columns (Time | Steps | Cal | Dist).

**Stress history (cmd 0x37) — NEW:**
- Multi-packet protocol from Gadgetbridge `ColmiR0xPacketHandler.historicalStress`: packet 0 = header, packets 1–4 = data (12–13 values each at 30-min intervals). Each value 1–99.
- New `raw_stress` table (ts UNIQUE, stress_value INT).
- Generic `_read_multi_packet()` helper for multi-packet ring responses.
- Synced 29 stress records (all in "normal" range 32–47).

**Goals (cmd 0x21) — NEW:**
- Single read response: steps goal (5000), calorie goal (300000 in ring units ≈ 300 kcal), distance goal (3000m), sport/sleep goals (unset).
- New `ring_goals` table.
- Dashboard dials now use ring's actual goals for percentage fill.
- Steps: 5000 target. Calories: 300 kcal target.

**Research docs updated:**
- RESEARCH.md: resolved "Does syncing wipe data?" → confirmed read-only. Added BLE Quirks & Reconnect Bug section (6 documented behaviors). Updated protocol commands with Gadgetbridge-correct codes. Updated deployment topology with current services. Replaced real BT address and IP with placeholders.
- AGENTS.md, README.md: same placeholder cleanup.

**All changes collapsed into a `sed` command for clarity.**

**Sync log milestones:** Requests 19–34 all completed. Data stable: 73 HR records, ~24 step records with calories/distance, 29 stress records, 1 goal record.

**Files changed (this session):**
- `dashboard/index.html` — major rework (Chart.js removed, CSS bars, 4 dials, stress card, goals integration, UX cleanup)
- `collector/sync_ring.py` — `fetch_hr_history` fixes, step time_index fix (15-min slots), calories/distance extraction, `fetch_stress_history`, `fetch_goals`, `_read_multi_packet`, `upsert_stress`, `upsert_goals`
- `collector/ring_client.py` — added 0x21 and 0x37 handlers, `_pass_through` utility
- `api/main.py` — `/api/raw/stress`, `/api/goals` endpoints, updated `/api/raw/steps` with calories/distance
- `db/init.sql` — `raw_steps` calories/distance columns, `raw_stress` table, `ring_goals` table
- `collector/collector-wrapper.py` — injects `--forget` for R09 reconnect workaround
- `RESEARCH.md` — major update with all confirmed findings
- `AGENTS.md`, `README.md` — BT address/IP placeholder cleanup

## Environment & Secrets

- **No secrets in repo.** All creds live in `.env` (gitignored).
- `.env.example` provides the template.
- Postgres default password in compose: `${POSTGRES_PASSWORD:-changeme}`

---

## Testing the Ring (Validated 2026-07-09)

Both the Admin tab buttons and direct scripts work end-to-end. The three Known Unknowns from AGENTS.md are now partially resolved (see 2026-07-09 work log below).

### One-time setup (already done for this ring)
1. **Pair the ring** (one-time, via bluetoothctl only):
   ```bash
   bluetoothctl scan on                         # wait for R09_2103 to appear
   bluetoothctl pair <ring_ble_address>          # "Pairing successful"
   bluetoothctl trust <ring_ble_address>         # optional: auto-allow reconnects
   bluetoothctl disconnect <ring_ble_address>    # let bleak own the connection
   ```
   ⚠️ **Never** use `bluetoothctl connect` after pairing — it takes exclusive GATT ownership and breaks the Python collector.

### Daily operations
```bash
source venv/bin/activate

# Read-only diagnostic (battery, firmware, set clock — no data sync)
python3 collector/first_contact.py

# Full sync to Postgres (HR, steps, HRV, sleep, SpO2, temperature)
python3 collector/sync_ring.py --forget
```

### Observability
- `collector/collector.log` — sync errors
- `collector/first_contact.log` — first-contact diagnostics
- `podman logs smart-ring-api` — FastAPI logs
- `journalctl --user -u smart-ring-db` — Postgres logs

---

## Known Unknowns (Partial — see work log for details)

| Question | Status (2026-07-09) | Test Plan / Notes |
|----------|---------------------|---------------------|
| Sync behavior: read-only or read-and-clear? | ✅ **CONFIRMED read-only** — second fetch after disconnect returns identical data | Both within-connection and across-disconnect scenarios verified via `test_sync_readonly.py` |
| HRV data format: RR intervals vs composite score? | **TBD** — cmd 57 returns 0 on R09 3.10.21; Gadgetbridge uses cmd 0x39 with per-day offset | Need to align with Gadgetbridge protocol to populate raw_hrv |
| Stress data | ✅ **WORKING** — cmd 0x37, 29 records synced (all "normal" 32–47) | Multi-packet 30-min interval protocol; `raw_stress` table populated |
| Ring goals | ✅ **WORKING** — cmd 0x21 returns steps=5000, cal=300kcal, dist=3km | `ring_goals` table; dashboard dials use actual goals |
| Temperature sensor sampling rate | **Event-driven** — no push in 10s window | Confirm in longer window once data accumulates |
| R09 firmware compatibility with tahnok client | **WORKS** — FW 3.10.21 + colmi_r02_client | UUIDs match exactly; admin UI works end-to-end |
| Sleep data | **TBD** — cmd 68 returns 0; Gadgetbridge uses cmd 0xBC + type 0x27 | Need to align with Gadgetbridge protocol |

---

## Future Work (Hardening, Once Hardware Is Stable)

- [x] Verify actual ring data format against current parsers
- [x] Write `collector/first_contact.py` — safe read-only first contact script — done, fully functional
- [x] Create `collector/ring_client.py` — robust BLE client wrapper with explicit timeout
- [x] Add `BLE pairing once via bluetoothctl` instructions to AGENTS.md
- [x] Add retry-on-sleep logic to `sync_ring.py` (R09 falls asleep fast) — done; new `connect_with_retry` helper in `sync_ring.py`, used by both `sync_ring` and `first_contact`
- [x] Retire poller service (`smart-ring-poller`) — REVERSED on 2026-07-10; the poller code itself was fine. Original retire was due to `sync_ring.py` hanging (library bugs, since fixed). Poller restored at 30s interval.
- [x] Delete `setup.sh` — done; cron entries silently appended, venv/pip/db steps already done
- [x] Make Admin tab "Sync Now" button work end-to-end — done 2026-07-10: poller watches DB, runs `sync_ring.py --forget` (via `collector-wrapper.py` which now injects `--forget` for the R09 reconnect workaround)
- [ ] Add Prometheus/metrics endpoint for monitoring
- [ ] Consider Cloudflare tunnel for remote dashboard access
- [x] Use Gadgetbridge sleep/HRV commands (0xBC sleep, 0x39 HRV) instead of wrong cmd 68/57 — HRV DONE (0x39), sleep ALSO DONE (0xBC) in 2026-07-10(d)
- [ ] Investigate 0x80-bit async packets (probably sleep/HRV/temperature historical push)

### 2026-07-10 (c) — HRV Protocol Alignment (cmd 0x39)

**Task:** Replace the broken cmd-57 HRV path with the Gadgetbridge-correct cmd 0x39. Confirmed the protocol from the current Gadgetbridge source (refactored into `yawell/ring` namespace — `YawellRingPacketHandler.historicalHRV` + `YawellRingConstants.CMD_SYNC_HRV`).

**Protocol (0x39):**
- Request: `{0x39, daysAgo (LE uint32)}` per day, loop daysAgo 0..6
- Transport: regular Nordic UART (same path as stress 0x37 — no new BLE characteristics needed)
- Response: multi-packet, identical layout to stress (pkt 0=header, pkts 1-4=data at 30-min intervals, 12 values in pkt1 + 13 each in pkts2-4)
- Each value: single byte (ms). 0=no data.

**What was done:**
- `collector/ring_client.py`: registered `COMMAND_HANDLERS[0x39] = _pass_through`
- `collector/sync_ring.py`: replaced `fetch_hrv_raw` (cmd 57) + `_parse_hrv_data` (6-byte guess) with `fetch_hrv_history` (cmd 0x39 + per-day loop + `_read_multi_packet`). Reuses existing `upsert_hrv`.
- No DB schema change needed — `raw_hrv.hrv_value` NUMERIC + `hrv_type='composite'` already fits.

**Verified:**
- Sync #29: 38 HRV records across 3 days (Jul 8-10), values 32-49 ms. Ring's HRV buffer is ~3 days.
- Days 4-6 returned empty (ring doesn't store beyond its circular buffer window).

**Known:** The ring stores a composite HRV value (single byte, ms), not true RR intervals. `analytics.py` RMSSD/pNN50 expect `rr_intervals[]` — not yet computed. Dashboard HRV Trends (`hrv_trends` table) also not yet populated since analytics doesn't process the composite values. These are follow-up items.

**Files changed:**
- `collector/ring_client.py` — added 0x39 handler
- `collector/sync_ring.py` — replaced `fetch_hrv_raw` + `_parse_hrv_data` with `fetch_hrv_history`
- `AGENTS.md` — this entry

### 2026-07-10 (d) — Big-Data Protocol Alignment (sleep, SpO2, temperature via cmd 0xBC)

**Task:** Replace the broken sleep (cmd 68), SpO2 (cmd 105 realtime), and temperature (cmd 115 event-listener) with the Gadgetbridge-correct CMD_BIG_DATA_V2 (0xBC) protocol. This was the big one — all three require the V2 BLE characteristic pair, which our code didn't use at all.

**Key discovery:** Big-data uses a SECOND BLE service (`de5bf728`) with its own notify/write characteristics. Responses can span multiple BLE packets (header bytes [2:3] = uint16 LE total length; accumulate until complete). This is NOT the Nordic UART path — it's a separate service that the R09 exposes.

**V2 service confirmed on R09 FW 3.10.21.** The ring does expose the de5bf728 service with de5bf72a (COMMAND write) and de5bf729 (NOTIFY_V2 notify). Our previous code never subscribed to this characteristic — which is why none of the old commands ever returned data.

**What was done:**

`collector/ring_client.py` — V2 big-data service support:
- Added V2 UUID constants (BIG_DATA_SERVICE_UUID, COMMAND_CHAR_UUID, NOTIFY_V2_CHAR_UUID)
- `connect()` now discovers V2 service, subscribes to NOTIFY_V2, stores COMMAND char
- `_handle_big_data()` — concatenates multi-packet responses (accumulate BLE chunks until `length + 6` bytes received), then pushes complete payload to `big_data_queue`
- `send_command()` — writes raw bytes to V2 COMMAND char (no 16-byte framing — the big-data protocol uses raw bytes, unlike the UART path)

`collector/sync_ring.py` — three new fetch functions + parsers:
- `fetch_sleep_history()` / `_parse_sleep_data()`: 0xBC + 0x27 → per-session sleep data: sleepStart/sleepEnd (minutes after midnight), then (dayBytes-4)/2 stage entries with type (2=light, 3=deep, 4=rem, 5=awake) and duration (minutes). Stores ALL stage segments (not collapsed to 1/day/type).
- `fetch_spo2_history()` / `_parse_spo2_data()`: 0xBC + 0x2A → per-day hourly min/max averaged to single SpO2%
- `fetch_temperature_history()` / `_parse_temperature_data()`: 0xBC + 0x25 → per-day 30-min interval temps: `temp_c = (raw / 10) + 20`
- Replaced `fetch_sleep_data` (cmd 68), `fetch_spo2_data` (cmd 105), `listen_temperature` (cmd 115) with new big-data versions. Old functions renamed to `_legacy` for reference.
- `upsert_sleep` updated: ON CONFLICT `(start_ts, stage, source)` to preserve all per-session stage segments
- Added `upsert_temperature_list` for bulk records (was single-value only)

DB changes:
- `raw_sleep.duration_minutes INT` added
- Unique constraint changed from `(day, stage, source)` to `(start_ts, stage, source)` to handle multiple sessions per night with same stage type

**Verified end-to-end on R09 FW 3.10.21:**
- V2 service detected correctly
- Sleep: 30 stage records across 3 nights (Jul 8-10) with realistic sleep architecture — deep sleep blocks at start, REM cycles every ~90 min, micro-wakes in morning. Stages: light (18), deep (3), rem (6), awake (3)
- SpO2: 26 hourly records. Temperature: 15 records at 30-min intervals

**Files changed:**
- `collector/ring_client.py` — V2 service discovery, _handle_big_data, send_command
- `collector/sync_ring.py` — new big-data fetch/parse functions, updated _collect_data, upsert_sleep
- `collector/test_open_questions.py` — updated imports for renamed functions
- `db/init.sql` — duration_minutes column, new unique constraint
- `AGENTS.md` — this entry

---

## Agent Notes

- **When editing this file:** Append new entries to the Agent Work Log. Keep it chronological.
- **When adding secrets:** Never commit them. Update `.env.example` if a new env var is needed.
- **When touching BLE protocol:** Cross-reference `colmi.puxtril.com` — the source of truth for command structures.
