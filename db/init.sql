-- Raw sensor data (append-only)
CREATE TABLE IF NOT EXISTS raw_heart_rate (
    id BIGSERIAL PRIMARY KEY,
    ts TIMESTAMPTZ NOT NULL,
    bpm INT NOT NULL,
    source TEXT DEFAULT 'ring',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (ts, source)
);
CREATE INDEX IF NOT EXISTS idx_raw_heart_rate_ts ON raw_heart_rate(ts DESC);

CREATE TABLE IF NOT EXISTS raw_hrv (
    id BIGSERIAL PRIMARY KEY,
    ts TIMESTAMPTZ NOT NULL,
    hrv_value NUMERIC,
    hrv_type TEXT,
    rr_intervals INT[],
    source TEXT DEFAULT 'ring',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (ts, hrv_type, source)
);
CREATE INDEX IF NOT EXISTS idx_raw_hrv_ts ON raw_hrv(ts DESC);

CREATE TABLE IF NOT EXISTS raw_sleep (
    id BIGSERIAL PRIMARY KEY,
    day DATE NOT NULL,
    stage TEXT NOT NULL,
    start_ts TIMESTAMPTZ,
    end_ts TIMESTAMPTZ,
    duration_minutes INT,
    source TEXT DEFAULT 'ring',
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_raw_sleep_start_stage ON raw_sleep(start_ts, stage, source);
CREATE INDEX IF NOT EXISTS idx_raw_sleep_day ON raw_sleep(day DESC);

CREATE TABLE IF NOT EXISTS raw_steps (
    id BIGSERIAL PRIMARY KEY,
    ts TIMESTAMPTZ NOT NULL,
    steps INT NOT NULL,
    calories INT,
    distance INT,
    source TEXT DEFAULT 'ring',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (ts, source)
);
CREATE INDEX IF NOT EXISTS idx_raw_steps_ts ON raw_steps(ts DESC);

CREATE TABLE IF NOT EXISTS raw_spo2 (
    id BIGSERIAL PRIMARY KEY,
    ts TIMESTAMPTZ NOT NULL,
    spo2_pct INT NOT NULL,
    source TEXT DEFAULT 'ring',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (ts, source)
);
CREATE INDEX IF NOT EXISTS idx_raw_spo2_ts ON raw_spo2(ts DESC);

CREATE TABLE IF NOT EXISTS raw_temperature (
    id BIGSERIAL PRIMARY KEY,
    ts TIMESTAMPTZ NOT NULL,
    temp_c NUMERIC(4,2) NOT NULL,
    source TEXT DEFAULT 'ring',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (ts, source)
);
CREATE INDEX IF NOT EXISTS idx_raw_temperature_ts ON raw_temperature(ts DESC);

CREATE TABLE IF NOT EXISTS raw_stress (
    id BIGSERIAL PRIMARY KEY,
    ts TIMESTAMPTZ NOT NULL,
    stress_value INT NOT NULL,
    source TEXT DEFAULT 'ring',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (ts, source)
);
CREATE INDEX IF NOT EXISTS idx_raw_stress_ts ON raw_stress(ts DESC);

CREATE TABLE IF NOT EXISTS ring_goals (
    id BIGSERIAL PRIMARY KEY,
    ts TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    steps_goal INT,
    calories_goal INT,
    distance_m_goal INT,
    sport_min_goal INT,
    sleep_min_goal INT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS ring_status (
    id BIGSERIAL PRIMARY KEY,
    ts TIMESTAMPTZ NOT NULL,
    battery_pct INT,
    clock_drift_ms INT,
    firmware_version TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_ring_status_ts ON ring_status(ts DESC);

-- Computed metrics (refreshed by analytics cron)
CREATE TABLE IF NOT EXISTS daily_recovery (
    day DATE PRIMARY KEY,
    rmssd NUMERIC,
    baseline_rmssd NUMERIC,
    z_score NUMERIC,
    readiness_text TEXT,
    computed_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS sleep_quality (
    day DATE PRIMARY KEY,
    score NUMERIC,
    deep_pct NUMERIC,
    rem_pct NUMERIC,
    light_pct NUMERIC,
    wake_pct NUMERIC,
    temp_drop_c NUMERIC,
    total_sleep_minutes INT,
    deep_min INT DEFAULT 0,
    rem_min INT DEFAULT 0,
    light_min INT DEFAULT 0,
    awake_min INT DEFAULT 0,
    sleep_start_ts TIMESTAMPTZ,
    sleep_end_ts TIMESTAMPTZ,
    computed_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS hrv_trends (
    day DATE PRIMARY KEY,
    rmssd_7d NUMERIC,
    rmssd_28d NUMERIC,
    pnn50_7d NUMERIC,
    computed_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS circadian_hr (
    day DATE NOT NULL,
    hour INT NOT NULL,
    avg_hr NUMERIC,
    min_hr NUMERIC,
    max_hr NUMERIC,
    sample_count INT,
    computed_at TIMESTAMPTZ DEFAULT NOW(),
    PRIMARY KEY (day, hour)
);

CREATE TABLE IF NOT EXISTS stress_classification (
    day DATE PRIMARY KEY,
    -- FIXME: columns below are named _rmssd but actually store stress_values
    -- (0-99 scale). Naming drift from early schema. Tracked in TASKS.md backlog.
    morning_rmssd NUMERIC,  -- actually morning stress_value (6-10h avg)
    noon_rmssd NUMERIC,     -- actually noon stress_value (11-15h avg)
    evening_rmssd NUMERIC,  -- actually evening stress_value (16-22h avg)
    classification TEXT,
    computed_at TIMESTAMPTZ DEFAULT NOW()
);

-- Per-day activity aggregates (server-computed in local tz so the dashboard
-- doesn't have to filter raw records client-side, which was flaky on day toggle).
CREATE TABLE IF NOT EXISTS daily_activity (
    day DATE PRIMARY KEY,
    steps_total INT DEFAULT 0,
    distance_m INT DEFAULT 0,
    calories_raw INT DEFAULT 0,      -- firmware units (goal column is ~300000)
    hr_avg INT,
    hr_min INT,
    hr_max INT,
    hr_samples INT DEFAULT 0,
    worn_minutes INT DEFAULT 0,      -- ~ hr_samples * 5min (HR is 5-min slots)
    first_hr_ts TIMESTAMPTZ,
    last_hr_ts TIMESTAMPTZ,
    hourly_steps JSONB,              -- [24] step counts by local hour
    hourly_worn JSONB,               -- [24] HR-sample counts by local hour
    computed_at TIMESTAMPTZ DEFAULT NOW()
);

-- Unified readiness score (WHOOP-style recovery, 0-100, composited from HRV/Sleep/RHR).
-- One row per day; computed in analytics.py after all sub-scores are available.
-- `frozen_at`: once set (typically at first analytics pass at/after 6 AM local),
-- the row stops updating. WHOOP-style morning lock. See analytics/readiness.py.
CREATE TABLE IF NOT EXISTS readiness_score (
    day DATE PRIMARY KEY,
    score INT NOT NULL DEFAULT 0,      -- 0-100 composite
    hrv_score INT DEFAULT 0,           -- 0-100 (from z-score mapping)
    sleep_score INT DEFAULT 0,         -- 0-100 (from sleep_quality)
    rhr_score INT DEFAULT 0,           -- 0-100 (lower RHR = better)
    hrv_zscore NUMERIC(5,2),
    resting_hr INT,
    hrv_rmssd NUMERIC(5,2),
    sleep_total_min INT,
    rhr_baseline INT,
    contributors JSONB,               -- {hrv: +5, sleep: -3, rhr: -2}
    confidence TEXT DEFAULT 'full',    -- 'full' | 'partial' (partial = one or more sub-scores missing)
    missing_components TEXT[] DEFAULT '{}', -- e.g. {'rhr'} for types missing real data
    frozen_at TIMESTAMPTZ,             -- NULL = still updating; non-NULL = morning lock applied
    computed_at TIMESTAMPTZ DEFAULT NOW()
);

-- Current Status: live intra-day score, one row per analytics pass.
-- Complementary to readiness_score (which is morning-frozen). Uses recent
-- raw data (HRV / HR / stress / trend) to answer "how is my body doing right now?"
-- Latest row = current snapshot; history retained for v2 trend chart.
CREATE TABLE IF NOT EXISTS current_status (
    id BIGSERIAL PRIMARY KEY,
    ts TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    score INT NOT NULL,                -- 0-100 weighted composite
    hrv_component NUMERIC,             -- 0-100 from recent HRV z-score
    hr_component NUMERIC,              -- 0-100 from current HR vs RHR baseline
    stress_component NUMERIC,          -- 0-100 from recent raw stress (inverted)
    trend_component NUMERIC,           -- 0-100 from HRV slope over last 2h
    hrv_zscore NUMERIC,                -- raw inputs (for debugging + display)
    hr_delta INT,                      -- avg HR - rhr_baseline
    stress_recent INT,                 -- recent stress avg
    hrv_trend NUMERIC,                 -- slope of HRV over last 2h
    samples INT,                       -- total raw readings considered
    confidence TEXT DEFAULT 'full',    -- 'full' | 'partial' (any component missing)
    computed_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS idx_current_status_ts ON current_status(ts DESC);

-- Heart rate zones: per-day zone minutes + Edwards TRIMP-based strain score.
-- Zone times are computed from raw_heart_rate 5-min samples using Karvonen
-- HR reserve boundaries. strain_score is scaled to 0-21 like WHOOP's product
-- surface, but derived from a transparent Edwards TRIMP, not their proprietary
-- formula. Empty/unworn days are skipped entirely.
CREATE TABLE IF NOT EXISTS heart_rate_zones (
    day DATE PRIMARY KEY,
    rhr_used INT NOT NULL,              -- baseline applied that day
    max_hr_used INT NOT NULL,
    zone1_min INT NOT NULL DEFAULT 0,   -- minutes in 50-60% HRR
    zone2_min INT NOT NULL DEFAULT 0,   -- minutes in 60-70% HRR
    zone3_min INT NOT NULL DEFAULT 0,   -- minutes in 70-80% HRR
    zone4_min INT NOT NULL DEFAULT 0,   -- minutes in 80-90% HRR
    zone5_min INT NOT NULL DEFAULT 0,   -- minutes in 90-100% HRR
    below_zone_min INT NOT NULL DEFAULT 0, -- worn samples under Z1, as minutes
    elevated_min INT NOT NULL DEFAULT 0,   -- Z2+Z3+Z4+Z5 minutes
    peak_zone INT CHECK (peak_zone IS NULL OR peak_zone BETWEEN 0 AND 5),
    trimp NUMERIC(8,1) NOT NULL DEFAULT 0,  -- Edwards raw load
    strain_score NUMERIC(4,1) NOT NULL DEFAULT 0,  -- 0.0-21.0
    hr_samples INT NOT NULL DEFAULT 0,
    computed_at TIMESTAMPTZ DEFAULT NOW()
);

-- Strain trend & training load: rolling 7d acute load, 28d chronic load (ACWR),
-- daily load labels, and trend direction.
CREATE TABLE IF NOT EXISTS strain_trend (
    day DATE PRIMARY KEY,
    strain_today NUMERIC(4,1) NOT NULL DEFAULT 0,
    load_label TEXT CHECK (load_label IN (
        'rest','light','moderate','hard','very_hard'
    )),
    strain_7d_sum NUMERIC(5,1),     -- acute load (7d sum)
    strain_7d_avg NUMERIC(4,1),
    strain_28d_avg NUMERIC(4,1),    -- chronic load (28d avg)
    acwr NUMERIC(4,2),              -- 7d_sum / 28d_avg; NULL until 28d baseline built
    trend_direction TEXT CHECK (trend_direction IN (
        'increasing','stable','decreasing'
    )),
    days_with_data INT,
    computed_at TIMESTAMPTZ DEFAULT NOW()
);

-- Sync tracking
CREATE TABLE IF NOT EXISTS sync_log (
    id BIGSERIAL PRIMARY KEY,
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,
    records_synced INT DEFAULT 0,
    battery_pct INT,
    clock_drift_ms INT,
    status TEXT DEFAULT 'running',
    current_step TEXT,
    error TEXT
);
CREATE INDEX IF NOT EXISTS idx_sync_log_started ON sync_log(started_at DESC);

-- Admin job queue (API -> host poller -> collector)
-- The API inserts rows here when admin clicks "Sync Now" in the dashboard.
-- A host-side poller (collector/sync_request_poller.py) picks up pending rows,
-- runs the collector, and updates the row with the result.
CREATE TABLE IF NOT EXISTS sync_requests (
    id BIGSERIAL PRIMARY KEY,
    requested_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    requested_by TEXT DEFAULT 'admin-ui',
    status TEXT NOT NULL DEFAULT 'pending',  -- pending | running | completed | failed
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    sync_log_id BIGINT REFERENCES sync_log(id),
    result TEXT,
    error TEXT
);
CREATE INDEX IF NOT EXISTS idx_sync_requests_status ON sync_requests(status, requested_at DESC);
-- Partial unique index: only one row can be pending or running at a time.
-- This is what prevents a race when two POSTs try to queue a sync simultaneously.
CREATE UNIQUE INDEX IF NOT EXISTS idx_sync_requests_one_active ON sync_requests(status)
    WHERE status IN ('pending', 'running');

-- Data quality: per-type freshness checked after each sync.
-- Stale detection: if ANY type has data for a day (ring worn + synced)
-- but a specific type does NOT, flag it as stale. Days with no data from
-- any type are marked 'missing' (ring not worn / no sync that day).
-- `source` is part of the PK so multi-source freshness is tracked
-- per-source (e.g. ring HR + garmin HR on the same day = 2 rows).
CREATE TABLE IF NOT EXISTS data_quality (
    day DATE NOT NULL,
    data_type VARCHAR(32) NOT NULL,
    source TEXT NOT NULL DEFAULT 'ring',
    last_ts TIMESTAMPTZ,
    sample_count INT DEFAULT 0,
    status VARCHAR(16) NOT NULL DEFAULT 'ok',  -- ok | stale | missing
    checked_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (day, data_type, source)
);

-- Migration for existing DBs: pre-Phase-0 the table was keyed on
-- (day, data_type) without source. The source column was added in
-- Phase 0 (n-source resolver) so per-source freshness is trackable.
-- Safe to run on a fresh DB — IF EXISTS / IF NOT EXISTS are no-ops
-- when the table already matches the new shape.
DO $$
BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name = 'data_quality' AND column_name = 'source'
    ) THEN
        -- column already exists; nothing to do
        NULL;
    ELSE
        ALTER TABLE data_quality ADD COLUMN source TEXT NOT NULL DEFAULT 'ring';
        -- Drop the old PK and recreate with source included
        ALTER TABLE data_quality DROP CONSTRAINT IF EXISTS data_quality_pkey;
        ALTER TABLE data_quality ADD PRIMARY KEY (day, data_type, source);
    END IF;
END $$;

-- User-set goals (NOT the firmware-stored ring_goals — those are the ring's
-- defaults, which we still sync to ring_goals for compatibility but don't
-- surface). This table holds the user's own targets, edited from the UI.
-- Key-value so we can add new goals without schema changes.
CREATE TABLE IF NOT EXISTS user_goals (
    key TEXT PRIMARY KEY,
    value INT NOT NULL,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);