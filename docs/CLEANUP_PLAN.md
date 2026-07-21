# Collector / Analytics Cleanup Plan

> Branch: `dev`
> Status: **All phases + API cleanup + Tier 1 test suite ✅ COMPLETE** · latest on `dev`
>
> Phases 0–4 (collector/analytics refactor, 2026-07-18) + TZ fix + perf merge ✅ done.
> Phase 0 hotfix applied 2026-07-19 (restored `set_time_local`).
> API cleanup Steps 1, 2, 4 done 2026-07-20 (Step 3 skipped indefinitely — pure relocation, no payoff).
> Tier 1 test suite (65 tests across 4 files) done 2026-07-20.
> `dev` ahead of `main` — push pending user verification per operational protocol.

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
| Tests | Exploratory scratchpad scripts removed; real test suite is a separate (deferred) project. |
| `*.log` files in source tree | **Drop `FileHandler(...)`. journald captures stdout.** |
| `/etc/timezone` reads | **Replace with `$TZ` env (already set in podman). Use bind params, not f-string interpolation.** |
| `--attempts` via `sys.argv.index()` | **argparse.** |
| `get_full_data` in ring_client | **Deleted (never called).** |
| `set_time` in ring_client | **Deleted (superseded by `set_time_local`).** |

---

## Commit timeline

| Commit | Phase | Summary |
|---|---|---|
| `89be367` | 0 + 1 | Remove shims + dead code; `pyproject.toml`; argparse; `pip install -e .` |
| `c664330` | 2 | Poller rewrite as thin orchestrator over `collector/jobs/` |
| `800eea2` | cross | TZ cleanup — bind params, `$TZ` env, session TZ in `__init__` |
| `64c0262` | cross | Merge redundant `wear_hourly_rows` query (single CTE) |
| `1c04efb` | 3 | Split `sync_ring.py` into `collector/protocol/` package |
| `2166151` | 3 post-fix | Import the timeout-capable `ring_client.Client` wrapper |
| `f416170` | 4 | Split `analytics.py` into `collector/analytics/` package |
| `630ac65` | docs | This cleanup plan |

---

## Phase 0 — Repo hygiene (no behavior change) ✅ COMPLETE

Commit: `89be367` on `dev`

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

**Post-review finding (2026-07-19):** Phase 0 also deleted the `async def set_time_local(...)` line (not just the deprecated `set_time`). The BCD body remained but as unreachable statements. Every `set_time_local` call raised `AttributeError`; the `sync_ring` orchestrator silently caught it. All syncs after `89be367` wrote `clock_drift_ms=NULL`. The Phase 0 "verified" was insufficient — py_compile does not catch missing methods and the grep targeted the wrong name.

Hotfix added back `async def set_time_local(self, ts: datetime) -> None:` before the preserved docstring+body + removed the now-orphaned broken HR-log wrapper methods that still referenced `date_utils`. Pure execution tests (BCD round-trip + full `sync_time_to_ring` ack path) pass. Operational verification requires next rise of a ring connection that reaches `_collect_data`.

---

---

## Phase 1 — Make `collector/` a real package ✅ COMPLETE

Commit: `89be367` on `dev`

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

Commit: `c664330` on `dev`

**New `collector/jobs/` package:**
```
collector/jobs/
  __init__.py      # exports SyncJob, RingSyncJob, AnalyticsJob
  base.py          # abstract SyncJob with _run_subprocess helper
  ring_sync.py     # RingSyncJob — runs sync_ring.py subprocess
  analytics.py     # AnalyticsJob — invokes `python -m collector.analytics` (post Phase 4)
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

## Phase 3 — Split `sync_ring.py` (1079 → 284 lines) ✅ COMPLETE

Commit: `1c04efb` on `dev` (+ post-fix `2166151`)

**New `collector/protocol/` package:**
```
collector/protocol/
  __init__.py           re-exports SyncResult, upserts, sync state
  db.py                 SyncResult, sync_log start/complete/progress, ring_status,
                        make_packet, _read_multi_packet, all upsert_*()
  scanner.py            scan_ring()
  connect.py            connect_with_retry + forget+repair flow
  time_sync.py          sync_time_to_ring() — SACRED code, see below
  parsers/
    _big_data.py        big_data_request() shared helper (drain queue + reset buf)
    hr.py               fetch_hr_history + upsert_heart_rate
    hrv.py              fetch_hrv_history
    sleep.py            fetch_sleep_history + _parse_sleep_data
    spo2.py             fetch_spo2_history + _parse_spo2_data
    temp.py             fetch_temperature_history + drain_live_temperature
    stress.py           fetch_stress_history
    steps.py            fetch_steps (15-min slot handling)
    goals.py            fetch_goals (Gadgetbridge layout)
```

**Sacred time-sync preserved verbatim:**
- `sync_time_to_ring()` calls `client.set_time_local()` (the carefully tuned BCD encoder)
- `set_time_local()` in `ring_client.py` is untouched: 6 BCD bytes, no language flag, matches Gadgetbridge `ColmiR0xDeviceSupport.setDateTime()` byte-for-byte
- `await asyncio.wait_for(client.queues[1].get(), timeout=3.0)` ack verification intact
- `clock_drift_ms` 1/0/NULL ack-bit semantics in sync_log unchanged
- No "improvements" against `colmi_r02_client` upstream applied anywhere in the protocol layer

**Verified:**
- All files compile cleanly (`python3 -m py_compile`)
- Imports work end-to-end (orchestrator + protocol + parsers + first_contact)
- `--help` output identical for `sync_ring` and `first_contact`
- Argparse surface preserved (`sync`/`scan` subcommand, `--no-retry`, `--attempts`, `--no-forget`)
- `first_contact.py` updated to import `connect_with_retry` from `collector.protocol.connect`

**Line counts:**
- `sync_ring.py`: 1079 → 284
- `collector/protocol/`: ~1100 lines total (split out, net ~zero growth, much higher cohesion)

---

## Phase 3 post-fix — wrong Client class imported

Commit: `2166151` on `dev`

The Phase 3 split imported `Client` from `colmi_r02_client.client` (upstream)
in `protocol/connect.py` instead of from `collector.ring_client` (the wrapper
that accepts `timeout`). Upstream `Client.__init__()` rejects the kwarg,
so every sync since Phase 3 hit:

```
Client.__init__() got an unexpected keyword argument 'timeout'
```

Fix: import the wrapper explicitly in `protocol/connect.py` and use it for
both the `Client(...)` call site and the return type annotation.

**Verified after restart:**
- Sync #126 completed (112 records, battery 52%)
- HR / HRV / stress / sleep wrote new rows
- Readiness recomputed (today: score 40, full confidence)
- SpO2/temp = 0 (ring's `daysAgo=0` publish cadence — see `docs/RING_BEHAVIOR.md`)

---

## Phase 4 — Split `analytics.py` (1079 → 13 focused files) ✅ COMPLETE

Commit: `f416170` on `dev`

**New `collector/analytics/` package:**
```
collector/analytics/
  __init__.py           re-exports main
  __main__.py           enables `python -m collector.analytics`
  main.py               main() + run_all() orchestration (57 lines)
  db.py                 connect() context manager + session TZ setup
  helpers.py            trap_score + readiness_text (pure functions)
  dedupe.py             dedupe_sources() — single source of truth
  hrv.py                compute_hrv_recovery
  sleep.py              compute_sleep_quality + _score_sleep_day +
                        _get_overnight_temps + _store_sleep_quality
  stress.py             compute_stress + _peak_sustained
  circadian.py          compute_circadian_hr
  rhr.py                compute_resting_hr
  daily_activity.py     compute_daily_activity (with merged wear_hourly CTE)
  readiness.py          compute_readiness_score + z→score mapping
  data_quality.py       compute_data_quality
```

**Architecture change:** `Analytics` class is gone. Each scorer is a
standalone function taking a DB connection. `main.py:run_all()` opens the
connection via `db.connect()` (context manager), calls `dedupe_sources`
first, then iterates through the scorers in dependency order.

**Verified:**
- `python -m py_compile` clean on all 13 files
- `python -m collector.analytics` runs end-to-end (dedupe + 8 scorers)
- All exports importable: `from collector.analytics.hrv import compute_hrv_recovery`, etc.
- `AnalyticsJob` in `collector/jobs/analytics.py` still works (invokes `python -m collector.analytics` via subprocess)

---

## Cross-phase (low priority, do when convenient)

- [x] **Migrate `/etc/timezone` reads → `$TZ` env var everywhere** — `analytics/db.py` `connect()` uses `$TZ` → `/etc/timezone` → `America/Vancouver` fallback, bind params
- [x] **Fix hardcoded `'America/Vancouver'` in `analytics.py` `compute_data_quality`** — now uses `DATE(ts)` against session TZ set in `__init__`
- [x] **Merge redundant `wear_hourly_rows` query in `compute_daily_activity`** — single CTE with `ARRAY_AGG(DISTINCT EXTRACT(HOUR FROM ts)::int)`

---

## Out of scope

- Dashboard (`dashboard/index.html`, 2928 lines) — existing rewrite plan in `docs/DASHBOARD_REWRITE_PLAN.md` (not started, untouched this session)
- Real pytest suite (Phase 8 in earlier drafts) — separate future project
- Service files in `deploy/systemd/` (Phase 7 in earlier drafts) — not started, the system service units on disk continue to work as before

---

## Next steps: API cleanup

**Scope:** bring `api/` to the same modular shape as `collector/`. End state: same dashboard behavior, but with cleaner code under the hood. No new features. No behavior changes.

**Why it matters:** the dashboard works, but `api/main.py` still has the cruft (inline SQL, dead dedup, f-string TZ in one spot) the original ask flagged. The collector/poller/analytics side is clean; `api/` should match, so future fixes are cheaper and the structure matches.

**Hard constraints (already established on `dev`):**
1. Time-sync code is sacred — no change to `set_time_local()` BCD encoding, `queues[1]` ack verification, or time-sync `tz` handling.
2. No destructive migrations — DB schema is the source of truth; API is a thin SQL layer on top.
3. R09 firmware quirks preserved — no "cleanup" of the working time-sync or reconnection flow.
4. Working dashboard is the success metric — after every step, `curl http://localhost:8000/health` returns 200 and `/api/sync-log`, `/api/readiness`, `/api/raw/heart-rate` return their current shapes with no schema changes.

### Step 1 — drop `Base`, `DeclarativeBase`, `create_all` (no-op ORM code)

**Why first:** zero-risk cleanup. `api/main.py` imports `DeclarativeBase` from SQLAlchemy, defines a `Base` class, and calls `Base.metadata.create_all(bind=engine)` in lifespan. There are no ORM models anywhere in the codebase. This code does literally nothing.

**What to do:**
- Delete `class Base(DeclarativeBase): pass` from `api/main.py`.
- Delete `Base.metadata.create_all(bind=engine)` from the `lifespan` context manager.
- Delete the `from sqlalchemy.orm import sessionmaker, DeclarativeBase` import (change to `from sqlalchemy.orm import sessionmaker`).
- Confirm no `Base` references remain: `grep -n "DeclarativeBase\|create_all" api/`.

**Verify:**
- `git diff api/main.py` — read the diff, confirm it's just deletions.
- `python3 -c "from api.main import app; print('ok')"` — must succeed.
- After rebuild + restart: `curl http://localhost:8000/health` returns 200.
- After rebuild + restart: `podman exec smart-ring-api grep "create_all\|DeclarativeBase" /app/main.py` returns nothing.

**Reversibility:** trivial. The deleted lines are 5 lines of no-op code. `git revert` restores them exactly.

### Step 2 — drop `_dedupe_sources` from `api/main.py` (analytics already owns dedup)

**Why second:** another zero-behavior-change cleanup. `analytics/dedupe.py:dedupe_sources()` runs at the start of every analytics pass. The API's `_dedupe_sources()` ran on every `/api/mobile/sync`. The API's copy is redundant.

**What to do:**
- Read `api/main.py` and find the `_dedupe_sources` function definition and its call site in `mobile_sync`.
- Delete the function definition.
- Delete the call site from `mobile_sync`.
- Confirm no references remain: `grep -n "_dedupe_sources" api/`.

**Verify:**
- `git diff api/main.py` — read the diff, confirm just deletions.
- After rebuild + restart: `curl -X POST http://localhost:8000/api/mobile/sync -H "Content-Type: application/json" -d '{"device_id":"x","records":{},"synced_at":"2026-01-01T00:00:00Z"}'` returns 200 with `{"accepted":0,"skipped":0,"errors":[]}`.
- The next analytics pass (after the next ring sync) will dedupe via `analytics/dedupe.py:dedupe_sources()`. Verify with `psql -c "SELECT source, COUNT(*) FROM raw_heart_rate GROUP BY source;"` after a sync.

**Reversibility:** trivial. `git revert` restores the function.

### Step 3 — extract raw SQL to `api/queries.py` (read-side cleanup) ❌ SKIPPED INDEFINITELY

**Why skipped:** pure relocation with no engineering payoff. The SQL strings would move from inline `text("""SELECT ...""")` to named constants in a new file — no behavior change, no deduplication benefit (queries aren't reused across endpoints), no bug fix, no perf win. You trade inline strings (greppable in their endpoint) for an import + a second file to jump between when editing.

The "matches `collector/` structure" argument is weak: `collector/protocol/db.py` exists because there are *shared* upsert helpers used by multiple parsers. The API has no such sharing; each endpoint owns its own SQL. Forcing a `queries.py` layer would be cargo-culting.

**Reversibility:** trivial. If a real shared-query need appears in the future (e.g., a CTE used by multiple endpoints), lift those queries then. Don't pre-emptively relocate.

### Step 4 — rewrite `/api/mobile/sync` with generic `upsert_many` (write-side dispatcher) ✅ COMPLETE

Commit: `0b14cae` on `dev` (+ docs `5110bcf`)

**New `api/upsert.py`:**
- `upsert_many(db, *, table, required_cols, records, optional_cols=None, source="phone") -> (accepted, skipped, errors)`
- Handles the 5 simple point tables (heart_rate, spo2, temperature, stress, steps) via a `simple_point_tables` dispatch loop in `mobile_sync`

**Tables kept inline (non-standard semantics):**
- `raw_hrv` — hrv_type defaults to 'composite'; conflict clause `(ts, hrv_type, source)`
- `raw_sleep` — day-based schema, conflict `(start_ts, stage, source)`
- `ring_goals` — singleton (not a list), no source column

**Verified:**
- All 16 `tests/test_mobile_sync.py` tests pass unchanged (Session A regression net)
- Full suite: 65 tests in 3.69s
- Image inspection after podman build: `upsert.py` shipped to `/app/`, import + dispatch loop present in main.py, no orphan inline INSERTs for the 5 simple tables, HRV/sleep/goals still inline as expected
- Smoke test: POST with all 5 dispatch types in one payload → `{"accepted":5,"skipped":0,"errors":[]}` HTTP 200, rows verified in DB
- Live data healthy: `raw_heart_rate` source ratio `ring=487 / phone=2` unchanged

**Net delta:** -30 lines (5 × ~12-line blocks → 1 × ~18-line dispatch loop).

**Import strategy:** `api/main.py` uses `from upsert import upsert_many` (script-style, matches container's `uvicorn main:app from /app`); `tests/conftest.py` inserts `api/` into sys.path so the same import resolves in test env.

**Quirk preserved:** per-attempt `accepted` counting (ON CONFLICT doesn't raise, so duplicate ts in one payload still counts both). Pinned by `test_mobile_sync_duplicate_ts_in_one_payload_counts_both_accepted`; may be fixed in separate PR using `cursor.rowcount`.

**Reversibility:** moderate. SQL is identical; the dispatch logic is more moving parts. `git revert` restores the explicit per-type blocks.

### What we are NOT doing in this plan

- No `time_sync_acked` column (that was Phase 6, reverted). Separate plan if needed.
- No `deploy/systemd/` directory. Separate housekeeping.
- No pytest suite. Step 4 verification is the manual testing for now.
- No dashboard rewrite. Out of scope.

### Operational protocol for the next session

These rules fix the failure mode that burned us this session. Non-negotiable.

1. **One step per session.** Not all four. Each step is independently shippable and reversible. If a step blows up, you've lost ~30 minutes max, not ~3 hours.
2. **You read the diff.** I show the diff, you read it, you confirm. I do not claim "verified" without showing the actual image contents.
3. **I do not run operational commands.** No `podman build`, no `podman restart`, no `systemctl`, no `podman exec grep`. I can read (`cat`, `grep`, `head`); I do not write or restart.
4. **You run the build + restart.** Sequence: `podman build --no-cache -t smart-ring-api:latest api/` (you run), `sudo systemctl restart smart-ring-api` (you run).
5. **Verification by image inspection, not by HTTP.** Show exactly what to check inside the container: `podman exec smart-ring-api grep "PATTERN" /app/main.py` and similar. If the image doesn't have the change baked in, the change isn't live — no matter what `curl` says.
6. **Don't push until you've seen the verification yourself.** `git push origin dev` only happens after you've read the image contents and confirmed the code is live.

### Estimated cost per step

- Step 1: ~10 minutes — 5 line deletions, one file, one rebuild, one verification.
- Step 2: ~15 minutes — one function deletion + one call site, one rebuild, one verification.
- Step 3: ~60 minutes — read every endpoint, lift SQL into `queries.py`, update each call site. Most reading, least editing.
- Step 4: ~45 minutes — read per-type INSERTs carefully, build dispatch correctly, verify phone-sync end-to-end.

Total across all four: ~2.5 hours, spread across 4 sessions (one per step).

---

## Tier 1 follow-up: pytest suite (separate from API cleanup)

**Why this exists separately from the API plan:** the API cleanup is best done without tests in flight (each step is small enough to verify manually, and the verification protocol above pins that down). Tests are best done *before* the codebase is touched again, so they pin down the current behavior as the regression net for all future work.

**Goal:** a `tests/` directory with smoke-level coverage of the modules most likely to silently break in a future refactor. Not exhaustive coverage — a regression net, not a test suite.

### What's in scope

1. **Parser tests** (`tests/test_parsers_temp.py`, `tests/test_parsers_sleep.py`): golden-byte parsing. Hand-craft a known-good ring response for sleep and temp, parse it, assert the records come out right.

2. **Time-sync BCD encoding test** (`tests/test_time_sync_bcd.py`): regression net for the sacred code. Construct a known `datetime`, run it through `set_time_local`'s BCD pipeline (extracted as a pure helper if needed), assert byte-for-byte match against Gadgetbridge's reference.

3. **Trap-score math** (`tests/test_trap_score.py`): boundary cases for the trapezoidal scoring function (4.0, 7.0, 9.0, 10.0 — each should be 0 or 100 at the edges, 100 in the middle, linear in between).

4. **`dedupe_sources` smoke test** (`tests/test_dedupe.py`): seed two `raw_heart_rate` rows at the same `ts` (one phone, one ring), call `dedupe_sources`, assert phone row is gone and ring row remains.

5. **`connect_with_retry` mock test**: stub `BleakClient`/`BleakScanner`, verify the wake-ping → forget+repair → connect → retry sequence fires in the right order on transient errors. (Skippable if it's too coupled to mocks; the manual verification protocol above is the fallback.)

### What's NOT in scope

- No coverage goals (no "80% lines" or similar). Tests that exist are tests that earn their keep.
- No CI workflow integration. Tests run locally via `pytest` from the venv. Add CI when the suite has enough value to justify the workflow file.
- No mocks of the database for the analytics scorers. The `_score_sleep_day` math is what matters, not the SQL — extract it to a pure helper first if needed, then test the helper.
- No mocking of the FastAPI app for the API tests. The API cleanup steps above are small enough that the manual verification protocol (you read the diff, you verify the image) is the test for now. Add `httpx.AsyncClient` tests if the API grows.

### File layout

```
tests/
  __init__.py
  conftest.py                  # small fixture set: temp DB, golden bytes
  test_parsers_temp.py
  test_parsers_sleep.py
  test_time_sync_bcd.py
  test_trap_score.py
  test_dedupe.py
pytest.ini                     # minimal config — no surprises
```

### Operational protocol (same rules as the API cleanup)

1. **One test file per session.** Same one-step-at-a-time discipline. ~30 minutes max per session.
2. **You read the diff.** I write the test, commit it locally. You read.
3. **You run the tests.** `venv/bin/python3 -m pytest tests/`. I do not run them. (If a test fails, that's the entire point — read the failure, decide what's broken.)
4. **Don't push until you've seen the tests pass yourself.**

### Estimated cost

- One parser test (temp or sleep): ~30 minutes including golden-byte fixture.
- Time-sync BCD test: ~30 minutes (extracting the helper may add 15 min).
- Trap-score: ~15 minutes.
- Dedupe smoke: ~30 minutes (DB setup is the slow part).
- Connect-mock or skip: ~30 min if done, 0 if skipped.

Total: ~2.5 hours, spread across 3–5 sessions. Same pace as the API cleanup.

### Recommended order

1. ~~**Trap-score first** (15 min, pure function, fastest win). Pin down the scoring math.~~ ✅ Done (commit `8e1e9d0`, 20 tests pass)
2. ~~**Time-sync BCD second** (30 min, regression net for the sacred code). This is the one that prevents "did my refactor break Gadgetbridge compatibility?" from being a question.~~ ✅ Done (refactor `4c12e06` + test `30cba4d`, 16 tests pass — `_encode_time_bcd` extracted as pure helper)
3. ~~**Dedupe smoke third** (30 min, real DB). Verifies the current dedup is correct before any more analytical work.~~ ✅ Done (commit `40903b0`, 13 tests pass — ephemeral DB fixture in conftest.py)
4. **Parser tests last** (30 min each, slowest because they need fixture data). Optional but high-value if/when the parsers get touched.

Skip Step 5 (connect mock) unless someone is going to refactor the connection flow soon. It's overhead without payoff.

### Sequencing vs the API cleanup

The recommendation in the response that drafted this section was: **pytest before any more API cleanup work.** Reason: pytest pins the current behavior, and Step 3 of the API cleanup (extracting raw SQL) is the riskiest of the four because "this endpoint returns the same JSON after the refactor" is hard to verify manually across all endpoints.

If you want to do API cleanup first instead: that's fine. The tests will catch any regressions the manual verification protocol misses. The sequencing is a recommendation, not a hard requirement.

### What this is NOT

This is not a test-driven-development project. It's not a CI setup. It's not a comprehensive coverage push. It's an immune system for the parts of the codebase most likely to silently break during future cleanup work. Build what's earnable, skip what isn't.

---
