# Smart Ring Research Summary

*Compiled 2026-07-01 — Updated 2026-07-01*

## Hardware Target: Colmi R09 (ORDERED)

- **Status:** ✅ Ordered from Colmi official store (AliExpress), $45 CAD, size 11
- **Est. delivery:** ~2-4 weeks from China
- **SoC:** BlueX RF03 ARM Cortex-M0 (200KB RAM, 512KB Flash) — same across entire R0x family
- **Sensors:** accelerometer (steps, sleep, gestures), heart rate (PPG), SpO2, **skin temperature** (R09 exclusive — R02/R06/R10 lack this)
- **Weight:** ~3.8g (20% lighter than R02 due to concave inner design)
- **Battery:** 15-18mAh, ~2-3 day battery life depending on size
- **Storage model:** ring logs sensor data onboard, syncs on demand via BLE. No persistent phone connection needed.

### Why R09 over R02?

| | R02 | R09 |
|---|---|---|
| Shell | Flat inner, stainless steel | Concave inner, 20% lighter |
| Temperature sensor | ❌ | ✅ Skin temperature |
| SoC | BlueX RF03 | BlueX RF03 (same) |
| CFW support | ✅ | ✅ confirmed |
| Price | ~$20-25 CAD | ~$45 CAD (official store) |

The temperature sensor is a real hardware advantage — enables body temp trending for sleep staging and cycle tracking alongside raw PPG data.

### Compatible Models Reference

All share the same RF03 SoC and BLE protocol. Rule of thumb: if the listing says "use the QRing app," it's compatible.

| Model | Confirmed | Notes |
|-------|-----------|-------|
| R02 | ✅ tahnok + Gadgetbridge + atc1441 | Reference device, most documented |
| R03 | ✅ Gadgetbridge PR #3896 | Same internals |
| R06 | ✅ tahnok + Gadgetbridge | Same internals |
| R09 | ✅ Gadgetbridge + community | + temp sensor, newer shell |
| R10 | ✅ tahnok client | Same internals |
| R12 | ❌ AVOID | Different hardware — has LCD display, different SoC |
| SR1 | ❌ | Oldest model, different board/chipset |

## Why It's Hackable

- **Zero auth.** No binding, no pairing ceremony, no security keys. First device to connect wins. Anyone in BLE range can read stored data.
- **Standard BLE protocol.** Uses Nordic UART Service (UUID `6E40FFF0-B5A3-F393-E0A9-E50E24DCCA9E`). You write 16-byte packets, ring responds. First byte = command type, last byte = checksum (sum of other 15 bytes mod 255), middle 14 bytes = payload.
- **No app lock-in.** The QRing app is completely optional. Multiple Gadgetbridge users confirmed connecting directly without ever installing QRing.

## Key Tools (all open source)

| Tool | Purpose |
|------|---------|
| **tahnok/colmi_r02_client** | Python client + full BLE protocol docs. CLI for scan, sync to SQLite, realtime HR, set time, set HR log interval, send raw commands. Can be used as a library. |
| **smittytone/RingCLI** | CLI for pulling historical data |
| **atc1441/ATC_RF03_Ring** | Custom firmware + SDK for the RF03 SoC. Includes a web-based OTA flasher (no hardware programmer needed). This is the foundation that cracked the platform. |
| **Gadgetbridge** | Open-source Android client (F-Droid, NOT Play Store). Package: `nodomain.freeyourgadget.gadgetbridge`. Supports R02/R03/R06/R09. |

## Setup Plan

### Phase 1: Gadgetbridge (interim — phone only)
1. Install Gadgetbridge from F-Droid
2. Charge ring, pair via BLE
3. Set clock, configure logging intervals
4. Verify sensors work — HR, SpO2, temperature, steps
5. Use for visual validation only — **don't rely on it for data pipeline**

### Phase 2: PC Collector (primary pipeline)
1. `pip install colmi-r02-client`
2. `colmi_r02_util scan` → get BLE address
3. `colmi_r02_client --address=XX:XX set-time` → sync clock
4. `colmi_r02_client --address=XX:XX set-heart-rate-log-settings` → set sampling interval
5. Build collector wrapper → sync → parse → push to Postgres on Hetzner

### Phase 3: Full pipeline
- Postgres schema (raw PPG, HR intervals, accelerometer, temperature, computed metrics)
- PWA dashboard with custom metrics
- Optional CFW for enhanced behavior

## Open Questions (test when ring arrives)

### Does syncing wipe data from the ring?
**Unknown.** Two possibilities:
1. Read-only sync — ring keeps data until circular buffer overwrites. Multiple devices can pull the same data.
2. Read-and-clear sync — sync marks data as read, next sync only gets new data.

**Test:** Sync with Python client, immediately sync again, check if same data is returned.
**Impact:** If Gadgetbridge clears on sync, using it on the go would prevent PC collector from getting that data.
**Safe approach until tested:** Only use Gadgetbridge for live HR viewing, don't hit sync. Let PC collector pull everything.

### Gadgetbridge raw data access?
Gadgetbridge stores processed metrics (HR values, step counts, sleep periods) but may not expose raw inter-beat intervals needed for HRV computation. The Python client is required for raw PPG data.

## Security Posture

**Stock firmware — wide open:**
- No auth, no pairing, no token exchange
- Practical risk is low: BLE range is ~1–3m (tiny antenna, 17mAh battery), single connection only, data is just HR/steps
- Same reason all cheap IoT gear ships open — auth costs engineering time + support tickets, and at $20 margins there's no ROI on security

**Custom firmware — you control it:**
- **MAC whitelist** (~10 lines of C): ring checks connecting device's address against stored list. Easy to defeat via spoofing but raises the bar above casual BLE scanning.
- **Shared secret** (~30 lines): collector sends a password byte before ring accepts data commands. Can't be defeated by sniffing.
- **Rolling challenge-response** (~100 lines): ring sends random nonce, collector encrypts with shared key. Defeats replay attacks. Needs a tiny crypto impl on the M0.

**Honest assessment:** MAC binding is probably sufficient for this threat model. The only realistic attacker is "someone physically in your house who knows what a Colmi ring is AND has reverse-engineered the BLE protocol" — approximately zero people. Layer MAC filtering for peace of mind.

## CFW Roadmap

Stock firmware is the starting point. Custom firmware mods to explore:

1. **Sync behavior control** — never clear on sync, or implement "give me everything since timestamp X" command
2. **Faster raw PPG polling** — atc1441 already has `R02_3.00.06_FasterRawValuesMOD.bin` firmware
3. **MAC whitelist** — only authorized devices can connect
4. **Custom storage model** — circular buffer with proper timestamps, configurable retention
5. **Shared secret auth** — prevent unauthorized data access

Flash via atc1441's web-based OTA tool: https://atc1441.github.io/ATC_RF03_Writer.html (WebBluetooth, Chrome required)

## Architecture (CONFIRMED — Local-First)

Both options share the same components — they differ in WHERE things run.

### Shared components (same for both options)
- **Collector:** Python wrapping `colmi_r02_client` + `bleak` for BLE
- **Storage:** Postgres (containerized — Podman or Docker)
- **Analytics:** Python with numpy/scipy for HRV math and sleep staging
- **API:** FastAPI serving JSON
- **Dashboard:** Web UI (SvelteKit or lightweight server-rendered + charts)
- **Ring management:** CLI (sync, battery, config) — infrequent, no UI needed

## Data Availability — What the Ring Stores vs Streams

### Stored on ring (syncable historically, 2-3 day buffer)
- **Heart Rate** (cmd 21) — processed BPM at intervals, requested by timestamp
- **HRV** (cmd 57) — pre-computed HRV data, requested by index/day offset
- **Sleep Data** (cmd 68) — sleep summaries, requested by day offset
- **Sports/Steps** (cmd 67, 72) — step counts, calories, distance
- **SpO2** — blood oxygen readings
- **Temperature** (R09 only) — skin temperature

### Real-time only (live stream, on-demand — NOT stored)
- **Raw PPG** — the actual light sensor waveform
- **Raw accelerometer** — x/y/z at full rate
- **ECG** — if supported
- **Live HR** — current BPM reading

### Critical constraint
The ring does NOT store raw PPG waveforms. It processes them internally into BPM/HRV metrics, stores those results, and discards the raw signal. The 512KB flash can't hold continuous waveform data. For raw PPG you must be actively connected and streaming — which drains the 15mAh battery in ~4-6 hours of continuous use.

### Open question: What's inside the stored HRV data (cmd 57)?
If the ring stores **RR intervals** (time between heartbeats), RMSSD/pNN50 can be computed retrospectively from historical syncs. If it only stores a composite "HRV score," we're limited to whatever the firmware computed. **Test this first when ring arrives.**

Source: Full BLE protocol docs at https://colmi.puxtril.com/commands/

---

## Metrics & Insights from Periodic Data (No Continuous Streaming Needed)

Research shows periodic sampling throughout the day is scientifically valid and widely used. You don't need continuous raw PPG to get meaningful health insights.

### Daily Recovery Score (Morning RMSSD)
- **What:** Single RMSSD measurement taken each morning, compared to 7-day rolling baseline
- **Science:** Validated as the gold standard for athlete recovery monitoring. Short-term RMSSD (60-120 seconds of clean data) is statistically reliable (Frontiers in Physiology, 2025). Marco Altini's research shows morning HRV is the most practical and effective way to capture acute stress response and chronic baseline changes.
- **Ring already does this:** The ring samples HR periodically throughout the night and morning. Those stored BPM readings + HRV data are exactly what you need.
- **Metric:** `(today's RMSSD - 7-day avg) / 7-day std dev` → z-score → readiness rating

### Stress vs Rest Classification (Tri-daily Sampling)
- **What:** HRV measured at morning, noon, and evening to classify stress/rest states
- **Science:** Frontiers in Physiology (2025) trained a classifier on 3x daily short-term HRV features with circadian rhythm removed. Successfully distinguished stress from resting states throughout the day.
- **Ring data:** The ring's periodic HR samples throughout the day provide the raw material for this.

### Sleep Quality Scoring (Periodic Overnight Sampling)
- **What:** Sleep stage estimation from periodic HR + HRV + accelerometer + temperature
- **Science:** Nature Scientific Reports (2023) demonstrated 4-class sleep staging (wake/light/deep/REM) using PPG-derived instantaneous heart rate + accelerometer, achieving Cohen's kappa 0.74 — competitive with PSG. The algorithm uses interbeat intervals and body movement patterns, sampled periodically.
- **Key insight:** The ring's overnight periodic samples (every 10-30 min) capture enough HR variability + movement data for sleep staging. You don't need continuous PPG.
- **Temperature bonus:** R09's skin temp adds body temperature drops during deep sleep — improves staging accuracy significantly.

### Resting Heart Rate Tracking
- **What:** Lowest sustained HR during sleep, trended over time
- **Science:** Elevated RHR correlates with illness onset, overtraining, stress, and poor sleep. WHOOP and Oura both use this.
- **Ring data:** Directly available from stored overnight HR samples — no raw PPG needed.

### HRV Trending (Weekly/Monthly)
- **What:** Rolling averages of RMSSD/HRV score over time
- **Science:** Long-term HRV trends (7-28 day rolling windows) reveal training adaptation, chronic stress, and seasonal patterns. More meaningful than day-to-day fluctuations.
- **Ring data:** Just need the stored HRV readings — compute trends in Postgres.

### Circadian HR Pattern
- **What:** HR mapped to time-of-day across days/weeks
- **Science:** HR follows a circadian rhythm — lowest ~3-4am, peak ~noon. Disruptions in this pattern indicate jet lag, shift work effects, or metabolic issues.
- **Ring data:** Periodic HR samples throughout the day are perfect for mapping this.

### Illness Early Warning
- **What:** Drop in HRV + rise in RHR above baseline
- **Science:** Both Oura and WHOOP validate this. HRV drops and RHR rises 1-3 days before symptom onset.
- **Ring data:** Just needs stored HR + HRV trends — the ring already captures this periodically.

### Activity-Based HR Zones
- **What:** HR during walking/running from accelerometer + HR correlation
- **Science:** Step count + HR during activity gives crude cardio zones without a chest strap.
- **Ring data:** Stored steps + stored HR at those timestamps.

---

### Metrics to Implement (both options)
- **RMSSD** (root mean square of successive differences) — primary HRV metric
- **pNN50** — percentage of successive intervals differing by >50ms
- **Sleep staging** — light/deep/REM/wake from periodic HR/HRV + accelerometer + temperature
- **Resting HR** — lowest sustained HR during sleep
- **Recovery score** — morning RMSSD z-score vs 7-day baseline
- **Stress/rest classification** — tri-daily HRV pattern analysis
- **HRV trends** — rolling 7/14/28-day windows
- **Circadian HR pattern** — HR mapped to time-of-day
- **Illness early warning** — HRV drop + RHR rise above baseline

### Local hardware available
- **Linux Mint HTPC** (AMD 3800x, 64GB RAM, GTX 1070) — on 24/7, has built-in BT (currently used for mouse)
- Runs Windows 10 VM (VMware Workstation Pro) for work — needs ~16GB RAM reserved
- Also has Unraid NAS on 24/7
- BT confirmed working

### Deployment Topology — BARE METAL + CONTAINERS
- **Collector:** Runs on bare metal host (Python venv) — needs direct BlueZ/DBus access for BLE
- **Postgres, FastAPI, Dashboard, Analytics:** Isolated in Podman containers
- **Windows 10 VM:** Unchanged, untouched
- **Why not VM with BT passthrough?** The BT chip is a combo WiFi+BT on motherboard PCIe. Passing it through to a VM would lose host connectivity (mouse dies). Bare metal avoids the mess entirely.
- **Collector on host vs container:** Host is simpler — collector is a thin script that needs DBus/BlueZ. Can containerize later by mounting `/var/run/dbus` if isolation is ever needed.

---

## Architecture (CONFIRMED — Local-First)

The agent (Hermes) runs on the same local Linux box, so full local deployment is now the starting point. Remote access can be added later (e.g. Cloudflare tunnel or reverse proxy to the VPS).

Current topology (Linux Mint HTPC):
```
Home Network
├─ Linux Mint Box (AMD 3800x, 64GB RAM, BT enabled)
   ├─ Collector (Python venv, bare metal — needs BlueZ/DBus for BLE)
   ├─ Postgres (Podman/Docker container)
   ├─ FastAPI (container)
   └─ Dashboard (served by FastAPI from container)
```

**Why local-first?**
- ✅ Agent can build, test, debug, maintain everything
- ✅ Full control, no data leaves the house
- ✅ Lowest latency, no network dependency
- ✅ Can add remote access later (Cloudflare tunnel, VPN, or sync to VPS)
- ✅ Postgres + FastAPI run fine in containers; collector stays bare metal for BLE

**When to consider VPS hybrid:**
- When you want remote dashboard access (add Cloudflare tunnel to the local FastAPI container)
- When you want a backup copy (sync computed metrics, not raw data, to VPS)
- Not needed for initial dev or data collection

---

## Deployment Topology — BARE METAL + CONTAINERS

- **Collector:** Runs on bare metal host (Python venv) — needs direct BlueZ/DBus access for BLE
- **Postgres, FastAPI, Dashboard, Analytics:** Isolated in Podman/Docker containers
- **Windows 10 VM:** Unchanged, untouched
- **Why not VM with BT passthrough?** The BT chip is a combo WiFi+BT on motherboard PCIe. Passing it through to a VM would lose host connectivity (mouse dies). Bare metal avoids the mess entirely.
- **Collector on host vs container:** Host is simpler — collector is a thin script that needs DBus/BlueZ. Can containerize later by mounting `/var/run/dbus` if isolation is ever needed.

---

## REMOVED — Old Multi-Option Comparison

> The previous multi-option comparison (All-Local vs OVH Hybrid vs Read-Only Mirror) has been removed. Local-first is the confirmed starting point. If a VPS component is needed later, it will be added as a remote mirror, not a hybrid backend.


## Quick Oura Comparison (for context)

- Oura Ring 5: ~$530 CAD + $8/month subscription forever
- Colmi R09: ~$45 CAD, no subscription
- BOM on an Oura is estimated $60–80 at scale — Colmi proves the hardware class is profitable at $20
- Oura's sleep staging is legitimately well-validated (peer-reviewed, tested against PSG), but the gap vs Apple Watch is marginal (Cohen's kappa 0.65 vs 0.60) and likely comes from the ring form factor, not the algorithm
- The proprietary composite scores (Readiness, Resilience, etc.) have no independent validation — the real science stops at sleep-stage detection

## Bottom Line

Colmi's lack of security is the feature, not the bug. Their cost-cutting created a fully hackable, fully documented, $45 biometric sensor platform with the same form-factor advantage as a $530 Oura ring. With tahnok's client for data extraction and atc1441's CFW for firmware control, you own every layer — hardware, protocol, storage, compute, visualization.
