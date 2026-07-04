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
    source TEXT DEFAULT 'ring',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (day, stage, source)
);
CREATE INDEX IF NOT EXISTS idx_raw_sleep_day ON raw_sleep(day DESC);

CREATE TABLE IF NOT EXISTS raw_steps (
    id BIGSERIAL PRIMARY KEY,
    ts TIMESTAMPTZ NOT NULL,
    steps INT NOT NULL,
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

-- Sync tracking
CREATE TABLE IF NOT EXISTS sync_log (
    id BIGSERIAL PRIMARY KEY,
    started_at TIMESTAMPTZ NOT NULL,
    completed_at TIMESTAMPTZ,
    records_synced INT DEFAULT 0,
    battery_pct INT,
    clock_drift_ms INT,
    status TEXT DEFAULT 'running',
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