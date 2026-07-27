# Activity Detection — Research & Implementation Plan

> How rings/watches/trackers do activity detection, what's feasible for the
> Colmi R09, and a concrete build plan for Phase 1 (zones + strain) and
> Phase 2 (step+HR segments). Research 2026-07-26; plan revised same day
> after codebase review.

**Status:** design only — not implemented.  
**Out of scope here:** ML classifiers, same-day readiness coupling, calories as features.

---

## 1. The Fundamental Constraint

The Colmi R09 **cannot store raw accelerometer data**. The RF03 SoC has an
accelerometer, but it's real-time streaming only — 512KB flash can't hold
continuous waveform data, and streaming it drains the 15mAh battery in ~4–6 hours.

Commercial devices (Oura, Apple Watch, Fitbit, Garmin) use accel motion signatures
as the **primary** activity sensor; HR is secondary. WHOOP is the exception:
**no auto-detect** — users tag workouts; the product surface is **Strain**
(cardiovascular load from HR). That is the closest honest analog for the R09.

What the R09 **does** store:

| Sensor | Resolution | Slots/day | Notes |
|--------|-----------|-----------|--------|
| Heart Rate | 5-min | 288 | zeros skipped when invalid/no reading |
| Steps | 15-min | 96 | steps + cal + distance; **zero-suppressed** (no row ⇒ unknown, not zero) |
| HRV | 30-min composite | 48 | not ECG RMSSD; trend-only |
| SpO₂ | ~hourly | 24 | wear confirmation |
| Temperature | 30-min | 48 | completed days only for history |
| Stress | 30-min | 0–99 | soft veto only — not a classifier |

Finger step counts under-read vs wrist (known ring limitation). Do not ship
wrist-tracker step thresholds without calibrating on this user's data.

---

## 2. How Commercial Devices Do Activity Detection

| Device | Primary Sensor | Classification | Auto-detect? | Types |
|--------|---------------|----------------|-------------|--------|
| **Oura** | Accel + gyro | On-ring ML | ✅ AAD (Gen 3+) | Walk, run, cycle |
| **Apple Watch** | Accel + gyro + GPS + HR | CoreML | ✅ | 10+ |
| **WHOOP** | PPG + accel | **None** — user tags | ❌ | User-labeled |
| **Fitbit** | Accel | SmartTrack | ✅ (≥10–15 min) | Walk, run, bike, swim, elliptical |
| **Garmin** | Accel + GPS | Move IQ | ✅ (≥10 min) | Walk, run, bike, swim, elliptical |

### Standard HAR (with accelerometer) — not available to us

1. Sliding windows over raw x/y/z (2–5 s)  
2. Features: mean, std, ZCR, FFT peaks, spectral entropy  
3. Classifier + majority-vote smoothing  
4. ≥10 min sustained → activity label  

### Strain analog (available)

WHOOP publishes that Strain (0–21) is driven by cardiovascular load / time in
HR zones. Exact weights are proprietary. **We implement a transparent
Edwards TRIMP-style score scaled to 0–21**, documented as a WHOOP-*like*
strain approximation — not WHOOP parity.

---

## 3. Feasible Approaches (summary)

| # | Approach | Ship? | Role |
|---|----------|-------|------|
| 3.1 | HR zone minutes + strain (Edwards TRIMP→0–21) | **Phase 1** | Daily cardiovascular load |
| 3.2 | 15-min step + HR fusion → activity segments | **Phase 2** | Walk / run / general blocks |
| 3.3 | ML on HR temporal features | Later only | Needs labeled N=1 set first |
| 3.4 | Per-hour HR/step anomaly | Optional later | No type labels |

Skipped for now: calories (firmware units broken until TASKS fix), confident
`cycling` labels (zero-step elevated HR is ambiguous), Phase 3 ML before a
manual-tag path exists.

---

## 4. Locked Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Strain formula | Edwards TRIMP: Σ (zone_minutes × zone_weight), scaled 0–21 | Transparent, testable; not proprietary WHOOP |
| Zone definition | Karvonen HRR %: Z1 50–60, Z2 60–70, Z3 70–80, Z4 80–90, Z5 90–100 | ACSM-style; thresholds recomputed daily |
| RHR baseline | **7-day median of prior days' `daily_activity.hr_min`** (exclude today). Fallback: prior-day `hr_min`, then 60 bpm | Avoids same-day circularity; `hr_min` is calendar-day min, not guaranteed overnight |
| Max HR | `max(220 - age, observed_max_30d)` from env `USER_AGE` (default 35 if unset) | Population bootstrap + individual lift |
| Slot grid | **15-minute** local-time slots | Native step resolution; 3× HR samples per slot |
| Wear at slot | Worn if **≥1 HR sample** in the 15-min window (optional: HRV≥15 or SpO2 85–100) | `hourly_worn` is too coarse (0/1 per hour) |
| Missing steps | If worn and no step row → steps = 0 for that slot | Corrects zero-suppression |
| Auto-segment min duration | **≥30 min (2 consecutive elevated/active slots)** | 15-min granularity; 1 slot is too noisy |
| Strain vs segments | Strain uses **all worn 5-min HR samples** (no 30-min gate). Segments need the 30-min gate | Short peaks still cost strain; labels need sustain |
| Activity types | `walking` \| `running` \| `general_activity` only | No `cycling` until user confirms / cadence exists |
| Step thresholds | **Bootstrap then calibrate** (see §6.2); not wrist defaults | Finger undercount |
| Idempotency | Zones: `ON CONFLICT (day) DO UPDATE`. Segments: `DELETE WHERE day = ?` then insert, or `UNIQUE (day, start_ts)` upsert | Analytics re-runs every poller pass |
| Readiness | **Unchanged** in Phases 1–2 (no same-day activity) | Prior-day strain as readiness pillar = Phase 4 later |
| Lookback | Last **14 days** per recompute (match `daily_activity`) | Fast; full history only if backfill script added |
| API + UI | Thin endpoints + strain on Activity hero / small card in Phase 1; segment markers in Phase 2 | Avoid orphan tables |

---

## 5. Pipeline Integration

### Production `run_all()` today

```
dedupe → hrv → sleep → stress → circadian → daily_activity
      → readiness → current_status → rhr → data_quality
```

HRV already runs **before** `daily_activity`; they are independent. New scorers
do **not** require reordering HRV.

### Target order (insert after `daily_activity`)

```
dedupe
  → hrv, sleep, stress, circadian          (existing)
  → daily_activity                         (existing — hr_min, steps context)
  → heart_rate_zones                       (Phase 1 — needs daily_activity RHR history)
  → activity_segments                      (Phase 2 — needs zones RHR/max + raw grid)
  → readiness, current_status, rhr, dq     (existing — still ignore same-day activity)
```

```
raw_heart_rate + raw_steps (+ wear proxies)
    ├── daily_activity      → day aggregates, hourly arrays
    ├── heart_rate_zones    → zone minutes, strain 0–21
    ├── activity_segments   → labeled blocks + confidence
    └── readiness           → unchanged until prior-day strain (later)
```

---

## 6. Algorithms (normative)

### 6.1 Phase 1 — Zones & Strain

**Inputs (per local calendar day, last 14 days):**

- All `raw_heart_rate` samples that day (`ts`, `bpm`), `bpm > 0`
- RHR = median of `daily_activity.hr_min` for the previous 7 days with non-null `hr_min`
- `max_hr = max(220 - USER_AGE, max(bpm) over last 30 days if any, RHR + 1)`
- `hrr = max_hr - rhr` (must be ≥ 1)

**Karvonen zone boundaries (bpm):**

```
z_lo(p) = rhr + hrr * p
Z1: [z_lo(0.50), z_lo(0.60))
Z2: [z_lo(0.60), z_lo(0.70))
Z3: [z_lo(0.70), z_lo(0.80))
Z4: [z_lo(0.80), z_lo(0.90))
Z5: [z_lo(0.90), +∞)
Below Z1: not counted toward strain zone buckets (still counts in hr_samples)
```

Each valid sample represents **5 minutes**. Assign to a zone; increment that
zone's minute counter by 5. Samples with `bpm < z_lo(0.50)` go to `below_zone_min`
(informational only).

**Edwards TRIMP-style raw load:**

```
weights = {1: 1, 2: 2, 3: 3, 4: 4, 5: 5}
trimp = Σ zoneN_min * weights[N]
```

**Scale to strain 0–21** (pin in tests; tune once against lived days):

```
# Soft cap: ~90 min Z5 + residual ≈ upper hard day for this user
STRAIN_TRIMP_CAP = 450   # trimp at which strain → 21
strain = min(21.0, 21.0 * trimp / STRAIN_TRIMP_CAP)
strain = round(strain, 1)
```

Also store `elevated_min` = sum of Z2–Z5 minutes (or Z1–Z5 — pick Z1–Z5 sum
as `zone_min_total`) and `peak_zone` = highest zone with any time.

**Pure helpers (unit-test these):**

```python
def karvonen_bounds(rhr: int, max_hr: int) -> tuple[int, int, int, int, int]: ...
def zone_for_bpm(bpm: int, bounds: ...) -> int | None:  # 1..5 or None if below Z1
def edwards_trimp(z_minutes: dict[int, int]) -> float: ...
def scale_strain(trimp: float, cap: float = 450.0) -> float: ...  # 0.0–21.0
def rhr_baseline(hr_mins: list[int]) -> int | None:  # median; None if empty
```

### 6.2 Phase 2 — Activity segments

**Build 15-min local slots for each day** (`slot_index` 0..95):

| Field | Source |
|-------|--------|
| `steps` | `SUM(raw_steps.steps)` in window; **0 if worn and no rows** |
| `hr_avg` | mean bpm of samples in window (None if unworn) |
| `hr_max` | max bpm in window |
| `hr_n` | count of HR samples |
| `worn` | `hr_n >= 1` |
| `stress_avg` | optional mean of `raw_stress` in window (soft veto) |

**Elevation & motion flags (defaults — calibrate after first live week):**

```
# Relative to Phase-1 RHR / max for that day (reuse same baseline helpers)
elevated = worn and hr_avg is not None and hr_avg >= rhr + 0.20 * (max_hr - rhr)
# Absolute step totals per 15-min slot (NOT steps/min)
steps_active  = steps >= STEP_ACTIVE   # bootstrap 150  (light movement)
steps_walk    = steps >= STEP_WALK     # bootstrap 400
steps_run     = steps >= STEP_RUN      # bootstrap 900
```

Bootstrap constants are **starting points** for tattooed finger undercount.
After deploy, sample 7 days of elevated slots and set:

- `STEP_WALK` ≈ p40 of elevated slots that user confirms as walks  
- `STEP_RUN` ≈ p85 of same  
Document actual constants in module header once locked; pin in tests.

**Active slot:**

```
active = worn and (
    elevated
    or steps >= STEP_ACTIVE
)
```

High stress + not elevated-by-steps does **not** alone create an activity
(sauna/anxiety); stress is only a **confidence penalty**, not a trigger.

**Segmentize:**

1. Find runs of consecutive `active` slots length ≥ 2 (≥30 min).  
2. Merge runs separated by a single inactive worn slot only if both sides same
   provisional type and gap ≤ 15 min (optional; ship simpler: no gap-fill first).  
3. Classify whole block from aggregate metrics:

```
block_steps = sum(steps)
block_minutes = n_slots * 15
cadence_spm = block_steps / block_minutes          # steps per minute over block
mean_hr = weighted mean of slot hr_avg
frac_elevated = fraction of slots with elevated

if block_steps >= STEP_RUN * n_slots and mean_hr >= rhr + 0.40 * hrr:
    type = 'running'
elif block_steps >= STEP_WALK * n_slots and mean_hr >= rhr + 0.15 * hrr:
    type = 'walking'
else:
    type = 'general_activity'   # includes cycling, lifting, sauna+HR, etc.
```

**Confidence (0.00–1.00), simple and tested:**

```
c = 0.40
c += 0.15 if n_slots >= 3 else 0
c += 0.15 if frac_elevated >= 0.75 else 0
c += 0.15 if type == 'running' and cadence_spm >= STEP_RUN/15 else 0
c += 0.10 if type == 'walking' and cadence_spm >= STEP_WALK/15 else 0
c += 0.10 if hr_max - hr_avg < 25 else 0   # steady effort
c -= 0.15 if stress_avg is not None and stress_avg >= 70 and type != 'running' else 0
c = clamp(c, 0.05, 0.99)
```

**Pure helpers:**

```python
def build_slots(hr_rows, step_rows, day_start_local) -> list[Slot]: ...
def flag_active(slot, rhr, max_hr, thresholds) -> bool: ...
def find_segments(slots) -> list[slice]: ...
def classify_segment(slots_slice, rhr, max_hr, thresholds) -> tuple[str, float]: ...
```

---

## 7. Schema

Add to `db/init.sql` (and apply live via one-shot SQL matching init — no migration framework).

### Phase 1 — `heart_rate_zones`

Stores **minutes in zone**, not bpm thresholds (thresholds are deterministic
from `rhr_used` / `max_hr_used`).

```sql
CREATE TABLE IF NOT EXISTS heart_rate_zones (
    day DATE PRIMARY KEY,
    rhr_used INT NOT NULL,              -- baseline applied that day
    max_hr_used INT NOT NULL,
    zone1_min INT NOT NULL DEFAULT 0,  -- minutes in Z1 (50-60% HRR)
    zone2_min INT NOT NULL DEFAULT 0,
    zone3_min INT NOT NULL DEFAULT 0,
    zone4_min INT NOT NULL DEFAULT 0,
    zone5_min INT NOT NULL DEFAULT 0,
    below_zone_min INT NOT NULL DEFAULT 0,  -- worn samples under Z1, as minutes
    elevated_min INT NOT NULL DEFAULT 0,    -- Z2+Z3+Z4+Z5 (or document Z1+)
    peak_zone INT CHECK (peak_zone IS NULL OR peak_zone BETWEEN 0 AND 5),
    trimp NUMERIC(8,1) NOT NULL DEFAULT 0,  -- Edwards raw before scale
    strain_score NUMERIC(4,1) NOT NULL DEFAULT 0,  -- 0.0–21.0
    hr_samples INT NOT NULL DEFAULT 0,
    computed_at TIMESTAMPTZ DEFAULT NOW()
);
```

### Phase 2 — `activity_segments`

```sql
CREATE TABLE IF NOT EXISTS activity_segments (
    id BIGSERIAL PRIMARY KEY,
    day DATE NOT NULL,
    start_ts TIMESTAMPTZ NOT NULL,
    end_ts TIMESTAMPTZ NOT NULL,
    duration_min INT NOT NULL,
    activity_type TEXT NOT NULL CHECK (activity_type IN (
        'walking', 'running', 'general_activity'
    )),
    confidence NUMERIC(3,2) NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    avg_hr INT,
    peak_hr INT,
    total_steps INT NOT NULL DEFAULT 0,
    avg_hrv INT,                       -- optional; NULL if no HRV in window
    source TEXT NOT NULL DEFAULT 'auto'
        CHECK (source IN ('auto', 'manual')),  -- manual reserved for later tags
    computed_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (day, start_ts)
);
CREATE INDEX IF NOT EXISTS idx_activity_segments_day
    ON activity_segments(day DESC);
```

Recompute pattern for segments:

```sql
DELETE FROM activity_segments WHERE day = %s AND source = 'auto';
-- then INSERT each segment for that day
```

(`${`manual`}` rows preserved when that lands.)

---

## 8. Concrete Implementation Plan

### Phase 1 — HR zones & strain  (estimate: ~½ day)

| Step | Work | Files |
|------|------|-------|
| 1.1 | Schema: add `heart_rate_zones` to `db/init.sql`; apply to live DB | `db/init.sql`, one-shot `psql` |
| 1.2 | Env: `USER_AGE` in `.env.example` (+ read via existing env pattern) | `.env.example`, module |
| 1.3 | Pure helpers + tests (bounds, zone assign, TRIMP, scale, median RHR) | `collector/analytics/heart_rate_zones.py`, `tests/test_heart_rate_zones.py` |
| 1.4 | Scorer: 14-day recompute, upsert by day, log counts | `heart_rate_zones.py` |
| 1.5 | Wire `run_all` after `daily_activity` | `collector/analytics/main.py` |
| 1.6 | API: `GET /api/heart-rate-zones?days=14` | `api/main.py` |
| 1.7 | Dashboard: type + hook; show today's `strain_score` + zone bar on Activity hero or compact card | `web/src/api/types.ts`, `hooks.ts`, `DashboardTab` / Activity area |
| 1.8 | Verify: `pytest` + rebuild API image / restart + one analytics run; spot-check SQL | — |

**Phase 1 done when:**

- [ ] 14 days of rows in `heart_rate_zones` after analytics  
- [ ] Pure tests cover edge cases (empty day, rhr≥max, no baseline → skip or defaults)  
- [ ] Strain visible on dashboard without page errors  
- [ ] Readiness scores unchanged byte-for-byte vs pre-deploy spot check  

**Phase 1 non-goals:** activity type labels, readiness weight, segment UI.

---

### Phase 2 — Activity segments  (estimate: ~1 day; after Phase 1 stable)

| Step | Work | Files |
|------|------|-------|
| 2.1 | Schema: `activity_segments` + live apply | `db/init.sql` |
| 2.2 | Pure slot/segment helpers + tests (fixtures with synthetic 15-min series) | `collector/analytics/activity.py`, `tests/test_activity_segments.py` |
| 2.3 | Scorer: build slots from raw HR+steps; delete auto rows; insert; reuse Phase 1 RHR/max helpers (import, don't duplicate) | `activity.py` |
| 2.4 | Wire `run_all` after `heart_rate_zones` | `main.py` |
| 2.5 | API: `GET /api/activity-segments?days=14` | `api/main.py` |
| 2.6 | UI: list today's segments under Activity or mark DayRing arcs by type color | React components |
| 2.7 | Threshold calib note: run SQL export of elevated slots; adjust module constants; update tests | module header + tests |
| 2.8 | Verify pytest + live analytics + one known walk day | — |

**Phase 2 done when:**

- [ ] Auto segments for multi-slot walks appear with type `walking` and confidence ≥ ~0.5  
- [ ] Re-running analytics does not duplicate rows  
- [ ] Ambiguous elevated-HR / low-step blocks are `general_activity`, never fake `cycling`  
- [ ] Zero-suppressed quiet worn time does not invent walks  

**Phase 2 non-goals:** manual edit UI, ML, readiness pillar.

---

### Later (explicitly not Phase 1–2)

| Phase | Item |
|-------|------|
| 3 | Manual tag / override UI (`source='manual'`) — true WHOOP workflow |
| 4 | Prior-day `strain_score` → optional readiness pillar (~5–10%), never same-day |
| 5 | Threshold auto-calib from confirmed tags; optional lightweight classifier |
| — | Calories as feature (after firmware ÷100 display fix) |
| — | CFW continuous accel buffer (different project) |

---

## 9. File touch list (authoritative)

```
db/init.sql                              + heart_rate_zones, + activity_segments
.env.example                             + USER_AGE=
collector/analytics/heart_rate_zones.py  NEW Phase 1
collector/analytics/activity.py          NEW Phase 2
collector/analytics/main.py              insert scorers after daily_activity
api/main.py                              GET endpoints (+ rebuild API image)
web/src/api/types.ts                     row types
web/src/api/hooks.ts                     useHeartRateZones, useActivitySegments
web/src/...                              strain + segments UI
tests/test_heart_rate_zones.py           NEW
tests/test_activity_segments.py          NEW
docs/ACTIVITY_DETECTION_RESEARCH.md      this file
AGENTS.md                                work-log line when shipped
```

No BLE/protocol changes. No readiness formula change in Phases 1–2.

---

## 10. Edge cases (must handle)

| Case | Behavior |
|------|----------|
| No HR samples that day | Skip zones row or zeros + NULL strain? → **skip upsert** (no row) |
| No 7d RHR history | Fallback prior-day; else skip day |
| HR logger stall (gaps) | Strain from available samples only; store `hr_samples`; UI can show sparse |
| Steps rows without HR (unworn noise) | Do not start segments; steps alone without wear ≠ activity |
| Finger undercount | Calibrate STEP_*; prefer HR elevation + moderate steps for walk |
| Sauna / anxiety | Elevated HR, ~0 steps → `general_activity`, lower confidence if stress high |
| Recompute every 30s analytics | Idempotent upsert / delete+insert auto only |
| Age unset | Default `USER_AGE=35` behind log warning once |

---

## 11. Verification checklist

```bash
cd /opt/smart-ring/code
venv/bin/python3 -m pytest tests/test_heart_rate_zones.py tests/test_activity_segments.py tests/ -q
venv/bin/python3 -m collector.analytics
podman exec smart-ring-db psql -U smart_ring -d smart_ring -c \
  'SELECT day, strain_score, zone2_min, zone3_min, zone4_min FROM heart_rate_zones ORDER BY day DESC LIMIT 7;'
podman exec smart-ring-db psql -U smart_ring -d smart_ring -c \
  'SELECT day, start_ts, duration_min, activity_type, confidence, total_steps FROM activity_segments ORDER BY start_ts DESC LIMIT 20;'
# after web change:
cd web && npm run build && npm run lint
sudo systemctl restart smart-ring-api   # if API image/code path requires it
```

---

## 12. Sources & Confidence

| Topic | Confidence | Notes |
|-------|-----------|-------|
| Commercial auto-detect methods | HIGH | Public docs / reverse-engineering |
| Karvonen / ACSM zones | HIGH | Karvonen 1957; ACSM guidelines |
| Edwards TRIMP → strain scale | MEDIUM | TRIMP established; 0–21 mapping is **ours**, pinned by tests + lived tuning |
| WHOOP exact formula | — | Proprietary; we do not claim parity |
| HAR ML literature | HIGH | Nearly all assume accel — limited transfer |
| HRV drop during exercise | HIGH | Context only; not required for Phases 1–2 |
| Type classification w/o accel | MEDIUM | Walk/run via steps+HR is plausible; everything else is `general_activity` |
| R09 slot/zero-suppression behavior | HIGH | Verified in this codebase + `RING_BEHAVIOR.md` |

---

## 13. Review fixes applied (vs first draft)

| Issue | Fix |
|-------|-----|
| Schema stored zone **thresholds**, not time | Minutes per zone + `trimp` / `strain_score` |
| Claimed WHOOP strain | Documented Edwards TRIMP→0–21 approximation |
| Calorie/table cadence unit mess | Steps **per 15-min slot**; `cadence_spm = steps/minutes` only for confidence |
| Min duration 10 vs 30 | Strain: no min gate; segments: **≥30 min** only |
| `cycling` type | Removed until confirmed; use `general_activity` |
| RHR = today's `hr_min` | **7-day median of prior days** |
| Wear via `hourly_worn` | Per-slot wear from HR presence |
| Pipeline order wrong | After real `daily_activity`; HRV stays where it is |
| Segment re-run dupes | `UNIQUE (day, start_ts)` + delete auto / upsert |
| No age source | `USER_AGE` env |
| Orphan tables | API + UI in same phase as scorer |
| Wrist step thresholds | Bootstrap + calibrate; undercount noted |
| ML as Phase 3 next | Deferred behind manual tags |

When implementing, keep this file as the contract; update constants here if
calibration changes them.
