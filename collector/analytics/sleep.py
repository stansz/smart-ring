"""Sleep quality score (5-component, Ohayon 2004 / Oura reverse-engineering).

Components: duration (30%), efficiency (25%), architecture (25%),
continuity (15%), latency (5%). Sessions are clustered by temporal gaps
and assigned to the wake date.
"""
from __future__ import annotations

import logging
import statistics
from datetime import date, datetime, timedelta
from typing import Dict, List, Optional

from .helpers import trap_score

log = logging.getLogger(__name__)

SESSION_GAP_MINUTES = 240  # 4 hours → new sleep session


def compute_sleep_quality(conn) -> None:
    """Compute sleep quality score from per-session stage data."""
    log.info("Computing sleep quality metrics...")
    with conn.cursor() as cur:
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

    all_stages.sort(key=lambda s: s['start_ts'])
    sessions: List[List[Dict]] = []
    current: List[Dict] = []
    for s in all_stages:
        if current:
            prev_end = current[-1]['end_ts']
            if prev_end and s['start_ts']:
                gap = (s['start_ts'] - prev_end).total_seconds() / 60
                if gap > SESSION_GAP_MINUTES:
                    sessions.append(current)
                    current = []
        current.append(s)
    if current:
        sessions.append(current)

    by_day: Dict = {}
    for sess in sessions:
        valid = [s for s in sess if s['end_ts']]
        if not valid:
            continue
        wake_dt = max(s['end_ts'] for s in valid)
        day = wake_dt.date()
        if day not in by_day:
            by_day[day] = []
        by_day[day].extend(sess)

    temp_data = _get_overnight_temps(conn)

    for day, stages in sorted(by_day.items()):
        score_data = _score_sleep_day(day, stages, temp_data.get(day, []))
        if score_data:
            _store_sleep_quality(conn, score_data)


def _score_sleep_day(day: date, stages: List[Dict], temps: List[Dict]) -> Optional[Dict]:
    stages_sorted = sorted(stages, key=lambda s: s['start_ts'])
    first_start = stages_sorted[0]['start_ts']
    last_end = stages_sorted[-1]['end_ts']
    time_in_bed = (last_end - first_start).total_seconds() / 60

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

    s_dur = trap_score(sleep_hours, 7.0, 9.0, 4.0, 10.0)
    s_eff = trap_score(efficiency, 90.0, 100.0, 60.0, 100.0)

    deep_penalty = max(0, 13 - deep_pct) + max(0, deep_pct - 23) * 1.5
    rem_penalty = max(0, 20 - rem_pct) + max(0, rem_pct - 25) * 1.0
    s_arch = max(0, 100 - deep_penalty - rem_penalty)

    waso_score = trap_score(wake_after_onset, 0, 20, 60, 0)
    aw_score = trap_score(awakenings, 0, 2, 6, 0)
    s_cont = (waso_score + aw_score) / 2

    s_lat = 80.0  # latency: ring doesn't report pre-sleep latency

    total_score = (0.30 * s_dur + 0.25 * s_eff + 0.25 * s_arch +
                   0.15 * s_cont + 0.05 * s_lat)

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


def _get_overnight_temps(conn) -> Dict[date, List[Dict]]:
    with conn.cursor() as cur:
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


def _store_sleep_quality(conn, data: Dict) -> None:
    with conn.cursor() as cur:
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
    conn.commit()
