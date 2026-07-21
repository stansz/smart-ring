# Smart Ring 💍

Open-source health data pipeline built around the **Colmi R09** — a $45 CAD hackable smart ring with the same form factor as a $530 Oura ring, zero BLE authentication, and full protocol documentation.

## Goal

Build a private, self-hosted health tracking system that:

- **Collects** biometric data from the ring via BLE (HR, HRV, SpO2, skin temperature, stress, sleep stages, steps)
- **Stores** everything in Postgres — raw sensor data + computed metrics
- **Computes** validated health scores: sleep quality (5-component), recovery (HRV z-score), stress classification
- **Visualizes** in a dashboard — local-first, dark mode, accessible via Tailscale
- **Stays hackable** — no subscriptions, no vendor lock-in, no cloud dependency

## Hardware

| Component | Detail |
|-----------|--------|
| **Ring** | Colmi R09 (~$45 CAD) — BlueX RF03 SoC, accelerometer + PPG + SpO2 + skin temperature |
| **BLE** | Standard Nordic UART Service, zero auth. Fully open protocol at [colmi.puxtril.com](https://colmi.puxtril.com/commands/) |
| **CFW** | [atc1441/ATC_RF03_Ring](https://github.com/atc1441/ATC_RF03_Ring) — custom firmware via web OTA flasher |

## Key Tools

- [tahnok/colmi_r02_client](https://github.com/tahnok/colmi_r02_client) — Python BLE client + protocol docs
- [atc1441/ATC_RF03_Ring](https://github.com/atc1441/ATC_RF03_Ring) — Custom firmware + SDK
- [Gadgetbridge](https://codeberg.org/Freeyourgadget/Gadgetbridge) — Open-source Android client

## Deployment

**Local-first, fully wired up.** All services run on the Linux box — rootless Podman containers for Postgres + FastAPI, bare-metal Python venv for the BLE collector (it needs direct BlueZ/DBus access).

```
Home Network
└─ Linux Mint Box (AMD 3800x, 64GB RAM, BT enabled)
   ├─ smart-ring-db.service      (rootless Podman quadlet, Postgres 16)
   │   └─ port localhost:5432, volume smart-ring-pgdata, health check
   ├─ smart-ring-api.service     (rootless Podman quadlet, FastAPI)
   │   ├─ Requires=smart-ring-db.service
   │   └─ port localhost:8000, serves dashboard
   ├─ smart-ring-poller.service  (bare metal, system systemd)
   │   └─ 30s poll of sync_requests → runs sync_ring.py + analytics
   └─ Manual collector commands also available
       └─ python -m collector.sync_ring --forget  (force-sync outside the poller)
```

Dashboard: single-page Alpine.js + Tailwind CSS app with three tabs — **Dashboard** (unified hero panel: 24h activity ring with wear/sleep/step radial bars + Readiness Score 0–100 with sub-scores + contributors; sleep donut; circadian HR line graph; vitals chart with HR + SpO₂ + Temp triple-axis; dark mode toggle), **Analytics** (data pipeline reference table, score breakdown cards with formula explanations, trend charts for HRV/sleep/stress/resting-HR with 7d/14d/30d/90d range selector), and **Admin** (ring status, manual sync controls, full sync log, system health, raw data tables). No build step.

## Usage

```bash
# One-time setup (already done for this ring)
#   - venv created, deps installed (pip install -e .)
#   - ring paired via bluetoothctl (address: <ring_ble_address>)
#   - Gadgetbridge installed on phone (Android)

# Pair the ring (one-time, via bluetoothctl — already done)
bluetoothctl scan on
bluetoothctl pair <ring_address>      # wait for "Pairing successful"
bluetoothctl disconnect <ring_address>

# Daily operations
venv/bin/python3 -m collector.first_contact     # read-only diagnostic (battery, fw, clock)
venv/bin/python3 -m collector.sync_ring --forget  # full sync to Postgres (forget+repair is default)
# Or use the dashboard: click "Sync Now" in the Admin tab
#   (the poller watches sync_requests every 30s — no manual cron)

# Run the regression net before any refactor
venv/bin/python3 -m pytest tests/               # 65 tests, ~4s
```

## Documentation

Detailed docs live in **[`docs/`](docs/)**:

- **[`docs/RING_BEHAVIOR.md`](docs/RING_BEHAVIOR.md)** — empirical Colmi R09 behavior: connection quirks, per-data-type reference (interval / buffer / publish cadence / format), V2 big-data protocol, background-logger stall, time-sync.
- **[`docs/RESEARCH.md`](docs/RESEARCH.md)** — hardware specs, validated score formulas (with peer-reviewed citations), readiness score gap analysis (Oura vs WHOOP vs Garmin), value-add analysis, Oura comparison.
- **[`docs/ROADMAP.md`](docs/ROADMAP.md)** — mobile sync design (WebBluetooth PWA + Gadgetbridge fork options).
- **[`docs/CLEANUP_PLAN.md`](docs/CLEANUP_PLAN.md)** — refactor history (collector/analytics Phases 0–4 + API cleanup Steps 1, 2, 4 + Tier 1 test suite). All complete.
- **[`docs/DASHBOARD_REWRITE_PLAN.md`](docs/DASHBOARD_REWRITE_PLAN.md)** — future dashboard modernization (not started).
- **[`AGENTS.md`](AGENTS.md)** — operational/deployment context (architecture, service commands, current state, work log).
- **[`TASKS.md`](TASKS.md)** — phase history, open backlog, CFW ideas, readiness improvements.

## Development

This project was built with use of AI/Vibe coding tools, primarily OpenCode as harness and various open weight models.

### Test suite

65 tests across 4 files, ~4s total runtime:

```bash
venv/bin/python3 -m pytest tests/                # full suite
venv/bin/python3 -m pytest tests/test_trap_score.py -v  # one file
```

| File | Tests | What it covers |
|------|-------|----------------|
| `tests/test_trap_score.py` | 20 | Trapezoidal scoring math — boundaries, ramp linearity, symmetry |
| `tests/test_time_sync_bcd.py` | 16 | Sacred BCD encoding — byte-for-byte vs Gadgetbridge's `setDateTime` |
| `tests/test_dedupe.py` | 13 | Source dedup contract — phone vs ring overlap (ephemeral PostgreSQL) |
| `tests/test_mobile_sync.py` | 16 | `/api/mobile/sync` end-to-end via FastAPI TestClient |

DB-backed tests use an ephemeral `smart_ring_test_<pid>` database created from `db/init.sql` — never touches production data. See `docs/CLEANUP_PLAN.md` "Tier 1 follow-up" for the design.    

## Status

🟢 **Working end-to-end. All 8 data types collecting + all health scores computing.**

R09 ring paired and validated (FW `RT09_3.10.21_251107`, HW `RT09_V3.1`). Sync pulls all data types to Postgres, analytics engine computes validated health scores, dashboard operational with dark mode. Sync behavior confirmed read-only (safe to sync from multiple devices). Remote access via Tailscale.

### Data collection (all protocols aligned with Gadgetbridge)
- ✅ Heart rate (cmd 0x15) — 5-min intervals, multi-packet per day
- ✅ Steps/activity (cmd 0x43) — 15-min slots with calories + distance
- ✅ HRV (cmd 0x39) — composite ms values at 30-min intervals (3-day buffer)
- ✅ Sleep stages (cmd 0xBC + type 0x27) — per-session deep/REM/light/awake with timestamps
- ✅ SpO2 (cmd 0xBC + type 0x2A) — hourly blood oxygen %
- ✅ Temperature (cmd 0xBC + types 0x23-0x2B, skip 0x2A) — skin temp at 30-min intervals, ~8-day history (R09 exclusive)
- ✅ Stress (cmd 0x37) — 30-min interval readings (0-99 scale)
- ✅ Ring goals (cmd 0x21) — steps/calorie/distance targets

### Health scores (server-side, persisted after each sync)
- ✅ **Readiness Score** — Unified 0-100 WHOOP-style 3-pillar composite (HRV 44% / Sleep 37% / RHR 19%). Per-day with contributors and sub-scores via `/api/readiness`.
- ✅ **Sleep quality** — 5-component score (0-100): duration, efficiency, architecture, continuity, latency. Trapezoidal scoring with Ohayon 2004 norms.
- ✅ **Recovery** — ln(HRV) z-score vs 7-day baseline (Altini/Plews framework), readiness text, confidence flags
- ✅ **Stress** — Garmin/Firstbeat thresholds + weighted daily score (daytime + peak sustained + overnight)
- ✅ **Circadian HR** — HR mapped to hour-of-day across all days
- ✅ **Resting HR** — overnight lowest HR (1-5 AM window)
- ✅ **HRV trends** — 7-day and 28-day rolling averages

### Dashboard
- **Dashboard tab**: Unified hero panel (24h activity ring with radial step bars + sleep overlay + tap tooltips along-side Readiness Score 0-100 ring with 4 sub-score cards + contributors), Vitals chart (HR line + SpO₂ dots + Temp dots triple-axis SVG with hover tooltips + smooth Catmull-Rom curves), sleep donut ring (empty state when no data), circadian HR SVG line graph, recovery panel, dark mode toggle
- **Analytics tab**: Data pipeline reference (ring-measured vs ring-computed vs our-validated-score), score breakdown cards with expandable formula explanations, 4 trend charts (HRV recovery, sleep quality, stress, resting HR) with 7d/14d/30d/90d range selector + hover crosshair tooltips
- **Admin tab**: Sync Now, ring status, full sync log, system health, raw data tables
- **Phone sync**: Web Bluetooth ("📱 BLE" button) — syncs ring from Android Chrome, posts to `/api/mobile/sync`, dedup on insert (ring canonical, phone fills gaps)

### How it works
```
Ring → BLE sync (on-demand) → Postgres raw tables → `python -m collector.analytics` → computed score tables
                                    ↑                                          ↓
                               FastAPI API ←←←←←←←←←←←←←←←←←←←←←←←←← Dashboard
```

The poller watches for sync requests every 30s, runs the collector, then runs `python -m collector.analytics` to recompute all scores. Fully automated after clicking "Sync Now".

## Attributions & Licensing

### License

This project is released under the [MIT License](LICENSE) — see `LICENSE` for details.

### Protocol & Hardware References

This project would not exist without the open work of the Colmi R09 reverse-engineering community:

| Project | Purpose |
|---------|---------|
| **[tahnok/colmi_r02_client](https://github.com/tahnok/colmi_r02_client)** | Python BLE client library, CLI tools, and foundational BLE protocol documentation. Used as the direct data-extraction layer for all 8 data types. |
| **[atc1441/ATC_RF03_Ring](https://github.com/atc1441/ATC_RF03_Ring)** | Custom firmware + SDK for the BlueX RF03 SoC. Cracked the platform open and provided the web-based OTA flasher. |
| **[Gadgetbridge](https://codeberg.org/Freeyourgadget/Gadgetbridge)** | Open-source Android client. Primary protocol reference for R09 command set, V2 big-data characteristic, and HR/HRV/SpO2 parsers. All our collector commands are cross-validated against Gadgetbridge source. |
| **[colmi.puxtril.com](https://colmi.puxtril.com/commands/)** | Community BLE protocol documentation site. Command reference for Nordic UART service and V2 big-data service. |

### Software Libraries & Frameworks

| Library / Tool | Role |
|----------------|------|
| **[bleak](https://github.com/hbldh/bleak)** | Cross-platform BLE client (async). Used for all ring communication. |
| **[FastAPI](https://fastapi.tiangolo.com/)** | Web API framework (container). Serves all JSON endpoints and the dashboard. |
| **[uvicorn](https://www.uvicorn.org/)** | ASGI server for FastAPI. |
| **[SQLAlchemy](https://www.sqlalchemy.org/)** | Python SQL toolkit and ORM. |
| **[psycopg2](https://www.psycopg.org/)** | PostgreSQL adapter for Python. |
| **[PostgreSQL 16](https://www.postgresql.org/)** | Primary data store — raw sensor tables + computed health scores. |
| **[Alpine.js](https://alpinejs.dev/)** | Lightweight JS framework for the dashboard UI (3 tabs, reactive charts, Web Bluetooth sync). |
| **[Tailwind CSS](https://tailwindcss.com/)** | Utility-first CSS framework. Dashboard uses CDN build (no build step). |
| **[Python asyncio](https://docs.python.org/3/library/asyncio.html)** | Async I/O for BLE collector (stdlib). |
| **[Podman](https://podman.io/)** | Rootless container engine for DB + API services. |
| **[systemd](https://systemd.io/)** | User services for poller + container quadlets. |

### Scientific & Research References

Health score formulas are grounded in peer-reviewed research:

| Source | Contribution |
|--------|-------------|
| **Ohayon 2004** — *Sleep Medicine* meta-analysis (65 studies, 3,577 subjects) | Sleep architecture norms (deep 13–23%, REM 20–25%), efficiency thresholds, sleep quality 5-component scoring. |
| **Altini 2021** — *Sensors* (9M measurements, 28,175 users) | HRV longitudinal monitoring, z-score recovery framework, ln-transform normalization. |
| **Plews et al. 2013** — *Sports Medicine* | HRV training adaptation in elite athletes. Basis for 7-day rolling baseline methodology. |
| **Garmin/Firstbeat** | Stress classification thresholds (0–99 scale → Relaxed/Low/Medium/High). Daily weighted score methodology. |
| **Shen et al. 2025** — *Frontiers in Physiology* | Circadian rhythm removal improves stress classification accuracy by 13.67%. |
| **Doherty & Altini 2025** | Comparative study of wearable readiness scores (Oura, WHOOP, Garmin, Fitbit). Validates that wearable readiness scores estimate recovery, not measure it. |
| **Dial et al. 2025** | Multi-wearable study (536 nights) showing Oura's nocturnal RHR accuracy vs ECG. |

### Deployment & Infrastructure

| Tool | Role |
|------|------|
| **[Tailscale](https://tailscale.com/)** | Secure remote access to dashboard without cloud dependency. |

### No Affiliation

This project is **not affiliated with, endorsed by, or connected to** Colmi, ATC, or any commercial ring manufacturer. It is an independent, community-built health tracking pipeline.

### Health Disclaimer

The health scores computed by this project are for informational purposes only. They are not medical devices, not FDA/Health Canada approved, and not a substitute for professional medical advice, diagnosis, or treatment. Always seek the advice of a physician or qualified health provider with any questions about a medical condition.
