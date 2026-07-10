# Smart Ring 💍

Open-source health data pipeline built around the **Colmi R09** — a $45 CAD hackable smart ring with the same form factor as a $530 Oura ring, zero BLE authentication, and full protocol documentation.

## Goal

Build a private, self-hosted health tracking system that:

- **Collects** biometric data from the ring via BLE (HR, HRV, SpO2, skin temperature, accelerometer)
- **Stores** everything in Postgres — raw sensor data + computed metrics
- **Computes** meaningful health metrics: RMSSD, pNN50, sleep staging, recovery scores, stress classification, circadian patterns
- **Visualizes** in a dashboard — local or remote
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

Dashboard tabs: **Dashboard** (recovery / sleep / HRV trends) and **Admin** (ring status, manual sync controls, sync log, system health). Both tabs served by FastAPI single-page (Alpine.js + Chart.js, no build step).

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
python3 collector/sync_ring.py         # full sync to Postgres
# Or use Gadgetbridge on your phone for quick checks
```

## Research

All technical research, architecture, metric methodology, and deployment details live in **[RESEARCH.md](RESEARCH.md)**.

Topics covered:
- Hardware specs & model comparison (R02 → R12)
- BLE protocol reverse-engineering
- Data availability (stored vs realtime)
- 8 health metrics backed by published research
- Deployment topology (bare metal + containers)
- Custom firmware roadmap
- Oura comparison & bottom-line analysis

## Status

🟢 **Working end-to-end.** R09 ring paired and validated (FW `RT09_3.10.21_251107`, HW `RT09_V3.1`). First contact succeeds, sync pulls HR + steps + stress to Postgres, dashboard operational, Gadgetbridge paired on phone. Sync behavior confirmed read-only (safe to sync from multiple devices).

### Currently working
- Heart rate (49 records, 30-min intervals) — dashboard with trends + circadian pattern
- Steps (15-min slots, per-hour counts with calories + distance)
- Stress (29 records, 30-min intervals, all "normal" range)
- Ring goals (steps target, calorie target) used in dashboard dials
- On-demand sync via "Sync Now" button (poller picks up within 30s)
- Analytics (circadian HR, resting HR, recovery score)

### Next steps
- Sleep protocol alignment (Gadgetbridge uses cmd 0xBC — we need to switch from cmd 68)
- HRV protocol alignment (Gadgetbridge uses cmd 0x39 — we need to switch from cmd 57)
- SpO2 protocol alignment
- Temperature data (event-driven push from ring)
- Remote dashboard access (Cloudflare tunnel or Tailscale)
