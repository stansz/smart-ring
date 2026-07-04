#!/usr/bin/env python3
"""
Analytics script for smart ring data.
Runs as a cron job every 30-60 minutes after collector completion.
Computes HRV metrics, sleep staging, recovery scores.
"""
import os
import sys
import logging
from datetime import date, datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple
import numpy as np
import statistics

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


class BaseAnalytics:
    def __init__(self):
        self.conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)

    def get_heart_rate_beats(self, hours: int = 24) -> List[Dict]:
        """Get raw heart rate beats with timestamps."""
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT ts, bpm FROM raw_heart_rate
                WHERE ts >= NOW() - INTERVAL '%s hours'
                ORDER BY ts ASC
            """, (hours,))
            return cur.fetchall()

    def get_hrv_data(self, days: int = 30) -> List[Dict]:
        """Get HRV data including RR intervals."""
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT ts, hrv_value, hrv_type, rr_intervals
                FROM raw_hrv
                WHERE ts >= NOW() - INTERVAL '%s days'
                ORDER BY ts ASC
            """, (days,))
            return cur.fetchall()

    def get_sleep_data(self, days: int = 30) -> List[Dict]:
        """Get sleep staging data."""
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT day, stage FROM raw_sleep
                WHERE day >= CURRENT_DATE - INTERVAL '%s days'
                ORDER BY day ASC
            """, (days,))
            return cur.fetchall()

    def get_steps_data(self, hours: int = 168) -> List[Dict]:
        """Get step count data."""
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT ts, steps FROM raw_steps
                WHERE ts >= NOW() - INTERVAL '%s hours'
                ORDER BY ts ASC
            """, (hours,))
            return cur.fetchall()

    def get_temperature_data(self, hours: int = 168) -> List[Dict]:
        """Get temperature data."""
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT ts, temp_c FROM raw_temperature
                WHERE ts >= NOW() - INTERVAL '%s hours'
                ORDER BY ts ASC
            """, (hours,))
            return cur.fetchall()



class HRVMetrics(BaseAnalytics):
    def compute_rmssd(self, rr_intervals_ms: List[float]) -> float:
        """Compute RMSSD from RR intervals (already in ms)."""
        if not rr_intervals_ms:
            return 0.0
        diffs = [(rr_intervals_ms[i] - rr_intervals_ms[i-1]) ** 2 for i in range(1, len(rr_intervals_ms))]
        return float(np.sqrt(np.mean(diffs)))

    def compute_pnn50(self, rr_intervals: List[float]) -> float:
        """Compute pNN50 from RR intervals."""
        if not rr_intervals:
            return 0.0
        diffs = [abs(rr_intervals[i] - rr_intervals[i-1]) for i in range(1, len(rr_intervals))]
        above_50 = sum(1 for diff in diffs if diff > 50)
        return (above_50 / len(diffs)) * 100 if diffs else 0.0

    def compute_hrv_metrics(self, days: int = 1) -> Tuple[List[Dict], Dict]:
        """Compute daily HRV metrics."""
        hrv_data = self.get_hrv_data(days)
        rr_intervals_by_day = {}
        hrv_values_by_day = {}

        for record in hrv_data:
            ts = record['ts']
            day = ts.date()
            rr_intervals = record.get('rr_intervals')

            if rr_intervals:
                # Convert to ms (raw data is in seconds)
                rr_ms = [r * 1000 for r in rr_intervals]
                rr_intervals_by_day.setdefault(day, []).extend(rr_ms)

            hrv_val = record.get('hrv_value')
            if hrv_val:
                hrv_values_by_day.setdefault(day, []).append(float(hrv_val))

        daily_metrics = []
        for day, rr_intervals in rr_intervals_by_day.items():
            rmssd = self.compute_rmssd(rr_intervals)
            pnn50 = self.compute_pnn50(rr_intervals)
            avg_hrv = statistics.mean(hrv_values_by_day.get(day, [rr_intervals[0]])) if rr_intervals else 0.0

            daily_metrics.append({
                'day': day,
                'rmssd': rmssd,
                'pnn50': pnn50,
                'avg_hrv': avg_hrv,
                'rr_intervals': rr_intervals,
                'rr_intervals_count': len(rr_intervals)
            })

        # Compute rolling averages
        rolling_metrics = self.compute_rolling_hrv(daily_metrics)
        return daily_metrics, rolling_metrics

    def compute_rolling_hrv(self, metrics: List[Dict]) -> List[Dict]:
        """Compute 7-day and 28-day rolling averages."""
        if not metrics:
            return []

        sorted_metrics = sorted(metrics, key=lambda x: x['day'])
        rolling = []

        for i, metric in enumerate(sorted_metrics):
            # 7-day window
            start_idx = max(0, i - 6)
            window_7d = [m['rmssd'] for m in sorted_metrics[start_idx:i+1] if m['rmssd']]

            # 28-day window
            start_idx = max(0, i - 27)
            window_28d = [m['rmssd'] for m in sorted_metrics[start_idx:i+1] if m['rmssd']]

            rolling.append({
                'day': metric['day'],
                'rmssd_7d': statistics.mean(window_7d) if window_7d else None,
                'rmssd_28d': statistics.mean(window_28d) if window_28d else None,
                'pnn50_7d': self.compute_pnn50_for_day(i, sorted_metrics, 7),
                'hrv_values_count': metric['rr_intervals_count']
            })

        return rolling

    def compute_pnn50_for_day(self, day_idx: int, metrics: List[Dict], window_size: int) -> Optional[float]:
        """Helper to compute pNN50 for a specific day."""
        start_idx = max(0, day_idx - window_size + 1)
        window_metrics = metrics[start_idx:day_idx+1]
        all_rr_intervals = []

        for metric in window_metrics:
            if 'rr_intervals' in metric:
                all_rr_intervals.extend(metric['rr_intervals'])

        return self.compute_pnn50(all_rr_intervals) if all_rr_intervals else None

    def store_hrv_metrics(self, metrics: List[Dict], rolling_metrics: List[Dict]):
        """Store daily HRV metrics."""
        for metric in metrics:
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
                    metric['day'],
                    metric['rmssd'],
                    None,
                    None,
                    None
                ))

        for metric in rolling_metrics:
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
                    metric['day'],
                    metric['rmssd_7d'],
                    metric['rmssd_28d'],
                    metric['pnn50_7d']
                ))


class SleepMetrics(BaseAnalytics):
    def detect_sleep_stages(self, raw_records: List[Dict], temp_records: List[Dict]) -> List[Dict]:
        """Detect sleep stages from raw data.

        The ring's cmd 68 response only provides: day, stage, sleep_qualities byte.
        No start_ts/end_ts are available from firmware. Duration is inferred.
        """
        if not raw_records:
            return []

        sleep_stages = []
        total_sleep_minutes = 0

        # Group records by day, then stage, to aggregate durations
        day_stage_records = {}
        for record in raw_records:
            day = record.get('day')
            stage = record.get('stage', 'unknown')
            if (day, stage) not in day_stage_records:
                day_stage_records[(day, stage)] = []
            day_stage_records[(day, stage)].append(record)

        for (day, stage), records in day_stage_records.items():
            # Infer duration: assume each record represents ~30 min block
            # (ring samples periodically, not continuously)
            duration_minutes = len(records) * 30

            # Build a synthetic start/end for the day based on stage type
            if stage in ['deep']:
                start_hour, start_min = 2, 0   # Deep sleep ~2 AM
            elif stage in ['rem']:
                start_hour, start_min = 4, 0   # REM ~4-5 AM
            elif stage in ['light']:
                start_hour, start_min = 23, 0  # Light sleep starts ~11 PM
            elif stage in ['wake']:
                start_hour, start_min = 7, 0   # Wake ~7 AM
            else:
                start_hour, start_min = 0, 0

            start_ts = datetime.combine(day, datetime.min.time().replace(hour=start_hour, minute=start_min))
            end_ts = start_ts + timedelta(minutes=duration_minutes)

            sleep_stages.append({
                'stage': stage,
                'duration_minutes': duration_minutes,
                'start_ts': start_ts,
                'end_ts': end_ts
            })

            if stage.lower() not in ('wake', 'w', 'unknown'):
                total_sleep_minutes += duration_minutes

        # If no sleep detected, fall back to HR-based inference
        if total_sleep_minutes == 0:
            sleep_stages = self.detect_sleep_from_hr_raw()

        return sleep_stages

    def detect_sleep_from_hr_raw(self) -> List[Dict]:
        """Fallback: detect sleep from overnight HR patterns when ring sleep data is missing.
        Uses raw_heart_rate data (ts, bpm) queried from DB — not raw_sleep."""
        hr_data = self.get_heart_rate_beats(hours=24)
        if not hr_data:
            return []

        sleep_stages = []
        night_hr = []

        for record in hr_data:
            ts = record['ts']
            bpm = record['bpm']

            hour = ts.hour
            if 1 <= hour <= 5:
                night_hr.append({'ts': ts, 'bpm': bpm})

        if len(night_hr) >= 3:
            avg_hr = sum(r['bpm'] for r in night_hr) / len(night_hr)
            hr_variance = statistics.variance([r['bpm'] for r in night_hr]) if len(night_hr) > 1 else 0

            if hr_variance < 50:
                sleep_stages.append({
                    'stage': 'SLEEP',
                    'duration_minutes': 180,
                    'start_ts': datetime.now().replace(hour=22, minute=0),
                    'end_ts': datetime.now().replace(hour=5, minute=0)
                })

        return sleep_stages

    def compute_sleep_quality_score(self, sleep_stages: List[Dict], temp_records: List[Dict]) -> Tuple[Dict, Dict]:
        """Compute sleep quality score with staging."""
        if not sleep_stages:
            return {}, {}

        total_score = 0.0
        detailed_scores = []

        # Sleep stage scoring
        stage_weights = {
            'SLEEP': 0.5,
            'DEEP': 2.0,
            'LIGHT': 1.0,
            'REM': 1.5,
            'S': 2.0,  # Short sleep
            'D': 2.0,  # Deep
            'L': 1.0,  # Light
            'R': 1.5,  # REM
        }

        for stage in sleep_stages:
            weight = stage_weights.get(stage['stage'], 1.0)
            score = stage['duration_minutes'] * weight
            total_score += score

            detailed_scores.append({
                'date': date.today(),
                f"{stage['stage'].lower()}_minutes": stage['duration_minutes'],
                'start_ts': stage['start_ts'],
                'end_ts': stage['end_ts']
            })

        # Temperature bonus for sleep staging
        temp_bonus = self.compute_temperature_bonus(temp_records)

        # Normalize to 0-100 scale
        normalized_score = min(100, total_score / 20 + temp_bonus)

        # Calculate percentages
        total_minutes = max(sum(s['duration_minutes'] for s in sleep_stages), 60)
        stage_percentages = {}
        for s in sleep_stages:
            key = f"{s['stage'].lower()}_pct"
            stage_percentages[key] = (s['duration_minutes'] / total_minutes) * 100

        # Calculate temperature drop during sleep (highest - lowest)
        temp_drop_c = 0.0
        if len(temp_records) >= 2:
            temps = [r['temp_c'] for r in temp_records]
            temp_drop_c = max(temps) - min(temps)

        return (
            {
                'day': date.today(),
                'score': normalized_score,
                **stage_percentages,
                'temp_drop_c': temp_drop_c,
                'total_sleep_minutes': total_minutes
            },
            {date.today(): {'stages': detailed_scores, 'temp_drop_c': temp_drop_c}}
        )

    def compute_temperature_bonus(self, temp_records: List[Dict]) -> float:
        """Compute temperature bonus for sleep staging."""
        if not temp_records or len(temp_records) < 2:
            return 0.0

        # Look for temp drops during sleep (typically 0.5-1.5°C)
        for i in range(1, len(temp_records)):
            prev_temp = temp_records[i-1]['temp_c']
            curr_temp = temp_records[i]['temp_c']
            drop = prev_temp - curr_temp

            if drop > 0.3:  # Significant temperature drop indicates deep sleep
                return min(drop * 10, 15)  # Max 15 points bonus

        return 0.0

    def compute_circadian_hr(self):
        """Compute circadian HR patterns."""
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT DATE(ts) as day, EXTRACT(HOUR FROM ts) as hour,
                       AVG(bpm) as avg_hr, MIN(bpm) as min_hr, MAX(bpm) as max_hr, COUNT(*) as sample_count
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
                    row['day'],
                    int(row['hour']),
                    row['avg_hr'],
                    row['min_hr'],
                    row['max_hr'],
                    row['sample_count']
                ))

    def store_sleep_metrics(self, score: Dict, detailed: Dict):
        """Store sleep quality metrics."""
        with self.conn.cursor() as cur:
            cur.execute("""
                INSERT INTO sleep_quality (day, score, deep_pct, rem_pct, light_pct,
                                         wake_pct, temp_drop_c, total_sleep_minutes)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (day) DO UPDATE SET
                score = EXCLUDED.score,
                deep_pct = EXCLUDED.deep_pct,
                rem_pct = EXCLUDED.rem_pct,
                light_pct = EXCLUDED.light_pct,
                wake_pct = EXCLUDED.wake_pct,
                temp_drop_c = EXCLUDED.temp_drop_c,
                total_sleep_minutes = EXCLUDED.total_sleep_minutes,
                computed_at = NOW()
            """, (
                score['day'],
                score['score'],
                score.get('deep_pct', 0),
                score.get('rem_pct', 0),
                score.get('light_pct', 0),
                score.get('wake_pct', 0),
                score['temp_drop_c'],
                score['total_sleep_minutes']
            ))

    def compute_resting_hr(self) -> Dict:
        """Compute resting heart rate from overnight samples."""
        with self.conn.cursor() as cur:
            cur.execute("""
                SELECT DATE_TRUNC('hour', ts) as hour, AVG(bpm) as avg_hr
                FROM raw_heart_rate
                WHERE ts >= NOW() - INTERVAL '90 days'
                AND EXTRACT(HOUR FROM ts) BETWEEN 1 AND 5
                GROUP BY DATE_TRUNC('hour', ts)
                ORDER BY hour
            """)
            results = cur.fetchall()

            if not results:
                return {'day': date.today(), 'resting_hr': None}

            # Get the minimum HR from nighttime periods for each day
            night_hr_by_day = {}
            for result in results:
                day = result['hour'].date()
                if day not in night_hr_by_day:
                    night_hr_by_day[day] = []
                night_hr_by_day[day].append(float(result['avg_hr']))

            latest_day = date.today()
            latest_hr_values = night_hr_by_day.get(latest_day, [])

            if latest_hr_values:
                resting_hr = min(latest_hr_values)
                return {'day': latest_day, 'resting_hr': resting_hr}

        return {'day': date.today(), 'resting_hr': None}

    def compute_recovery_score(self, rmssd_metrics: List[Dict], resting_hr: Dict) -> Dict:
        """Compute Recife Recovery Score (z-score)."""
        if not rmssd_metrics:
            return {'day': date.today(), 'rmssd': None, 'baseline_rmssd': None, 'z_score': None, 'readiness_text': None}

        sorted_metrics = sorted(rmssd_metrics, key=lambda x: x['day'])

        if len(sorted_metrics) < 7:
            baseline_rmssd = sorted_metrics[-1]['rmssd']
            z_score = 0
        else:
            # Compute 7-day baseline (exclude current day)
            baseline_days = sorted_metrics[:-1]
            baseline_rmssd = statistics.mean([m['rmssd'] for m in baseline_days])
            current_rmssd = sorted_metrics[-1]['rmssd']

            if baseline_rmssd and current_rmssd and baseline_rmssd > 0:
                std_dev = statistics.stdev([m['rmssd'] for m in baseline_days]) if len(baseline_days) > 1 else baseline_rmssd * 0.1
                z_score = (current_rmssd - baseline_rmssd) / std_dev if std_dev > 0 else 0
            else:
                z_score = 0

        # Convert z-score to readiness rating
        if z_score is None:
            readiness_text = "Poor"
        elif z_score > 1.5:
            readiness_text = "Excellent"
        elif z_score > 0.5:
            readiness_text = "Good"
        elif z_score > -0.5:
            readiness_text = "Fair"
        elif z_score > -1.5:
            readiness_text = "Poor"
        else:
            readiness_text = "Very Poor"

        return {
            'day': date.today(),
            'rmssd': sorted_metrics[-1]['rmssd'] if sorted_metrics else None,
            'resting_hr': resting_hr.get('resting_hr'),
            'baseline_rmssd': baseline_rmssd,
            'z_score': z_score,
            'readiness_text': readiness_text
        }

    def compute_stress_classification(self) -> Dict:
        """Compute stress classification based on tri-daily HRV pattern."""
        hrv_data = self.get_hrv_data(30)
        if not hrv_data:
            return {'day': date.today(), 'stress_class': 'unknown'}

        # Collect morning, noon, and evening HRV for each day
        daily_samples = {}

        for record in hrv_data:
            ts = record['ts']
            hour = ts.hour
            day = ts.date()
            rmssd = record.get('rmssd')

            if rmssd is not None:
                if day not in daily_samples:
                    daily_samples[day] = {'morning': None, 'noon': None, 'evening': None}

                if 6 <= hour <= 10:
                    daily_samples[day]['morning'] = rmssd
                elif 11 <= hour <= 15:
                    daily_samples[day]['noon'] = rmssd
                elif 16 <= hour <= 22:
                    daily_samples[day]['evening'] = rmssd

        # Analyze most recent complete day
        if not daily_samples:
            return {'day': date.today(), 'stress_class': 'no_data'}

        samples = daily_samples[latest_day]

        if not all(samples.values()):
            return {'day': latest_day, 'stress_class': 'partial'}

        morning, noon, evening = samples['morning'], samples['noon'], samples['evening']

        # Simple stress classification based on HRV variance
        hrv_values = [morning, noon, evening]
        mean_hrv = statistics.mean(hrv_values)
        variance = statistics.variance(hrv_values) if len(hrv_values) > 1 else 0

        if mean_hrv < 20 and variance < 50:
            classification = 'resting'
        elif mean_hrv > 40 and variance > 100:
            classification = 'stressed'
        else:
            classification = 'normal'

        return {
            'day': latest_day,
            'morning_rmssd': morning,
            'noon_rmssd': noon,
            'evening_rmssd': evening,
            'classification': classification
        }

    def run_all_analytics(self):
        """Run all analytics computations."""
        log.info("Running analytics computations...")

        hrv = HRVMetrics()

        log.info("Computing HRV metrics...")
        hrv_metrics, rolling_metrics = hrv.compute_hrv_metrics(days=30)
        hrv.store_hrv_metrics(hrv_metrics, rolling_metrics)

        log.info("Computing sleep metrics...")
        sleep_records = self.get_sleep_data(30)
        temp_records = self.get_temperature_data(168)
        sleep_stages = self.detect_sleep_stages(sleep_records, temp_records)
        if sleep_stages:
            score, detailed = self.compute_sleep_quality_score(sleep_stages, temp_records)
            self.store_sleep_metrics(score, detailed)

        log.info("Computing circadian HR...")
        self.compute_circadian_hr()

        log.info("Computing resting HR...")
        resting_hr = self.compute_resting_hr()
        with self.conn.cursor() as cur:
            cur.execute("""
                INSERT INTO daily_recovery (day, rmssd, baseline_rmssd, z_score, readiness_text)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (day) DO UPDATE SET
                rmssd = EXCLUDED.rmssd
                WHERE daily_recovery.day = %s
            """, (resting_hr['day'], resting_hr['resting_hr'], None, None, None, resting_hr['day']))

        log.info("Computing recovery score...")
        recovery_score = self.compute_recovery_score(hrv_metrics, resting_hr)
        if recovery_score['z_score'] is not None:
            with self.conn.cursor() as cur:
                cur.execute("""
                    UPDATE daily_recovery
                    SET baseline_rmssd = %s,
                        z_score = %s,
                        readiness_text = %s
                    WHERE day = %s
                """, (
                    recovery_score['baseline_rmssd'],
                    recovery_score['z_score'],
                    recovery_score['readiness_text'],
                    recovery_score['day']
                ))

        log.info("Computing stress classification...")
        stress = self.compute_stress_classification()
        with self.conn.cursor() as cur:
            cur.execute("""
                INSERT INTO stress_classification (day, morning_rmssd, noon_rmssd, evening_rmssd, classification)
                VALUES (%s, %s, %s, %s, %s)
                ON CONFLICT (day) DO UPDATE SET
                morning_rmssd = EXCLUDED.morning_rmssd,
                noon_rmssd = EXCLUDED.noon_rmssd,
                evening_rmssd = EXCLUDED.evening_rmssd,
                classification = EXCLUDED.classification,
                computed_at = NOW()
            """, (
                stress['day'],
                stress['morning_rmssd'],
                stress['noon_rmssd'],
                stress['evening_rmssd'],
                stress['classification']
            ))

        log.info("Analytics completed successfully")


def main():
    """Main analytics function."""
    try:
        log.info("Starting analytics job...")
        SleepMetrics().run_all_analytics()
        log.info("Analytics job completed successfully")
    except Exception as e:
        log.exception("Analytics failed")
        sys.exit(1)


if __name__ == "__main__":
    main()