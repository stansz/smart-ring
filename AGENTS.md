# AGENTS.md — Smart Ring Project

> Agent-facing context. This file is **lean** — details go in `docs/` (research, device behavior, roadmap) or git history.
> Update this when architecture, key files, or current state changes.

---

## Project Overview

Private, self-hosted health tracking around the **Colmi R09** (~$45 CAD).

- **Hardware:** Colmi R09 (FW RT09_3.10.21_251107), BLE → Postgres → health metrics → Alpine.js dashboard
- **Stack:** Python (bleak), FastAPI, Postgres 16, Alpine.js + Tailwind (no build)
- **Deployment:** Linux Mint HTPC (AMD 3800x / 64 GB) — bare metal for collector

**BLE address** is in `.env` as `RING_ADDRESS`. Ring size 11. Host on 24/7.

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

**Critical facts (do not violate):**

- Collector is **bare metal only** (needs BlueZ/DBus) — runs `python -m collector.sync_ring`. Phone pairing requires `forget_ring()` after each sync.
- **R09 single-connection**: Linux box holds the BLE connection; `forget_ring()` releases the ring for phone use.
- **Poller** (`smart-ring-poller.service`): DB-only 30s loop. Watches `sync_requests`, dispatches jobs, then runs analytics. Auto-reaps stuck `sync_log` rows.
- **Services are system-level** (`/etc/systemd/system/`, `User=sz`). Never use `systemctl --user` for production autostart. Use `sudo systemctl`.

### Key commands
```bash
sudo systemctl restart smart-ring-api smart-ring-poller
sudo journalctl -u smart-ring-poller -f
venv/bin/python3 -m collector.sync_ring --forget
venv/bin/python3 -m collector.first_contact
venv/bin/python3 -m pytest tests/                # full regression net (65 tests, ~4s)
podman exec smart-ring-db psql -U smart_ring -d smart_ring
```

Source unit files live in `~/.config/systemd/user/`; deploy with `sudo cp ... /etc/systemd/system/ && daemon-reload`.

---

## Key Source Files

| File | Purpose |
|------|---------|
| `collector/ring_client.py` | BLE wrapper (timeout, `set_time_local`, forget/repair helpers, `_encode_time_bcd` pure helper) |
| `collector/sync_ring.py` + `protocol/` | Thin orchestrator + all BLE protocol, parsers, upserts |
| `collector/analytics/` | Package of per-scorer modules; `python -m collector.analytics` |
| `collector/jobs/` | `SyncJob` / `RingSyncJob` / `AnalyticsJob` for the poller |
| `collector/sync_request_poller.py` | Host poller watching `sync_requests` |
| `api/main.py` | FastAPI app + all endpoints (mobile_sync uses dispatch loop) |
| `api/upsert.py` | `upsert_many` generic dispatcher for simple point tables |
| `dashboard/index.html` | Pure client-side UI (Alpine.js + Tailwind, no build) |
| `tests/` + `pytest.ini` | 65-test regression net (trap_score, BCD, dedupe, mobile_sync) |
| `docs/RING_BEHAVIOR.md` | Firmware quirks, data publish cadence, logger stall |
| `docs/RESEARCH.md` | Scoring formulas & methodology |
| `docs/CLEANUP_PLAN.md` | Cleanup arc history + Step 4 details |

---

## Current State

All 8 raw data types and the 5 health scores (including unified Readiness 0-100) are collecting and computing successfully. Phone sync + dashboard + poller are stable.

**Test suite:** 65 tests across 4 files (`tests/test_trap_score.py`, `tests/test_time_sync_bcd.py`, `tests/test_dedupe.py`, `tests/test_mobile_sync.py`). Run with `venv/bin/python3 -m pytest tests/` — ~4s total. DB-backed tests use an ephemeral `smart_ring_test_<pid>` database created from `db/init.sql`; pure-function tests need no fixtures.

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
- **Runtime:** Collector = bare-metal venv; API + DB = Podman. Never `systemctl --user`; services are system-level.
- **BLE protocol:** Cross-reference Gadgetbridge `yawell/ring` + `colmi.puxtril.com`.
- **Never raw Python to the ring.** Always use `python -m collector.sync_ring --forget` (or `python -m collector.first_contact`). The R09 needs the forget+repair+wake flow.
- **No wrapper services or shims.** If autostart is broken, find the real missing dependency instead of writing `smart-ring-startup.service`.
