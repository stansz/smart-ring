"""Readiness score (WHOOP-style, 3-pillar).

HRV 44% / Sleep 37% / RHR 19%. Activity (same-day steps) intentionally
removed — circular to score "readiness for today" using today's activity.

RHR uses daily_activity.hr_min (overnight minimum) as the resting-HR proxy,
NOT a 1-5 AM average.
"""
from __future__ import annotations

import json
import logging

log = logging.getLogger(__name__)


def compute_readiness_score(conn, days: int = 30) -> None:
    log.info("Computing readiness scores...")
    with conn.cursor() as cur:
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
                   da.hr_min AS resting_hr_approx
            FROM days d
            LEFT JOIN sleep_quality sq ON d.day = sq.day
            LEFT JOIN daily_recovery dr ON d.day = dr.day
            LEFT JOIN daily_activity da ON d.day = da.day
            ORDER BY d.day
        """, (days, days, days))
        rows = cur.fetchall()

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
    weights = {"hrv": 0.44, "sleep": 0.37, "rhr": 0.19}
    for r in rows:
        day = r['day']

        has_hrv      = r['hrv_zscore'] is not None
        has_sleep    = r['sleep_score'] is not None
        has_rhr      = r['resting_hr_approx'] is not None
        available_weight = sum(
            w for k, w in weights.items()
            if {"hrv": has_hrv, "sleep": has_sleep, "rhr": has_rhr}[k]
        )

        hrv  = _hrv_to_score(r['hrv_zscore']) if has_hrv else None
        slp  = int(r['sleep_score']) if has_sleep else None
        rhr_s = None
        if has_rhr:
            delta = r['resting_hr_approx'] - rhr_baseline
            rhr_s  = max(0, min(100, 60 - delta * 3))

        sub_scores = [
            (hrv, weights["hrv"]),
            (slp, weights["sleep"]),
            (rhr_s, weights["rhr"]),
        ]
        if available_weight > 0:
            score = round(sum(s * w for s, w in sub_scores if s is not None)
                          / available_weight)
        else:
            score = 0

        missing = [
            k for k, v in {"hrv": has_hrv, "sleep": has_sleep, "rhr": has_rhr}.items()
            if not v
        ]
        confidence = "partial" if missing else "full"

        contrib = {}
        if hrv is not None:
            contrib["hrv"] = round((hrv - 50) * weights["hrv"])
        if slp is not None:
            contrib["sleep"] = round((slp - 50) * weights["sleep"])
        if rhr_s is not None:
            contrib["rhr"] = round((rhr_s - 50) * weights["rhr"])

        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO readiness_score
                    (day, score, hrv_score, sleep_score, rhr_score,
                     hrv_zscore, resting_hr, hrv_rmssd,
                     sleep_total_min, rhr_baseline, contributors,
                     confidence, missing_components, computed_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
                ON CONFLICT (day) DO UPDATE SET
                    score=EXCLUDED.score, hrv_score=EXCLUDED.hrv_score,
                    sleep_score=EXCLUDED.sleep_score,
                    rhr_score=EXCLUDED.rhr_score, hrv_zscore=EXCLUDED.hrv_zscore,
                    resting_hr=EXCLUDED.resting_hr,
                    hrv_rmssd=EXCLUDED.hrv_rmssd,
                    sleep_total_min=EXCLUDED.sleep_total_min,
                    rhr_baseline=EXCLUDED.rhr_baseline,
                    contributors=EXCLUDED.contributors,
                    confidence=EXCLUDED.confidence,
                    missing_components=EXCLUDED.missing_components,
                    computed_at=EXCLUDED.computed_at
            """, (day, score, hrv, slp, rhr_s,
                  r['hrv_zscore'], r['resting_hr_approx'],
                  r['hrv_rmssd'], r['sleep_total_min'], rhr_baseline,
                  json.dumps(contrib), confidence, missing))
        count += 1
    conn.commit()
    if count:
        partial = sum(1 for r in rows if r.get('resting_hr_approx') is None or r.get('hrv_zscore') is None)
        log.info(f"  Readiness: {count} days updated (baseline RHR={rhr_baseline} bpm)"
                 + (f", {partial} with partial confidence" if partial else ""))
