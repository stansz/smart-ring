# Packaged App — Standalone All-in-One

> **Status:** Design review. No implementation committed. This doc captures what a
> standalone, container-free packaged version of smart-ring would look like and
> the tradeoffs vs the current server-oriented architecture.

## Motivation

The current architecture is server-oriented:

```
Linux HTPC (always-on, Tailscale)
├── Postgres 16 (Podman container)
├── FastAPI (Podman container)
├── Poller (bare metal, systemd, 30s loop)
└── Collector (bare metal, bluetoothctl, cron/manual)
    └── Dashboard (PWA, served by API)
```

This works well for a primary always-on setup but requires:
- A Linux box with Bluetooth running 24/7
- Docker/Podman for two containers
- Four systemd units (DB, API, poller, collector)
- Network access (Tailscale) for remote dashboard

A standalone packaged app would be a **Gadgetbridge-style single-user tool**:
sync on demand, data lives in a local file, no server, no containers.
Useful as a travel companion or secondary client alongside the existing rig.

## Proposed Architecture

```
smart-ring/
├── server.py           # FastAPI + SQLite + dashboard + analytics
├── smart-ring.db       # SQLite, created on first run
├── dashboard/          # unchanged (single HTML file + PWA assets)
├── collector/          # unchanged, optional (Linux-only cron syncs)
├── start.bat           # Windows: open server + browser
├── start.command       # macOS: same
└── start.desktop       # Linux: same
```

### One process, no containers

```python
# server.py
app = FastAPI()
app.mount("/static", StaticFiles(directory="dashboard"))
db = sqlite3.connect("smart-ring.db")
# analytics runs inline on /api/mobile/sync — no poller needed
# optional: background thread for Linux cron syncs
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
handler — the request completes when scores are computed.

### Platform support

| Platform          | Dashboard | Ring sync              |
|-------------------|-----------|------------------------|
| Android Chrome    | ✅ PWA    | ✅ Web Bluetooth       |
| Windows Chrome    | ✅        | ✅ Web Bluetooth       |
| macOS Chrome      | ✅        | ✅ Web Bluetooth       |
| Linux Chrome      | ✅        | ✅ Web BT + cron opt.  |
| iOS Safari        | ✅ read   | ❌ (WebKit limitation) |

### What goes away

| Component          | Current                 | Packaged                |
|--------------------|-------------------------|-------------------------|
| Database           | Postgres 16 (container) | SQLite (file)           |
| API                | Podman container        | In-process FastAPI      |
| Poller             | systemd, 30s loop       | Removed (inline)        |
| Collector          | systemd, bluetoothctl   | Optional, Linux-only    |
| sync_requests      | Job queue + claims      | Removed                 |
| Source dedup       | ring vs phone conflict  | Moot (single source)    |
| Multi-device write | Multiple collectors     | Single browser instance |

## SQLite Migration

The current Postgres schema uses nothing SQLite can't handle. Mapping:

| Postgres              | SQLite                                  |
|-----------------------|-----------------------------------------|
| `TIMESTAMPTZ`         | `TEXT` (ISO 8601, parse in Python)      |
| `JSONB` (2 cols)      | `TEXT` + `json.loads/dumps`            |
| `TEXT[]` (1 col)      | `TEXT` (JSON array)                     |
| `NUMERIC(5,2)`        | `REAL`                                  |
| `BIGSERIAL`           | `INTEGER PRIMARY KEY AUTOINCREMENT`     |
| `ON CONFLICT DO NOTHING` | `INSERT OR IGNORE`                   |
| `NOW() - INTERVAL`    | `datetime('now', '-N days')`            |
| `FOR UPDATE SKIP LOCKED` | Not needed (single-writer)            |
| Partial unique index  | Supported ✓                             |

**Estimated effort:** 3-5 days. ~30 files to touch. 132-test suite
gives a solid safety net for the migration.

**Risk:** SQLite is single-writer. For one user on one machine this is
ideal — WAL mode lets reads (dashboard queries) proceed concurrently
with writes (sync inserts). If multi-machine database sharing is ever
needed, migrate back to Postgres.

## What stays unchanged

- **Dashboard HTML/CSS/JS** — single file, zero changes. The Web Bluetooth
  "📱 BLE" button already works cross-platform.
- **Web Bluetooth phone sync** — `POST /api/mobile/sync` unchanged.
  Browser handles BLE, Python handles storage. Transparent to the JS.
- **Analytics** — `collector/analytics/` package. Same scoring formulas,
  just called inline instead of via poller. All 132 tests still pass.
- **Linux collector** — `collector/sync_ring.py` stays as-is for users
  who want scheduled cron syncs on a Linux box. Optional, not required.

## Export Options

Since the packaged app owns its data file, export is a natural feature:

- **CSV per data type** — raw HR, HRV, sleep, steps, SpO2, temp, stress
- **Full JSON bundle** — everything, portable between instances
- **Health summary PDF** — daily/weekly reports
- **Health Connect** (Android only) — write steps, HR, HRV, sleep, SpO2,
  temp to Android Health Connect. Requires a thin native Android companion
  (Kotlin SDK, no web API). Stress has no standard HC record type.

## Relationship to Existing Server Setup

The packaged app is an **additional client**, not a replacement. It runs
independently with its own SQLite file:

```
Current setup (unchanged)          Packaged app (standalone)
┌──────────────────────┐           ┌──────────────────────┐
│ HTPC (Linux)         │           │ Laptop / phone       │
│ Postgres + API       │           │ SQLite + API         │
│ Poller + Collector   │           │ Web Bluetooth only   │
│ ~2+ years history    │           │ Travel / secondary   │
└──────────────────────┘           └──────────────────────┘
```

No shared state, no conflicts, no coordination. Same ring, different
databases. Merge/compare between them is a future nice-to-have.

## Not in Scope

- **Multi-user / multi-ring** — single-user, single-ring tool
- **iOS native sync** — Apple blocks Web Bluetooth, not fixable
- **Gadgetbridge replacement** — Gadgetbridge handles more device types;
  this is Colmi R09 focused
- **Cloud sync** — intentionally local-first; export covers portability
- **Background sync on desktop** — browser tab must stay open during sync
  (~5 min for full history)

## Open Questions

- **PyInstaller or plain Python?** Single binary is cleaner for non-technical
  users; plain `python server.py` is simpler for devs. Both work.
- **Health Connect companion scope.** Could be a minimal WebView wrapper
  around the PWA + HC write bridge, or a standalone Android app.
- **Auto-open browser?** `start.bat` / `start.command` launchers are
  trivial. Could also ship as a `.desktop` entry on Linux.
