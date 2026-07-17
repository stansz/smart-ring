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
    morning_rmssd NUMERIC,
    noon_rmssd NUMERIC,
    evening_rmssd NUMERIC,
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

-- Unified readiness score (Oura-style 0-100, composited from HRV/Sleep/Activity/RHR).
-- One row per day; computed in analytics.py after all sub-scores are available.
CREATE TABLE IF NOT EXISTS readiness_score (
    day DATE PRIMARY KEY,
    score INT NOT NULL DEFAULT 0,      -- 0-100 composite
    hrv_score INT DEFAULT 0,           -- 0-100 (from z-score mapping)
    sleep_score INT DEFAULT 0,         -- 0-100 (from sleep_quality)
    activity_score INT DEFAULT 0,      -- 0-100 (steps vs goal + active min)
    rhr_score INT DEFAULT 0,           -- 0-100 (lower RHR = better)
    hrv_zscore NUMERIC(5,2),
    steps INT,
    resting_hr INT,
    hrv_rmssd NUMERIC(5,2),
    sleep_total_min INT,
    rhr_baseline INT,
    contributors JSONB,               -- {hrv: +5, sleep: -3, activity: +12, rhr: -2}
    confidence TEXT DEFAULT 'full',    -- 'full' | 'partial' (partial = one or more sub-scores missing)
    missing_components TEXT[] DEFAULT '{}', -- e.g. {'rhr'} for types missing real data
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
CREATE TABLE IF NOT EXISTS data_quality (
    day DATE NOT NULL,
    data_type VARCHAR(32) NOT NULL,
    last_ts TIMESTAMPTZ,
    sample_count INT DEFAULT 0,
    status VARCHAR(16) NOT NULL DEFAULT 'ok',  -- ok | stale | missing
    checked_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (day, data_type)
);