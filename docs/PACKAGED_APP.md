# Packaged App — Standalone All-in-One

> **Status:** Design review (v2). **Phase 1 (dialect layer) in progress** in the main repo.
> Fork creation waits until after the dashboard React rewrite
> ([`DASHBOARD_REWRITE_PLAN.md`](./DASHBOARD_REWRITE_PLAN.md)) reaches Phase 10 cutover.
>
> **Last revised:** 2026-07-25 — corrected factual errors, added query-dialect risks, tz strategy,
> test-harness port, fork-hygiene plan, phased rollout, risk register, and sequencing.

## Sequencing

The packaged app is the **last** of three sequential work streams:

1. **Phase 1 — Dialect layer** (in progress): Replace Postgres-only query constructs
   (`NOW() - INTERVAL`, `REGR_SLOPE`, `PERCENTILE_CONT`) with dialect-neutral Python — same
   code runs on PG and SQLite. Happens in the main repo; all 132 tests stay green.
2. **Dashboard rewrite** — per [`DASHBOARD_REWRITE_PLAN.md`](./DASHBOARD_REWRITE_PLAN.md).
   Alpine.js monolith → React + TypeScript (8–10 days). At cutover, `dashboard/index.html` is
   deleted and replaced by `dashboard/dist/` build output.
3. **Fork** (this doc) — after the rewrite is settled. The gadget vendors `dashboard/dist/`
   (pre-built snapshot, no npm in the gadget repo) instead of `dashboard/index.html`.
   The fork's remaining phases are ~3–5 days once Phase 1 is complete.

> The vendoring strategy described in this doc assumes the **post-rewrite** dashboard state
> (React app, `dist/` snapshot). If work starts on the fork before the rewrite cutover, the
> gadget would temporarily vendor the Alpine `index.html` and re-vendor `dist/` later —
> a ~1–2 day rework.

## Motivation

The current architecture is server-oriented:

```
Linux HTPC (always-on, Tailscale)
├── Postgres 16 (Podman container)
├── FastAPI (Podman container)
├── Poller (bare metal, systemd, 30s loop)
└── Collector (bare metal, bluetoothctl, dispatched by poller)
    └── Dashboard (PWA, served by API)
```

This works well for a primary always-on setup but requires:
- A Linux box with Bluetooth running 24/7
- Docker/Podman for two containers
- Three systemd units (DB, API, poller — collector is a poller job, no unit)
- Network access (Tailscale) for remote dashboard

A standalone packaged app would be a **Gadgetbridge-style single-user tool**:
sync on demand, data lives in a local file, no server, no containers — a
**shareable gadget** any Colmi user can run on their own machine.
Mobile sync works via Web Bluetooth through the dashboard; no collector software,
no Linux, no network required.

## Proposed Architecture

```
smart-ring/
├── server.py            # FastAPI + SQLite + dashboard + analytics
├── smart-ring.db        # SQLite, created on first run
├── dashboard/           # vendored: React build output (dist/) + PWA assets
├── collector/           # vendored (analytics only; collector omitted)
└── pyproject.toml       # slim deps: no bleak/colmi_r02_client
```

> Post-rewrite, the gadget vendors the **built** `dashboard/dist/` snapshot (no npm in the
> gadget repo). `start.bat` / `start.command` / `start.desktop` launchers are replaced by
> `webbrowser.open()` in `server.py` — one cross-platform entry point.

### One process, no containers

```python
# server.py
app = FastAPI()
app.mount("/static", StaticFiles(directory="dashboard/dist"))
# analytics runs inline on /api/mobile/sync — no poller needed
# TZ sent by the browser in the sync POST (no /etc/timezone dependency)
```

### Sync model (Web Bluetooth only)

```
Chrome (any OS) → 📱 BLE button → ring → POST /api/mobile/sync → SQLite
                                                  ↓
                                          analytics.run_all() inline
                                                  ↓
                                          dashboard refreshes
```

No `sync_requests` table. No poller. Analytics runs synchronously in the API
handler — the request completes when scores are computed (~1–3 s, covered by the
dashboard's existing spinner UX).

### Platform support

| Platform          | Dashboard | Ring sync           | Notes |
|-------------------|-----------|---------------------|-------|
| Android Chrome    | ✅ PWA    | ✅ Web Bluetooth    | Primary target |
| Windows Chrome    | ✅        | ✅ Web Bluetooth    | |
| macOS Chrome      | ✅        | ✅ Web Bluetooth    | |
| Linux Chrome      | ✅        | ⚠️ flag required    | Web Bluetooth is partially implemented, not shipped; requires `chrome://flags/#enable-experimental-web-platform-features`. The optional cron collector path is the supported Linux route. |
| iOS Safari        | ✅ read   | ❌ (WebKit limitation) | |

## Implementation Plan (phased)

### Phase 0 — Schema mapping (DDL + column types)

One new file: `db/init_sqlite.sql`. The current Postgres schema uses nothing SQLite
can't handle at the DDL level:

| Postgres              | SQLite                                    | Count |
|-----------------------|-------------------------------------------|-------|
| `TIMESTAMPTZ`         | `TEXT` (UTC ISO 8601)                     | ~30   |
| `NUMERIC` / `NUMERIC(5,2)` | `REAL`                              | ~25   |
| `JSONB`               | `TEXT` + `json.loads/dumps`              | 3     |
| `TEXT[]` / `INT[]`    | `TEXT` (JSON array)                       | 2     |
| `BIGSERIAL`           | `INTEGER PRIMARY KEY AUTOINCREMENT`       | many  |
| `ON CONFLICT DO NOTHING` | `ON CONFLICT (...) DO NOTHING` (≥3.24) | both |
| `RETURNING`           | `RETURNING` (≥3.35, stdlib ≥3.12)         | both |
| `FOR UPDATE SKIP LOCKED` | Not needed (single-writer; poller removed) | 0 |
| Partial unique index  | Supported ✓                                | both |

> **Correction from v1:** JSONB columns are 3, not 2 (`hourly_steps`, `hourly_worn`,
> `contributors`). Array columns are 2, not 1 (`rr_intervals INT[]`,
> `missing_components TEXT[]`). `interactiveDEFAULT NOW()` in DDL → `DEFAULT (datetime('now'))`
> in SQLite (returns UTC text — acceptable since we store UTC everywhere; see Phase 1).

### Phase 1 — Query dialect layer (the real work)

The DDL mapping table is the easy part. The hard dialect work is in the **SQL strings**
scattered across `api/main.py` (~30 sites), the analytics package (~10 files), and
`collector/protocol/db.py`. The Postgres constructs that have no direct SQLite equivalent:

| Construct | Sites | Approach |
|-----------|-------|----------|
| `NOW() - INTERVAL ':days days'` / `CURRENT_DATE - INTERVAL ...` | ~25 | **Compute cutoff in Python**, pass as bind param (`WHERE ts >= :cutoff`). Dialect-neutral — works on both PG and SQLite unchanged. |
| `REGR_SLOPE(hrv_value, EXTRACT(EPOCH FROM ts)/3600)` | 1 (`current_status.py:165`) | Pull (ts, hrv_value) rows, compute with `statistics.linear_regression` in Python. Pure helper, unit-testable. |
| `PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY hr_min)` | 1 (`current_status.py:193`) | Pull hr_min rows, compute with `statistics.median` in Python. Pure helper, unit-testable. |
| `ts AT TIME ZONE :tz`, `::date`, `ROUND(...)::int` | ~10 | Move day-bucketing to Python (see tz strategy below). |
| `SET TIME ZONE` per connection | 1 (`analytics/db.py:34`) | **Remove entirely** — tz handled at data layer, not session state. |
| `EXTRACT(EPOCH FROM ts)` | 3 | `datetime.fromisoformat(ts).timestamp()` in Python. |

> None of these changes make the code PG-incompatible. The same SQL/helpers will
> run on both engines — see "Fork hygiene" below.

#### Timezone strategy (the deepest change)

The current server relies on PG's session TZ (`SET TIME ZONE` per connection) so
`DATE(ts)` / `EXTRACT(HOUR FROM ts)` evaluate in local time. SQLite has neither
tz-aware types nor session TZ. Plan:

1. **Store all timestamps as UTC ISO-8601 text** (`2026-07-25T14:30:00+00:00` or `...Z`).
   Lexicographically sortable, comparable, unambiguous.
2. **Do local-day bucketing in Python** with `zoneinfo`.
3. **Gadget gets the TZ from the browser**, not `/etc/timezone`: the mobile-sync POST
   already carries per-record timestamps; add a `timezone` field (`"America/Vancouver"`)
   from `Intl.DateTimeFormat().resolvedOptions().timeZone`. This is actually *more correct*
   than the current server — the wearer's local TZ is what matters for day boundaries,
   not whatever timezone the HTPC happens to be set to.

#### Dedup: scoped claim, not moot

In the current architecture, `dedupe_sources()` (`collector/analytics/dedupe.py`)
removes phone records that duplicate ring-collector records at the same timestamp.
In the packaged app:
- **Web-Bluetooth-only configuration:** single source, dedup is a no-op (and harmless to run).
- **If the optional Linux cron collector is also used against the same SQLite file:** dedup is still needed. The gadget should keep `dedupe_sources()` in the analytics run — it's idempotent and costs nothing.

### Phase 2 — Packaged server + test harness port

#### New files
- `server.py` — FastAPI + SQLAlchemy (`sqlite:///smart-ring.db`, WAL, `busy_timeout`), mounts dashboard, opens browser, inlines `analytics.run_all()` in mobile sync. Auth endpoints simplified (no poller → the sync-request endpoints return 501 or are absent; the Health Check endpoint returns bare-minimum).
- `db/init_sqlite.sql` — Phase 0 schema, to be executed on first run.

#### Modified (vendored) files
- **Dashboard** — near-zero change. All ~40 `fetch()` calls are relative paths and work unchanged. The Admin tab's sync-queue UI (`/api/admin/sync`, cancel, sync-requests list) is meaningless in packaged mode and should be **feature-flagged** (show/hide based on API health check response or a query param). Everything else (vitals, readiness, current-status, data-quality, raw endpoints, ring-status) is identical.
- **Analytics** — Phase 1 query rewrites (postgres-compatible, upstreamable).
- **API** — Phase 1 query rewrites, mobile_sync inline-analytics block, `sync_requests` table removed from schema (all related endpoints drop or return 501).

#### Test harness
Current harness (`tests/conftest.py`) creates ephemeral Postgres databases — the
entire DB-backed test surface (51 functions) runs on PG only. A new SQLite conftest
is **simpler** (temp file + `executescript(init_sqlite.sql)` — no admin connection,
no `pg_terminate_backend` teardown) and makes the full 132-test suite self-contained
(run anywhere, no dev Postgres dependency).

> **Correction from v1:** "132-test suite gives a solid safety net for the migration"
> was circular — the safety net itself must be ported first. Phase 2 porting the harness
> to SQLite is what *makes* it the safety net. Pure-function tests (BCD, trap score —
> 13 functions) are the only ones that carry over without harness work.

### Phase 3 — Gadget packaging

| Priority | Item | Notes |
|----------|------|-------|
| **Now** | Plain `python server.py` | Dev mode, works on all platforms. No PyInstaller yet. |
| **Later** | PyInstaller one-file builds | StaticFiles as PyInstaller data files. Per-OS binaries. Note unsigned-binary friction: SmartScreen (Windows) and Gatekeeper (macOS) will flag the build — document the bypass for sharees. |
| **Omit** | `bleak` / `colmi_r02_client` | The gadget is Web-Bluetooth-only. These git-deps are hostile to distribution and the collector they serve is Linux-only. Keep them in the main repo only. |
| **Omit** | `start.bat` / `start.command` | `webbrowser.open()` at FastAPI startup replaces all per-OS launchers with one cross-platform entry. |

#### First-run experience
1. User runs `python server.py` (or double-clicks the PyInstaller binary).
2. `server.py` creates `smart-ring.db` from `init_sqlite.sql` (if missing).
3. Opens browser to `http://localhost:8000`.
4. User opens the dashboard, connects ring via Web Bluetooth, syncs.
5. Analytics runs inline; scores appear in the dashboard.

### Phase 4 — Fork hygiene (minimizing dual-maintenance cost)

The packaged app is a **fork**, but all Phase-1 SQL changes are **Postgres-compatible**.
They can be upstreamed to the main repo. The goal:

```
main repo (HTPC, Postgres)          packaged app (gadget, SQLite)
┌─────────────────────────┐         ┌─────────────────────────┐
│ dashboard/dist/ (build)  │ =====≫ │ dashboard/dist/ (snapshot)│ (periodic copy)
│ collector/analytics/*   │ =====≫ │ collector/analytics/*   │ (identical)
│ api/upsert.py           │ =====≫ │ (inline in server.py)    │ (same query logic)
│ db/init.sql             │ ---    │ db/init_sqlite.sql       │ (schema fork, necessary)
│ tests/conftest.py       │ ---    │ tests/conftest_sqlite.py │ (harness fork, necessary)
│ server.py (new)         │ ---    │ server.py                │ (gadget-only)
└─────────────────────────┘         └─────────────────────────┘
```

Files vendored **identically** (dashboard `dist/` snapshot, analytics, upsert logic) can be
periodically re-synced from the main repo. Files that must diverge are limited to
the schema script, test harness, and the gadget entry point. The annual cost of the
fork is a snapshot-copy of the build output + diff-and-copy of ~3 source files, not
a manual re-port.

## What stays unchanged

- **Dashboard** — post-rewrite React app, vendored as `dashboard/dist/` build
  snapshot (no npm in the gadget repo). All ~40 `fetch()` calls are relative paths;
  the Web Bluetooth "📱 BLE" button works cross-platform. The Admin tab is gated by
  a conditional render driven by the `/health` response `mode` field.
- **Web Bluetooth phone sync** — `POST /api/mobile/sync` payload shape unchanged.
  Browser handles BLE, Python handles storage. Transparent to the JS. Add a
  `timezone` field to the POST body (optional — chrome sends IANA tz name).
- **Analytics scoring formulas** — `collector/analytics/` package. Same logic,
  called inline instead of via poller. Two PG-only aggregates move into Python
  pure helpers (`statistics.linear_regression`, `statistics.median`) — matching
  the project's existing pattern of pure testable helpers pinned by the test suite.
- **Linux collector** — `collector/sync_ring.py` is NOT vendored into the gadget
  (adds bleak + colmi_r02_client deps that harm portability). It remains in the
  main repo for the HTPC setup. A Linux user who wants scheduled cron syncs with
  the gadget can opt into the full collector deps separately.

## Export Options

Since the packaged app owns its data file, export is a natural feature:

- **CSV per data type** — raw HR, HRV, sleep, steps, SpO2, temp, stress
- **Full JSON bundle** — everything, portable between instances
- **Health summary PDF** — daily/weekly reports
- **SQLite file itself** — portable single-file database; copy between machines
- **Health Connect** (Android only) — write steps, HR, HRV, sleep, SpO2, temp to
  Android Health Connect. Gadgetbridge already supports Colmi R02/R03/R06 (same
  protocol family as the R09 this project cross-references) and has a Health Connect
  export PR in progress — likely solved upstream before this feature ships. Defer;
  don't build a Kotlin companion app.

## Relationship to Existing Server Setup

The packaged app is an **additional client**, not a replacement. It runs
independently with its own SQLite file:

```
Current setup (unchanged)          Packaged app (standalone)
┌──────────────────────┐           ┌──────────────────────┐
│ HTPC (Linux)         │           │ Laptop / desktop     │
│ Postgres + API       │           │ SQLite + API         │
│ Poller + Collector   │           │ Web Bluetooth only   │
│ ~2+ years history    │           │ Own SQLite file      │
└──────────────────────┘           └──────────────────────┘
```

No shared state, no conflicts, no coordination. Same ring, different
databases. Merge/compare between them is a future nice-to-have.

## Risk Register

| Risk | Likelihood | Mitigation |
|------|-----------|------------|
| TZ day-boundary drift | Medium | Unit tests around DST transitions + explicit UTC-isochronous storage. Browser sends IANA tz, Python `zoneinfo` does the bucketing — no silent OS-tz dependency. |
| REGR / median parity mismatch | Low | Pin Phase 1 helpers against PG output on real data before switching. Both are standard statistical operations; parity expected within float tolerance. |
| Linux Web Bluetooth flakiness | Medium | Document the flag requirement. The cron collector path is a stable fallback for Linux gadget users. |
| Concurrent-write contention (WAL) | Low | Single-user, single-browser sync + inline analytics — writes are serialized per request. If the optional cron collector also writes, `busy_timeout=5000` handles brief lock contention. |
| PyInstaller AV false positives | Medium (Windows) | Note in the README/add to the FAQ. Not fixable without EV code signing (not justified for this project). |
| Fork rot (main repo diverges) | Medium | Dialect-neutral SQL upstreamed so vendored files diverge minimally. Re-vending is a diff of ~5 files. |

## Not in Scope

- **Multi-user / multi-ring** — single-user, single-ring tool
- **iOS native sync** — Apple blocks Web Bluetooth, not fixable
- **Gadgetbridge replacement** — Gadgetbridge handles more device types;
  this is Colmi R09 focused. The gadget's differentiator is the analytics
  (Morning Readiness + Current Status) and the dashboard; GB covers raw sync.
- **Cloud sync** — intentionally local-first; export covers portability
- **Background sync on desktop** — browser tab must stay open during sync
  (~5 min for full history)
- **Health Connect companion** — deferred; watch Gadgetbridge upstream

## Open Questions

- **PyInstaller or plain Python?** **Phased.** Plain `python server.py` first
  (dev + technical users). PyInstaller one-file builds later if non-technical
  sharees actually appear — this is a small project and paying the unsigned-binary
  tax prematurely isn't worth it.
- **Auto-open browser?** Solved — `webbrowser.open()` in `server.py` startup. One
  cross-platform entry point replaces all per-OS launcher scripts.
- **Dashboard feature flag mechanism.** Simplest approach: the API `/health` response
  includes `{"mode": "packaged"|"server"}`; the dashboard JS reads it once and
  hides/shows the Admin tab accordingly. Alternatively, serve a slightly different
  `index.html` (the gadget already venders dashboard — one `display:none` on the
  admin section is trivial).

---

## Effort Summary

| Phase | What | Days |
|-------|------|------|
| 0 | `init_sqlite.sql` + DDL mapping | 0.5 |
| 1 | Query dialect layer (cutoffs, aggregates, tz) | 2–3 |
| 2 | `server.py` + dashboard gate + test harness port | 1.5–2 |
| 3 | PyInstaller builds (deferred) | 0.5–1 |
| 4 | Fork hygiene (upstream PG-compatible SQL, vendored-file sync) | 0.5 |
| **Total** | | **5–8 days** |

> Estimate is for one developer familiar with the codebase. Critical path is Phase 1:
> the tz model (UTC storage + Python bucketing) and analyst aggregate parity must be
> verified against real production data before proceeding.
