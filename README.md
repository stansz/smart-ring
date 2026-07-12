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
   └─ Manual collector           (bare metal Python venv — needs BlueZ/DBus for BLE)
       └─ python3 collector/sync_ring.py  (run manually, no cron)
```

Dashboard: single-page Alpine.js + Tailwind CSS app with three tabs — **Dashboard** (sleep donut, circadian HR line graph, vitals chart with HR + SpO₂ + Temp triple-axis, activity dials, health-coded stat cards with emoji icons, dark mode toggle), **Analytics** (data pipeline reference table, score breakdown cards with formula explanations, trend charts for HRV/sleep/stress/resting-HR with 7d/14d/30d/90d range selector), and **Admin** (ring status, manual sync controls, full sync log with clock drift tracking, clock alert banner, system health, raw data tables). No build step.

## Usage

```bash
# One-time setup (already done for this ring)
#   - venv created, deps installed
#   - ring paired via bluetoothctl (address: <ring_ble_address>)
#   - Gadgetbridge installed on phone (Android)

# Pair the ring (one-time, via bluetoothctl — already done)
bluetoothctl scan on
bluetoothctl pair <ring_address>      # wait for "Pairing successful"
bluetoothctl disconnect <ring_address>

# Daily operations
python3 collector/first_contact.py     # read-only diagnostic (battery, fw, clock)
python3 collector/sync_ring.py --forget  # full sync to Postgres (with R09 reconnect workaround)
# Or use the dashboard: click "Sync Now" in the Admin tab
```

## Research

All technical research, architecture, validated score formulas, and deployment details live in **[RESEARCH.md](RESEARCH.md)**.

Topics covered:
- Hardware specs & model comparison (R02 → R12)
- BLE protocol (Nordic UART + V2 big-data characteristic)
- Data availability (stored vs realtime) — all 8 data types documented
- **Validated score formulas** with peer-reviewed citations:
  - Sleep quality (5-component, Ohayon 2004 architecture norms, Oura reverse-engineering)
  - HRV recovery (Altini/Plews z-score framework, ln-transform, 7-day baseline)
  - Stress classification (Garmin/Firstbeat thresholds, circadian awareness)
- BLE quirks & reconnect bug (R09 firmware 3.10.21)
- Deployment topology (bare metal + Podman containers)
- Custom firmware roadmap
- Oura comparison & bottom-line analysis

## Status

🟢 **Working end-to-end. All 8 data types collecting + all health scores computing.**

R09 ring paired and validated (FW `RT09_3.10.21_251107`, HW `RT09_V3.1`). Sync pulls all data types to Postgres, analytics engine computes validated health scores, dashboard operational with dark mode. Sync behavior confirmed read-only (safe to sync from multiple devices). Remote access via Tailscale.

### Data collection (all protocols aligned with Gadgetbridge)
- ✅ Heart rate (cmd 0x15) — 5-min intervals, multi-packet per day
- ✅ Steps/activity (cmd 0x43) — 15-min slots with calories + distance
- ✅ HRV (cmd 0x39) — composite ms values at 30-min intervals (3-day buffer)
- ✅ Sleep stages (cmd 0xBC + type 0x27) — per-session deep/REM/light/awake with timestamps
- ✅ SpO2 (cmd 0xBC + type 0x2A) — hourly blood oxygen %
- ✅ Temperature (cmd 0xBC + type 0x25) — skin temp at 30-min intervals (R09 exclusive)
- ✅ Stress (cmd 0x37) — 30-min interval readings (0-99 scale)
- ✅ Ring goals (cmd 0x21) — steps/calorie/distance targets

### Health scores (server-side, persisted after each sync)
- ✅ **Sleep quality** — 5-component score (0-100): duration, efficiency, architecture, continuity, latency. Trapezoidal scoring with Ohayon 2004 norms.
- ✅ **Recovery** — ln(HRV) z-score vs 7-day baseline (Altini/Plews framework), readiness text, confidence flags
- ✅ **Stress** — Garmin/Firstbeat thresholds + weighted daily score (daytime + peak sustained + overnight)
- ✅ **Circadian HR** — HR mapped to hour-of-day across all days
- ✅ **Resting HR** — overnight lowest HR (1-5 AM window)
- ✅ **HRV trends** — 7-day and 28-day rolling averages

### Dashboard
- **Dashboard tab**: Vitals chart (HR line + SpO₂ dots + Temp dots triple-axis SVG with hover tooltips + smooth Catmull-Rom curves), sleep donut ring, circadian HR SVG line graph, recovery panel, today's activity dials, dark mode toggle
- **Analytics tab**: Data pipeline reference (ring-measured vs ring-computed vs our-validated-score), score breakdown cards with expandable formula explanations, 4 trend charts (HRV recovery, sleep quality, stress, resting HR) with 7d/14d/30d/90d range selector + hover crosshair tooltips
- **Admin tab**: Sync Now, ring status, full sync log with clock drift tracking (color-coded), clock alert banner, system health, raw data tables

### How it works
```
Ring → BLE sync (on-demand) → Postgres raw tables → analytics.py → computed score tables
                                    ↑                                          ↓
                               FastAPI API ←←←←←←←←←←←←←←←←←←←←←←←←← Dashboard
```

The poller watches for sync requests every 30s, runs the collector, then runs analytics.py to recompute all scores. Fully automated after clicking "Sync Now".
