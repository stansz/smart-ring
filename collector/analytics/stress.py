"""Stress classification (Garmin/Firstbeat thresholds).

Daily score = 0.5 * daytime_avg + 0.3 * peak_sustained + 0.2 * overnight_avg.
Reference: Frontiers in Physiology 2025 for circadian stress patterns.
"""
from __future__ import annotations

import logging
import statistics
from typing import Dict, List

log = logging.getLogger(__name__)


def compute_stress(conn) -> None:
    log.info("Computing stress classification...")
    with conn.cursor() as cur:
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

        peak = _peak_sustained(readings)
        daily_score = (0.5 * daytime_avg + 0.3 * peak + 0.2 * overnight_avg)

        if daily_score <= 25:
            classification = "relaxed"
        elif daily_score <= 50:
            classification = "low"
        elif daily_score <= 75:
            classification = "medium"
        else:
            classification = "high"

        morning = [r['stress_value'] for r in readings if 6 <= r['hour'] <= 10]
        noon = [r['stress_value'] for r in readings if 11 <= r['hour'] <= 15]
        evening = [r['stress_value'] for r in readings if 16 <= r['hour'] <= 22]

        with conn.cursor() as cur:
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
        conn.commit()

        log.info(f"  Stress {day}: avg={daily_score:.0f} ({classification})")


def _peak_sustained(readings: List[Dict]) -> float:
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
