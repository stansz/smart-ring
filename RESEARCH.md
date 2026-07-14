# Smart Ring Research Summary

*Compiled 2026-07-01 — Updated 2026-07-11*
*Ring arrived and fully validated July 9, 2026. Firmware RT09_3.10.21_251107, HW RT09_V3.1. All data types collecting, all health scores computing.*

## Hardware Target: Colmi R09 ✅ ARRIVED & VALIDATED

- **Status:** ✅ Arrived July 9, 2026 — working end-to-end
- **BLE address:** `<ring_ble_address>` (R09_2103)
- **Firmware:** RT09_3.10.21_251107
- **Hardware:** RT09_V3.1
- **Cost:** ~$45 CAD from Colmi official store (AliExpress), size 11
- **SoC:** BlueX RF03 ARM Cortex-M0 (200KB RAM, 512KB Flash)
- **Sensors:** accelerometer (steps, sleep, gestures), heart rate (PPG), SpO2, **skin temperature** (R09 exclusive — R02/R06/R10 lack this)
- **Weight:** ~3.8g (20% lighter than R02 due to concave design)
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

### Phase 1: Gadgetbridge (interim — phone only) ✅ DONE
1. Install Gadgetbridge from F-Droid ✅
2. Charge ring, pair via BLE ✅
3. Set clock, configure logging intervals ✅
4. Verify sensors work — HR, SpO2, temperature, steps ✅
5. Use for visual validation only — don't rely on it for data pipeline ✅

### Phase 2: PC Collector (primary pipeline) ✅ DONE
1. `pip install colmi-r02-client` ✅
2. `colmi_r02_util scan` → get BLE address ✅ (<ring_ble_address>)
3. `colmi_r02_client --address=XX:XX set-time` → sync clock ✅
4. `colmi_r02_client --address=XX:XX set-heart-rate-log-settings` → set sampling interval ✅
5. Build collector wrapper → sync → parse → push to Postgres ✅ (see `collector/sync_ring.py`)

### Phase 3: Full pipeline ✅ DONE
- Postgres schema (raw HR, steps, HRV, sleep, SpO2, temperature, stress, goals + computed metrics) ✅
- Web dashboard (Alpine.js + Tailwind CSS, dark mode, no external chart library) ✅ — served at `http://localhost:8000`
- Admin UI with Sync Now button, ring status, system health, sync log, raw data tables ✅
- On-demand sync via web UI → DB queue → host-side poller → BLE sync ✅
- All 8 data types collecting (HR, steps, HRV, sleep, SpO2, temp, stress, goals) ✅
- Validated health scores (sleep quality, recovery z-score, stress classification) ✅
- Remote access via Tailscale ✅
- ~~Optional CFW for enhanced behavior~~ (evaluating, not a priority)
- Phone sync path (Gadgetbridge → FastAPI via Tailscale) — PLANNED

## Open Questions

### Does syncing wipe data from the ring? ✅ RESOLVED — READ-ONLY

**Confirmed read-only on firmware RT09_3.10.21.** Syncing reads data from the ring without clearing it. Two scenarios were tested via `collector/test_sync_readonly.py`:

1. **Within-connection:** Two fetches within the same BLE link returned identical data (9 entries, 731 steps each).
2. **Across-disconnect:** Fetch → disconnect → reconnect → fetch. Reconnect required the `forget+repair` workaround (see BLE Quirks below). Both fetches returned identical data.

**Data persists on the ring regardless of read or disconnect.** The ring's storage is an age-based circular buffer (~7 days). Data is only lost when it ages out of the buffer window. This means:
- Multiple devices (phone/Gadgetbridge + Linux collector) can both sync independently without data loss.
- Timer-driven or manual syncs are safe — no risk of missed data.
- The ring can be synced by Gadgetbridge in the morning on the go, then synced again by the Linux box in the afternoon — both get the same data.

### What is the HRV data format? ✅ RESOLVED — COMPOSITE VALUE

The ring stores a **composite HRV value** (single byte, 0-255, in milliseconds) — NOT true RR intervals. This is fetched via `CMD_SYNC_HRV` (0x39) with a per-day offset parameter (0-6). The ring's HRV buffer is ~3 days.

The composite value can substitute for RMSSD in trend/z-score analysis — this is exactly how all commercial rings work (PPG-derived values against personal baselines). The z-score methodology is robust to monotonic transforms since it uses your own baseline and SD. See "Validated Score Formulas" below for the full methodology.

RMSSD and pNN50 (which require RR intervals) are **NOT available** from this ring.

### What commands does the R09 actually use? ✅ ALL RESOLVED

| Data Type | Command | Status |
|-----------|---------|--------|
| Sleep | `CMD_BIG_DATA_V2` (0xBC) + type 0x27 | ✅ Implemented — per-session stages via V2 BLE characteristic |
| HRV | `CMD_SYNC_HRV` (0x39) with per-day offset | ✅ Implemented — composite ms values at 30-min intervals |
| SpO2 | `CMD_BIG_DATA_V2` (0xBC) + type 0x2A | ✅ Implemented — hourly min/max averaged |
| Temperature | `CMD_BIG_DATA_V2` (0xBC) + types 0x25-0x29 | ✅ Implemented — 30-min intervals, temp = (raw/10)+20°C. **5 days of history** split across big-data types 0x25-0x29 (one type per day, oldest to newest). Each type holds 1 day of 30-min interval readings. R09 exclusive. |
| Stress | `CMD_SYNC_STRESS` (0x37) | ✅ Implemented — 30-min interval readings (0-99) |
| Heart Rate | cmd 21 (0x15) | ✅ Same as library |
| Steps | cmd 67 (0x43) | ✅ Same as library |
| Battery | cmd 3 | ✅ Same as library |
| Goals | `CMD_GOALS` (0x21) | ✅ Implemented — steps/calorie/distance targets |
| Device Info | GATT 0x180A | ✅ Same as library |

**Heart rate data format:** The ring's SportDetail returns `time_index` as a **15-minute slot** from local midnight (slots 0–95 per day), NOT the hour of the day. Each 15-min slot represents steps/calories/distance for that window.

**Ring time — R09 Time Sync Protocol (Gadgetbridge source-verified, Jul 2026):**

The R09 firmware reads the set_time BCD bytes as **local wall-clock values** (not UTC). Three implementations compared:

| Aspect | Gadgetbridge `setDateTime()` | Our `set_time_local()` | Library `set_time_packet()` |
|--------|------------------------------|------------------------|-----------------------------|
| Timezone | LOCAL (`GregorianCalendar.getInstance()`) | LOCAL (`datetime.now()`) | UTC (converts via `.astimezone(timezone.utc)`) |
| Data bytes | 6 (year/month/day/hour/min/sec) | 6 (same) | 7 (+ language flag `0x01`) |
| Encoding | BCD via `Byte.parseByte(str, 16)` | BCD via `byte_to_bcd()` | BCD via `byte_to_bcd()` |

The library's UTC approach shifts the ring's "midnight" by the host's UTC offset, causing data to land in wrong time slots. Our 6-byte local packet matches Gadgetbridge byte-for-byte.

**The ring acknowledges `set_time`:** After sending cmd 0x01, the ring responds with a 16-byte capability packet (same cmd byte). The library's `client.py` registers `empty_parse` for 0x01, which returns `None` and silently discards this response. We override with `_pass_through` so the ack reaches `client.queues[0x01]`. After `set_time_local()`, we wait 3s for this response — if it arrives, the ring processed the command.

**Ring buffer behavior after clock jumps:** When the ring's clock is changed (e.g., factory UTC+8 → our local time), old data in the ring's circular buffer retains its original timestamps. This creates "phantom" future-dated entries in the DB. The `clipFuture` filter on the dashboard hides these. The ring's ~7-day buffer flushes old entries naturally as new data fills in.

**Drift measurement pitfall:** Do NOT measure clock drift as `max(HR ts) - now()`. With 30-min HR sampling, this always shows -10 to -30 min "drift" — that's just the time since the last HR sample, not clock error. Any data-freshness-based check will false-alarm when the ring is off the finger. The ack-based approach avoids this entirely.

All stored data uses the ring's local time as the reference. When building timestamps, use local midnight (not UTC midnight) as the base, then convert to UTC via `.astimezone()`.

---

## BLE Quirks & Reconnect Bug (R09 Firmware 3.10.21)

The R09 firmware has several BLE behaviors that required workarounds in the collector code. These are documented in `collector/ring_client.py` as utility functions (`forget_ring`, `pair_ring`, `disconnect_ring`, `forget_and_repair`).

### 1. Aggressive Sleep
The ring **stops advertising ~30 seconds** after losing a BLE connection. RSSI drops from -68 to -127 within seconds. The ring will not be discoverable again until:
- You wear/tap the ring (movement wakes the accelerometer)
- You connect it briefly to a charger
- A BLE scan "nudges" the radio awake (used as a wake-ping in `connect_with_retry`)

### 2. Reconnect Bug (Linux/BlueZ Specific)
After a BLE disconnect, **BlueZ holds stale GATT state** that prevents new connections. The symptom on Linux is:
- `BleakDeviceNotFoundError`: "Device was not found" (ring is advertising but BlueZ can't see it)
- `BleakError`: "failed to discover services, device disconnected"
- `EOFError` on `start_notify` (BlueZ has GATT cache from previous session)

**This does NOT happen on Android** — Android's BLE stack properly maintains the bond and clears stale GATT state on reconnect. The R09 bug only manifests on Linux BlueZ.

### 3. The Forget+Repair Workaround
The reliable workaround on Linux is a **full forget+re-pair** before every connection:

```
bluetoothctl disconnect <addr>    # Release any lingering GATT link
bluetoothctl remove <addr>        # Clear ALL cached state (bond, GATT services, connection history)
    → SCAN (BlueZ must re-discover the device before pairing)
bluetoothctl pair <addr>          # Establish a fresh bond
bluetoothctl disconnect <addr>    # Release the GATT link so bleak can own it
    → bleak connects and owns the notification stream
```

After the sync completes, the ring is forgotten again (`bluetoothctl remove`) to leave it in a clean state for the next sync (or for phone pairing).

This workaround is automated in `collector/ring_client.py`:
- `forget_ring(addr)` — disconnect + remove
- `pair_ring(addr)` — pair + auto-disconnect (releases GATT for bleak)
- `forget_and_repair(addr)` — forget → scan → pair (async, includes scan between forget and pair so BlueZ re-discovers the device)

### 4. Single BLE Connection
The R09 only supports **one BLE connection at a time**. If the Linux box is connected, the phone (Gadgetbridge) cannot connect — and vice versa. This is a hardware limitation of the BlueX RF03 SoC.

Our design works around this by:
- Connecting only during sync (no persistent BLE link)
- Doing `forget_ring()` at the end of each sync → ring is immediately free for phone pairing
- The poller (`smart-ring-poller.service`) polls the DB every 30s and only initiates a BLE connection when there's a pending sync request

### 5. bluetoothctl vs bleak Ownership Conflict
**bluetoothctl and bleak cannot share a connection.** If `bluetoothctl pair` establishes a GATT link, it must be disconnected (`bluetoothctl disconnect`) before bleak can `connect()`. The `pair_ring()` function now auto-disconnects after pairing to prevent this conflict.

### 6. Retry-on-Sleep with Exponential Backoff
`connect_with_retry()` in `sync_ring.py` handles the ring's sleep behavior:
- Attempts: 5 (configurable via `--attempts N` CLI flag)
- Backoff: 2s, 4s, 8s, 16s, 32s
- Wake-ping: a 5-10s BLE scan before the first attempt and before the last attempt
- Catches: `BleakError`, `OSError`, `TimeoutError`, `EOFError`, `ConnectionError`

---

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

### Stored on ring (syncable historically, ~3-7 day buffer depending on data type)
- **Heart Rate** (cmd 0x15) ✅ — processed BPM at 5-minute intervals. Fetched via custom `fetch_hr_history()` which bypasses the library's buggy `HeartRateLogParser`.
- **Steps/Activity** (cmd 0x43) ✅ — `SportDetail` objects with `time_index` as **15-minute slots** from local midnight (0–95), each containing `steps`, `calories`, `distance`.
- **HRV** (cmd 0x39) ✅ — composite ms values at 30-minute intervals. Ring's buffer is ~3 days. NOT true RR intervals — the ring computes a single-byte composite HRV internally.
- **Sleep** (cmd 0xBC + type 0x27) ✅ — per-session sleep data via V2 BLE characteristic: sleepStart/sleepEnd (minutes after midnight) + per-stage entries (type: 2=light, 3=deep, 4=rem, 5=awake + duration in minutes).
- **SpO2** (cmd 0xBC + type 0x2A) ✅ — per-day hourly min/max blood oxygen, averaged to single value.
- **Temperature** (cmd 0xBC + types 0x25-0x29) ✅ — skin temperature at 30-min intervals: `temp_c = (raw / 10) + 20`. **5 days of history** split across big-data types 0x25-0x29 (one type per day, oldest to newest). R09 exclusive.
- **Stress** (cmd 0x37) ✅ — stress values 0-99 at 30-min intervals. Multi-packet protocol (pkt 0=header, pkts 1-4=data).
- **Goals** (cmd 0x21) ✅ — daily step/calorie/distance/sport/sleep targets.

### V2 Big-Data Protocol (sleep, SpO2, temperature)
These three data types use a **second BLE service** (`de5bf728`) separate from the Nordic UART:
- **Request**: write to COMMAND char (`de5bf72a`) — raw bytes, no 16-byte framing
- **Response**: notify on NOTIFY_V2 char (`de5bf729`) — multi-packet, accumulate until `length + 6` bytes (header bytes [2:3] = uint16 LE total length)
- Implemented in `collector/ring_client.py` (`_handle_big_data`, `send_command`)

### Real-time only (live stream, on-demand — NOT stored)
- **Raw PPG** — the actual light sensor waveform
- **Raw accelerometer** — x/y/z at full rate
- **ECG** — if supported
- **Live HR** — current BPM reading

### Critical constraint
The ring does NOT store raw PPG waveforms. It processes them internally into BPM metrics, stores those results in a ~7-day circular buffer, and discards the raw signal. The 512KB flash can't hold continuous waveform data. For raw PPG you must be actively connected and streaming — which drains the 15mAh battery in ~4-6 hours of continuous use.

### HRV data details
The ring stores a **composite HRV value** (single byte, ms) — not RR intervals. This means:
- ❌ True RMSSD and pNN50 cannot be computed (require beat-to-beat interval arrays)
- ✅ Trend analysis works: the composite value tracks meaningfully day-to-day
- ✅ Z-score recovery computation works: uses personal baseline + SD, robust to the composite transform
- ✅ All commercial rings (Oura, WHOOP) use PPG-derived values the same way

The ring's HRV buffer is ~3 days (daysAgo 0-2 return data, 3-6 return empty).

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
- ~~**RMSSD** (root mean square of successive differences)~~ — NOT AVAILABLE: ring provides composite HRV, not RR intervals
- ~~**pNN50**~~ — NOT AVAILABLE: requires RR intervals
- ✅ **Sleep staging** — light/deep/REM/wake from cmd 0xBC big-data (IMPLEMENTED)
- ✅ **Resting HR** — lowest sustained HR during sleep (IMPLEMENTED)
- ✅ **Recovery score** — ln(composite_HRV) z-score vs 7-day baseline (IMPLEMENTED)
- ✅ **Stress classification** — Garmin/Firstbeat thresholds from raw_stress (IMPLEMENTED)
- ✅ **HRV trends** — rolling 7d/28d windows of composite HRV (IMPLEMENTED)
- ✅ **Circadian HR pattern** — HR mapped to time-of-day (IMPLEMENTED)
- [ ] **Illness early warning** — HRV drop + RHR rise above baseline (future)

---

## Validated Score Formulas (2026-07-10)

All formulas are backed by peer-reviewed research and commercial validation studies. See `collector/analytics.py` for implementation.

### Sleep Quality Score (0-100)

**5-component composite** — mirrors Oura's architecture (reverse-engineered by Chheda, ~500 nights, R²=0.846):

```
SleepScore = 30%·S_dur + 25%·S_eff + 25%·S_arch + 15%·S_cont + 5%·S_lat
```

Each sub-score uses trapezoidal scoring (full credit in optimal range, linear decline outside):

| Component | Optimal | Declines to 0 at | Reference |
|-----------|---------|-------------------|-----------|
| Duration | 7-9 hours | <4h, >10h | Watson et al. 2015 (NSF consensus); Koemel et al. 2026 |
| Efficiency | ≥90% | <60% | Ohayon 2004 meta-analysis (3,327 citations) |
| Architecture | deep 13-23%, REM 20-25% | penalize below/above | Ohayon et al. 2004, AASM norms |
| Continuity | WASO <20min, <2 awakenings | WASO >60min, >6 awakenings | AASM clinical practice |
| Latency | 10-20 min | <5min (debt), >30min (poor) | PSQI / Oura contributor |

**Why these weights:** Oura's reverse-engineering (Chheda) shows total sleep time is the #1 predictor (coefficient 25.26), followed by latency (12.14), then REM (7.56). Duration gets ~2-3× the weight of any single stage metric.

**Normal sleep architecture (Ohayon 2004 meta-analysis, 65 studies, 3,577 subjects):**
- Deep (N3): 13-23% (declines ~2%/decade with age; men >70 have ~50% less than men <55)
- REM: 20-25% (subtle decline; meaningful impairment usually only after 80)
- Light (N1+N2): 50-60%
- Wake: <10%

**Previous formula** (`deep_pct × 2.5 + rem_pct × 1.5`) was duration-blind, over-rewarded supra-physiological deep sleep, and ignored efficiency/continuity. Replaced.

### HRV Recovery Score (z-score)

**Altini/Plews/Buchheit framework** — the gold standard for athlete recovery monitoring:

1. **Log-transform**: `ln(composite_hrv)` — normalizes the distribution (RMSSD is right-skewed)
2. **7-day rolling baseline**: mean of ln(HRV) over previous 7 days
3. **Z-score**: `z = (ln_today - mean_7d) / SD_7d`
4. **Readiness mapping**:

| Z-score | Readiness |
|---------|-----------|
| > +1.0 | Excellent |
| +0.5 to +1.0 | Good |
| -0.5 to +0.5 | Fair (normal) |
| -1.0 to -0.5 | Poor |
| < -1.0 | Very Poor |

5. **Coefficient of variation** (CV): SD/mean × 100; CV >15% with suppressed baseline = accumulated fatigue flag
6. **Cold-start**: ≥5 nights/week needed for reliable 7-day estimates (Grosicki et al. 2026, 2M nights). Scores flagged "low confidence" until 7+ days.

**Why composite HRV works:** The ring's composite value is a PPG-derived HRV metric. All commercial rings (Oura, WHOOP, Garmin) use PPG-derived RMSSD against personal baselines — population norms are less useful than individual trends. The z-score methodology is robust to monotonic transforms since it uses your own baseline and SD.

**Key references:**
- Altini M (2021). "Longitudinal HRV monitoring." *Sensors*. 9M measurements, 28,175 users.
- Plews DJ, Laursen PB, Stanley J, et al. (2013). "Training adaptation and heart rate variability in elite endurance athletes." *Sports Medicine*.
- Marco Altini is data science advisor at Oura; creator of HRV4Training.

### Stress Classification

**Garmin/Firstbeat thresholds** (industry standard, most cited):

| Level | Score Range | Garmin Band |
|-------|------------|-------------|
| Relaxed | 0-25 | Rest/recovery |
| Low | 26-50 | Normal daytime |
| Medium | 51-75 | Elevated |
| High | 76-100 | Acute stress |

**Daily weighted stress score:**
```
daily_stress = 0.5 × daytime_avg + 0.3 × peak_sustained + 0.2 × overnight_avg
```
- **Daytime average** (0.5 weight): bulk of readings, 6AM-10PM
- **Peak sustained** (0.3 weight): highest 2-hour rolling average — prolonged stress is more meaningful than brief spikes
- **Overnight average** (0.2 weight): recovery quality signal, 10PM-6AM

**Circadian awareness** (Frontiers in Physiology 2025, Shen et al.): Detrending HRV features with circadian rhythm removal improved stress classification accuracy by **13.67%**. Future: compute per-slot 14-day baselines and report deviation from baseline.

**Cross-validation:** Pearson r between `raw_stress.stress_value` and `raw_hrv.hrv_value` should be ≈ -0.4 to -0.7. Healthy systems show inverse correlation (high stress → low HRV).

### Resting Heart Rate

Tracked as complement to HRV (Altini: "HRV is more sensitive, HR is more specific"):
- Overnight lowest HR (1-5 AM window)
- >3 bpm elevation for 2+ consecutive days vs 7-day baseline = warning (illness, overtraining)
- Most useful when it **diverges** from HRV (confirms or contradicts the signal)

### Local hardware available
- **Linux Mint HTPC** (AMD 3800x, 64GB RAM, GTX 1070) — on 24/7, has built-in BT (currently used for mouse)
- Runs Windows 10 VM (VMware Workstation Pro) for work — needs ~16GB RAM reserved
- Also has Unraid NAS on 24/7
- BT confirmed working

### Deployment Topology — BARE METAL + CONTAINERS
- **Collector:** Python wrapping `colmi_r02_client` + `bleak` (bare metal venv — needs BlueZ/DBus)
- **Polling:** `smart-ring-poller.service` (systemd user unit, bare metal) — watches `sync_requests` table every 30s, runs `sync_ring.py --forget` as subprocess for any pending row. Does NOT hold a BLE connection between syncs.
- **DB:** Postgres 16 (rootless Podman quadlet, `smart-ring-db.service`, port `localhost:5432`)
- **API:** FastAPI + Dashboard (rootless Podman quadlet, `smart-ring-api.service`, port `localhost:8000`) — mounts `dashboard/` directory for live HTML reload
- **Analytics:** Runs on host via poller after each successful sync (not cron) — computes derived tables from raw data

---

## Architecture (CONFIRMED — Local-First)

The agent (Hermes) runs on the same local Linux box, so full local deployment is now the starting point. Remote access can be added later (e.g. Cloudflare tunnel or reverse proxy to the VPS).

Current topology (Linux Mint HTPC):
```
Home Network
├─ Linux Mint Box (AMD 3800x, 64GB RAM, BT enabled)
│   ├─ smart-ring-poller.service  (systemd user unit, bare metal)
│   │   └─ watches sync_requests table every 30s
│   │   └─ runs sync_ring.py --forget for pending requests
│   ├─ collector/sync_ring.py     (bare metal venv — needs BlueZ/DBus for BLE)
│   │   └─ triggered by poller or run manually
│   ├─ smart-ring-db.service      (rootless Podman quadlet, Postgres 16)
│   │   └─ port localhost:5432
│   └─ smart-ring-api.service     (rootless Podman quadlet, FastAPI)
│       └─ port localhost:8000, serves dashboard
│
└─ Phone (on the go — planned)
    └─ Gadgetbridge → HTTPS (Tailscale) → FastAPI
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
- **Postgres, FastAPI, Dashboard:** Isolated in Podman/Docker containers
- **Analytics:** Runs on host via cron (2 min after collector, shares collector's venv)
- **Windows 10 VM:** Unchanged, untouched
- **Why not VM with BT passthrough?** The BT chip is a combo WiFi+BT on motherboard PCIe. Passing it through to a VM would lose host connectivity (mouse dies). Bare metal avoids the mess entirely.
- **Collector on host vs container:** Host is simpler — collector is a thin script that needs DBus/BlueZ. Can containerize later by mounting `/var/run/dbus` if isolation is ever needed.

---

## REMOVED — Old Multi-Option Comparison

> The previous multi-option comparison (All-Local vs OVH Hybrid vs Read-Only Mirror) has been removed. Local-first is the confirmed starting point. If a VPS component is needed later, it will be added as a remote mirror, not a hybrid backend.


---

---

## Readiness Score (Oura-style 0-100)

**Implemented July 2026.** Stored in `readiness_score` table, computed daily by `analytics.py`.

### Formula

```
readiness = 0.35*HRV + 0.30*Sleep + 0.20*Activity + 0.15*RHR
```

Each sub-score normalized 0-100:

| Pillar | Weight | Computation | Normalization |
|--------|--------|-------------|---------------|
| **HRV** | 35% | z-score from 7-day baseline (Altini/Plews) | z≥1.0→100, z=0→60, z≤-1→10 |
| **Sleep** | 30% | `sleep_quality.score` (0-100 from Ohayon 2004) | As-is (already 0-100) |
| **Activity** | 20% | Steps vs goal (default 8000) + active-minute bonus | capped at 100 |
| **RHR** | 15% | Deviation from 30-day median resting HR | delta × 3 offset; lower RHR = higher score |

### Contributors

Each pillar gets a "contributor" score = (sub_score - 50) × weight, showing whether it's pushing readiness UP (+) or DOWN (−). Displayed in the hero panel as e.g. "+18 HRV · +9 Sleep · -6 Activity · +6 RHR."

### RHR Baseline

30-day median of resting HR across all days. Recalculated each analytics run. Excludes days with no HR data.

### Prior Art

- **Oura**: Proprietary Readiness Score (0-100). Three pillars: Sleep, Activity, Readiness. Weights and normalization not public — but the three-pillar architecture is well-documented in their patents and UX.
- **Garmin**: Body Battery (0-100) uses HRV + stress + activity. More continuous (updates throughout the day). Heavier on real-time HRV streams.
- **Whoop**: Recovery Score (0-100%) weights HRV heaviest (~50%), plus RHR, sleep, respiratory rate. Morning assessment only.
- **Fitbit**: Daily Readiness Score (1-100) uses HRV + recent activity + sleep. Arrives in the morning; adjusts throughout the day.

---

## Source Dedup (Phone vs Ring)

**Implemented July 2026.** Phone (Web Bluetooth) and Ring (Linux box collector) capture the same physical measurements, so ~99% of phone records duplicate ring. Dedup runs in two places:
1. `mobile_sync` endpoint (container): `_dedupe_sources(db)` after inserts — deletes phone rows where ring has same timestamp (point tables) or same day (sleep).
2. `analytics.py` (host): `dedupe_sources()` at top of `run_all` — same logic, covers ring syncs.

Policy: **ring canonical, phone fills gaps.** The `source` column (ring/phone) survives on every row; phone rows only persist where ring has no data. First run removed 356 duplicates; only 7 phone gap-fills remain.

---

## Timezone: Pacific (America/Vancouver)

**Fixed July 2026.** Day boundaries are now consistently Pacific:

- **Postgres**: `ALTER SYSTEM SET TimeZone='America/Vancouver'` — `CURRENT_DATE`, `ts::date`, `NOW()::date` all use Pacific midnight. Persists across restarts.
- **Containers**: `TZ=America/Vancouver` in both quadlets (API + DB).
- **Analytics**: was already Pacific (`SET TIME ZONE` from `/etc/timezone`). Now consistent with server tz.
- **Ring time-setting**: unaffected — host collector's `set_time_local()` sends Pacific-local BCD bytes.
- **Stored `ts` values**: unchanged (correct instants). Only date-boundary interpretation changed.
- **Why it mattered**: Evening Pacific activity (after 5pm PDT) was attributed to the next UTC day. E.g., a Saturday 7pm walk showed under Sunday.

---

## Value Add: Our Analytics vs Ring/Gadgetbridge Raw Data

The ring and Gadgetbridge provide **raw measurements** — single data points without context. A composite HRV of 42ms or 7h sleep duration has no inherent meaning without comparison to **your own baseline** and **population norms**. Our analytics layer adds clinical interpretation with peer-reviewed formulas.

### What the Ring Provides (Measurements Only)

| Data Type | Ring Output | Limitation |
|-----------|-------------|-------------|
| HR | 30-min BPM | Point value, no context |
| Steps | 15-min slot counts | Raw count, no goal context |
| SpO₂ | Hourly % | Isolated reading |
| Temp | 30-min °C | Single value |
| Sleep stages | Light/deep/REM/awake + durations | Raw stage totals |
| HRV | Single-byte composite (ms) | Ambiguous number — 42ms could be excellent or poor, unknown without baseline |
| Stress | 1-99 scale, 30-min | Ambiguous — 55 could be "medium" or "high" depending on context |
| Goals | Target steps/cal/distance | Static targets |

### What Our Analytics Adds (Interpretation + Clinical Context)

| Our Metric | Ring Data Used | Key Value Add |
|------------|----------------|---------------|
| **Recovery/Readiness** | HRV composite | Log-transform → 7-day rolling baseline (mean + SD) → z-score → actionable classification (Excellent/Good/Fair/Poor/Very Poor) + confidence flag. **Longitudinal context is 90% of the value.** |
| **Sleep Quality (0-100)** | Sleep stages + duration + temp | 5-component validated score (Duration 30% + Efficiency 25% + Architecture 25% + Continuity 15% + Latency 5%) using Ohayon 2004 meta-analysis norms (3,327 subjects). Weighted, norm-referenced, transparent. |
| **Stress Classification** | Stress 1-99 | Garmin/Firstbeat clinical thresholds + daily weighted score (daytime + peak sustained + overnight) + morning/noon/evening breakdown. **Converts ambiguous 1-99 scale to meaningful clinical categories.** |
| **Circadian HR / Resting HR** | Hourly HR | 24h pattern visualization + overnight 1-5 AM average. **Trend detection + clinical reference (elevated RHR = illness/overtraining signal).** |

### Key Differentiators

1. **Transparency** — Every formula cited (Ohayon 2004, Altini 2021, Plews, Garmin/Firstbeat). Gadgetbridge algorithms are opaque black boxes.

2. **Personalized baselines** — 7-day rolling mean/SD for HRV is *essential*. A raw HRV of 42ms means nothing without "your baseline is 38±5". All commercial rings do this internally — we make it transparent.

3. **Validated population norms** — Sleep architecture targets from 3,327-subject meta-analysis (Ohayon 2004: deep 13-23%, REM 20-25%), not arbitrary thresholds.

4. **Customizability** — Weights and thresholds adjustable for personal physiology (e.g., shift worker circadian norms, athlete recovery windows).

5. **Auditability** — All SQL/Python, reproducible. Gadgetbridge's health scores are compiled Java — good luck tweaking them.

6. **Divergence detection** — RHR + HRV together form a stronger signal than either alone. Altini: "HRV is more sensitive, HR is more specific." When they diverge (HRV drops but RHR holds), it confirms fatigue vs illness.

### Bottom Line

The ring gives **measurements** — ~10% of the health-tracking value. Our analytics give **clinical interpretation with validated baselines** — the other ~90%.

**Worth the complexity?** Yes if you want to track trends and understand *why* your readiness changed. No if you just want "slept 7h, HRV 42ms" — Gadgetbridge already shows that. The difference between "my HRV is 42ms" and "my HRV is 42ms, baseline is 38±5, z-score is +0.8, readiness is Good" is the difference between data and actionable insight.


## Quick Oura Comparison (for context)

- Oura Ring 5: ~$530 CAD + $8/month subscription forever
- Colmi R09: ~$45 CAD, no subscription
- BOM on an Oura is estimated $60–80 at scale — Colmi proves the hardware class is profitable at $20
- Oura's sleep staging is legitimately well-validated (peer-reviewed, tested against PSG), but the gap vs Apple Watch is marginal (Cohen's kappa 0.65 vs 0.60) and likely comes from the ring form factor, not the algorithm
- The proprietary composite scores (Readiness, Resilience, etc.) have no independent validation — the real science stops at sleep-stage detection

## Bottom Line

Colmi's lack of security is the feature, not the bug. Their cost-cutting created a fully hackable, fully documented, $45 biometric sensor platform with the same form-factor advantage as a $530 Oura ring. With tahnok's client for data extraction and atc1441's CFW for firmware control, you own every layer — hardware, protocol, storage, compute, visualization.
