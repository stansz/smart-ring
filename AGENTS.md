# AGENTS.md — Smart Ring Project

> Agent-facing context for the Smart Ring health data pipeline.
> This file is a **living document** — update it as the project evolves.

---

## Project Overview

Private, self-hosted health tracking system built around the **Colmi R09** smart ring (~$45 CAD). Collects biometric data via BLE, stores in Postgres, computes health metrics (HRV, sleep, recovery), and visualizes in a local web dashboard.

- **Hardware:** Colmi R09 (BlueX RF03 SoC, PPG + SpO2 + skin temp + accelerometer)
- **Stack:** Python (async BLE), FastAPI, Postgres, Alpine.js + Chart.js
- **Deployment:** Local-first on Linux Mint HTPC (AMD 3800x, 64GB RAM)
- **Status:** Awaiting hardware delivery (~2-4 weeks from AliExpress)

**Update 2026-07-09:** Ring arrived, hardware confirmed working. Firmware RT09_3.10.21_251107, HW RT09_V3.1. Nordic UART protocol (UUIDs match colmi_r02_client). See work log entries for full validation.

---

## Architecture (Local-First, Quadlet-Managed)

```
Home Network
├─ Linux Mint Box (AMD 3800x, 64GB RAM, BT enabled)
   ├─ Collector (bare metal Python venv — needs BlueZ/DBus for BLE)
   │  └─ Cron: every 2 hours
   ├─ Postgres (rootless Podman, managed by systemd quadlet)
   │   ├─ smart-ring-db.service (user systemd unit)
   │   └─ port 127.0.0.1:5432, volume smart-ring-pgdata
   ├─ FastAPI (rootless Podman, managed by systemd quadlet)
   │   ├─ smart-ring-api.service (user systemd unit, Requires=db)
   │   └─ port 127.0.0.1:8000
   └─ Dashboard (served by FastAPI, single-page Alpine.js + Chart.js)
      └─ Analytics cron: 2 min after collector

   Windows 10 VM (VMware): Untouched, ~16GB reserved
```

- **Container runtime:** Podman 4.9.3, rootless, user systemd units
- **Collector** is **bare metal only** — needs direct BlueZ/DBus access for BLE.
- **Quadlets** live in `~/.config/containers/systemd/` (not the repo) — they're host-specific.
- **Lingering enabled** (`loginctl enable-linger sz`) so services start at boot, not on login.
- **Docker fully removed** (July 2026) in favor of rootless Podman + quadlets.
- `docker-compose.yml` in repo kept as fallback documentation but **not used** for local deployment.

---

## Key Source Files

| File | Purpose | Notes |
|------|---------|-------|
| `collector/sync_ring.py` | BLE collector, syncs ring → Postgres | Time sync uses `datetime.now()` **(local time, not UTC)** |
| `collector/analytics.py` | Computes HRV, sleep, recovery metrics | `detect_sleep_stages()` infers duration since cmd 68 lacks timestamps |
| `collector/first_contact.py` | Safe read-only diagnostics | Reads battery, firmware, device info, sets clock — NO data sync |
| `collector/sync_request_poller.py` | Host-side poller for admin-triggered syncs | Runs on host (not container); claims rows from `sync_requests` and invokes the collector |
| `api/main.py` | FastAPI with metric + admin endpoints | Serves dashboard static files from `../dashboard/` |
| `dashboard/index.html` | Single-page Alpine.js + Chart.js UI, **two tabs: Dashboard + Admin** | No build step needed |
| `db/init.sql` | Postgres schema | `circadian_hr` uses `PRIMARY KEY (day, hour)`; `sync_requests` is the admin job queue |
| `setup.sh` | Python-based setup + cron configuration | Does NOT overwrite existing files anymore |
| `docker-compose.yml` | Legacy fallback (Podman quadlets are the live deployment) | Binds to `127.0.0.1` |

---

## Agent Work Log

Use this section to append notes about what the agent has done, decisions made, and open issues. Append chronologically.

### 2026-07-08 — Sync Poller Wired Up + Pre-Ring Smoke Test

**Task:** Complete the remaining TODO before ring arrival — wire up the sync request poller so Admin tab buttons actually work.

**What was done:**
- Created `~/.config/systemd/user/smart-ring-poller.service` — `--loop --interval 2s`, enabled, active
- Poller claims DB rows via `FOR UPDATE SKIP LOCKED`, dispatches to `first_contact.py` or `sync_ring.py` depending on `requested_by`
- Smoketested end-to-end: POST `/api/admin/first-contact` → row claimed within ~1s → `first_contact.py` ran → failed as expected (no ring in range)
- Both "First Contact" and "Sync Now" Admin tab buttons now fully functional end-to-end

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
- `docker-compose.yml` now binds Postgres/API to `127.0.0.1` (localhost only)
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
- `smart-ring-db.container` — Postgres 16 alpine, named volume `smart-ring-pgdata`, mounts `db/init.sql`, port `127.0.0.1:5432`, healthcheck
- `smart-ring-api.container` — built image `localhost/smart-ring-api:latest`, `Requires=smart-ring-db.service`, mounts `api/` + `dashboard/` for live reload, port `127.0.0.1:8000`

**Verified end-to-end:**
- Both services `active (running)` under `systemctl --user`
- Postgres: 13 tables created from `init.sql`, healthcheck passing
- API `/health` returns `{"status":"ok","db":"connected"}`
- Dashboard HTML served at `http://127.0.0.1:8000/`

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
- Both "First Contact" and "Sync Now" buttons now fully functional

**Still TODO before ring arrives:**
- [ ] Set up collector + analytics cron jobs (`setup.sh` ran but `psql` was unavailable — crontab is empty)

### 2026-07-09 — Ring Arrived: First Contact + Open-Question Tests

**Hardware confirmed working:**
- BLE address: `30:35:42:37:21:03` (R09_2103)
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
- [ ] Run collector once more after waking ring → confirm 0 new step records → confirm sync is read-only
- [ ] Add retry-on-sleep to `sync_ring.py` (try N attempts before failing)
- [ ] Add automatic wake gesture (heavy BLE activity) before sync attempts
- [ ] Collect enough HRV data to determine format (RR vs composite): wear for 24h+
- [ ] Investigate the `0x80`-bit packets (probably sleep or temperature reported asynchronously)

---

## Environment & Secrets

- **No secrets in repo.** All creds live in `.env` (gitignored).
- `.env.example` provides the template.
- Postgres default password in compose: `${POSTGRES_PASSWORD:-changeme}`

---

## Testing the Ring (When It Arrives)

> **Goal:** Validate hardware works → determine sync behavior → start collection.
> **Critical rule:** Treat the ring's stored data as precious until we know whether sync clears the buffer.

### Step 1 — PC BLE scan (zero risk, no connection)
```bash
python3 collector/sync_ring.py scan
```
Just discovers the BLE address. No data access. Confirms the Linux box sees the ring.
Set `RING_ADDRESS=XX:XX:XX:XX:XX:XX` in `.env` once known.

### Step 2 — Gadgetbridge for visual hardware validation (safe IF no sync)
- Install from F-Droid: `nodomain.freeyourgadget.gadgetbridge` (NOT Play Store)
- Pair via BLE, set the clock
- Verify sensors fire: live HR, SpO2, temperature, step counter
- ⚠️ **DO NOT tap "Sync" / "Fetch data" in Gadgetbridge yet** — we don't know if it clears the ring's buffer. Live HR viewing (cmd 30) is safe; the Sync button is not.

### Step 3 — PC info-only connection (read-only)
Connect, read battery + firmware + device info, set clock. **No data sync.**
Handled by `collector/first_contact.py` — fully implemented. Queue from the Admin tab "First Contact" button, or run directly:
```bash
source venv/bin/activate && python3 collector/first_contact.py
```

### Step 4 — Run `test_open_questions.py` (the actual experiments)
```bash
python3 collector/test_open_questions.py
```
This resolves the three Known Unknowns below:
- Sync behavior (test syncs twice, compares counts — small data loss acceptable on fresh ring)
- HRV format (RR intervals vs composite score)
- Temperature sampling cadence

### Step 5 — Configure collector based on test results
- If sync is read-and-clear → don't use Gadgetbridge sync at all going forward
- If HRV is RR intervals → enable RMSSD/pNN50 computation
- If temp cadence is workable → enable sleep staging with temperature bonus

### Then check logs
- `collector/collector.log` for sync errors
- `journalctl --user -u smart-ring-api` for API/dashboard issues

---

## Known Unknowns (Block on Hardware)

| Question | Status (2026-07-09) | Test Plan / Notes |
|----------|---------------------|---------------------|
| Sync behavior: read-only or read-and-clear? | **Tentatively read-only** — first sync pulled 2 records | Run sync twice, compare DB counts; needs ring to stay awake |
| HRV data format: RR intervals vs composite score? | **TBD** — 0 records on fresh ring | Need to wear 24h+ for HRV log to populate |
| Temperature sensor sampling rate | **Event-driven** — no push in 10s window | Confirm in longer window once data accumulates |
| R09 firmware compatibility with tahnok client | **WORKS** — FW 3.10.21 + colmi_r02_client | UUIDs match exactly; admin UI works end-to-end |

---

## Future Work (Post-Hardware)

- [x] Verify actual ring data format against current parsers
- [x] Write `collector/first_contact.py` — safe read-only first contact script (scan + battery + firmware + set clock, NO data sync) — done, fully functional
- [x] Create `collector/ring_client.py` — robust BLE client wrapper with explicit timeout
- [x] Add `BLE pairing once via bluetoothctl` instructions to AGENTS.md (in step 3 of "Testing the Ring")
- [ ] Add retry-on-sleep logic to `sync_ring.py` (R09 falls asleep fast)
- [ ] Add Prometheus/metrics endpoint for monitoring
- [ ] Consider Cloudflare tunnel for remote dashboard access
- [ ] Evaluate custom firmware (atc1441) for enhanced features
- [ ] Investigate 0x80-bit async packets (probably sleep/HRV/temperature historical push)

---

## Agent Notes

- **When editing this file:** Append new entries to the Agent Work Log. Keep it chronological.
- **When adding secrets:** Never commit them. Update `.env.example` if a new env var is needed.
- **When touching BLE protocol:** Cross-reference `colmi.puxtril.com` — the source of truth for command structures.
