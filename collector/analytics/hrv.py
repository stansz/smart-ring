"""HRV recovery score (Plews/Buchheit/Altini framework).

ln(RMSSD) z-score against 7-day rolling baseline.
Marco Altini, Sensors 2021 (9M measurements).
"""
from __future__ import annotations

import logging
import math
import statistics

from .helpers import readiness_text

log = logging.getLogger(__name__)


def compute_hrv_recovery(conn) -> None:
    """Compute daily HRV recovery metrics from composite HRV values."""
    log.info("Computing HRV recovery metrics...")
    with conn.cursor() as cur:
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

    ln_values = []  # list of (day, ln_avg, avg_hrv, samples)
    for row in daily:
        ln_val = math.log(row['avg_hrv'])
        ln_values.append((row['day'], ln_val, float(row['avg_hrv']),
                          int(row['samples']), float(row['min_hrv']),
                          float(row['max_hrv'])))

    for i, (day, ln_today, avg_hrv, samples, min_h, max_h) in enumerate(ln_values):
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

        with conn.cursor() as cur:
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
        conn.commit()

        # hrv_trends (7-day and 28-day rolling)
        window_7d = [v[1] for v in ln_values[max(0, i - 6):i + 1]]
        window_28d = [v[1] for v in ln_values[max(0, i - 27):i + 1]]
        rmssd_7d = math.exp(statistics.mean(window_7d)) if window_7d else None
        rmssd_28d = math.exp(statistics.mean(window_28d)) if len(window_28d) >= 7 else None

        with conn.cursor() as cur:
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
        conn.commit()

        if z_score:
            log.info(f"  HRV {day}: avg={avg_hrv:.1f}ms z={z_score:.2f}")
        else:
            log.info(f"  HRV {day}: avg={avg_hrv:.1f}ms (no baseline)")
