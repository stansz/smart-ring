"""Daily activity aggregates + hourly arrays.

Server-computed in session TZ (set in db.connect). Powers the activity dials,
24h day ring, and steps-over-the-day graph.
"""
from __future__ import annotations

import json
import logging
from typing import Dict

log = logging.getLogger(__name__)


def compute_daily_activity(conn) -> None:
    log.info("Computing daily activity...")
    with conn.cursor() as cur:
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
        # Single round-trip via CTE: same UNION ALL, two projections.
        cur.execute("""
            WITH skin AS (
                SELECT ts FROM raw_heart_rate WHERE ts >= NOW() - INTERVAL '14 days'
                UNION ALL
                SELECT ts FROM raw_hrv WHERE ts >= NOW() - INTERVAL '14 days' AND hrv_value >= 15
                UNION ALL
                SELECT ts FROM raw_spo2 WHERE ts >= NOW() - INTERVAL '14 days' AND spo2_pct BETWEEN 85 AND 100
            )
            SELECT
                DATE(ts) AS day,
                COUNT(DISTINCT EXTRACT(HOUR FROM ts))::int AS active_hours,
                MIN(ts) AS wear_first,
                MAX(ts) AS wear_last,
                ARRAY_AGG(DISTINCT EXTRACT(HOUR FROM ts)::int) AS hours
            FROM skin
            GROUP BY 1
        """)
        wear_rows = cur.fetchall()

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

    wear_by_day = {r['day']: {'first': r['wear_first'], 'last': r['wear_last'],
                               'hours': r['active_hours']} for r in wear_rows}
    wear_hourly_by_day: Dict = {}
    for r in wear_rows:
        d = r['day']
        arr = wear_hourly_by_day.setdefault(d, [0] * 24)
        for hr in r['hours'] or []:
            if 0 <= hr < 24:
                arr[hr] = 1

    count = 0
    for d in sorted(set(steps_by_day) | set(hr_by_day) | set(wear_by_day)):
        s = steps_by_day.get(d)
        h = hr_by_day.get(d)
        hr_samples = h['samples'] if h else 0
        hr_avg = round(h['sum_bpm'] / hr_samples) if (h and hr_samples) else None
        worn_min = None
        wear = wear_by_day.get(d)
        if wear and wear.get('hours'):
            worn_min = wear['hours'] * 60
        with conn.cursor() as cur:
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
    conn.commit()
    if count:
        log.info(f"  Daily activity: {count} days updated")
