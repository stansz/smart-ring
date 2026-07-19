"""Circadian HR — average/min/max heart rate by hour of day.

Date(ts) and EXTRACT(HOUR FROM ts) use the session timezone set in db.connect().
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)


def compute_circadian_hr(conn) -> None:
    log.info("Computing circadian HR...")
    with conn.cursor() as cur:
        cur.execute("""
            SELECT DATE(ts) AS day, EXTRACT(HOUR FROM ts) AS hour,
                   AVG(bpm) AS avg_hr, MIN(bpm) AS min_hr, MAX(bpm) AS max_hr,
                   COUNT(*) AS sample_count
            FROM raw_heart_rate
            WHERE ts >= NOW() - INTERVAL '30 days'
            GROUP BY DATE(ts), EXTRACT(HOUR FROM ts)
            ORDER BY day, hour
        """)
        rows = cur.fetchall()

    for row in rows:
        with conn.cursor() as cur:
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
    conn.commit()
    log.info(f"  Circadian HR: {len(rows)} hour-day entries updated")
