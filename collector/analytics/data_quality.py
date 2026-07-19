"""Data quality — per-type freshness check.

Flag stale/missing data:
- For each day, if ANY type has data (ring worn + synced) but a specific
  type has 0 records → 'stale'
- Days with zero records across ALL types → 'missing' (not worn / no sync)
- Otherwise → 'ok'

Temperature has a 1-day publish cadence (history buffer exposes completed
days only), so today's temp is normally pending — not stale.
DATE() uses session TZ set in db.connect.
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)


def compute_data_quality(conn, days: int = 7) -> None:
    log.info("Computing data quality...")
    types = {
        "heart_rate":   "raw_heart_rate",
        "spo2":         "raw_spo2",
        "temperature":  "raw_temperature",
        "hrv":          "raw_hrv",
        "steps":        "raw_steps",
        "stress":       "raw_stress",
    }
    with conn.cursor() as cur:
        day_counts: dict = {}  # day -> {type: count}
        for data_type, table in types.items():
            cur.execute(f"""
                SELECT DATE(ts) AS day,
                       COUNT(*) AS cnt, MAX(ts) AS last_ts
                FROM {table}
                WHERE ts >= NOW() - INTERVAL %s
                GROUP BY 1
            """, (f"{days} days",))
            for row in cur.fetchall():
                d = str(row["day"])
                day_counts.setdefault(d, {})[data_type] = row["cnt"]
                day_counts[d].setdefault(f"{data_type}_last_ts", row["last_ts"])

        today_str = max(day_counts.keys()) if day_counts else None
        for d, counts in day_counts.items():
            any_data = any(
                counts.get(t, 0) > 0 for t in types
            )
            for data_type in types:
                cnt = counts.get(data_type, 0)
                if any_data and cnt == 0:
                    if data_type == "temperature" and d == today_str:
                        status = "ok"
                    else:
                        status = "stale"
                elif not any_data:
                    status = "missing"
                else:
                    status = "ok"
                last_ts = counts.get(f"{data_type}_last_ts")
                cur.execute("""
                    INSERT INTO data_quality (day, data_type, last_ts,
                                              sample_count, status, checked_at)
                    VALUES (%s, %s, %s, %s, %s, NOW())
                    ON CONFLICT (day, data_type) DO UPDATE SET
                        last_ts = EXCLUDED.last_ts,
                        sample_count = EXCLUDED.sample_count,
                        status = EXCLUDED.status,
                        checked_at = EXCLUDED.checked_at
                """, (d, data_type, last_ts, cnt, status))
        conn.commit()
        stale_types = [t for t in types
                       if any(day_counts.get(d, {}).get(t, 0) == 0
                              and any(day_counts.get(d, {}).get(t2, 0) > 0 for t2 in types)
                              for d in day_counts)]
        if stale_types:
            log.info(f"  Data quality: stale types = {stale_types}, "
                     f"checked {len(day_counts)} days")
        else:
            log.info(f"  Data quality: all types fresh ({len(day_counts)} days)")
