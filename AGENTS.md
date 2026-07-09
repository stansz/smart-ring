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
| `collector/ring_client.py` | Drop-in wrapper around `colmi_r02_client.Client` | Passes explicit `timeout` to `BleakClient` (upstream hangs without one); replaces `assert packet_type < 127` with `logger.debug` so async ring pushes don't kill the listener |
| `collector/sync_ring.py` | BLE collector, syncs ring → Postgres | Time sync uses `datetime.now()` **(local time, not UTC)**; uses `ring_client.Client` |
| `collector/collector-wrapper.py` | Tiny shim that sets `sys.path` and runs `sync_ring.main()` | Cron / poller entry point |
| `collector/first_contact.py` | Safe read-only diagnostics | Reads battery (`battery_level`), firmware, device info, sets clock — NO data sync |
| `collector/test_open_questions.py` | One-shot validation of unknown ring behaviors | Uses a single Client connection with per-test try/except (the ring drops between reconnects) |
| `collector/sync_request_poller.py` | Host-side poller for admin-triggered syncs | Runs on host (not container); claims rows from `sync_requests` via `FOR UPDATE SKIP LOCKED`, dispatches based on `requested_by` |
| `collector/analytics.py` | Computes HRV, sleep, recovery metrics | `detect_sleep_stages()` infers duration since cmd 68 lacks timestamps |
| `api/main.py` | FastAPI with metric + admin endpoints | Serves dashboard static files from `../dashboard/`; 5 admin endpoints (`ring-status`, `health`, `sync-log`, `first-contact`, `sync`, `sync-requests`) |
| `dashboard/index.html` | Single-page Alpine.js + Chart.js UI, **two tabs: Dashboard + Admin** | No build step needed; polls every 5s for active sync status |
| `db/init.sql` | Postgres schema | `circadian_hr` uses `PRIMARY KEY (day, hour)`; `sync_requests` is the admin job queue |
| `setup.sh` | Python-based setup + cron configuration | Does NOT overwrite existing files anymore |
| `docker-compose.yml` | Legacy fallback (rootless Podman quadlets are the live deployment) | Binds to `127.0.0.1` only |

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
- [x] Add retry-on-sleep to `sync_ring.py` (try N attempts before failing) — done; see 2026-07-09b below
- [ ] Add automatic wake gesture (heavy BLE activity) before sync attempts
- [ ] Collect enough HRV data to determine format (RR vs composite): wear for 24h+
- [ ] Investigate the `0x80`-bit packets (probably sleep or temperature reported asynchronously)

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

---

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
   bluetoothctl pair 30:35:42:37:21:03          # "Pairing successful"
   bluetoothctl trust 30:35:42:37:21:03         # optional: auto-allow reconnects
   bluetoothctl disconnect 30:35:42:37:21:03    # let bleak own the connection
   ```
   ⚠️ **Never** use `bluetoothctl connect` after pairing — it takes exclusive GATT ownership and breaks the Python collector.

### Daily operations
```bash
source venv/bin/activate

# Read-only diagnostic (battery, firmware, set clock — no data sync)
python3 collector/first_contact.py

# Full sync to Postgres (HR, steps, HRV, sleep, SpO2, temperature)
python3 collector/sync_ring.py

# Or use the Admin tab "First Contact" / "Sync Now" buttons
# → POST /api/admin/first-contact, /api/admin/sync
# → sync_request_poller.py picks up the row within ~2s
```

### Observability
- `collector/collector.log` — sync errors
- `collector/first_contact.log` — first-contact diagnostics
- `collector/sync_request_poller.log` — poller activity
- `journalctl --user -u smart-ring-poller -f` — poller service logs
- `podman logs smart-ring-api` — FastAPI logs
- `journalctl --user -u smart-ring-db` — Postgres logs

---

## Known Unknowns (Partial — see work log for details)

| Question | Status (2026-07-09) | Test Plan / Notes |
|----------|---------------------|---------------------|
| Sync behavior: read-only or read-and-clear? | **Tentatively read-only** — first sync pulled 2 records to DB | Run sync twice, compare DB counts; needs ring to stay awake long enough |
| HRV data format: RR intervals vs composite score? | **TBD** — 0 records on fresh ring | Need to wear 24h+ for HRV log to populate |
| Temperature sensor sampling rate | **Event-driven** — no push in 10s window | Confirm in longer window once data accumulates |
| R09 firmware compatibility with tahnok client | **WORKS** — FW 3.10.21 + colmi_r02_client | UUIDs match exactly; admin UI works end-to-end |

---

## Future Work (Hardening, Once Hardware Is Stable)

- [x] Verify actual ring data format against current parsers
- [x] Write `collector/first_contact.py` — safe read-only first contact script — done, fully functional
- [x] Create `collector/ring_client.py` — robust BLE client wrapper with explicit timeout
- [x] Add `BLE pairing once via bluetoothctl` instructions to AGENTS.md
- [x] Add retry-on-sleep logic to `sync_ring.py` (R09 falls asleep fast) — done; new `connect_with_retry` helper in `sync_ring.py`, used by both `sync_ring` and `first_contact`
- [ ] Add Prometheus/metrics endpoint for monitoring
- [ ] Consider Cloudflare tunnel for remote dashboard access
- [ ] Evaluate custom firmware (atc1441) for enhanced features
- [ ] Investigate 0x80-bit async packets (probably sleep/HRV/temperature historical push)

---

## Agent Notes

- **When editing this file:** Append new entries to the Agent Work Log. Keep it chronological.
- **When adding secrets:** Never commit them. Update `.env.example` if a new env var is needed.
- **When touching BLE protocol:** Cross-reference `colmi.puxtril.com` — the source of truth for command structures.
