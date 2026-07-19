# Collector / Analytics Cleanup Plan

> Branch: `refactor/collector-package`
> Status: Phase 0 complete ✅ · Phase 1 complete ✅ · Phase 2 complete ✅ · Phase 3 pending

---

## Locked constraints (do not violate)

- **Time-sync is sacred.** No change to:
  - `set_time_local()` BCD encoding (6 data bytes, no language flag, matches Gadgetbridge `ColmiR0xDeviceSupport.setDateTime`)
  - `await client.queues[1].get()` ack verification (3s timeout)
  - `clock_drift_ms` 1/0/NULL ack-bit semantics for any existing reader
  - The tz-handling in time-sync timestamp generation
- **R09 firmware quirks preserved.** When `colmi_r02_client` upstream and our working code disagree, **working code wins.** No "improvements" against a "correct upstream."
- **No destructive migrations.** Schema changes are additive only. Old readers keep working.

---

## Defaults (baked into the plan — change via PR comment)

| Concern | Decision |
|---|---|
| `collector-wrapper.py` / `analytics-wrapper.py` | **Deleted** |
| `--forget` flag | **Default `True`**. Rename to `--no-forget` for diagnostics only |
| Poller subprocess for collector | **Kept** — crash isolation + clean BLE state per sync. Wrapper removed (Phase 0). |
| `DISPATCH` magic-string dict | **Replaced with `SyncJob` class hierarchy** in `collector/jobs/` |
| Schema: `clock_drift_ms` repurpose | **Add `sync_log.time_sync_acked BOOLEAN`. Stop writing the int. Leave int column in place (no drop).** |
| Tests | **Pytest smoke tests. Delete the two exploratory scripts.** |
| Service files | **Single source: `deploy/systemd/*.service` in repo. Drop `~/.config/systemd/user/` copies.** |
| `*.log` files in source tree | **Drop `FileHandler(...)`. journald captures stdout.** |
| `/etc/timezone` reads | **Replace with `$TZ` env (already set in podman). Use bind params, not f-string interpolation.** |
| `--attempts` via `sys.argv.index()` | **argparse.** |
| Dashboard | **Not touched. Out of scope — existing rewrite plan in `docs/DASHBOARD_REWRITE_PLAN.md`.** |
| `docker-compose.yml` | **Kept as documentation. Active deployment is podman via `deploy/systemd/*.service`.** |
| Dockerfile `--reload` | **Dropped in production image.** |
| `get_full_data` in ring_client | **Deleted (never called).** |
| `set_time` in ring_client | **Deleted (superseded by `set_time_local`).** |

---

## Phase 0 — Repo hygiene (no behavior change) ✅ COMPLETE

Commit: `89be367` on `refactor/collector-package`

**Deleted files:**
- `collector/collector-wrapper.py`
- `collector/analytics-wrapper.py`
- `collector/test_open_questions.py`
- `collector/test_sync_readonly.py`

**Dead code removed from `collector/sync_ring.py`:**
- `fetch_sleep_data_legacy` (was 487–521)
- `_decode_sleep_qualities` (was 524–539)
- `fetch_spo2_data_legacy` (was 547–566)
- `listen_temperature_legacy` (was 569–583)
- `upsert_temperature_single` (was 691–703)
- `test_sync_behavior` (was 1174–1188)
- Commented HR-recovery block (was 1101–1130)
- `test-sync` CLI branch in `main()`

**Dead code removed from `collector/ring_client.py`:**
- `get_full_data` (was 471–483)
- `set_time` (was 362–366) — `set_time_local` is the only one used
- Removed unused `date_utils` import

**Live-temp path fixed:** `upsert_temperature_single(live_temp)` → `upsert_temperature_list([{"ts": ..., "temp_c": live_temp}])` using the existing list upsert.

**Logging:** Removed `FileHandler(...)` from:
- `collector/sync_ring.py`
- `collector/analytics.py`
- `collector/sync_request_poller.py`
- `collector/first_contact.py`

All four now log to stdout only. journald captures via `Environment=PYTHONUNBUFFERED=1` in systemd service.

**Poller updated:** `COLLECTOR_WRAPPER` → `COLLECTOR_SCRIPT = sync_ring.py` (calls the real script, not the wrapper).

**Untracked-on-disk cleanup:** Deleted `__pycache__/`, `collector/*.log`, `setup.log`.

**Verified:** All 5 collector scripts compile cleanly (`python3 -m py_compile`). No remaining references to deleted symbols (`grep` confirms zero matches).

---

## Phase 1 — Make `collector/` a real package ✅ COMPLETE

Commit: `89be367` on `refactor/collector-package`

**Added `pyproject.toml`:**
```toml
[build-system]
requires = ["setuptools>=68"]
build-backend = "setuptools.build_meta"

[project]
name = "smart-ring-collector"
version = "0.1.0"
requires-python = ">=3.12"
dependencies = [
  "bleak>=0.21",
  "psycopg2-binary>=2.9",
  "python-dotenv>=1.0",
  "colmi_r02_client @ git+https://github.com/tahnok/colmi_r02_client.git",
]

[tool.setuptools.packages.find]
include = ["collector*"]
```

**Entry points now work:**
```
venv/bin/python3 -m collector.sync_ring --no-forget   # forget is now default
venv/bin/python3 -m collector.analytics
venv/bin/python3 -m collector.first_contact
```

**Verified:** `pip install -e .` succeeded in host venv. All imports work:
```python
from collector.ring_client import Client
from collector.sync_ring import connect_with_retry, _parse_sleep_data
from collector.analytics import Analytics
from collector.first_contact import first_contact
from collector.sync_request_poller import claim_next_request
```

**sys.path hacks dropped:**
- Removed `sys.path.insert(0, ...)` from `sync_ring.py` and `first_contact.py`
- `sync_request_poller.py` and `analytics.py` already had no hacks
- Confirmed zero remaining `sys.path.insert` calls in collector/

**argparse in `sync_ring.main()`:**
- Replaced `sys.argv.index(...)` hacks with proper `argparse.ArgumentParser`
- `--forget` is now the reliable default (no flag needed)
- `--no-forget` is opt-out for diagnostics only
- `--attempts N` is a typed int argument
- `--no-retry` is a boolean flag
- `scan` is a subcommand

**Verified:**
```bash
$ python -m collector.sync_ring --help
usage: sync_ring.py [-h] [--no-retry] [--attempts ATTEMPTS] [--no-forget]
                    [{sync,scan}]
```

---

## Phase 2 — Restructure the poller ✅ COMPLETE

Commit: `c664330` on `refactor/collector-package`

**New `collector/jobs/` package:**
```
collector/jobs/
  __init__.py      # exports SyncJob, RingSyncJob, AnalyticsJob
  base.py          # abstract SyncJob with _run_subprocess helper
  ring_sync.py     # RingSyncJob — runs sync_ring.py subprocess
  analytics.py     # AnalyticsJob — runs analytics.py subprocess
```

**Poller (`sync_request_poller.py`) is now a thin orchestrator:**
- Replaced `DISPATCH` dict + `ANALYTICS_ONLY` magic string with `JOBS` factory mapping to `SyncJob` subclasses
- Adding a new request type = new `SyncJob` subclass + entry in `JOBS`
- Hard error if venv Python missing (no silent fallback to `sys.executable`)
- `reap_stuck_rows` always commits (removed conditional rollback)
- DB session `TIME ZONE` set from `$TZ` env (with `/etc/timezone` fallback) at startup
- Poller reconnects and re-sets TZ on `psycopg2.OperationalError`

**Verified:** All imports work, `py_compile` clean, old symbols (`DISPATCH`, `ANALYTICS_ONLY`, `COLLECTOR_WRAPPER`, `run_collector`, `run_analytics`) gone.

---

## Phase 3 — Split `sync_ring.py` (1254 → <300 lines)

```
collector/
  protocol/
    ble.py          = existing ring_client.py content (timeout, V2, packet dispatch, BlueZ helpers)
    parsers/
      hr.py
      hrv.py
      sleep.py
      spo2.py
      temp.py
      stress.py
      steps.py
      goals.py
    db.py           upsert_many(table, records, source='ring')
    state.py        sync_log start/update/complete, ring_status insert, current_step writer
    time_sync.py    set_time_local wrapper + ack verification (PRESERVE EXACT BEHAVIOR)
  sync_ring.py      orchestrator only: argparse, connect_with_retry, _collect_data, main()
```

Tasks:
- [ ] Phase 3 [SACRED]: PRESERVE `set_time_local()` BCD encoding EXACTLY
- [ ] Phase 3 [SACRED]: PRESERVE `queues[1]` ack verification (3s timeout)
- [ ] Phase 3 [SACRED]: Working code wins over `colmi_r02_client` upstream

---

## Phase 4 — Split `analytics.py` (1080 → <200)

```
collector/analytics/
  __init__.py           run_all() — orchestrator
  hrv.py                compute_hrv_recovery + trap_score helpers
  sleep.py              compute_sleep_quality + _score_sleep_day + session clustering
  stress.py             compute_stress + _peak_sustained
  circadian.py          compute_circadian_hr
  rhr.py                compute_resting_hr
  daily_activity.py     compute_daily_activity
  readiness.py          compute_readiness_score + z→score mapping
  data_quality.py       compute_data_quality
  dedupe.py             dedupe_sources (single source of truth)
collector/analytics.py  re-exports `from collector.analytics import main`
```

Tasks:
- [ ] Split into `collector/analytics/` package
- [ ] Single `dedupe_sources()` source of truth (analytics owns it, api drops its copy)

---

## Phase 5 — API cleanup (`api/main.py`)

- [ ] Drop `Base`, `DeclarativeBase`, `create_all` (no ORM models exist)
- [ ] Move raw `text(...)` SQL to `api/queries/*.py`
- [ ] Rewrite `/api/mobile/sync` as generic `upsert_many(table, records, source='phone')`
- [ ] Fix SQL injection: `/api/resting-hr` uses bind params, not f-string
- [ ] Drop duplicate dedup in API (analytics owns it)

---

## Phase 6 — Schema migration (additive only)

```sql
ALTER TABLE sync_log ADD COLUMN IF NOT EXISTS time_sync_acked BOOLEAN;
```

Tasks:
- [ ] Phase 6 [SACRED]: No `DROP COLUMN` on `clock_drift_ms` — leave int column populated for one release
- [ ] Stop writing to `clock_drift_ms` (use new bool), keep int readers working

---

## Phase 7 — Service files + deployment

```
deploy/systemd/
  smart-ring-db.service
  smart-ring-api.service
  smart-ring-poller.service
deploy/Makefile
deploy/install.sh
deploy/uninstall.sh
```

Tasks:
- [ ] Move service files to `deploy/systemd/` in repo
- [ ] Add `deploy/Makefile` + `deploy/install.sh` + `deploy/uninstall.sh`
- [ ] Delete `~/.config/systemd/user/smart-ring-*.service`
- [ ] Drop `--reload` from Dockerfile CMD
- [ ] Update AGENTS.md to reference `deploy/systemd/` as new source of truth

---

## Phase 8 — Real tests

```
tests/
  conftest.py
  test_parsers_temp.py
  test_parsers_sleep.py
  test_time_sync_bcd.py
  test_trap_score.py
  test_readiness.py
  test_dedupe.py
pytest.ini
```

Tasks:
- [ ] Add `tests/` with pytest smoke tests
- [ ] Add `pytest.ini` + `conftest.py` with DB fixture

---

## Cross-phase (low priority, do when convenient)

- [x] **Migrate `/etc/timezone` reads → `$TZ` env var everywhere** — analytics.py + api/main.py both fixed; uses $TZ → /etc/timezone → America/Vancouver fallback chain, bind params
- [x] **Fix hardcoded `'America/Vancouver'` in `analytics.py` `compute_data_quality`** — now uses `DATE(ts)` against session TZ set in `__init__`

---

## Out of scope

- Dashboard (`dashboard/index.html`, 2928 lines) — existing rewrite plan in `docs/DASHBOARD_REWRITE_PLAN.md`
