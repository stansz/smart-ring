# Activity Detection — Research & Implementation Plan

> How rings/watches/trackers do activity detection, and what's feasible for the
> Colmi R09 given its sensor limitations. Research conducted 2026-07-26.

---

## 1. The Fundamental Constraint

The Colmi R09 **cannot store raw accelerometer data**. The RF03 SoC has an
accelerometer, but it's real-time streaming only — 512KB flash can't hold
continuous waveform data, and streaming it drains the 15mAh battery in ~4–6 hours.

This is a critical difference from every commercial wearable. All of them —
Oura, WHOOP, Apple Watch, Fitbit, Garmin — use accelerometer motion signatures
as their **primary** sensor for activity detection. Heart rate is a secondary
confirmation signal.

So we need an approach that works from what the R09 **does** store:

| Sensor | Resolution | Slots/day |
|--------|-----------|-----------|
| Heart Rate | 5-min slots | 288 |
| Steps / Activity | 15-min slots (steps + calories + distance) | 96 |
| HRV | 30-min composite (0-255) | 48 |
| SpO₂ | Hourly % | 24 |
| Temperature | 30-min (completed days only) | 48 |
| Stress | 30-min (0-99) | 48 |

---

## 2. How Commercial Devices Do Activity Detection

| Device | Primary Sensor | Classification | Auto-detect? | Activity Types |
|--------|---------------|----------------|-------------|----------------|
| **Oura Ring** | Accelerometer + gyroscope | On-ring firmware ML | ✅ AAD (Gen 3+) | Walking, running, cycling |
| **Apple Watch** | Accel + gyro + GPS + HR | On-device CoreML | ✅ Auto start/stop | 10+ types |
| **WHOOP** | PPG HR + accelerometer | **None** — user tags | ❌ Manual only | User-labeled |
| **Fitbit** | Accelerometer | SmartTrack pattern matching | ✅ (10-15 min min) | Walk, run, bike, swim, elliptical |
| **Garmin** | Accelerometer + GPS | Move IQ event detection | ✅ (10 min min) | Walk, run, bike, swim, elliptical |

### Standard HAR Pipeline (with accelerometer)

When you have raw accelerometer data, the standard approach is:

1. **Sliding windows** over raw x/y/z (2–5 second windows)
2. **Feature extraction:** mean, std, skewness, kurtosis, zero-crossing rate, FFT peaks, spectral entropy
3. **Classification:** Random Forest, SVM, CNN, LSTM, or TCN
4. **Post-processing:** majority-vote smoothing over consecutive windows
5. **Time threshold:** ≥10 min sustained classification → label as activity

### WHOOP is the Exception

WHOOP notably does **NOT** auto-detect activities. Users must manually tag them.
Instead, WHOOP computes **Strain** (0–21) — a cardiovascular load score based
entirely on time spent in each HR zone. This model is the closest analog to
what's achievable with R09 data.

---

## 3. What's Feasible Without Accelerometer

Four viable approaches, ordered by complexity:

### 3.1 HR Zone Duration (WHOOP-style Strain)

Compute time spent in each HR zone (% of max HR) and produce a cardiovascular
load score.

**Pros:** Well-validated by exercise physiology; no ML needed; transparent.  
**Cons:** Cannot distinguish activity types; false positives from stress/anxiety/sauna.  
**Implementation effort:** Low (~50 lines, new DB table, piggybacks on `daily_activity`).

### 3.2 Step Cadence + HR Fusion ⭐ Recommended

The R09's step data is the differentiator. At 15-min resolution you can compute
cadence (steps/15min), then fuse with HR elevation to classify activity:

| Pattern | Step Cadence | HR Behavior | Classification |
|---------|-------------|-------------|----------------|
| High steps, moderate HR, sustained | >200/15min | resting + 20-40% | **Walking** |
| Very high steps, high HR, sustained | >400/15min | resting + 40-70% | **Running** |
| Low/zero steps, sustained elevated HR | <50/15min | resting + 30-60% | **Cycling / Strength** (ambiguous) |
| Any steps + HR not elevated | variable | near resting | **Not an activity** |
| HR elevated, zero steps, stress normal | — | elevated >30 min | **Non-exercise activity** |

**Algorithm outline:**

```
For each 15-min slot:
  cadence = steps / 15
  hr_elevation = hr_avg - rhr_baseline
  hrv_drop = baseline_hrv - current_hrv

Find contiguous blocks where:
  (cadence > threshold OR hr_elevation > threshold)
  for >= 30 minutes (2+ consecutive slots)

Classify each block:
  - High steps + high HR → running
  - Moderate steps + moderate HR → walking
  - Low/zero steps + sustained elevated HR → cycling/strength (ambiguous)
  - Sustained elevated HR + any step pattern → general_activity

Post-processing:
  - Merge adjacent blocks of same type
  - Enforce minimum 10-min block duration
  - Confidence = f(consistency, hrv_confirmation, number_of_slots)
```

**Pros:** Uses specific R09 stored data; distinguishes walking vs running vs
cycling; step cadence provides motion proxy without accelerometer.  
**Cons:** 15-min resolution limits precision; step data is zero-suppressed
(empty slots = unknown, not zeros); cycling/lifting cannot be told apart without
cadence sensor or GPS.  
**Implementation effort:** Medium (~150 lines, new `activity_segments` table + scorer module).

### 3.3 HR Temporal Pattern Recognition (ML-based)

Extract time-domain features from HR series over sliding windows (30–90 min):
rate of HR rise (first derivative), plateau duration, recovery slope, HR
variability within window (std dev), HRV depression magnitude.

Train a lightweight classifier (Random Forest or XGBoost) on labeled data:
resting, light activity, moderate exercise, vigorous exercise.

**Pros:** Generalizes beyond step data; captures exercise physiology principles.  
**Cons:** Requires labeled training data; individual calibration needed;
risk of overfitting to one person.  
**Implementation effort:** High (~300 lines + model training pipeline).

### 3.4 Per-Hour Anomaly Detection

Establish personal baselines for HR and steps per hour of day (partially done
in `daily_activity.hourly_steps` / `hourly_worn`). Flag hours where both metrics
significantly exceed the baseline.

**Pros:** No activity type labels needed; adapts to personal patterns; catches
unusual exertion even if not exercise.  
**Cons:** Requires weeks of baseline data; can't distinguish activity types;
false positives during unusual days (travel, illness).  
**Implementation effort:** Medium (~100 lines, extends existing hourly arrays).

---

## 4. Implementation Plan

### Phase 1: HR Zones & Strain Score

New module `collector/analytics/heart_rate_zones.py` and DB table:

```sql
CREATE TABLE heart_rate_zones (
    day DATE PRIMARY KEY,
    resting_hr INT,
    max_hr INT,
    zone1_min INT,     -- 50-60% HRR (very light)
    zone2_min INT,     -- 60-70% HRR (light)
    zone3_min INT,     -- 70-80% HRR (moderate)
    zone4_min INT,     -- 80-90% HRR (hard)
    zone5_min INT,     -- 90-100% HRR (maximum)
    strain_score NUMERIC(4,1),
    computed_at TIMESTAMPTZ DEFAULT NOW()
);
```

Karvonen formula: `target_HR = ((max_HR - resting_HR) × %intensity) + resting_HR`.  
Max HR: `max(observed, 220 - age)`. RHR: from `daily_activity.hr_min`.

### Phase 2: Activity Segment Detection

New module `collector/analytics/activity.py` and DB table:

```sql
CREATE TABLE activity_segments (
    id BIGSERIAL PRIMARY KEY,
    day DATE NOT NULL,
    start_ts TIMESTAMPTZ NOT NULL,
    end_ts TIMESTAMPTZ,
    duration_min INT,
    activity_type TEXT CHECK (activity_type IN (
        'walking','running','cycling','general_activity'
    )),
    confidence NUMERIC(3,2),   -- 0.00-1.00
    avg_hr INT,
    peak_hr INT,
    total_steps INT,
    avg_hrv INT,
    computed_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_activity_segments_day ON activity_segments(day DESC);
```

Plugs into `run_all()` pipeline after `daily_activity` and HRV are computed.

### Phase 3: ML Enhancement (optional, later)

Train a Random Forest on per-slot features to improve classification
confidence. Could use self-labeled activities as training data.

---

## 5. Pipeline Integration

```
raw_heart_rate + raw_steps + raw_hrv
    ├── daily_activity (existing)  → per-day aggregates, hourly arrays
    ├── heart_rate_zones (new)     → zone times, strain score
    ├── activity_segments (new)    → detected activities with confidence
    └── readiness_score (existing) → unchanged (excludes same-day activity)
```

Order in `run_all()`:
1. `daily_activity` (existing) — needed for HR aggregates, RHR baseline
2. `hrv` (existing) — needed for baseline HRV
3. `heart_rate_zones` (new)
4. `activity_segments` (new)
5. `readiness_score` (existing) — unchanged

---

## 6. Key Design Decisions

| Decision | Recommendation | Rationale |
|----------|---------------|-----------|
| Minimum activity duration | 30 min (2 × 15-min slots) | Commercial devices use 10 min, but 15-min R09 resolution means 2-slot minimum is more robust |
| Resting HR baseline | `daily_activity.hr_min` (overnight low) | Already computed; good enough for elevation detection |
| Step zero-suppression | Use `hourly_worn` for context | Ring only emits step samples for hours with activity; need wear detection to distinguish "quiet" from "off finger" |
| Cycling detection | Flag as "general_activity" with note | Elevated HR + zero steps is inherently ambiguous without cadence sensor |
| Max HR estimation | `220 - age` initially, use observed max when higher | Standard formula is population-level; individual max improves with use |

---

## 7. Sources & Confidence

| Topic | Confidence | Notes |
|-------|-----------|-------|
| Commercial device detection methods | HIGH | Public documentation, patents, reverse-engineering analyses |
| Karvonen HR zone formula | HIGH | Karvonen et al. 1957; ACSM guidelines; standard in exercise physiology |
| WHOOP strain model | MEDIUM | Public blog posts and engineering content; exact weights are proprietary |
| ML approaches to activity recognition | HIGH | Extensive IEEE/MDPI/JMIR literature — but almost all assume accelerometer |
| HRV dynamics during exercise | HIGH | HRV (RMSSD) drops during exercise, recovers post-exercise — well-established |
| Feasibility without accelerometer | MEDIUM | Novel application; validated by WHOOP's HR-only strain model but activity *type* classification without motion data is less proven |
