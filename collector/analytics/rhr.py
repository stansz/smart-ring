"""Resting HR — average bpm between 1-5 AM local time.

NOTE: kept for legacy compatibility but the readiness score now uses
`daily_activity.hr_min` (overnight minimum) instead of this 1-5 AM
average. See /api/readiness and analytics/readiness.py.
"""
from __future__ import annotations

import logging
from datetime import date

log = logging.getLogger(__name__)


def compute_resting_hr(conn) -> dict:
    """Compute resting heart rate from overnight samples (1-5 AM)."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT DATE(ts) AS day, AVG(bpm) AS avg_hr, MIN(bpm) AS min_hr
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
        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO daily_recovery (day, rmssd)
                VALUES (%s, %s)
                ON CONFLICT (day) DO UPDATE SET
                    rmssd = daily_recovery.rmssd
            """, (row['day'], None))
            # Don't overwrite rmssd (HRV); store RHR separately
    conn.commit()

    latest = results[-1]
    return {'day': latest['day'], 'resting_hr': float(latest['min_hr'])}
