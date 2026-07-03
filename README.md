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

## Research

All technical research, architecture options, metric methodology, and deployment topologies live in **[RESEARCH.md](RESEARCH.md)**.

Topics covered:
- Hardware specs & model comparison (R02 → R12)
- BLE protocol reverse-engineering
- Data availability (stored vs realtime)
- 8 health metrics backed by published research — all doable from periodic data
- 3 architecture options (local-only, OVH hybrid, privacy-first hybrid)
- Deployment topology (bare metal + Podman containers)
- Custom firmware roadmap
- Oura comparison & bottom-line analysis

## Status

🟡 **Awaiting hardware.** R09 ordered from AliExpress, est. delivery ~2-4 weeks. Once it arrives, testing and pipeline building begins.
