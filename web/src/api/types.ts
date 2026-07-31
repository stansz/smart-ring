// ─── Health ────────────────────────────────────────────────────────────────
export interface HealthResponse {
  status: "ok";
  db: "connected";
}

// ─── Readiness / Recovery / Current Status ──────────────────────────────────
export interface RecoveryRow {
  day: string;
  rmssd: number | null;
  baseline_rmssd: number | null;
  z_score: number | null;
  readiness_text: string | null;
}

export interface ReadinessRow {
  day: string;
  score: number;
  hrv_score: number;
  sleep_score: number;
  rhr_score: number;
  hrv_zscore: number | null;
  resting_hr: number | null;
  hrv_rmssd: number | null;
  sleep_total_min: number | null;
  rhr_baseline: number | null;
  contributors: Record<string, number> | null;
  confidence: "full" | "partial";
  missing_components: string[];
  frozen_at: string | null;
}

export interface CurrentStatusRow {
  ts: string;
  score: number;
  hrv_component: number | null;
  hr_component: number | null;
  stress_component: number | null;
  trend_component: number | null;
  hrv_zscore: number | null;
  hr_delta: number | null;
  stress_recent: number | null;
  hrv_trend: number | null;
  samples: number;
  confidence: "full" | "partial";
  computed_at: string;
}

// ─── Sleep ──────────────────────────────────────────────────────────────────
export interface SleepQualityRow {
  day: string;
  score: number | null;
  deep_pct: number | null;
  rem_pct: number | null;
  light_pct: number | null;
  wake_pct: number | null;
  temp_drop_c: number | null;
  total_sleep_minutes: number | null;
  deep_min: number;
  rem_min: number;
  light_min: number;
  awake_min: number;
  sleep_start_ts: string | null;
  sleep_end_ts: string | null;
}

// ─── HRV / Stress / Activity ────────────────────────────────────────────────
export interface HrvTrendRow {
  day: string;
  rmssd_7d: number | null;
  rmssd_28d: number | null;
  pnn50_7d: number | null;
}

export interface CircadianHrRow {
  day: string;
  hour: number;
  avg_hr: number | null;
  min_hr: number | null;
  max_hr: number | null;
  sample_count: number;
}

export interface CircadianHrResponse extends Array<CircadianHrRow> {
  // The API appends a _range object as the last element
}

export interface StressClassificationRow {
  day: string;
  morning_rmssd: number | null;
  noon_rmssd: number | null;
  evening_rmssd: number | null;
  classification: string | null;
}

export interface RestingHrRow {
  day: string;
  resting_hr: number | null;
  samples: number;
}

export interface DailyActivityRow {
  day: string;
  steps_total: number;
  distance_m: number;
  calories_raw: number;
  hr_avg: number | null;
  hr_min: number | null;
  hr_max: number | null;
  hr_samples: number;
  worn_minutes: number;
  first_hr_ts: string | null;
  last_hr_ts: string | null;
  hourly_steps: number[] | null;
  hourly_worn: number[] | null;
}

export interface HeartRateZonesRow {
  day: string;
  rhr_used: number;
  max_hr_used: number;
  zone1_min: number;
  zone2_min: number;
  zone3_min: number;
  zone4_min: number;
  zone5_min: number;
  below_zone_min: number;
  elevated_min: number;
  peak_zone: number;
  trimp: number;
  strain_score: number;
  hr_samples: number;
  computed_at: string;
}

export interface StrainTrendRow {
  day: string;
  strain_today: number;
  load_label: "rest" | "light" | "moderate" | "hard" | "very_hard";
  strain_7d_sum: number | null;
  strain_7d_avg: number | null;
  strain_28d_avg: number | null;
  acwr: number | null;
  trend_direction: "increasing" | "stable" | "decreasing";
  days_with_data: number | null;
  computed_at: string;
}

// ─── Data Quality ───────────────────────────────────────────────────────────
export interface DataQualityRow {
  day: string;
  data_type: string;
  source: string;
  last_ts: string | null;
  sample_count: number;
  status: "ok" | "stale" | "missing";
  checked_at: string;
}

// ─── Raw data ───────────────────────────────────────────────────────────────
export interface RawHeartRateRow {
  ts: string;
  bpm: number;
}

export interface RawStepsRow {
  ts: string;
  steps: number;
  calories: number | null;
  distance: number | null;
}

export interface RawStressRow {
  ts: string;
  stress_value: number;
}

export interface RawSleepRow {
  day: string;
  stage: string;
  start_ts: string;
  end_ts: string;
  duration_minutes: number;
}

export interface RawSpo2Row {
  ts: string;
  spo2_pct: number;
}

export interface RawHrvRow {
  ts: string;
  hrv_value: number;
}

export interface RawTemperatureRow {
  ts: string;
  temp_c: number;
}

// ─── Goals ──────────────────────────────────────────────────────────────────
export interface GoalsResponse {
  steps_goal: number | null;
  calories_goal: number | null;
  distance_m_goal: number | null;
  sport_min_goal: number | null;
  sleep_min_goal: number | null;
}

// User-set goals (distinct from GoalsResponse above, which is the firmware-stored
// values synced from the ring). These are the user's own targets, edited via UI.
export interface UserGoals {
  steps_goal: number;
  sleep_min_goal: number;
}

// ─── Sync ───────────────────────────────────────────────────────────────────
export interface SyncLogRow {
  started_at: string;
  completed_at: string | null;
  records_synced: number;
  battery_pct: number | null;
  clock_drift_ms: number | null;
  status: string;
  error: string | null;
}

// ─── Admin ──────────────────────────────────────────────────────────────────
export interface RingStatusRow {
  ts: string;
  battery_pct: number | null;
  clock_drift_ms: number | null;
  firmware_version: string | null;
}

export interface RingStatusResponse {
  ring: RingStatusRow | null;
  last_sync: {
    completed_at: string | null;
    records_synced: number | null;
    status: string | null;
  } | null;
}

export interface AdminHealthResponse {
  db: string;
  ring_status_rows: number;
  sync_log_rows: number;
  pending_requests: number;
  container_host: string;
}

export interface AdminSyncLogRow {
  id: number;
  started_at: string;
  completed_at: string | null;
  records_synced: number;
  battery_pct: number | null;
  clock_drift_ms: number | null;
  status: string;
  error: string | null;
}

export interface ClockAlertResponse {
  future_rows: number;
  future_hr: number;
}

export interface SyncRequestRow {
  id: number;
  requested_at: string;
  requested_by: string;
  status: "pending" | "running" | "completed" | "failed" | "cancelled";
  started_at: string | null;
  completed_at: string | null;
  sync_log_id: number | null;
  result: string | null;
  error: string | null;
}

export interface SyncProgressResponse {
  current_step: string | null;
  started_at: string | null;
}

// ─── Mobile Sync ────────────────────────────────────────────────────────────
export interface MobileSyncRequest {
  device_id: string;
  records: {
    heart_rate?: { ts: string; bpm: number }[];
    spo2?: { ts: string; spo2_pct: number }[];
    hrv?: { ts: string; hrv_value: number; hrv_type?: string }[];
    sleep?: { day: string; stage: string; start_ts: string; end_ts: string; duration_minutes: number }[];
    temperature?: { ts: string; temp_c: number }[];
    steps?: { ts: string; steps: number; calories?: number; distance?: number }[];
    stress?: { ts: string; stress_value: number }[];
    goals?: {
      steps_goal?: number;
      calories_goal?: number;
      distance_m_goal?: number;
      sport_min_goal?: number;
      sleep_min_goal?: number;
    };
  };
  synced_at: string;
  battery_pct: number | null;
}

export interface MobileSyncResponse {
  accepted: number;
  skipped: number;
  errors: string[];
}

export interface QueueSyncResponse {
  id: number;
  requested_at: string;
  status: string;
}

export interface CancelSyncResponse {
  cancelled: number;
  sync_log_cleared: number;
}

// ─── Garmin Activities ─────────────────────────────────────────────────────
export interface ActivityRow {
  id: number;
  activity_type: string;
  sub_sport: string;
  start_ts: string;
  end_ts: string | null;
  duration_s: number;
  timer_time_s: number | null;
  distance_m: number | null;
  calories: number | null;
  avg_hr: number | null;
  max_hr: number | null;
  avg_cadence: number | null;
  max_cadence: number | null;
  avg_speed_mps: number | null;
  max_speed_mps: number | null;
  elevation_gain_m: number | null;
  elevation_loss_m: number | null;
  avg_temperature_c: number | null;
  training_effect_aerobic: number | null;
  training_effect_anaerobic: number | null;
  total_strides: number | null;
  lap_count: number;
}

export interface ActivityDetail extends ActivityRow {
  avg_vertical_oscillation_mm: number | null;
  avg_ground_contact_time_ms: number | null;
  avg_stride_length_cm: number | null;
  fit_file_path: string | null;
}

export interface TrackpointRow {
  ts: string;
  lat: number | null;
  lon: number | null;
  altitude_m: number | null;
  hr: number | null;
  cadence: number | null;
  speed_mps: number | null;
  distance_m: number | null;
  temperature_c: number | null;
}

export interface ActivityHrRow {
  ts: string;
  hr: number;
}

export interface ActivityLapRow {
  lap_index: number;
  start_ts: string;
  end_ts: string | null;
  duration_s: number;
  timer_time_s: number | null;
  distance_m: number | null;
  calories: number | null;
  avg_hr: number | null;
  max_hr: number | null;
  avg_cadence: number | null;
  max_cadence: number | null;
  avg_speed_mps: number | null;
  max_speed_mps: number | null;
  elevation_gain_m: number | null;
  elevation_loss_m: number | null;
}
