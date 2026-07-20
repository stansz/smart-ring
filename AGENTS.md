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
podman exec smart-ring-db psql -U smart_ring -d smart_ring
```

Source unit files live in `~/.config/systemd/user/`; deploy with `sudo cp ... /etc/systemd/system/ && daemon-reload`.

---

## Key Source Files

| File | Purpose |
|------|---------|
| `collector/ring_client.py` | BLE wrapper (timeout, `set_time_local`, forget/repair helpers) |
| `collector/sync_ring.py` + `protocol/` | Thin orchestrator + all BLE protocol, parsers, upserts |
| `collector/analytics/` | Package of per-scorer modules; `python -m collector.analytics` |
| `collector/jobs/` | `SyncJob` / `RingSyncJob` / `AnalyticsJob` for the poller |
| `collector/sync_request_poller.py` | Host poller watching `sync_requests` |
| `api/main.py` + `dashboard/index.html` | FastAPI + pure client-side UI |
| `docs/RING_BEHAVIOR.md` | Firmware quirks, data publish cadence, logger stall |
| `docs/RESEARCH.md` | Scoring formulas & methodology |

---

## Current State

All 8 raw data types and the 5 health scores (including unified Readiness 0-100) are collecting and computing successfully. Phone sync + dashboard + poller are stable.

**See `docs/RING_BEHAVIOR.md`** for:
- Firmware quirks, per-data-type reference (command, publish cadence, etc.)
- Critical details: background logger stall behavior, temp history only publishing *completed* days (`daysAgo` >= 1), R09 single-connection limit

**See `docs/RESEARCH.md`** for validated scoring formulas and methodology.

**See `TASKS.md`** for CFW ideas, readiness improvements, and open backlog.

**High-signal recent facts (verify via DB + source):**
- Clock sync uses the sacred local BCD `set_time_local()` + ack path (clock_drift_ms=1 means success).
- Poller auto-reaps stuck `sync_log` rows.
- Source dedup prefers ring data.

---

## Recent Work Log (Jul 2026)

Keep only high-signal recent sessions. For prior work: `git log --oneline` and `docs/CLEANUP_PLAN.md`.

### 2026-07-20 — API cleanup Steps 1+2 + trap_score test suite (CLEANUP_PLAN Tier 1)
- Shipped `docs/CLEANUP_PLAN.md` "Next steps: API cleanup" Steps 1+2 in one commit
  (`4032415`): dropped dead `Base(DeclarativeBase)` + `create_all()` from `api/main.py`
  (no ORM models exist) and dropped redundant `_dedupe_sources` (analytics owns dedup
  via `collector/analytics/dedupe.py:dedupe_sources()`). Verified live: image grep
  clean, `/api/mobile/sync` 200 OK, `raw_heart_rate` source ratio `ring=487 / phone=2`
  confirms analytics-side dedup still runs.
- First `tests/` suite (`8e1e9d0`): `pytest.ini` + `tests/test_trap_score.py` (20
  cases — boundaries, ramp linearity via per-unit slope, symmetry). All pass in 0.04s.
  pytest 9.1.1 installed in venv. Next Tier 1 item: BCD helper extraction + test
  (Option A in plan — touches sacred `set_time_local`, deserves solo review).

### 2026-07-20 — Sync retry investigation + battery noise documentation
- Morning dashboard sync took 4 attempts (sync_log #138–141). Two failures were R09
  quirks (cold-start BLE negotiation, `Fetching goals...` stall), one was an overlap
  artifact (#127-equivalent timed out and the next request fired immediately, BlueZ
  couldn't release the previous connection in time). Final sync succeeded with
  `clock_drift_ms=1`, 262 records.
- Investigated battery reading noise over past 2 days (37%→52% jumps, 88% outlier in
  sync_log #127). Root cause: R09 has no battery history — every reading is a noisy
  instantaneous ADC sample (observer-effect under BLE load). Verified Gadgetbridge's
  `ColmiR0xDeviceSupport.java` does identical `value[1]` parsing with no smoothing.
- Documented findings in `docs/RING_BEHAVIOR.md` (new "Battery readings are noisy"
  section). Smoothing deferred — currently tracking raw values in `sync_log` +
  `ring_status`.

### 2026-07-19 — Live verification + poller analytics job fix (post-refactor)
- User triggered dashboard sync #132 (~14:16). `clock_drift_ms=1`, 117 records, battery 52%.
- Fixed `collector/jobs/analytics.py` (was referencing deleted `collector/analytics.py` causing rc=2). Now uses `python -m collector.analytics`.
- `set_time_local` hotfix (from earlier Phase 0 regression) now proven in production.
- Re-ran analytics; readiness 40 → 53 (full). Stale doc references cleaned.

### 2026-07-18 — Readiness overhaul + cleanup plan
- 3-pillar readiness (HRV 44% / Sleep 37% / RHR 19%).
- Major collector refactor: split into `protocol/` + `analytics/` packages + `jobs/`.
- `docs/CLEANUP_PLAN.md` created.

**July 13–17:** Dashboard overhaul, temp big-data fix, docs reorganization. Details in git.

---

## Agent Notes

- **When editing:** Update the work log above. Keep it lean — details go in `docs/` or git history.
- **Secrets:** Never commit. Update `.env.example` for new env vars.
- **Runtime:** Collector = bare-metal venv; API + DB = Podman. Never `systemctl --user`; services are system-level.
- **BLE protocol:** Cross-reference Gadgetbridge `yawell/ring` + `colmi.puxtril.com`.
- **Never raw Python to the ring.** Always use `sync_ring.py --forget` (or `first_contact.py`). The R09 needs the forget+repair+wake flow.
- **No wrapper services or shims.** If autostart is broken, find the real missing dependency instead of writing `smart-ring-startup.service`.
