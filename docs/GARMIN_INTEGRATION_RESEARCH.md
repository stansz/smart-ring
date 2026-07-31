# Garmin Integration Research

> Investigation into integrating Garmin Forerunner 745 data alongside the Colmi R09 ring.
> Covers privacy analysis, data sync options, BLE protocol reverse-engineering status,
> Rust ecosystem, and recommended phased approach.
>
> **Date:** July 2026 · **Author:** Sz + Hermes

---

## Table of Contents

1. [Context & Motivation](#1-context--motivation)
2. [Privacy Analysis](#2-privacy-analysis)
3. [Garmin 745 — Device Capabilities](#3-garmin-745--device-capabilities)
4. [Data Sync Options](#4-data-sync-options)
5. [Garmin BLE Protocol — Reverse Engineering Status](#5-garmin-ble-protocol--reverse-engineering-status)
6. [Schema & Multi-Source Architecture](#6-schema--multi-source-architecture)
7. [Rust Ecosystem](#7-rust-ecosystem)
8. [Geo-API Integration for Activity Maps](#8-geo-api-integration-for-activity-maps)
9. [Cross-Device Data Fusion](#9-cross-device-data-fusion)
10. [Recommended Approach](#10-recommended-approach)

---

## 1. Context & Motivation

The smart-ring project currently tracks health data from a **Colmi R09** ring via BLE →
Postgres → React dashboard. The goal is to add data from a **Garmin Forerunner 745** as a
second source, providing:

- **Richer health metrics** (multi-constellation GNSS, barometric altitude, running dynamics, training effect)
- **Structured activity/workout data** (GPS tracks, lap splits, per-km pace, HR zones)
- **Cross-device redundancy** (both devices worn simultaneously — coverage when one is off)
- **Cross-validation** (independent HR readings during overlapping windows)

The Garmin adds an entirely new data category (structured sport sessions) that the Colmi
cannot provide, making this an expansion of capabilities rather than mere redundancy.

---

## 2. Privacy Analysis

### EFF Findings (July 2026)

Source: [EFF Deeplinks — "Most Smart Watches, Rings, and Bands Lack Basic Transparency
Reports and Key Privacy
>Features"](https://www.eff.org/deeplinks/2026/07/most-smart-watches-rings-and-bands-lack-basic-transparency-reports-and-key-privacy)

The EFF surveyed 10 major wearable companies on two privacy pillars:

#### Transparency Reports (government data requests)

| Company | Publishes Report? | Notifies Users? |
|---------|:-:|:-:|
| Apple | ✅ | ✅ |
| Google (Fitbit) | ✅ | ✅ |
| Whoop | ❌ | ✅ |
| Oura | ❌ | Promises to (June 2026 policy update) |
| Garmin | ❌ | ❌ |
| Polar | ❌ | ❌ |
| Suunto | ❌ | ❌ (says "may" in future) |
| Amazfit | ❌ | ❌ |
| Coros | ❌ | ❌ |
| Hume | ❌ | ❌ |

#### End-to-End Encryption

| Company | E2EE for Health Data? |
|---------|:--:|
| Apple (Health app) | ✅ (on by default, only wearable with E2EE) |
| All others (Google, Garmin, Oura, Whoop, Polar, etc.) | ❌ |

Apple Watch is the **only** popular fitness wearable offering E2EE. Most companies offer
encryption in transit and at rest — meaning they can still read and use your data.

#### Key Privacy Concerns

- ~40% of US adults own a wearable health device ([PMC survey](https://pmc.ncbi.nlm.nih.gov/articles/PMC12795147/))
- Wearable data has been used in criminal cases (heart rate, steps, location)
- Surveillance company Penlink calls fitness trackers an "overlooked source" for law enforcement
- Data shared with insurers, used for AI training, subject to subpoenas/warrants
- Health data can reveal movements and infer daily activities

### Garmin-Specific Privacy Posture

- **No transparency report** — will not say how often they hand data to law enforcement
- **No E2EE** — Garmin can read your health data stored in their cloud
- **No local-only wireless option** — all wireless sync routes through Garmin Connect cloud
- **No commitment to notify users** of law enforcement requests

### Our Setup vs. the Industry

Our smart-ring setup is **more private than Apple Watch with E2EE**:

- No company stores the data — it goes ring → BLE → local Postgres → local dashboard
- No intermediary — the data never leaves the house
- No account required — no company knows the data exists
- E2EE solves the problem of "company has my data and can be compelled to share it" —
  we solved it by eliminating the company entirely
- Encryption at rest (pgcrypto/LUKS) is not used, but the threat model (physical access to
  a home HTPC) doesn't justify the operational cost. Health data in isolation is worthless
  to a random thief — its value is in aggregate at scale, which is what companies/brokers want.

---

## 3. Garmin 745 — Device Capabilities

### Sensors & Data

| Data Type | Capability | Notes |
|-----------|------------|-------|
| Heart Rate | 24/7 wrist HR (Elevate v3) | More accurate than Colmi |
| GPS | Multi-constellation GNSS (GPS + GLONASS + Galileo, **single-frequency**) | Full track recording. Not dual-band/multi-band (that arrived with FR255/955, Fenix 7 era, 2022) |
| Barometer | Barometric altitude | Elevation, stairs, climbs |
| Accelerometer | Activity detection, running dynamics | Cadence, stride length |
| Gyroscope | Running dynamics | Ground contact time, vertical oscillation |
| Pulse Ox (SpO2) | Wrist-based blood oxygen | Available |
| Temperature | Skin temp (during training) | Limited use outside workouts |
| Stress | Garmin stress score | Proprietary, 0-100 |
| Body Battery | Energy reserve estimate | Proprietary, based on HRV/stress |
| Sleep | Sleep stages + score | Light/deep/REM/awake |

### Activity/Sport Data (unique to Garmin, Colmi cannot provide)

- GPS track points (lat/lon per second during activity)
- Lap splits (per-km or per-mile pace, HR per lap)
- Running dynamics (cadence, stride length, ground contact time, vertical oscillation)
- Training effect (aerobic + anaerobic)
- VO2 max estimation
- Lactate threshold estimation
- Barometric elevation profiles (gain/loss, grade)
- Course mapping and route history

### Connectivity

- **Bluetooth** — Primary sync to Garmin Connect via phone app
- **ANT+** — Broadcasts HR/steps to external receivers (live only, no historical backfill)
- **USB** — Mounts as mass storage, FIT files accessible directly
- **No Wi-Fi** — The 745 lacks Wi-Fi. This is significant for privacy (see below).

### Trade-offs of Disabling Bluetooth

| Feature Lost | Impact |
|--------------|--------|
| Smart notifications, weather, music controls | Not used |
| Garmin algorithms (Training Readiness, Body Battery) | Biggest miss, but we have our own |
| Over-the-air firmware updates | Net positive (avoids unwanted changes) |
| Social/Strava auto-sync | Not used |

With Bluetooth disabled:
- No phone sync → no Garmin Connect cloud upload
- No Wi-Fi (745 doesn't have it) → no alternate cloud path
- Data leaves the watch **only via USB cable** → fully local
- The Forerunner 745 becomes a pure data capture device with zero cloud leakage

---

## 4. Data Sync Options

### Option A: Garmin Connect API (Cloud-Mediated Backfill)

- Use `garminconnect` (Python) or `garmin_client` (Rust) to authenticate to Garmin Connect
- Pull activities, daily health metrics, sleep, HR, stress, HRV, SpO2
- Runs as a one-time backfill or recurring cron
- **Privacy:** Garmin already has this data; pulling a copy doesn't change the privacy picture
- **Effort:** Medium — libraries exist (`garminconnect` Python, `garmin_client` /
  `garmin_download` Rust), **but** Garmin Connect enforces per-session download limits (one
  endpoint per session token; repeated OAuth token requests trigger multi-hour lockouts) and now
  commonly requires email 2FA on new logins, which the older username/password flows in these
  crates don't handle. A backfill needs throttling + a 2FA story.
- **Use case:** Historical backfill + bridge until private sync is built

### Option B: USB + FIT Files (Direct, Private)

- Plug 745 into any computer via USB → mounts as flash drive
- Copy `.FIT` files from `Garmin/Activities/`, `Garmin/Monitor/`, `Garmin/Health/`
- Parse with FIT SDK (Python: `garmin-fit-sdk`, Rust: `fitparser`)
- **Privacy:** Data never touches Garmin's cloud
- **Effort:** Low — well-documented file format, mature parsers
- **Use case:** Private ongoing sync (with BT disabled on watch)

### Option C: Gadgetbridge (Open-Source BLE Sync)

- Open-source Android app that has reverse-engineered the Garmin BLE protocol
- Replaces Garmin Connect on the phone — pairs directly with watch over BLE
- Can auto-export FIT files to local storage
- **Privacy:** Bypasses Garmin cloud entirely; no vendor app required
- **Effort:** Medium — Gadgetbridge works, but needs a bridge to get files to the server
- **745 Status:** **Initial support shipped** — Freeyourgadget release notes now list the
  Forerunner 745 alongside Venu 4, Descent G2, Epix, Fenix 6 Pro, Quatix 8, etc. under "Initial
  support." This is no longer hypothetical; on-device verification of *which* features work (FIT
  sync vs. real-time HR/stress/etc.) is still wanted, but Gadgetbridge is now the leading Phase 2
  candidate rather than a maybe.
- **Use case:** Wireless private sync — preferred Phase 2 path (pending on-device verification)

### Option D: Custom BLE Client (Python/Rust)

- Implement the Garmin BLE protocol directly using `bleak` (Python) or `btleplug` (Rust)
- Protocol is fully documented by Gadgetbridge (see §5)
- **Privacy:** Fully private, wireless, no intermediary
- **Effort:** High — protocol is complex (COBS encoding, CRC, Multi-Link/MLR transport,
  protobuf messages). Weeks of work.
- **Use case:** Future option for fully autonomous wireless sync

### Option E: ANT+ Live Stream

- The 745 broadcasts HR/steps over ANT+ to any receiver
- Live-only — no historical data
- **Use case:** Supplement, not primary sync. Limited utility for our pipeline.

### Comparison Matrix

| Option | Bypasses Cloud? | Wireless? | Automation | Effort | 745 Ready? |
|--------|:---:|:---:|:---:|:---:|:---:|
| A. Garmin Connect API | ❌ | ✅ | ✅ | Low | ✅ |
| B. USB + FIT | ✅ | ❌ | ❌ | Low | ✅ |
| C. Gadgetbridge | ✅ | ✅ | ✅* | Medium | ✅ (initial) |
| D. Custom BLE Client | ✅ | ✅ | ✅ | High | N/A |
| E. ANT+ Live | ✅ | ✅ | ✅ | Low | ✅ (limited) |

*Gadgetbridge auto-export needs a phone→server bridge (Tasker, Syncthing, or custom script).

---

## 5. Garmin BLE Protocol — Reverse Engineering Status

The Garmin BLE protocol has been substantially reverse-engineered by the **Gadgetbridge**
(Freeyourgadget) project. Full protocol documentation is published at:
<https://gadgetbridge.org/internals/specifics/garmin-protocol/>

### Protocol Generations

Three families identified:

1. **Older Protocol** — Uses separate BLE characteristics per data type. Used on legacy
   wearables (Vivomove HR era). This was the first protocol Gadgetbridge implemented.

2. **Multi-Link (ML) Protocol** — Multiplexes all data over shared characteristics using
   handle-based "threads." The **Forerunner 745 uses this generation.** (Protocol was
   documented from a Forerunner 245, firmware 13.00, same generation as the 745.)

3. **Multi-Link Reliable (MLR)** — Adds retransmission, acknowledgment, sequencing on top
   of ML. Used on newer devices (Venu 3 era).

### Protocol Stack

```
BLE Service (6A4E2800-667B-11E3-949A-0800200C9A66)
  └─ Multi-Link Protocol (ML)
       ├─ Handle Management (service registration, close handles)
       │    ├─ Register service request/response (client_uuid + service ID → handle)
       │    ├─ Close handle request/response
       │    └─ Error responses (unknown handle, protocol error)
       │
       └─ GFDI (Garmin Fit Data Interface)
            ├─ COBS-encoded message framing
            ├─ CRC-16 checksums
            ├─ Message types (with 5-bit sequence numbers):
            │    ├─ 5007: Directory Filter
            │    ├─ 5008: Set File Flags (read/write/archive/erase)
            │    └─ 5000: Response (ACK/NAK/UNKNOWN/ERROR)
            └─ Protobuf payloads (health data, settings, device info)
```

### BLE Characteristics

The protocol exposes three pairs of read/write characteristics (plus optional extra pairs
on newer devices):

| Write Char | Read Char | Purpose |
|------------|-----------|---------|
| 2820 | 2810 | Pair 1 (primary) |
| 2821 | 2811 | Pair 2 |
| 2822 | 2812 | Pair 3 |

The 745 (same family as FR245) uses the standard 3-pair configuration.

### Available Services (by service ID)

| ID | Service Name |
|----|-------------|
| 1 | **GFDI** (file transfer — FIT files) |
| 2 | NFC |
| 3 | HEALTH_SDK |
| 4 | REGISTRATION |
| 5 | CONNEXT |
| 6 | REAL_TIME_HR |
| 7 | REAL_TIME_STEPS |
| 8 | REAL_TIME_CALORIES |
| 9 | REAL_TIME_FLOORS |
| 10 | REAL_TIME_INTENSITY |
| 11 | REAL_TIME_DUMMY |
| 12 | REAL_TIME_HRV |
| 13 | REAL_TIME_STRESS |
| 14 | AUTH_STATUS |
| 15 | ECHO |
| 16 | REAL_TIME_ACCELEROMETER |
| 17 | REAL_TIME_SPAM |
| 18 | REAL_TIME_BMX_RAW |
| 19 | REAL_TIME_SPO2 |
| 20 | REAL_TIME_BODY_BATTERY |
| 21 | REAL_TIME_RESPIRATION |
| 22 | KEEP_ALIVE |
| 26 | REAL_TIME_ACTIVE_TIME |

The Forerunner 245 (745's sibling) supports: `GFDI, REGISTRATION, REAL_TIME_{HR, STEPS,
CALORIES, INTENSITY, HRV, STRESS, ACCELEROMETER, SPO2, BODY_BATTERY, RESPIRATION},
KEEP_ALIVE`.

### FIT File Transfer via BLE

The GFDI service supports full file operations over BLE:

- **Directory listing** (message 5007) — list available files with filtering
- **File flags** (message 5008):
  - `0x04` CRYPTO
  - `0x08` APPEND
  - `0x10` ARCHIVE
  - `0x20` ERASE
  - `0x40` WRITE
  - `0x80` READ

This means FIT files can be pulled from the watch over BLE without any cloud involvement —
the same data that's available via USB is available wirelessly once the protocol is
implemented.

### Message Encoding

GFDI messages use:
- 2-byte length field
- 2-byte message type field (can include 5-bit sequence number via `byte & 0x80` flag)
- Message-specific payload
- 2-byte CRC-16 (using `crc-16` from `python-crcmod` or equivalent)
- **COBS encoding** — splits at zero bytes, max chunk 254 bytes

### MLR (Multi-Link Reliable) Transport

Newer devices use MLR instead of plain ML. MLR adds:
- 2-byte header per chunk: handle (3 bits) + request number (6 bits) + sequence number (6 bits)
- Stateful acknowledgment (req_num acknowledges all sequences < req_num)
- Retransmission with exponential backoff (500ms → 20s cap)
- Dynamic congestion control (max unacked budget, halved on timeout)
- In-order delivery with sequence tracking

### What's Missing / Unknown

- **GFDI message details beyond 5007/5008:** The full set of protobuf message types for
  health data sync (activity uploads, sleep data, HRV records) is not fully documented on
  the protocol page. Gadgetbridge's source code would contain the implementations.
- **Third protocol variant:** A third version adds sequence bytes between handle and
  payload (issue #3063 on Gadgetberg). May affect newer firmware versions.
- **745-specific testing:** The 745 now has "initial support" in Gadgetbridge releases, but
  nobody has confirmed which services (FIT file sync vs. the real-time HR/stress/HRV/etc.
  streams) actually work end-to-end on it.

### Gadgetbridge's Implementation

Gadgetbridge (Java/Kotlin, Android) is the only working open-source implementation:
- Repository: <https://codeberg.org/Freeyourgadget/Gadgetbridge>
- Language: Java + Kotlin (Android app)
- Garmin support added progressively through 2025-2026
- Supports: device pairing, FIT file sync, activity/sleep tracking, notifications
- **Not ported to** Python, Rust, or any non-Android platform

### Other Reverse Engineering Efforts

| Project | Language | Scope | Status |
|---------|----------|-------|--------|
| **Gadgetbridge** | Java/Kotlin | Full protocol (ML + MLR + GFDI + protobuf) | Active, production |
| **mjsir911/GarminBLE** | Python + Wireshark/Lua | Vivofit3 protocol brain dump | Abandoned (4 commits) |
| **gwerneckp/garmin-ble** | Python | BLE protocol guide | Minimal, incomplete |

---

## 6. Schema & Multi-Source Architecture

### Storage Layer: Already Multi-Source Ready

The current schema (in `db/init.sql`) was designed with multi-source **storage** from day one.
Every raw data table has a `source TEXT DEFAULT 'ring'` column with `UNIQUE (ts, source)`
constraints, so ring / phone / garmin records can coexist without clobbering each other:

| Table | Unique Constraint |
|-------|-------------------|
| `raw_heart_rate` | `UNIQUE (ts, source)` |
| `raw_hrv` | `UNIQUE (ts, hrv_type, source)` |
| `raw_sleep` | `UNIQUE (start_ts, stage, source)` |
| `raw_steps` | `UNIQUE (ts, source)` |
| `raw_spo2` | `UNIQUE (ts, source)` |
| `raw_temperature` | `UNIQUE (ts, source)` |
| `raw_stress` | `UNIQUE (ts, source)` |
| `ring_goals` | N/A — ring-specific |
| `ring_status` | N/A — device-specific (battery, firmware) |

> ⚠️ **Resolution layer is NOT ready — this is the real blocker.** Storing a third source is
> trivial; *consuming* it correctly is not. Today every scorer reads `FROM raw_*` with **no
> `source` filter** (verified in `hrv.py`, `rhr.py`, `stress.py`, `heart_rate_zones.py`,
> `daily_activity.py`, `current_status.py`) and relies on `collector/analytics/dedupe.py`
> collapsing everything to one row per timestamp *first*. That dedupe is **hardcoded binary** —
> it deletes `'phone'` rows wherever a `'ring'` row exists, nothing more. A third `'garmin'`
> source has no resolution rule, so overlapping ring + garmin readings at the same instant would
> both survive → every daily score (HRV, RHR, strain, readiness…) **double-counts**.
> Generalizing this is the single largest piece of missing work and must land **before** any
> overlapping Garmin data enters the raw tables. See **Phase 0** (§10).

**New tables needed** for Garmin activity/sport data: GPS track points, lap splits, running
dynamics, training effect — these have no equivalent in the current schema.

### Proposed New Tables for Activity Data

```sql
-- Activity sessions (runs, rides, etc.)
CREATE TABLE IF NOT EXISTS activities (
    id BIGSERIAL PRIMARY KEY,
    source TEXT NOT NULL DEFAULT 'garmin',  -- 'garmin' | 'colmi' (future)
    activity_type TEXT NOT NULL,            -- 'running' | 'cycling' | 'walking'
    start_ts TIMESTAMPTZ NOT NULL,
    duration_s INT NOT NULL,
    distance_m INT,                         -- total distance (meters)
    calories INT,
    avg_hr INT,
    max_hr INT,
    avg_cadence INT,                        -- steps/min or rpm
    avg_pace_s_per_km INT,                  -- seconds per km
    elevation_gain_m INT,                   -- barometric
    elevation_loss_m INT,
    avg_contact_time_ms INT,                -- ground contact time (running dynamics)
    avg_vertical_oscillation_mm INT,
    avg_stride_length_cm INT,
    training_effect_aerobic NUMERIC(3,1),
    training_effect_anaerobic NUMERIC(3,1),
    vo2_max NUMERIC(4,1),
    raw_json JSONB,                         -- full raw payload for replay
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (source, start_ts)
);

-- Per-lap data (splits within an activity)
CREATE TABLE IF NOT EXISTS activity_laps (
    id BIGSERIAL PRIMARY KEY,
    activity_id BIGINT NOT NULL REFERENCES activities(id) ON DELETE CASCADE,
    lap_index INT NOT NULL,
    start_ts TIMESTAMPTZ NOT NULL,
    duration_s INT NOT NULL,
    distance_m INT,
    calories INT,
    avg_hr INT,
    max_hr INT,
    avg_pace_s_per_km INT,
    elevation_gain_m INT,
    UNIQUE (activity_id, lap_index)
);

-- GPS track points (for route maps)
CREATE TABLE IF NOT EXISTS activity_trackpoints (
    id BIGSERIAL PRIMARY KEY,
    activity_id BIGINT NOT NULL REFERENCES activities(id) ON DELETE CASCADE,
    ts TIMESTAMPTZ NOT NULL,
    lat NUMERIC(10,7) NOT NULL,
    lon NUMERIC(10,7) NOT NULL,
    altitude_m NUMERIC(7,2),                -- barometric
    hr INT,
    speed_mps NUMERIC(5,2),                 -- meters per second
    cadence INT
);
CREATE INDEX idx_trackpoints_activity ON activity_trackpoints(activity_id, ts);

-- Per-second activity HR (finer granularity than 5-min raw_heart_rate)
CREATE TABLE IF NOT EXISTS activity_hr (
    id BIGSERIAL PRIMARY KEY,
    activity_id BIGINT NOT NULL REFERENCES activities(id) ON DELETE CASCADE,
    ts TIMESTAMPTZ NOT NULL,
    hr INT NOT NULL,
    UNIQUE (activity_id, ts)
);
CREATE INDEX idx_activity_hr_activity ON activity_hr(activity_id, ts);
```

> **Relationship to `docs/ACTIVITY_DETECTION_RESEARCH.md`:** that doc derives activity/strain
> **from the Colmi ring** (HR-zone minutes → Edwards TRIMP strain in the already-running
> `heart_rate_zones` table; planned `activity_segments` for walk/run blocks). These are
> **different calculations from different sources** — the Garmin tables above hold structured
> sport sessions the ring cannot produce. They coexist fine today; merging them into one unified
> strain number needs new math and is out of scope here (far future, if ever).

> **Note:** Computed metric tables (`daily_recovery`, `sleep_quality`, `heart_rate_zones`,
> `strain_trend`, `readiness_score`) use `day DATE` primary keys; `current_status` is the
> exception (`id BIGSERIAL`, one row per analytics pass). They are "source-agnostic" only in the
> sense that they read whatever the dedupe stage left behind — they do not themselves pick a
> source. See Phase 0 (§10).

### Source-Aware Analytics

The analytics pipeline would need a "source preference" strategy:
- For HR during sleep → prefer Colmi (more comfortable, continuous overnight)
- For HR during activity → prefer Garmin (Elevate v3, more accurate during movement)
- For stress → Garmin stress score + Colmi stress value → corroboration
- For sleep → prefer Colmi (comfortable, continuous temp)
- For HRV → prefer whichever has fresher/more data
- For steps → cross-validate, take max (Colmi counts differently than Garmin)
- For training load → Garmin only (GPS pace, altitude, training effect)
- Redundancy: if one device is off/not worn, use the other. Analytics don't break — just
  lower confidence.

This preference strategy is **not implemented** today and is the substance of **Phase 0** (§10).
Until it exists, Garmin data must be kept out of the shared raw tables during any window where
both devices are worn, or the source-blind scorers will double-count. The Garmin-only tables
(`activities`, `activity_laps`, `activity_trackpoints`) are safe to ingest at any time because
no existing scorer reads them.

---

## 7. Rust Ecosystem

### Available Crates

| Crate | Purpose | Status | Link |
|-------|---------|--------|------|
| **`fitparser`** | FIT file parsing (serde-based) | Active, maintained | [crates.io](https://crates.io/crates/fitparser) · [GitHub](https://github.com/stadelmanma/fitparse-rs) |
| **`garmin_client`** | OAuth2 Garmin Connect authentication | On crates.io | [crates.io](https://crates.io/crates/garmin_client) |
| **`garmin_download`** | Health data download from Garmin Connect | On crates.io | [docs.rs](https://docs.rs/garmin_download) |
| **`garmin-cli`** | CLI for activities + health metrics | Active | [GitHub](https://github.com/vicentereig/garmin-cli) |
| **`btleplug`** | Cross-platform BLE | Mature | [crates.io](https://crates.io/crates/btleplug) |
| **`tokio-postgres`** | Async PostgreSQL client | Industry standard | [crates.io](https://crates.io/crates/tokio-postgres) |

### Reference Project: fit-dashboard

**[arpanghosh8453/fit-dashboard](https://github.com/arpanghosh8453/fit-dashboard)** — A
standalone offline Garmin analytics tool built in Rust:
- Uses `fitparser` natively for FIT file extraction
- Local storage (no cloud dependency)
- Health data analysis without vendor lock-in
- Same philosophy as our smart-ring project
- Dev.to writeup: [Local Analysis of Garmin Activities and Fitness Data without
Cloud](https://dev.to/arpandesign/local-analysis-of-garmin-activities-and-fitness-data-without-cloud-4cap)

### Reference Project: Rust-Garmin

**[poster515/Rust-Garmin](https://github.com/poster515/Rust-Garmin)** — Rust library for
downloading Garmin Connect data:
- Downloads activities and monitoring FIT files
- Stores into InfluxDB (we'd use Postgres instead)
- Key insight from author: "FIT files contain everything you need — the JSON files
  downloaded are good to have as a reference"

### Architecture: Rust Garmin Collector

```
┌─────────────────────────────────────────────┐
│           Rust Garmin Collector              │
│                                             │
│  ┌──────────────┐    ┌──────────────────┐   │
│  │ garmin_client │───>│  Garmin Connect  │   │
│  │ (OAuth2)     │    │  API (backfill)  │   │
│  └──────────────┘    └──────────────────┘   │
│                                             │
│  ┌──────────────┐    ┌──────────────────┐   │
│  │  fitparser   │───>│  FIT Files       │   │
│  │  (parsing)   │    │  (USB / Gadgetbr.)│  │
│  └──────────────┘    └──────────────────┘   │
│                                             │
│  ┌──────────────┐    ┌──────────────────┐   │
│  │tokio-postgres│───>│  Postgres        │   │
│  │ (db writes)  │    │  (shared DB)     │   │
│  └──────────────┺───────────────────┘   │
│                                             │
│  ┌──────────────┐    ┌──────────────────┐   │
│  │  btleplug    │───>│  BLE (future)    │   │
│  │  (future)    │    │  Direct to watch │   │
│  └──────────────┘    └──────────────────┘   │
└─────────────────────────────────────────────┘
```

The collector would be a single compiled binary running on the HTPC alongside the Python
Colmi collector. Both write to the same Postgres instance with different `source` values.

### Why Rust Over Python for This Module

- Single compiled binary — no venv/dependency management
- Fast FIT parsing — FIT files can be large (activities with GPS at 1Hz)
- Future BLE implementation reuses same language + Postgres code
- Sz prefers Rust over Python (per user preference)
- Clean separation from Python Colmi collector — no shared runtime
- `fitparser` + serde gives type-safe parsing vs Python's dict-based approach

---

## 8. Geo-API Integration for Activity Maps

The existing geo-api (maps.ogsapps.cc, running on geo-ogs VPS) provides everything needed
to render Garmin activity maps without any external mapping service:

### Available Geo-API Capabilities

| Capability | API Endpoint | Data Source |
|------------|-------------|-------------|
| Map tiles | Leaflet + Voyager tiles | Existing bike-map pattern |
| Elevation lookup | `/api/elevation` | 17GB elevation DB (BC TRIM + CDEM) |
| Route rendering | Polylines on Leaflet map | Existing bike-map pattern |
| Elevation profiles | SVG grade-colored profiles | bike-map slide-up panel pattern |
| POI lookup | `/api/...` (various) | OSM POIs, GNIS, custom places |

### Integration Pattern

The smart-ring dashboard would reuse the bike-map's proven patterns:
1. Activity GPS track points → polyline on Leaflet map
2. Track points → geo-api `/api/elevation` → SVG elevation profile with grade coloring
3. Lap markers overlaid on route + elevation profile
4. HR zones color-coded along the route

No new infrastructure needed — geo-api already serves bike.ogsapps.cc with exactly this
pattern. The smart-ring dashboard would call `maps.ogsapps.cc/api/...` directly from the
browser (same as bike-map does).

### Coordinate Convention

Geo-API uses `[lon, lat]` ordering (consistent across all databases and API endpoints).
FIT files store coordinates as `semicircles` (lat/lon as sint32, where 1 semicircle =
180/2^31 degrees). The Rust collector would convert during ingestion.

### No External Dependencies

- No Google Maps API key
- No Mapbox token
- No Strava API
- No third-party tile servers
- Only our own geo-api + Leaflet (open-source, self-hosted tiles possible)

---

The result: fully self-hosted health tracking with maps — no external API calls.

---

## 9. Cross-Device Data Fusion

With both the Colmi R09 and Garmin 745 feeding the same Postgres tables, several fusion
strategies become possible:

### 9.1 Complementary Coverage

The two devices have complementary wear patterns:
- **Colmi** is worn 24/7 (sleep, overnight HRV, continuous HR, skin temp)
- **Garmin** is worn for training (GPS tracks, running dynamics, activity HR)

When both are worn simultaneously, there are overlapping data windows. When only one is
worn, the other provides coverage.

### 9.2 Cross-Validation

Both devices measure heart rate independently. During overlapping wear windows:
- Compare HR readings → detect sensor anomalies (cadence lock on watch, poor contact on ring)
- Flag low-confidence readings automatically
- Build trust scores per device per metric type
- Use divergence as a data quality signal

### 9.3 Source Preference Strategy

Not all sources are equal for all metrics:

| Metric | Preferred Source | Rationale |
|--------|-----------------|-----------|
| Sleep HR | Colmi | Comfortable, continuous overnight wear |
| Activity HR | Garmin | Elevate v3 more accurate during movement |
| Resting HR | Either | Use freshest data |
| HRV | Either | Use freshest/most data; prefer Colmi overnight |
| Steps | Garmin (activity), Colmi (daily) | Different counting algorithms |
| Stress | Both | Corroboration; Garmin's proprietary score vs Colmi's |
| Sleep stages | Colmi | More comfortable, continuous temp data |
| Training load | Garmin | GPS pace, altitude, training effect |
| SpO2 | Either | Cross-validate |
| Temperature | Colmi | Continuous skin temp; Garmin only during training |

### 9.4 Redundancy and Graceful Degradation

- Forgot to charge/wear one device? The other covers.
- Analytics don't break — they degrade gracefully with a confidence drop.
- The `readiness_score.confidence` column already supports `'full' | 'partial'`.
- ⚠️ The `data_quality` table currently keys on `(day, data_type)` with **no `source` column**
  — so per-source freshness tracking needs a schema change to `(day, data_type, source)`. This
  is rolled into Phase 0.

### 9.5 Samsung-Style Merge

Samsung Galaxy Watch + Ring offer a "best of both" merged view. Our approach would be
similar but transparent — the user can see exactly which source was used for each data
point, and the fusion logic is auditable (not a black box).

---

## 10. Recommended Approach

### Phase 0: N-Source Resolver (Prerequisite — gate Phase 1 overlap on this)

**Goal:** Stop the analytics pipeline from double-counting the moment a third source exists.

The raw tables will happily store ring + garmin at the same timestamp (the `UNIQUE (ts, source)`
constraint allows it), but every scorer then sees two measurements per slot and double-counts.
Generalize the resolution stage **before** overlapping Garmin data lands in `raw_*`:

- Replace the hardcoded `ring > phone` collapse in `collector/analytics/dedupe.py` with an
  N-source preference resolver driven by a per-metric, per-time-window rule table (e.g.:
  sleep-window HR → prefer `ring`; activity-window HR → prefer `garmin`; HRV overnight → prefer
  `ring`; steps → max of sources; training load → `garmin` only).
- Emit the resolved set the same way dedupe does today (delete non-preferred rows pre-score, or
  materialize a `preferred_*` view) so existing scorers keep reading `FROM raw_*` with **no
  source filter** and still see one measurement per slot. Zero scorer changes.
- Add `source` to `data_quality` → `(day, data_type, source)` so freshness is reported per
  source instead of collapsed.

**If Phase 0 is deferred:** Phase 1 may still run, but it must ingest **only Garmin-only
tables** (`activities`, `activity_laps`, `activity_trackpoints`) and Garmin metrics during
windows the ring provably wasn't worn. Keep overlapping Garmin HR / HRV / steps / stress **out**
of `raw_*` until the resolver exists, or daily scores silently corrupt.

### Phase 1: Garmin Connect API Backfill (Now)

**Goal:** Get all historical data into Postgres immediately.

Garmin already has the data — pulling a copy doesn't change the privacy picture. We do the
remapping work once and get immediate value.

- Language: **Rust** (per Sz's preference)
- Crates: `garmin_client` / `garmin_download` for API access
- Pull: activities (FIT files), daily health metrics (sleep, stress, HRV, HR, SpO2)
- Map: Garmin JSON/FIT → existing raw tables with `source = 'garmin'`
- New tables: `activities`, `activity_laps`, `activity_trackpoints`, `activity_hr` (for
  structured sport data)
- Deploy: Single Rust binary on HTPC, runs on demand or cron

**Privacy justification:** This is a one-time copy of data Garmin already has. After this
backfill, new data can be captured privately going forward.

### Phase 1.5: Daily Monitoring Files (Metrics/ + Sleep/) — DEFERRED

**Status (as of 2026-07-30): framework shipped, extractors pending.**

The 745 also writes daily summary files to `Garmin/Metrics/` (~100 files
covering ~24 days of daily summaries) and one `Garmin/Sleep/` file. These
contain the per-day HR, HRV, SpO2, body battery, overnight skin temp, and
sometimes step totals that would map to the existing `raw_*` tables with
`source='garmin'`.

**Blocker: FIT SDK profile mismatch.** The monitoring files use new FIT
SDK message types (global_id 229, 232, 281, 294, 339, 356, etc.) that
post-date the public FIT SDK profile bundled with `fitparse` (21.60) and
`fitparser` Rust crate. The binary format is stable and we can read
the raw field IDs, but without a profile we don't know what each field
*means*:

- `global_id 232 (Hr)`: fids 5,6,7,8 are HR values (67, 218, 263...) — the
  scale is unclear (daily min/avg/max? 5-min samples?)
- `global_id 281 (Hrv)`: all fids 0-3 are UINT32Z nulls in our sample
- `global_id 339 (HsaSpo2Data)`: fids 1,2,3,4 are 1785, 3964, 9636, 22995
  — too large for SpO2% (90-100), may be seconds-in-zone
- `global_id 356 (SkinTempOvernight)`: fids 2,3 are 1268600, 4380400 —
  too large for centi-degrees, may be time-weighted temps

**What `collector/garmin/monitoring.py` does ship today:**
- File discovery (Metrics/ + Sleep/ subdirs)
- fit_tool-based record reader (extracts global_id + field IDs)
- `ParsedMonitoring` dataclass with hr/hrv/spo2/temp/steps lists
- Per-message extractor functions (`_extract_hr`, `_extract_hrv`, etc.)
  that are *wired up* but currently return empty for the unknown
  field-ID reason above
- 15 unit tests pinning the framework's contract

**To unblock (one of these):**
1. **Drop in a newer FIT SDK profile** (21.202+ has full message
   definitions for these gids). Would require forking `fitparse` to
   bundle the new profile, or switching to the Rust `fitparser` crate
   which already uses 21.202.
2. **Decode against reference data** — pull a known day's HRV / SpO2
   / temp from Garmin Connect (or compare against the user's ring's
   overnight readings for the same night) and hand-decode the field
   IDs. ~1 day of work but produces a permanent local mapping.
3. **Bridge to Gadgetbridge's data model** — Gadgetbridge has
   already reverse-engineered these messages for the 745
   (`codeberg.org/Freeyourgadget/Gadgetbridge`). Reading their source
   would give us the field mappings for free.

Recommended: option 1 (the Rust port) since Phase 2 is heading that
way anyway. Once the Rust `fitparser` crate handles these gids, the
Python monitoring.py becomes the spec and the Rust version replaces
it.

### Phase 1.6: Upload UI (Optional, Low Priority)

- Drag-and-drop FIT file upload on the React dashboard
- New `POST /upload/fit` endpoint on FastAPI
- Uses existing `sync_requests` queue for async processing
- Allows manual USB sync without running the CLI on the HTPC

### Phase 2: Private Sync (Future)

**Goal:** Stop sending new data to Garmin's cloud.

Pick one based on what's easiest when the time comes:

**Option 2A — Gadgetbridge (if 745 confirmed working):**
- Install Gadgetbridge on phone, pair 745
- Disable Garmin Connect app
- Gadgetbridge auto-exports FIT files to phone storage
- Bridge to server (Syncthing / Tasker / script)

**Option 2B — USB + FIT (always works):**
- Disable BT on 745
- Periodic USB sync → upload to dashboard or direct file drop
- Collector binary parses FIT → Postgres

**Option 2C — Custom BLE (if we want wireless):**
- Implement Garmin ML protocol in Rust using `btleplug`
- Protocol is fully documented (Gadgetbridge spec)
- Pull FIT files over BLE directly on the HTPC
- Reuses same FIT parsing + Postgres code from Phase 1

### Phase 3: Cross-Device Analytics (Future)

- Source preference logic in analytics pipeline
- Cross-validation and trust scoring
- Merged dashboard views (Samsung-style)
- Activity maps via geo-api integration
- Enhanced readiness/strain with richer Garmin inputs

---

## Appendix A: Key Links

| Resource | URL |
|----------|-----|
| EFF Wearable Privacy Report | <https://www.eff.org/deeplinks/2026/07/most-smart-watches-rings-and-bands-lack-basic-transparency-reports-and-key-privacy> |
| Gadgetbridge Garmin Protocol Doc | <https://gadgetbridge.org/internals/specifics/garmin-protocol/> |
| Gadgetbridge Garmin Devices Page | <https://gadgetbridge.org/gadgets/wearables/garmin-watches/> |
| Gadgetbridge Repository (Codeberg) | <https://codeberg.org/Freeyourgadget/Gadgetbridge> |
| fitparser (Rust FIT parser) | <https://crates.io/crates/fitparser> |
| garmin_client (Rust) | <https://crates.io/crates/garmin_client> |
| garmin_download (Rust) | <https://docs.rs/garmin_download> |
| garmin-cli (Rust CLI) | <https://github.com/vicentereig/garmin-cli> |
| fit-dashboard (Rust reference project) | <https://github.com/arpanghosh8453/fit-dashboard> |
| Rust-Garmin (Rust reference project) | <https://github.com/poster525/Rust-Garmin> |
| mjsir911/GarminBLE (Wireshark plugin) | <https://github.com/mjsir911/GarminBLE> |

---

## Appendix B: Garmin 745 Service List (Expected)

Based on Forerunner 245 (same generation, firmware 13.00):

| Service ID | Name |
|------------|------|
| 1 | GFDI |
| 4 | REGISTRATION |
| 6 | REAL_TIME_HR |
| 7 | REAL_TIME_STEPS |
| 8 | REAL_TIME_CALORIES |
| 10 | REAL_TIME_INTENSITY |
| 12 | REAL_TIME_HRV |
| 13 | REAL_TIME_STRESS |
| 16 | REAL_TIME_ACCELEROMETER |
| 19 | REAL_TIME_SPO2 |
| 20 | REAL_TIME_BODY_BATTERY |
| 21 | REAL_TIME_RESPIRATION |
| 22 | KEEP_ALIVE |
