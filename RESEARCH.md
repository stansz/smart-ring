# Smart Ring Research

*Hardware specs, BLE protocol, validated score formulas, and design rationale. For operational details (deployment, setup, BLE workarounds) see `AGENTS.md`.*

## Hardware Target: Colmi R09

- **SoC:** BlueX RF03 ARM Cortex-M0 (200KB RAM, 512KB Flash)
- **Sensors:** accelerometer (steps, sleep, gestures), heart rate (PPG), SpO2, **skin temperature** (R09 exclusive — R02/R06/R10 lack this)
- **Weight:** ~3.8g (20% lighter than R02 due to concave design)
- **Battery:** 15-18mAh, ~2-3 day battery life
- **Storage model:** ring logs sensor data onboard, syncs on demand via BLE. No persistent phone connection needed.

### Why R09 over R02?

| | R02 | R09 |
|---|---|---|
| Shell | Flat inner, stainless steel | Concave inner, 20% lighter |
| Temperature sensor | ❌ | ✅ Skin temperature |
| SoC | BlueX RF03 | BlueX RF03 (same) |
| CFW support | ✅ | ✅ confirmed |
| Price | ~$20-25 CAD | ~$45 CAD (official store) |

The temperature sensor enables body temp trending for sleep staging alongside raw PPG data.

### Compatible Models

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

- **Zero auth.** No binding, no pairing ceremony, no security keys. First device to connect wins.
- **Standard BLE protocol.** Uses Nordic UART Service (`6E40FFF0-B5A3-F393-E0A9-E50E24DCCA9E`). You write 16-byte packets, ring responds. First byte = command type, last byte = checksum (sum of other 15 bytes mod 255), middle 14 bytes = payload.
- **No app lock-in.** The QRing app is completely optional. Multiple Gadgetbridge users confirmed connecting directly without ever installing QRing.

## Key Tools

| Tool | Purpose |
|------|---------|
| **tahnok/colmi_r02_client** | Python client + full BLE protocol docs. CLI for scan, sync to SQLite, realtime HR, set time. Used as a library in our collector. |
| **atc1441/ATC_RF03_Ring** | Custom firmware + SDK for the BlueX RF03 SoC. Includes web-based OTA flasher (no hardware programmer needed). Foundation that cracked the platform. |
| **Gadgetbridge** | Open-source Android client (F-Droid). Supports R02/R03/R06/R09. Primary protocol reference for command set and V2 big-data characteristic. |
| **colmi.puxtril.com** | Community BLE protocol documentation site. Command reference for Nordic UART + V2 big-data service. |

## Open Questions (All Resolved)

### Does syncing wipe data from the ring? ✅ READ-ONLY

**Confirmed read-only on firmware RT09_3.10.21.** Syncing reads data without clearing it. Tested both within-connection (two fetches, same session) and across-disconnect (fetch → disconnect → reconnect → fetch). Both returned identical data.

Data persists on the ring regardless of read or disconnect. The ring's storage is an age-based circular buffer (~7 days). Under normal operation, data is only lost when it ages out.

**Caveat (R09 firmware quirk):** The background logging task (cmd 0x15 HeartRateLog + temperature) runs as a separate firmware task from live PPG measurement. It can hang silently — the ring continues real-time measurement (HRV, SpO₂, stress still flow), but new HR/temp samples stop being written to the on-board buffer. When this happens, the buffer returns NoData/empty for the affected days, and no client (our collector, Gadgetbridge, phone) can recover data the ring never wrote.

**Detection signal:** HRV present for today (ring worn + measuring) but HR log/temp empty → logger stalled. Auto-recovery: toggle `set_heart_rate_log_settings(False→True)` to re-kick the firmware logger task (implemented in `sync_ring.py`). If the toggle doesn't revive it, a full power-cycle (discharge → recharge) is needed.

Multiple devices (phone + Linux collector) can sync independently without data loss (for data the ring *did* record).

### What is the HRV data format? ✅ COMPOSITE VALUE

The ring stores a **composite HRV value** (single byte, 0-255, in milliseconds) — NOT true RR intervals. Fetched via `CMD_SYNC_HRV` (0x39) with per-day offset (0-6). Buffer is ~3 days.

The composite value works for trend/z-score analysis — this is exactly how all commercial rings work (PPG-derived values against personal baselines). RMSSD and pNN50 (which require RR intervals) are **NOT available**.

### What commands does the R09 actually use? ✅ ALL RESOLVED

| Data Type | Command | Notes |
|-----------|---------|-------|
| Heart Rate | cmd 0x15 | 5-min intervals, multi-packet per day, 288 slots |
| Steps | cmd 0x43 | 15-min slots with calories + distance (slots 0–95 per day) |
| HRV | cmd 0x39 | 30-min intervals, composite ms values, 3-day buffer |
| Sleep | cmd 0xBC + type 0x27 | V2 big-data: per-session stages with timestamps |
| SpO2 | cmd 0xBC + type 0x2A | V2 big-data: hourly min/max, averaged |
| Temperature | cmd 0xBC + types 0x25-0x29 | V2 big-data: 30-min intervals, 5-day history (R09 exclusive). `temp_c = (raw/10)+20` |
| Stress | cmd 0x37 | 30-min intervals, 0-99 scale |
| Battery | cmd 0x03 | Battery percentage |
| Goals | cmd 0x21 | Steps/calorie/distance targets |
| Device Info | GATT 0x180A | Hardware + firmware version |

### R09 Time Sync Protocol

The R09 firmware reads the set_time BCD bytes as **local wall-clock values** (not UTC). Three implementations compared:

| Aspect | Gadgetbridge | Our `set_time_local()` | Library `set_time_packet()` |
|--------|-------------|----------------------|---------------------------|
| Timezone | LOCAL | LOCAL | UTC |
| Data bytes | 6 (year/month/day/hour/min/sec) | 6 (same) | 7 (+ language flag) |
| Encoding | BCD | BCD | BCD |

The library's UTC approach shifts the ring's "midnight" by the host's UTC offset, causing data to land in wrong time slots. Our 6-byte local packet matches Gadgetbridge byte-for-byte.

The ring acknowledges `set_time` with a 16-byte capability packet. The library's `client.py` silently discards this via `empty_parse` — we override with `_pass_through` so the ack is captured. After sending, we wait 3s for the response to confirm the ring processed the command.

**Drift measurement pitfall:** Do NOT measure clock drift as `max(HR ts) - now()`. With 30-min HR sampling, this always shows -10 to -30 min "drift" — that's sampling lag, not clock error. Any data-freshness-based check will false-alarm when the ring is off the finger.

## BLE Quirks (R09 Firmware 3.10.21)

The R09 firmware has several BLE behaviors requiring workarounds. See `AGENTS.md` for the operational details (forget+repair procedure, retry backoff). Key facts:

1. **Aggressive sleep** — stops advertising ~30s after disconnect. RSSI drops from -68 to -127.
2. **Reconnect bug (Linux/BlueZ specific)** — BlueZ holds stale GATT state after disconnect. Does NOT happen on Android.
3. **Single BLE connection** — hardware limitation of the RF03 SoC. Only one device can connect at a time.
4. **bluetoothctl vs bleak conflict** — pair → disconnect → bleak connect (see AGENTS.md for procedure).

## Data Availability

### Stored on ring (syncable historically, ~3-7 day buffer)

| Data Type | Interval | Buffer | Format |
|-----------|----------|--------|--------|
| Heart Rate | 5-min | ~7 days | Processed BPM, 288 slots/day |
| Steps/Activity | 15-min | ~7 days | Steps + calories + distance per slot |
| HRV | 30-min | ~3 days | Composite single-byte (0-255 ms) |
| Sleep | Per-session | ~7 days | Stages + durations via V2 characteristic |
| SpO2 | Hourly | ~7 days | Min/max averaged to single % |
| Temperature | 30-min | 5 days | Skin temp °C (R09 exclusive) |
| Stress | 30-min | ~7 days | 0-99 scale |

### V2 Big-Data Protocol (sleep, SpO2, temperature)

These use a second BLE service (`de5bf728`) separate from Nordic UART:
- **Request**: write raw bytes to COMMAND char (`de5bf72a`) — no 16-byte framing
- **Response**: notify on NOTIFY_V2 char (`de5bf729`) — multi-packet, accumulate until `length + 6` bytes (header bytes [2:3] = uint16 LE total length)

### Real-time only (NOT stored — requires active BLE connection)

- Raw PPG (photoplethysmogram waveform)
- Raw accelerometer (x/y/z at full rate)
- Live HR (current BPM reading)

The 512KB flash can't hold continuous waveform data. For raw PPG you must be actively connected and streaming — drains the 15mAh battery in ~4-6 hours.

### HRV data limitations

The ring provides a composite HRV value — not RR intervals. This means:
- ❌ True RMSSD and pNN50 cannot be computed
- ✅ Trend analysis works: composite value tracks meaningfully day-to-day
- ✅ Z-score recovery works: uses personal baseline + SD, robust to monotonic transform
- ✅ All commercial rings (Oura, WHOOP) use PPG-derived values the same way

## Validated Score Formulas

All formulas backed by peer-reviewed research. Implementation in `collector/analytics.py`.

### Sleep Quality (0-100)

5-component composite — mirrors Oura's architecture (reverse-engineered by Chheda, ~500 nights):

```
SleepScore = 30%·S_dur + 25%·S_eff + 25%·S_arch + 15%·S_cont + 5%·S_lat
```

Each sub-score uses trapezoidal scoring (full credit in optimal range, linear decline outside):

| Component | Optimal | Declines to 0 at | Reference |
|-----------|---------|-------------------|-----------|
| Duration | 7-9 hours | <4h, >10h | Watson et al. 2015 (NSF consensus) |
| Efficiency | ≥90% | <60% | Ohayon 2004 meta-analysis |
| Architecture | deep 13-23%, REM 20-25% | penalize below/above | Ohayon et al. 2004, AASM norms |
| Continuity | WASO <20min, <2 awakenings | WASO >60min, >6 awakenings | AASM clinical practice |
| Latency | 10-20 min | <5min (debt), >30min (poor) | PSQI / Oura contributor |

**Normal sleep architecture** (Ohayon 2004 meta-analysis, 65 studies, 3,577 subjects):
- Deep (N3): 13-23% (declines ~2%/decade with age)
- REM: 20-25%
- Light (N1+N2): 50-60%
- Wake: <10%

### HRV Recovery (z-score)

Altini/Plews/Buchheit framework — gold standard for athlete recovery monitoring:

1. **Log-transform**: `ln(composite_hrv)` — normalizes the distribution
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

5. **Coefficient of variation** (CV): SD/mean × 100; CV >15% = accumulated fatigue flag
6. **Cold-start**: ≥5 nights needed for reliable 7-day estimates (Grosicki et al. 2026, 2M nights)

**References:**
- Altini M (2021). "Longitudinal HRV monitoring." *Sensors*. 9M measurements, 28,175 users.
- Plews DJ, Laursen PB, Stanley J, et al. (2013). "Training adaptation and heart rate variability in elite endurance athletes." *Sports Medicine*.

### Stress Classification

Garmin/Firstbeat thresholds (industry standard):

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
- Daytime average (0.5 weight): 6AM-10PM
- Peak sustained (0.3 weight): highest 2-hour rolling average
- Overnight average (0.2 weight): 10PM-6AM, recovery quality signal

**Circadian awareness** (Shen et al. 2025, *Frontiers in Physiology*): Detrending HRV features with circadian rhythm removal improved stress classification accuracy by 13.67%.

### Resting Heart Rate

Tracked as complement to HRV (Altini: "HRV is more sensitive, HR is more specific"):
- Overnight lowest HR (1-5 AM window)
- >3 bpm elevation for 2+ consecutive days vs 7-day baseline = warning
- Most useful when it **diverges** from HRV (confirms or contradicts the signal)

## Readiness Score (0–100)

**Implemented July 2026.** Stored in `readiness_score` table, computed daily by `analytics.py`.

### Formula

```
readiness = 0.35*HRV + 0.30*Sleep + 0.20*Activity + 0.15*RHR
```

Each sub-score normalized 0–100:

| Pillar | Weight | Computation | Normalization |
|--------|--------|-------------|---------------|
| **HRV** | 35% | z-score from 7-day baseline | z≥3→100, z=1→80, z=0→55, z≤-1→10 |
| **Sleep** | 30% | `sleep_quality.score` (0-100) | As-is (already 0-100) |
| **Activity** | 20% | Steps vs goal (default 8000) + active-minute bonus | capped at 100 |
| **RHR** | 15% | Deviation from 30-day median resting HR | delta × 3 offset; lower RHR = higher score |

### Contributors

Each pillar gets a "contributor" score = (sub_score - 50) × weight, showing whether it's pushing readiness UP (+) or DOWN (−). Displayed as e.g. "+18 HRV · +9 Sleep · -6 Activity · +6 RHR."

### How Commercial Wearables Compare

#### Oura Ring — 9 Contributors
Uses 9 separate contributors combined into a single 0-100 score. "Balance" contributors use 14-day weighted averages vs 2-month long-term averages.

| Contributor | Time window |
|-------------|------------|
| HRV Balance | 14-day vs 3-month average |
| Resting Heart Rate | Last night vs long-term average |
| Body Temperature | Last night's deviation vs baseline |
| Recovery Index | Time after HR hits overnight low (6h+ ideal) |
| Sleep + Sleep Balance + Sleep Regularity | Multi-window (single + 2-week + consistency) |
| Previous Day Activity + Activity Balance | Single day + 14-day vs 2-month |

Oura tiers: 85-100 Optimal · 70-84 Good · 60-69 Fair · <60 Pay Attention

#### WHOOP — 3 Contributors (HRV-dominant)
- HRV: ~70% (during slow-wave sleep)
- Resting HR: ~20%
- Sleep Performance: ~10% (sleep need vs actual)

WHOOP tiers: 67-100% Green · 34-66% Yellow · 0-33% Red. Average member score: 58%.

#### Garmin — Body Battery
Continuous model using HRV + stress + activity. Updates throughout the day, not just morning. 0-100 "battery charge" that depletes during activity and recharges during rest.

### Key Research Findings (Doherty & Altini 2025)

From the most comprehensive comparative study of wearable readiness scores:

1. **"Wearables estimate recovery, they don't measure it."** There is no gold standard for "recovery" the way PSG exists for sleep.
2. **"No brand publishes its exact readiness formula and very few scores have been independently validated."** The composite scores themselves have no clinical validation.
3. **"Trust the trend of Readiness, not the exact number."** 75→68→55 is meaningful; whether it's exactly 68 vs 72 is noise.
4. **Oura had the best nocturnal RHR accuracy vs ECG** in a 536-night multi-wearable study (Dial et al. 2025).

### What Lowers Readiness

| Factor | Effect | Source |
|--------|--------|--------|
| Alcohol (1-2 drinks) | HRV down ~15%, RHR up same night | Oura 2025 |
| Short/broken sleep | HRV down, RHR up; 2-3 nights to clear | Zhang et al. 2025 |
| Hard training/overreaching | HRV down, RHR up; 5-7 day slide | Noon et al. 2018 |
| Illness onset | RHR + skin temp rise 1-3 days before symptoms | Kasl et al. 2024 |
| Late/heavy meal | Raises cortisol, disturbs sleep | Ucar et al. 2021 |
| Dehydration | HRV down, RHR up | Castro-Sepulveda et al. 2015 |
| Chronic stress | HRV reduction over weeks; lingers after feeling calm | Mohammadi et al. 2019 |
| Luteal phase (cyclical) | RHR up, HRV down, temp up — normal, not poor recovery | Alzueta et al. 2022 |

### Gap Analysis: Our Score vs Commercial Offerings

| Feature | Oura | WHOOP | Us | Gap |
|---------|------|-------|----|-----|
| HRV weight | ~equal contributor | **70%** (dominant) | 35% | WHOOP suggests higher HRV weight |
| HRV baseline | 14-day vs 3-month | personal baseline | 7-day z-score | Could add multi-week "HRV Balance" |
| Sleep contributors | 3 (sleep, balance, regularity) | 1 | 1 (quality score) | Could add regularity + sleep debt |
| Activity contributors | 2 (previous day + balance) | 0 | 1 (today vs goal) | Could add multi-day activity balance |
| Temperature | ✅ | ✅ | ❌ (have data, don't use) | Could add as 5th pillar |
| Recovery Index | ✅ | ❌ | ❌ | Future: compute from overnight HR |
| Number of contributors | 9 | 3 | 4 | More granular than WHOOP, less than Oura |
| Time-to-first-score | ~2 weeks | ~4 weeks | ~7 days | ✅ Faster |

See `TASKS.md` for prioritized improvement roadmap.

## Source Dedup (Phone vs Ring)

**Ring canonical, phone fills gaps.** Phone (Web Bluetooth) and ring (Linux box) capture the same physical measurements. Dedup runs in two places:
1. `mobile_sync` endpoint (container): deletes phone rows where ring has same timestamp
2. `analytics.py` (host): same logic, covers ring syncs

The `source` column survives on every row; phone rows only persist where ring has no data.

## Timezone: Pacific (America/Vancouver)

Day boundaries are consistently Pacific:
- **Postgres**: `ALTER SYSTEM SET TimeZone='America/Vancouver'` — persists across restarts
- **Containers**: `TZ=America/Vancouver` in both quadlets
- **Ring time-setting**: host collector's `set_time_local()` sends Pacific-local BCD bytes
- **Stored timestamps**: correct instants (unchanged). Only date-boundary interpretation changed.

Why it mattered: evening Pacific activity (after 5pm PDT) was attributed to the next UTC day.

## Value Add: Our Analytics vs Raw Ring Data

The ring and Gadgetbridge provide **raw measurements** without context. A composite HRV of 42ms or 7h sleep has no meaning without comparison to **your own baseline** and **population norms**.

| What We Add | Ring Data Used | Key Value |
|-------------|----------------|-----------|
| **Recovery/Readiness** | HRV composite | Log-transform → 7-day baseline → z-score → actionable classification |
| **Sleep Quality (0-100)** | Sleep stages + duration | 5-component validated score using Ohayon 2004 norms |
| **Stress Classification** | Stress 1-99 | Garmin/Firstbeat clinical thresholds + daily weighted score |
| **Circadian HR / Resting HR** | Hourly HR | 24h pattern + overnight baseline + trend detection |

### Key Differentiators

1. **Transparency** — every formula cited (Ohayon 2004, Altini 2021, Plews, Garmin/Firstbeat). Gadgetbridge algorithms are opaque.
2. **Personalized baselines** — 7-day rolling mean/SD for HRV is essential. A raw 42ms means nothing without "your baseline is 38±5."
3. **Validated population norms** — sleep targets from 3,327-subject meta-analysis, not arbitrary thresholds.
4. **Auditability** — all SQL/Python, reproducible. Gadgetbridge's scores are compiled Java.
5. **Divergence detection** — RHR + HRV together form a stronger signal than either alone (Altini: "HRV is more sensitive, HR is more specific").

### Bottom Line

The ring gives **measurements** — ~10% of the health-tracking value. Our analytics give **clinical interpretation with validated baselines** — the other ~90%.

## Oura Comparison

- Oura Ring 5: ~$530 CAD + $8/month subscription
- Colmi R09: ~$45 CAD, no subscription
- BOM on an Oura is estimated $60–80 at scale — Colmi proves the hardware class is profitable at $20
- Oura's sleep staging is well-validated (peer-reviewed, tested against PSG), but the gap vs Apple Watch is marginal (Cohen's kappa 0.65 vs 0.60) and likely comes from the ring form factor, not the algorithm
- The proprietary composite scores (Readiness, Resilience, etc.) have no independent validation — the real science stops at sleep-stage detection

---

Colmi's lack of security is the feature, not the bug. Their cost-cutting created a fully hackable, fully documented, $45 biometric sensor platform with the same form-factor advantage as a $530 Oura ring. With tahnok's client for data extraction and atc1441's CFW for firmware control, you own every layer — hardware, protocol, storage, compute, visualization.
