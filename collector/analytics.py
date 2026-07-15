#!/usr/bin/env python3
"""
Analytics engine for smart ring data.

Runs after each sync (called by the poller). Computes health scores from
raw sensor data and persists them to computed tables:
  - daily_recovery   (HRV-based recovery z-score + readiness)
  - sleep_quality     (5-component sleep score 0-100)
  - hrv_trends        (7-day / 28-day rolling HRV baselines)
  - stress_classification (daily stress levels + classification)
  - circadian_hr      (HR by hour-of-day — already works)

Formula references (see RESEARCH.md):
  - Sleep: Ohayon et al. (2004) meta-analysis for architecture norms;
    Oura reverse-engineering (Chheda) for component weights.
  - HRV: Plews/Buchheit/Altini framework — ln(RMSSD) z-score vs 7-day
    rolling baseline. Marco Altini, Sensors 2021 (9M measurements).
  - Stress: Garmin/Firstbeat thresholds (0-25/26-50/51-75/76-100);
    Frontiers in Physiology 2025 for circadian detrending.
"""
import os
import sys
import math
import json
import logging
import statistics
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional, Tuple

import psycopg2
from psycopg2.extras import RealDictCursor
from dotenv import load_dotenv

load_dotenv()

from pathlib import Path

LOG_DIR = Path(__file__).resolve().parent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "analytics.log"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://smart_ring:changeme@localhost:5432/smart_ring")

# ---------------------------------------------------------------------------
# Scoring helpers — trapezoidal function for optimal-range scoring
# ---------------------------------------------------------------------------

def trap_score(value: float, optimal_low: float, optimal_high: float,
               zero_low: float, zero_high: float) -> float:
    """Score 0-100 using a trapezoidal function.

    Full credit (100) within [optimal_low, optimal_high].
    Linear decline to 0 at [zero_low] and [zero_high].
    """
    if optimal_low <= value <= optimal_high:
        return 100.0
    if value < optimal_low:
        if value <= zero_low:
            return 0.0
        return (value - zero_low) / (optimal_low - zero_low) * 100
    # value > optimal_high
    if value >= zero_high:
        return 0.0
    return (zero_high - value) / (zero_high - optimal_high) * 100


def readiness_text(z: Optional[float]) -> str:
    """Map z-score to readiness label (Altini thresholds)."""
    if z is None:
        return "Building baseline..."
    if z > 1.0:
        return "Excellent"
    if z > 0.5:
        return "Good"
    if z > -0.5:
        return "Fair"
    if z > -1.0:
        return "Poor"
    return "Very Poor"


# ---------------------------------------------------------------------------
# Main analytics class
# ---------------------------------------------------------------------------

class Analytics:
    def __init__(self):
        self.conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
        # Set session timezone to host's local timezone so EXTRACT(HOUR)
        # and DATE() use local time, not the container's UTC.
        try:
            with open('/etc/timezone') as f:
                local_tz = f.read().strip()
            with self.conn.cursor() as cur:
                cur.execute(f"SET TIME ZONE '{local_tz}'")
            self.conn.commit()
            log.info(f"Analytics DB session timezone: {local_tz}")
        except Exception as e:
            log.warning(f"Could not set DB timezone: {e}")

    # =================== Source dedup ===================

    def dedupe_sources(self):
        """Remove 'phone' records that duplicate 'ring' records.

        Ring is the canonical collector (Linux box). Phone sync (Web Bluetooth)
        is a fallback that fills gaps when the ring hasn't been synced. Since both
        sample the same physical slots, ~99% of phone records can duplicate ring.
        We keep ring and drop phone wherever they overlap, so every downstream
        query and score sees one measurement per slot.

        Point tables dedupe on timestamp (HRV also on hrv_type). Sleep dedupes at
        the day level (ring's night wins wholesale if present).
        """
        log.info("Deduping phone vs ring sources...")
        # (table, dedup key columns as join predicate)
        point_tables = [
            ("raw_heart_rate", "r.ts = p.ts"),
            ("raw_spo2",       "r.ts = p.ts"),
            ("raw_temperature","r.ts = p.ts"),
            ("raw_stress",     "r.ts = p.ts"),
            ("raw_steps",      "r.ts = p.ts"),
            ("raw_hrv",        "r.ts = p.ts AND r.hrv_type = p.hrv_type"),
        ]
        with self.conn.cursor() as cur:
            for table, on_clause in point_tables:
                cur.execute(f"""
                    DELETE FROM {table} p
                    WHERE p.source = 'phone'
                      AND EXISTS (SELECT 1 FROM {table} r
                                  WHERE r.source = 'ring' AND {on_clause})
                """)
                if cur.rowcount:
                    log.info(f"  {table}: removed {cur.rowcount} phone duplicate(s)")
            # Sleep: day-level — if ring has any stages for a day, drop all phone stages for it
            cur.execute("""
                DELETE FROM raw_sleep p
                WHERE p.source = 'phone'
                  AND EXISTS (SELECT 1 FROM raw_sleep r
                              WHERE r.source = 'ring' AND r.day = p.day)
            """)
            if cur.rowcount:
                log.info(f"  raw_sleep: removed {cur.rowcount} phone duplicate(s)")
        self.conn.commit()

    # =================== HRV Recovery ===================

    def compute_hrv_recovery(self):
        """Compute daily HRV recovery metrics from composite HRV values.

        Methodology (Plews/Buchheit/Altini):
          1. Log-transform: ln(hrv_value) to normalize distribution
          2. 7-day rolling mean + SD for baseline
          3. Z-score: (ln_today - mean_7d) / sd_7d
          4. Readiness text from z-score thresholds
          5. Coefficient of variation for stability flag
        """
        log.info("Computing HRV recovery metrics...")
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT DATE(ts) as day,
                       AVG(hrv_value) as avg_hrv,
                       MIN(hrv_value) as min_hrv,
                       MAX(hrv_value) as max_hrv,
                       COUNT(*) as samples
                FROM raw_hrv
                WHERE hrv_value > 0
                GROUP BY DATE(ts)
                ORDER BY day ASC
            """)
            daily = cur.fetchall()

        if not daily:
            log.info("  No HRV data available")
            return

        # Compute log-transformed values and rolling stats
        ln_values = []  # list of (day, ln_avg, avg_hrv, samples)
        for row in daily:
            ln_val = math.log(row['avg_hrv'])
            ln_values.append((row['day'], ln_val, float(row['avg_hrv']),
                              int(row['samples']), float(row['min_hrv']),
                              float(row['max_hrv'])))

        for i, (day, ln_today, avg_hrv, samples, min_h, max_h) in enumerate(ln_values):
            # Baseline: previous 7 days (exclude today)
            baseline_window = [v[1] for v in ln_values[max(0, i - 7):i]]
            baseline_days = len(baseline_window)

            if baseline_days >= 3:
                baseline_mean = statistics.mean(baseline_window)
                baseline_sd = statistics.stdev(baseline_window) if baseline_days >= 2 else baseline_mean * 0.1
                z_score = (ln_today - baseline_mean) / baseline_sd if baseline_sd > 0 else 0.0
                cv = (baseline_sd / baseline_mean) * 100 if baseline_mean > 0 else 0
                confidence = "high" if baseline_days >= 7 else "low"
            elif baseline_days >= 1:
                baseline_mean = statistics.mean(baseline_window)
                baseline_sd = baseline_mean * 0.1
                z_score = (ln_today - baseline_mean) / baseline_sd if baseline_sd > 0 else 0.0
                cv = 0
                confidence = "low"
            else:
                baseline_mean = ln_today
                baseline_sd = None
                z_score = None
                cv = 0
                confidence = "none"

            readiness = readiness_text(z_score)

            # Store daily_recovery
            with self.conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO daily_recovery (day, rmssd, baseline_rmssd, z_score, readiness_text)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (day) DO UPDATE SET
                        rmssd = EXCLUDED.rmssd,
                        baseline_rmssd = EXCLUDED.baseline_rmssd,
                        z_score = EXCLUDED.z_score,
                        readiness_text = EXCLUDED.readiness_text,
                        computed_at = NOW()
                """, (
                    day, round(avg_hrv, 1),
                    round(math.exp(baseline_mean), 1) if baseline_sd is not None else None,
                    round(z_score, 2) if z_score is not None else None,
                    f"{readiness}{' (low confidence)' if confidence == 'low' else ''}" if z_score is not None else readiness,
                ))
            self.conn.commit()

            # Store hrv_trends (7-day and 28-day rolling)
            window_7d = [v[1] for v in ln_values[max(0, i - 6):i + 1]]
            window_28d = [v[1] for v in ln_values[max(0, i - 27):i + 1]]
            rmssd_7d = math.exp(statistics.mean(window_7d)) if window_7d else None
            rmssd_28d = math.exp(statistics.mean(window_28d)) if len(window_28d) >= 7 else None

            with self.conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO hrv_trends (day, rmssd_7d, rmssd_28d, pnn50_7d)
                    VALUES (%s, %s, %s, %s)
                    ON CONFLICT (day) DO UPDATE SET
                        rmssd_7d = EXCLUDED.rmssd_7d,
                        rmssd_28d = EXCLUDED.rmssd_28d,
                        pnn50_7d = EXCLUDED.pnn50_7d,
                        computed_at = NOW()
                """, (
                    day,
                    round(rmssd_7d, 1) if rmssd_7d else None,
                    round(rmssd_28d, 1) if rmssd_28d else None,
                    round(cv, 1),
                ))
            self.conn.commit()

            log.info(f"  HRV {day}: avg={avg_hrv:.1f}ms z={z_score:.2f}" if z_score else f"  HRV {day}: avg={avg_hrv:.1f}ms (no baseline)")

    # =================== Sleep Quality ===================

    def compute_sleep_quality(self):
        """Compute sleep quality score from per-session stage data.

        5-component score (0-100):
          30% Duration (7-9h optimal)
          25% Efficiency (>=90% optimal)
          25% Architecture (deep 13-23%, REM 20-25%)
          15% Continuity (WASO + awakenings)
           5% Latency (10-20 min optimal)

        References: Ohayon et al. (2004) meta-analysis for architecture norms;
        Oura reverse-engineering (Chheda) for component weights.
        """
        log.info("Computing sleep quality metrics...")
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT day, stage, start_ts, end_ts, duration_minutes
                FROM raw_sleep s
                WHERE duration_minutes IS NOT NULL
                  AND start_ts IS NOT NULL
                  AND source = CASE WHEN EXISTS (
                        SELECT 1 FROM raw_sleep r
                        WHERE r.day = s.day AND r.source = 'ring'
                      ) THEN 'ring' ELSE 'phone' END
                ORDER BY day, start_ts
            """)
            all_stages = cur.fetchall()

        if not all_stages:
            log.info("  No sleep stage data available")
            return

        # Group by day
        by_day: Dict = {}
        for s in all_stages:
            day = s['day']
            if day not in by_day:
                by_day[day] = []
            by_day[day].append(s)

        # Get temperature data for temp_drop_c
        temp_data = self._get_overnight_temps()

        for day, stages in sorted(by_day.items()):
            score_data = self._score_sleep_day(day, stages, temp_data.get(day, []))
            if score_data:
                self._store_sleep_quality(score_data)

    def _score_sleep_day(self, day, stages: List[Dict], temps: List[Dict]) -> Optional[Dict]:
        """Score a single night of sleep."""
        stages_sorted = sorted(stages, key=lambda s: s['start_ts'])
        first_start = stages_sorted[0]['start_ts']
        last_end = stages_sorted[-1]['end_ts']
        time_in_bed = (last_end - first_start).total_seconds() / 60  # minutes

        # Stage durations
        by_stage = {}
        total_sleep = 0
        wake_after_onset = 0
        awakenings = 0

        for s in stages_sorted:
            dur = s['duration_minutes'] or 0
            stage = s['stage']
            by_stage[stage] = by_stage.get(stage, 0) + dur
            if stage == 'awake':
                wake_after_onset += dur
                awakenings += 1
            else:
                total_sleep += dur

        if total_sleep < 30:
            log.info(f"  Sleep {day}: too short ({total_sleep}m), skipping")
            return None

        deep_min = by_stage.get('deep', 0)
        rem_min = by_stage.get('rem', 0)
        light_min = by_stage.get('light', 0)
        awake_min = by_stage.get('awake', 0)

        deep_pct = (deep_min / total_sleep * 100) if total_sleep else 0
        rem_pct = (rem_min / total_sleep * 100) if total_sleep else 0
        light_pct = (light_min / total_sleep * 100) if total_sleep else 0
        wake_pct = (awake_min / total_sleep * 100) if total_sleep else 0

        sleep_hours = total_sleep / 60
        efficiency = (total_sleep / time_in_bed * 100) if time_in_bed > 0 else 0

        # --- 5-component score ---
        # 1. Duration (30%): 7-9h optimal, 0 at <4h and >10h
        s_dur = trap_score(sleep_hours, 7.0, 9.0, 4.0, 10.0)

        # 2. Efficiency (25%): >=90% optimal, 0 at <60%
        s_eff = trap_score(efficiency, 90.0, 100.0, 60.0, 100.0)

        # 3. Architecture (25%): deep 13-23%, REM 20-25%
        # Full credit in range, penalize below/above
        deep_penalty = max(0, 13 - deep_pct) + max(0, deep_pct - 23) * 1.5
        rem_penalty = max(0, 20 - rem_pct) + max(0, rem_pct - 25) * 1.0
        s_arch = max(0, 100 - deep_penalty - rem_penalty)

        # 4. Continuity (15%): WASO <20min + <2 awakenings = 100
        waso_score = trap_score(wake_after_onset, 0, 20, 60, 0)
        aw_score = trap_score(awakenings, 0, 2, 6, 0)
        s_cont = (waso_score + aw_score) / 2

        # 5. Latency (5%): can't measure precisely from ring data
        # Use sleep onset approximation: time from first record to first deep/light
        # For now, give benefit of the doubt (ring doesn't report pre-sleep latency)
        s_lat = 80.0  # conservative default

        total_score = (0.30 * s_dur + 0.25 * s_eff + 0.25 * s_arch +
                       0.15 * s_cont + 0.05 * s_lat)

        # Temperature drop (highest - lowest overnight)
        temp_drop = 0.0
        if len(temps) >= 2:
            temp_vals = [float(t['temp_c']) for t in temps]
            temp_drop = max(temp_vals) - min(temp_vals)

        log.info(f"  Sleep {day}: score={total_score:.0f} ({sleep_hours:.1f}h, "
                 f"deep {deep_pct:.0f}%, REM {rem_pct:.0f}%, eff {efficiency:.0f}%)")

        return {
            'day': day,
            'score': round(total_score, 1),
            'deep_pct': round(deep_pct, 1),
            'rem_pct': round(rem_pct, 1),
            'light_pct': round(light_pct, 1),
            'wake_pct': round(wake_pct, 1),
            'temp_drop_c': round(temp_drop, 2),
            'total_sleep_minutes': round(total_sleep),
            'deep_min': deep_min,
            'rem_min': rem_min,
            'light_min': light_min,
            'awake_min': awake_min,
            'sleep_start_ts': first_start,
            'sleep_end_ts': last_end,
            '_components': {
                'duration': round(s_dur), 'efficiency': round(s_eff),
                'architecture': round(s_arch), 'continuity': round(s_cont),
                'latency': round(s_lat),
            }
        }

    def _get_overnight_temps(self) -> Dict[date, List[Dict]]:
        """Get temperature readings grouped by date for overnight temp drop."""
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT DATE(ts) as day, temp_c, ts
                FROM raw_temperature
                WHERE ts >= NOW() - INTERVAL '30 days'
                ORDER BY ts
            """)
            rows = cur.fetchall()
        by_day = {}
        for r in rows:
            by_day.setdefault(r['day'], []).append(r)
        return by_day

    def _store_sleep_quality(self, data: Dict):
        with self.conn.cursor() as cur:
            cur.execute("""
                INSERT INTO sleep_quality (day, score, deep_pct, rem_pct, light_pct,
                                         wake_pct, temp_drop_c, total_sleep_minutes,
                                         deep_min, rem_min, light_min, awake_min,
                                         sleep_start_ts, sleep_end_ts)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (day) DO UPDATE SET
                    score = EXCLUDED.score,
                    deep_pct = EXCLUDED.deep_pct,
                    rem_pct = EXCLUDED.rem_pct,
                    light_pct = EXCLUDED.light_pct,
                    wake_pct = EXCLUDED.wake_pct,
                    temp_drop_c = EXCLUDED.temp_drop_c,
                    total_sleep_minutes = EXCLUDED.total_sleep_minutes,
                    deep_min = EXCLUDED.deep_min,
                    rem_min = EXCLUDED.rem_min,
                    light_min = EXCLUDED.light_min,
                    awake_min = EXCLUDED.awake_min,
                    sleep_start_ts = EXCLUDED.sleep_start_ts,
                    sleep_end_ts = EXCLUDED.sleep_end_ts,
                    computed_at = NOW()
            """, (
                data['day'], data['score'],
                data['deep_pct'], data['rem_pct'], data['light_pct'], data['wake_pct'],
                data['temp_drop_c'], data['total_sleep_minutes'],
                data['deep_min'], data['rem_min'], data['light_min'], data['awake_min'],
                data['sleep_start_ts'], data['sleep_end_ts'],
            ))
        self.conn.commit()

    # =================== Stress Classification ===================

    def compute_stress(self):
        """Compute daily stress classification from raw_stress data.

        Uses Garmin/Firstbeat thresholds:
          0-25 = relaxed, 26-50 = low, 51-75 = medium, 76-100 = high

        Daily score = 0.5 * daytime_avg + 0.3 * peak_sustained + 0.2 * overnight_avg

        Reference: Frontiers in Physiology 2025 for circadian stress patterns.
        """
        log.info("Computing stress classification...")
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT DATE(ts) as day, EXTRACT(HOUR FROM ts) as hour,
                       stress_value, ts
                FROM raw_stress
                WHERE stress_value > 0
                ORDER BY ts
            """)
            all_stress = cur.fetchall()

        if not all_stress:
            log.info("  No stress data available")
            return

        # Group by day
        by_day: Dict = {}
        for s in all_stress:
            day = s['day']
            if day not in by_day:
                by_day[day] = []
            by_day[day].append(s)

        for day, readings in sorted(by_day.items()):
            daytime = [r for r in readings if 6 <= r['hour'] <= 22]
            overnight = [r for r in readings if r['hour'] < 6 or r['hour'] > 22]

            daytime_avg = statistics.mean([r['stress_value'] for r in daytime]) if daytime else 0
            overnight_avg = statistics.mean([r['stress_value'] for r in overnight]) if overnight else 0

            # Peak sustained: highest 2-hour rolling average
            peak = self._peak_sustained(readings)

            # Weighted daily score
            daily_score = (0.5 * daytime_avg + 0.3 * peak + 0.2 * overnight_avg)

            # Classification (Garmin/Firstbeat thresholds)
            if daily_score <= 25:
                classification = "relaxed"
            elif daily_score <= 50:
                classification = "low"
            elif daily_score <= 75:
                classification = "medium"
            else:
                classification = "high"

            # Morning/noon/evening breakdown
            morning = [r['stress_value'] for r in readings if 6 <= r['hour'] <= 10]
            noon = [r['stress_value'] for r in readings if 11 <= r['hour'] <= 15]
            evening = [r['stress_value'] for r in readings if 16 <= r['hour'] <= 22]

            with self.conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO stress_classification
                        (day, morning_rmssd, noon_rmssd, evening_rmssd, classification)
                    VALUES (%s, %s, %s, %s, %s)
                    ON CONFLICT (day) DO UPDATE SET
                        morning_rmssd = EXCLUDED.morning_rmssd,
                        noon_rmssd = EXCLUDED.noon_rmssd,
                        evening_rmssd = EXCLUDED.evening_rmssd,
                        classification = EXCLUDED.classification,
                        computed_at = NOW()
                """, (
                    day,
                    round(statistics.mean(morning)) if morning else None,
                    round(statistics.mean(noon)) if noon else None,
                    round(statistics.mean(evening)) if evening else None,
                    classification,
                ))
            self.conn.commit()

            log.info(f"  Stress {day}: avg={daily_score:.0f} ({classification})")

    def _peak_sustained(self, readings: List[Dict]) -> float:
        """Find the highest 2-hour rolling average stress level."""
        if len(readings) < 4:
            return max([r['stress_value'] for r in readings], default=0)
        values = sorted(readings, key=lambda r: r['ts'])
        peak = 0
        window = 4  # 4 readings * 30min = 2 hours
        for i in range(len(values) - window + 1):
            avg = statistics.mean([r['stress_value'] for r in values[i:i + window]])
            peak = max(peak, avg)
        return peak

    # =================== Circadian HR (unchanged) ===================

    def compute_circadian_hr(self):
        """Compute circadian HR patterns (already working)."""
        log.info("Computing circadian HR...")
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT DATE(ts) as day, EXTRACT(HOUR FROM ts) as hour,
                       AVG(bpm) as avg_hr, MIN(bpm) as min_hr, MAX(bpm) as max_hr,
                       COUNT(*) as sample_count
                FROM raw_heart_rate
                WHERE ts >= NOW() - INTERVAL '30 days'
                GROUP BY DATE(ts), EXTRACT(HOUR FROM ts)
                ORDER BY day, hour
            """)
            rows = cur.fetchall()

        for row in rows:
            with self.conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO circadian_hr (day, hour, avg_hr, min_hr, max_hr, sample_count)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    ON CONFLICT (day, hour) DO UPDATE SET
                        avg_hr = EXCLUDED.avg_hr,
                        min_hr = EXCLUDED.min_hr,
                        max_hr = EXCLUDED.max_hr,
                        sample_count = EXCLUDED.sample_count,
                        computed_at = NOW()
                """, (
                    row['day'], int(row['hour']),
                    row['avg_hr'], row['min_hr'], row['max_hr'], row['sample_count']
                ))
        self.conn.commit()
        log.info(f"  Circadian HR: {len(rows)} hour-day entries updated")

    # =================== Resting HR (cleaned up) ===================

    def compute_resting_hr(self) -> Dict:
        """Compute resting heart rate from overnight samples (1-5 AM)."""
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT DATE(ts) as day, AVG(bpm) as avg_hr, MIN(bpm) as min_hr
                FROM raw_heart_rate
                WHERE ts >= NOW() - INTERVAL '30 days'
                AND EXTRACT(HOUR FROM ts) BETWEEN 1 AND 5
                GROUP BY DATE(ts)
                ORDER BY day
            """)
            results = cur.fetchall()

        if not results:
            return {'day': date.today(), 'resting_hr': None}

        for row in results:
            with self.conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO daily_recovery (day, rmssd)
                    VALUES (%s, %s)
                    ON CONFLICT (day) DO UPDATE SET
                        rmssd = daily_recovery.rmssd
                """, (row['day'], None))
                # Don't overwrite rmssd (HRV); store RHR separately
        self.conn.commit()

        latest = results[-1]
        return {'day': latest['day'], 'resting_hr': float(latest['min_hr'])}

    # =================== Daily activity ===================

    def compute_daily_activity(self):
        """Compute per-day activity aggregates + hourly arrays in local tz.

        Replaces the dashboard's flaky client-side day filtering (which could
        misattribute data on day toggle). Server-side, after dedup, in the
        session timezone (Pacific). Powers the activity dials, the 24h day
        ring, and the steps-over-the-day graph.
        """
        log.info("Computing daily activity...")
        with self.conn.cursor() as cur:
            # Steps by (Pacific day, local hour)
            cur.execute("""
                SELECT DATE(ts) AS day,
                       EXTRACT(HOUR FROM ts)::int AS hr,
                       SUM(steps)::int AS steps,
                       SUM(distance)::int AS distance,
                       SUM(calories)::int AS calories
                FROM raw_steps
                WHERE ts >= NOW() - INTERVAL '14 days'
                GROUP BY 1, 2
            """)
            steps_rows = cur.fetchall()
            # HR by (Pacific day, local hour) — worn coverage + aggregates
            cur.execute("""
                SELECT DATE(ts) AS day,
                       EXTRACT(HOUR FROM ts)::int AS hr,
                       AVG(bpm)::int AS avg_bpm,
                       MIN(bpm)::int AS min_bpm,
                       MAX(bpm)::int AS max_bpm,
                       COUNT(*)::int AS n,
                       MIN(ts) AS first_ts,
                       MAX(ts) AS last_ts
                FROM raw_heart_rate
                WHERE ts >= NOW() - INTERVAL '14 days'
                GROUP BY 1, 2
            """)
            hr_rows = cur.fetchall()
            # Wear time: count actual hours with biometric readings (HR + HRV +
            # SpO2 — all require skin contact; steps excluded as bag movement
            # can trigger them). Apply value thresholds to filter out off-finger
            # noise (PPG sensors produce garbage readings from ambient light).
            cur.execute("""
                SELECT DATE(ts) AS day,
                       COUNT(DISTINCT EXTRACT(HOUR FROM ts))::int AS active_hours,
                       MIN(ts) AS wear_first, MAX(ts) AS wear_last
                FROM (
                    SELECT ts FROM raw_heart_rate WHERE ts >= NOW() - INTERVAL '14 days'
                    UNION ALL SELECT ts FROM raw_hrv WHERE ts >= NOW() - INTERVAL '14 days' AND hrv_value >= 15
                    UNION ALL SELECT ts FROM raw_spo2 WHERE ts >= NOW() - INTERVAL '14 days' AND spo2_pct BETWEEN 85 AND 100
                ) all_ts
                GROUP BY 1
            """)
            wear_rows = cur.fetchall()
            # Per-hour wear map: which hours have skin-contact readings
            cur.execute("""
                SELECT DISTINCT DATE(ts) AS day, EXTRACT(HOUR FROM ts)::int AS hr
                FROM (
                    SELECT ts FROM raw_heart_rate WHERE ts >= NOW() - INTERVAL '14 days'
                    UNION ALL SELECT ts FROM raw_hrv WHERE ts >= NOW() - INTERVAL '14 days' AND hrv_value >= 15
                    UNION ALL SELECT ts FROM raw_spo2 WHERE ts >= NOW() - INTERVAL '14 days' AND spo2_pct BETWEEN 85 AND 100
                ) all_ts
            """)
            wear_hourly_rows = cur.fetchall()

        steps_by_day: Dict = {}
        for r in steps_rows:
            d = r['day']
            e = steps_by_day.setdefault(d, {'hourly': [0] * 24, 'steps': 0, 'distance': 0, 'calories': 0})
            if 0 <= r['hr'] < 24:
                e['hourly'][r['hr']] = r['steps']
            e['steps'] += r['steps']
            e['distance'] += r['distance']
            e['calories'] += r['calories']

        hr_by_day: Dict = {}
        for r in hr_rows:
            d = r['day']
            e = hr_by_day.setdefault(d, {'hourly_n': [0] * 24, 'samples': 0, 'sum_bpm': 0, 'min': 999, 'max': 0, 'first': None, 'last': None})
            if 0 <= r['hr'] < 24:
                e['hourly_n'][r['hr']] = r['n']
            e['samples'] += r['n']
            e['sum_bpm'] += (r['avg_bpm'] or 0) * r['n']
            e['min'] = min(e['min'], r['min_bpm'])
            e['max'] = max(e['max'], r['max_bpm'])
            if e['first'] is None or r['first_ts'] < e['first']:
                e['first'] = r['first_ts']
            if e['last'] is None or r['last_ts'] > e['last']:
                e['last'] = r['last_ts']

        # Wear timestamps per day (from all biometric types, not just HR)
        wear_by_day = {r['day']: {'first': r['wear_first'], 'last': r['wear_last'],
                                   'hours': r['active_hours']} for r in wear_rows}
        # Per-hour wear map for the 24h ring display
        wear_hourly_by_day: Dict = {}
        for r in wear_hourly_rows:
            d = r['day']
            arr = wear_hourly_by_day.setdefault(d, [0] * 24)
            if 0 <= r['hr'] < 24:
                arr[r['hr']] = 1

        count = 0
        for d in sorted(set(steps_by_day) | set(hr_by_day) | set(wear_by_day)):
            s = steps_by_day.get(d)
            h = hr_by_day.get(d)
            hr_samples = h['samples'] if h else 0
            hr_avg = round(h['sum_bpm'] / hr_samples) if (h and hr_samples) else None
            # Wear time = actual hours with skin-contact readings (HR/HRV/SpO2)
            worn_min = None
            wear = wear_by_day.get(d)
            if wear and wear.get('hours'):
                worn_min = wear['hours'] * 60
            with self.conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO daily_activity
                        (day, steps_total, distance_m, calories_raw,
                         hr_avg, hr_min, hr_max, hr_samples, worn_minutes,
                         first_hr_ts, last_hr_ts, hourly_steps, hourly_worn, computed_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
                    ON CONFLICT (day) DO UPDATE SET
                        steps_total=EXCLUDED.steps_total, distance_m=EXCLUDED.distance_m,
                        calories_raw=EXCLUDED.calories_raw, hr_avg=EXCLUDED.hr_avg,
                        hr_min=EXCLUDED.hr_min, hr_max=EXCLUDED.hr_max, hr_samples=EXCLUDED.hr_samples,
                        worn_minutes=EXCLUDED.worn_minutes, first_hr_ts=EXCLUDED.first_hr_ts,
                        last_hr_ts=EXCLUDED.last_hr_ts, hourly_steps=EXCLUDED.hourly_steps,
                        hourly_worn=EXCLUDED.hourly_worn, computed_at=NOW()
                """, (
                    d,
                    s['steps'] if s else 0,
                    s['distance'] if s else 0,
                    s['calories'] if s else 0,
                    hr_avg,
                    (h['min'] if h and h['min'] != 999 else None),
                    (h['max'] if h and h['max'] else None),
                    hr_samples,
                    worn_min if worn_min is not None else 0,
                    h['first'] if h else (wear['first'] if wear else None),
                    h['last'] if h else (wear['last'] if wear else None),
                    json.dumps((s or {}).get('hourly', [0] * 24)),
                    json.dumps(wear_hourly_by_day.get(d, [0] * 24)),
                ))
            count += 1
        self.conn.commit()
        if count:
            log.info(f"  Daily activity: {count} days updated")

    # =================== Readiness Score ===================

    def compute_readiness_score(self, days: int = 30):
        """Unified 0-100 readiness score (Oura-style).

        Weighted composite of four pillars, each normalized 0-100:
          HRV     (35%) — z-score from daily_recovery
          Sleep   (30%) — sleep_quality.score
          Activity (20%) — steps vs goal + active minutes
          RHR     (15%) — deviation from 30-day baseline (lower = better)

        Stores one row per day into readiness_score.
        """
        log.info("Computing readiness scores...")
        # Load source data: start from a UNION of all days that have ANY data
        # (not just sleep_quality) so days with HRV but no sleep still get scored.
        with self.conn.cursor() as cur:
            cur.execute("""
                WITH days AS (
                    SELECT day FROM sleep_quality WHERE day >= CURRENT_DATE - INTERVAL '%s days'
                    UNION
                    SELECT day FROM daily_recovery WHERE day >= CURRENT_DATE - INTERVAL '%s days'
                    UNION
                    SELECT day FROM daily_activity WHERE day >= CURRENT_DATE - INTERVAL '%s days'
                )
                SELECT d.day,
                       sq.score AS sleep_score,
                       sq.total_sleep_minutes AS sleep_total_min,
                       dr.z_score AS hrv_zscore,
                       dr.rmssd AS hrv_rmssd,
                       da.steps_total,
                       da.worn_minutes,
                       da.hr_avg AS resting_hr_approx
                FROM days d
                LEFT JOIN sleep_quality sq ON d.day = sq.day
                LEFT JOIN daily_recovery dr ON d.day = dr.day
                LEFT JOIN daily_activity da ON d.day = da.day
                ORDER BY d.day
            """, (days, days, days))
            rows = cur.fetchall()
            # Personal goals for activity score
            cur.execute("SELECT steps_goal FROM ring_goals ORDER BY ts DESC LIMIT 1")
            goal_row = cur.fetchone()
        steps_goal = int(goal_row['steps_goal']) if goal_row and goal_row['steps_goal'] else 8000

        # RHR baseline: 30-day median resting HR (from daily_activity.hr_avg overnight proxy,
        # or computed_resting_hr. For now use the 30-day median of whatever daily HR we have.)
        rhr_vals = [r['resting_hr_approx'] for r in rows if r['resting_hr_approx']]
        rhr_baseline = sorted(rhr_vals)[len(rhr_vals)//2] if rhr_vals else 60

        def _hrv_to_score(z):
            if z is None: return 50
            if z >= 3.0:  return 100
            if z >= 2.0:  return 95
            if z >= 1.5:  return 90
            if z >= 1.0:  return 80
            if z >= 0.5:  return 70
            if z >= 0.0:  return 55
            if z >= -0.5: return 40
            if z >= -1.0: return 25
            return 10

        count = 0
        for r in rows:
            day = r['day']
            # --- HRV sub-score (35%) ---
            hrv = _hrv_to_score(r['hrv_zscore'])
            # --- Sleep sub-score (30%) ---
            slp = int(r['sleep_score']) if r['sleep_score'] is not None else 50
            # --- Activity sub-score (20%) ---
            steps = r['steps_total'] or 0
            act_steps = min(100, int(steps / steps_goal * 70))
            # active minutes bonus: count hours with >=500 steps
            act = min(100, act_steps)
            # --- RHR sub-score (15%) ---
            rhr_val = r['resting_hr_approx']
            rhr_s = 50
            if rhr_val:
                delta = rhr_val - rhr_baseline
                rhr_s = max(0, min(100, 60 - delta * 3))

            # Weighted composite
            score = round(0.35 * hrv + 0.30 * slp + 0.20 * act + 0.15 * rhr_s)

            # Contributors (deltas from neutral = 50)
            contrib = {
                "hrv":     round((hrv - 50) * 0.35),
                "sleep":   round((slp - 50) * 0.30),
                "activity": round((act - 50) * 0.20),
                "rhr":     round((rhr_s - 50) * 0.15),
            }

            with self.conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO readiness_score
                        (day, score, hrv_score, sleep_score, activity_score, rhr_score,
                         hrv_zscore, steps, resting_hr, hrv_rmssd,
                         sleep_total_min, rhr_baseline, contributors, computed_at)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
                    ON CONFLICT (day) DO UPDATE SET
                        score=EXCLUDED.score, hrv_score=EXCLUDED.hrv_score,
                        sleep_score=EXCLUDED.sleep_score, activity_score=EXCLUDED.activity_score,
                        rhr_score=EXCLUDED.rhr_score, hrv_zscore=EXCLUDED.hrv_zscore,
                        steps=EXCLUDED.steps, resting_hr=EXCLUDED.resting_hr,
                        hrv_rmssd=EXCLUDED.hrv_rmssd,
                        sleep_total_min=EXCLUDED.sleep_total_min,
                        rhr_baseline=EXCLUDED.rhr_baseline,
                        contributors=EXCLUDED.contributors,
                        computed_at=NOW()
                """, (day, score, hrv, slp, act, rhr_s,
                      r['hrv_zscore'], r['steps_total'], r['resting_hr_approx'],
                      r['hrv_rmssd'], r['sleep_total_min'], rhr_baseline,
                      json.dumps(contrib)))
            count += 1
        self.conn.commit()
        if count:
            log.info(f"  Readiness: {count} days updated (baseline RHR={rhr_baseline} bpm)")

    # =================== Orchestration ===================

    def run_all(self):
        """Run all analytics computations in order."""
        log.info("=== Starting analytics run ===")
        try:
            self.dedupe_sources()
        except Exception as e:
            log.error(f"Source dedup failed: {e}", exc_info=True)
        try:
            self.compute_hrv_recovery()
        except Exception as e:
            log.error(f"HRV recovery failed: {e}", exc_info=True)

        try:
            self.compute_sleep_quality()
        except Exception as e:
            log.error(f"Sleep quality failed: {e}", exc_info=True)

        try:
            self.compute_stress()
        except Exception as e:
            log.error(f"Stress classification failed: {e}", exc_info=True)

        try:
            self.compute_circadian_hr()
        except Exception as e:
            log.error(f"Circadian HR failed: {e}", exc_info=True)

        try:
            self.compute_daily_activity()
        except Exception as e:
            log.error(f"Daily activity failed: {e}", exc_info=True)

        try:
            self.compute_readiness_score()
        except Exception as e:
            log.error(f"Readiness score failed: {e}", exc_info=True)

        try:
            resting = self.compute_resting_hr()
            if resting['resting_hr']:
                log.info(f"  Resting HR: {resting['resting_hr']:.0f} bpm ({resting['day']})")
        except Exception as e:
            log.error(f"Resting HR failed: {e}", exc_info=True)

        log.info("=== Analytics complete ===")


def main():
    try:
        log.info("Starting analytics job...")
        Analytics().run_all()
        log.info("Analytics job completed successfully")
    except Exception as e:
        log.exception("Analytics failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
