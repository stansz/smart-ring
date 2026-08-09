#!/usr/bin/env python3
"""One-time demo-data seeder for screenshot capture.

Generates synthetic-but-plausible Colmi R09 data (HR / HRV / SpO2 / skin temp /
stress / steps / sleep) plus a handful of fake Garmin activities with
**generic, arbitrary GPS coordinates** (NOT real locations) into the database
named by ``DATABASE_URL``. The real analytics engine then computes every score
from that raw data, so the dashboard renders fully-populated, internally
consistent numbers — with zero exposure of real health data or real GPS routes.

Isolated from production by ``DATABASE_URL``: point it at a throwaway DB
(e.g. ``smart_ring_demo``) and production is never touched.

Pure generator helpers are unit-tested in ``tests/test_demo_data.py``; the
``seed(conn, days=...)`` entry point is exercised DB-backed there too.

Usage::

    DATABASE_URL=postgresql://smart_ring:changeme@localhost:5432/smart_ring_demo \
        venv/bin/python3 -m scripts.seed_demo_data            # default 30 days
    DATABASE_URL=... venv/bin/python3 -m scripts.seed_demo_data --days 30 --seed 42
"""
from __future__ import annotations

import argparse
import hashlib
import math
import os
import random
import sys
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import psycopg2
from psycopg2.extras import RealDictCursor

# Demo raw rows are tagged ``source='ring'`` (NOT a synthetic tag like 'demo')
# because the analytics scorers filter to known sources only — sleep scorer's
# `WHERE source = ANY(priority_chain)` and dedupe both ignore unknown sources.
# In a throwaway DB there's no production data to confuse, and 'ring' is the
# semantically-correct tag for data representing what the ring collects.
# Garmin activity tables use source='garmin' (the schema default).
DEMO_SOURCE = "ring"

DEFAULT_DAYS = 30
DEFAULT_TZ = "America/Vancouver"

# Arbitrary, generic GPS anchor for fake activities. Clearly synthetic — not
# derived from any real data. Chosen so the Leaflet map renders streets.
GPS_CENTER = (43.6532, -79.3832)  # arbitrary placeholder coords

# Garmin activities to fabricate: (sport, days_ago, duration_min, start_hour)
GARMIN_ACTIVITIES = [
    ("walking", 2, 55, 18),
    ("walking", 5, 42, 7),
    ("running", 8, 33, 6),
    ("walking", 12, 68, 19),
    ("running", 17, 28, 7),
    ("walking", 24, 50, 18),
]

# ---------------------------------------------------------------------------
# Pure helpers — unit tested. Keep them side-effect-free (take an `rng`).
# ---------------------------------------------------------------------------

_SEMICIRCLE_FACTOR = 2 ** 31 / 180.0  # FIT: 1 semicircle = 180 / 2^31 degrees


def deg_to_semicircles(deg: float) -> int:
    """Convert decimal degrees to FIT semicircles (sint32 range)."""
    return int(round(deg * _SEMICIRCLE_FACTOR))


def semicircles_to_deg(semi: int) -> float:
    """Inverse of deg_to_semicircles."""
    return semi / _SEMICIRCLE_FACTOR


def circadian_hr(hour: float, *, in_activity: bool = False,
                 rng: random.Random | None = None) -> int:
    """Plausible heart rate (bpm) for a local time-of-day.

    Minimum (~52) around 05:00, maximum (~76) mid-afternoon, +noise. Activity
    windows push HR into the 95-130 cardio range.
    """
    rng = rng or random
    base = 64.0 - 12.0 * math.cos(2 * math.pi * (hour - 5) / 24.0)
    if in_activity:
        base += rng.uniform(28, 55)
    base += rng.uniform(-4, 4)
    return max(45, int(round(base)))


def hrv_for_time(hour: float, rng: random.Random | None = None) -> int:
    """HRV (ms): peaks overnight (~50 at 04:00), dips midday (~26). Always > 0."""
    rng = rng or random
    base = 38.0 + 12.0 * math.cos(2 * math.pi * (hour - 4) / 24.0)
    base += rng.uniform(-5, 5)
    return max(15, int(round(base)))


def steps_for_slot(hour: int, rng: random.Random | None = None) -> int:
    """Steps in a 15-min slot: zero overnight, two walk bursts, light rest."""
    rng = rng or random
    if hour < 6 or hour >= 23:
        return 0
    if hour in (7, 8, 18, 19):  # morning + evening walks
        return rng.randint(400, 1100)
    return rng.randint(10, 150)


def spo2_value(rng: random.Random | None = None) -> int:
    rng = rng or random
    return rng.randint(95, 99)


def stress_for_time(hour: float, *, in_activity: bool = False,
                    rng: random.Random | None = None) -> int:
    """Stress (0-99): low overnight (5-15), moderate day (15-35), spikes in activity."""
    rng = rng or random
    base = 20.0 - 8.0 * math.cos(2 * math.pi * (hour - 5) / 24.0)
    if in_activity:
        base += rng.uniform(25, 45)
    base += rng.uniform(-6, 6)
    return max(0, min(99, int(round(base))))


def skin_temp_for_time(hour: float, rng: random.Random | None = None) -> float:
    """Skin temperature (°C, NUMERIC 4,2): ~30.5-32.5 with overnight dip."""
    rng = rng or random
    base = 31.5 - 0.6 * math.cos(2 * math.pi * (hour - 4) / 24.0)
    base += rng.uniform(-0.3, 0.3)
    return round(base, 2)


def sleep_stages_for_night(bedtime: datetime, wake: datetime,
                           rng: random.Random | None = None) -> list[dict]:
    """Build a realistic stage block list spanning [bedtime, wake).

    Returns rows: {stage, start_ts, end_ts, duration_minutes}. Architecture
    targets Ohayon 2004 norms: deep 14-20%, REM 20-24%, light ~55%, awake 5-9%.
    Blocks are packed front-to-back and always fill the full window.
    """
    rng = rng or random
    total_min = int((wake - bedtime).total_seconds() // 60)
    if total_min < 30:
        return []

    # Target proportions (Ohayon 2004 norms).
    awake_pct = rng.uniform(0.05, 0.09)
    deep_pct = rng.uniform(0.14, 0.20)
    rem_pct = rng.uniform(0.20, 0.24)
    light_pct = 1.0 - awake_pct - deep_pct - rem_pct

    awake_budget = int(total_min * awake_pct)
    deep_budget = int(total_min * deep_pct)
    rem_budget = int(total_min * rem_pct)
    light_budget = total_min - awake_budget - deep_budget - rem_budget

    n_cycles = rng.randint(4, 6)
    deep_w = [max(1, n_cycles - i) for i in range(n_cycles)]  # front-loaded
    rem_w = [i + 1 for i in range(n_cycles)]                   # back-loaded
    deep_w_sum, rem_w_sum = sum(deep_w), sum(rem_w)

    blocks: list[dict] = []
    cursor = bedtime
    remaining = total_min

    def _emit(stage: str, minutes: int) -> None:
        nonlocal cursor, remaining
        minutes = min(minutes, remaining)
        if minutes <= 0:
            return
        end = cursor + timedelta(minutes=minutes)
        blocks.append({"stage": stage, "start_ts": cursor, "end_ts": end,
                       "duration_minutes": minutes})
        cursor = end
        remaining -= minutes

    for c in range(n_cycles):
        if remaining <= 5:
            break
        _emit("light", light_budget // n_cycles)
        _emit("deep", deep_budget * deep_w[c] // deep_w_sum)
        _emit("rem", rem_budget * rem_w[c] // rem_w_sum)
        # Brief awake between cycles (not after the last one).
        if c < n_cycles - 1:
            _emit("awake", awake_budget // max(n_cycles - 1, 1))

    # Absorb any rounding remainder as light sleep so the window is fully filled.
    if remaining > 0:
        _emit("light", remaining)
    return blocks


def generate_polyline(center_lat: float, center_lon: float, n_points: int,
                      speed_mps: float, dt_s: float = 2.0,
                      rng: random.Random | None = None) -> list[tuple[float, float]]:
    """Smoothed random-walk GPS path around an arbitrary anchor.

    Returns [(lat, lon), ...] of length n_points. Bearing does a gentle random
    walk so the route meanders like a real walk rather than zig-zagging.
    """
    rng = rng or random
    lat, lon = center_lat, center_lon
    bearing = rng.uniform(0, 2 * math.pi)
    pts: list[tuple[float, float]] = [(lat, lon)]
    step = speed_mps * dt_s
    meters_to_deg_lat = 1.0 / 111000.0
    for _ in range(n_points - 1):
        bearing += rng.uniform(-0.35, 0.35)
        lat += step * math.cos(bearing) * meters_to_deg_lat
        lon += step * math.sin(bearing) * meters_to_deg_lat / max(math.cos(math.radians(lat)), 0.5)
        pts.append((lat, lon))
    return pts


# ---------------------------------------------------------------------------
# DB seeding
# ---------------------------------------------------------------------------

def _connect() -> "psycopg2.extensions.connection":
    url = os.environ.get(
        "DATABASE_URL",
        "postgresql://smart_ring:changeme@localhost:5432/smart_ring",
    )
    conn = psycopg2.connect(url, cursor_factory=RealDictCursor)
    tz = os.getenv("TZ") or DEFAULT_TZ
    with conn.cursor() as cur:
        cur.execute("SET TIME ZONE %s", (tz,))
    return conn


def seed(conn, days: int = DEFAULT_DAYS, rng_seed: int = 42) -> dict:
    """Seed ``days`` of synthetic data into ``conn`` (already-open, tz-set).

    Idempotent: every insert is ON CONFLICT DO NOTHING. Returns a counts dict.
    Safe to call repeatedly on the same DB.
    """
    rng = random.Random(rng_seed)
    tz = ZoneInfo(os.getenv("TZ") or DEFAULT_TZ)
    now = datetime.now(tz)
    counts: dict[str, int] = {}

    # Anchor at local midnight `days` ago, generate forward to now.
    start_date = (now - timedelta(days=days - 1)).date()
    _seed_raw(conn, rng, start_date, now, tz, counts)
    _seed_sleep(conn, rng, start_date, now, tz, counts)
    _seed_goals_status(conn, rng, now, counts)
    _seed_sync_log(conn, rng, start_date, now, tz, counts)
    _seed_garmin(conn, rng, now, tz, counts)
    return counts


def _iter_sample_ts(start_date, now, tz, *, step_min: int, include_today_partial: bool = True):
    """Yield local-time datetimes every `step_min` from start_date 00:00 up to now."""
    cursor = datetime(start_date.year, start_date.month, start_date.day, tzinfo=tz)
    cutoff = now if include_today_partial else cursor + timedelta(days=(now - cursor).days)
    while cursor <= cutoff:
        yield cursor
        cursor += timedelta(minutes=step_min)


def _seed_raw(conn, rng, start_date, now, tz, counts) -> None:
    hr_rows, hrv_rows, steps_rows, spo2_rows, stress_rows, temp_rows = [], [], [], [], [], []

    # HR / HRV / stress / temp / spo2 / steps on their native cadences.
    for ts in _iter_sample_ts(start_date, now, tz, step_min=5):
        hour = ts.hour + ts.minute / 60.0
        in_act = hour in (7.0, 7.25, 7.5, 7.75, 8.0, 18.0, 18.25, 18.5, 18.75, 19.0)
        hr_rows.append((ts, circadian_hr(hour, in_activity=in_act, rng=rng), DEMO_SOURCE))

    for ts in _iter_sample_ts(start_date, now, tz, step_min=30):
        hour = ts.hour + ts.minute / 60.0
        hrv_rows.append((ts, hrv_for_time(hour, rng), "composite", DEMO_SOURCE))
        stress_rows.append((ts, stress_for_time(hour, rng=rng), DEMO_SOURCE))
        temp_rows.append((ts, skin_temp_for_time(hour, rng), DEMO_SOURCE))

    for ts in _iter_sample_ts(start_date, now, tz, step_min=60):
        spo2_rows.append((ts, spo2_value(rng), DEMO_SOURCE))

    for ts in _iter_sample_ts(start_date, now, tz, step_min=15):
        steps = steps_for_slot(ts.hour, rng)
        calories = int(steps * rng.uniform(0.035, 0.045))
        distance = int(steps * 0.76)  # cm -> m (avg stride ~0.76m)
        steps_rows.append((ts, steps, calories, distance, DEMO_SOURCE))

    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO raw_heart_rate (ts, bpm, source) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
            hr_rows,
        )
        cur.executemany(
            "INSERT INTO raw_hrv (ts, hrv_value, hrv_type, source) VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING",
            hrv_rows,
        )
        cur.executemany(
            "INSERT INTO raw_steps (ts, steps, calories, distance, source) VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
            steps_rows,
        )
        cur.executemany(
            "INSERT INTO raw_spo2 (ts, spo2_pct, source) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
            spo2_rows,
        )
        cur.executemany(
            "INSERT INTO raw_stress (ts, stress_value, source) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
            stress_rows,
        )
        cur.executemany(
            "INSERT INTO raw_temperature (ts, temp_c, source) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
            temp_rows,
        )
    conn.commit()
    counts.update(hr=len(hr_rows), hrv=len(hrv_rows), steps=len(steps_rows),
                  spo2=len(spo2_rows), stress=len(stress_rows), temp=len(temp_rows))


def _seed_sleep(conn, rng, start_date, now, tz, counts) -> None:
    rows = []
    d = start_date
    while d <= now.date():
        bedtime = datetime(d.year, d.month, d.day, 23, tzinfo=tz) + timedelta(
            minutes=rng.randint(0, 45)
        )
        wake = bedtime + timedelta(hours=rng.randint(7, 8), minutes=rng.randint(10, 50))
        if wake > now:
            break  # don't fabricate a night that hasn't happened
        for blk in sleep_stages_for_night(bedtime, wake, rng):
            rows.append((wake.date(), blk["stage"], blk["start_ts"], blk["end_ts"],
                         blk["duration_minutes"], DEMO_SOURCE))
        d += timedelta(days=1)
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO raw_sleep (day, stage, start_ts, end_ts, duration_minutes, source) "
            "VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
            rows,
        )
    conn.commit()
    counts["sleep_blocks"] = len(rows)


def _seed_goals_status(conn, rng, now, counts) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO ring_goals (ts, steps_goal, calories_goal, distance_m_goal, sport_min_goal, sleep_min_goal) "
            "VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
            (now, 10000, 2400, 8000, 30, 480),
        )
        cur.execute(
            "INSERT INTO user_goals (key, value) VALUES ('steps_goal', 10000) ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value"
        )
        # ring_status: a few recent battery/firmware reads.
        for hrs_ago in (1, 6, 24, 48):
            cur.execute(
                "INSERT INTO ring_status (ts, battery_pct, clock_drift_ms, firmware_version) VALUES (%s,%s,%s,%s)",
                (now - timedelta(hours=hrs_ago), rng.randint(65, 95), 1,
                 "RT09_3.10.21_251107"),
            )
    conn.commit()
    counts["goals_status"] = 5


def _seed_sync_log(conn, rng, start_date, now, tz, counts) -> None:
    rows = []
    d = start_date
    while d <= now.date():
        ts = datetime(d.year, d.month, d.day, rng.randint(7, 22), rng.randint(0, 59), tzinfo=tz)
        if ts > now:
            ts = now - timedelta(minutes=rng.randint(5, 200))
        rows.append((ts, ts + timedelta(seconds=rng.randint(40, 90)),
                     rng.randint(1500, 9000), rng.randint(65, 95), 1, "completed"))
        d += timedelta(days=1)
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO sync_log (started_at, completed_at, records_synced, battery_pct, clock_drift_ms, status) "
            "VALUES (%s,%s,%s,%s,%s,%s)",
            rows,
        )
    conn.commit()
    counts["sync_log"] = len(rows)


def _seed_garmin(conn, rng, now, tz, counts) -> None:
    """Fabricate Garmin activities with generic GPS, one clean pass each.

    Per activity: generate trackpoints deterministically → compute summary
    stats from those points → insert activity row (RETURNING id) → batch-insert
    that activity's children (trackpoints / activity_hr / laps / ingest) with
    the parent id. Single pass, no regeneration, consistent stats.
    """
    n_activities = n_tp = n_ahr = n_laps = 0

    for sport, days_ago, dur_min, start_hour in GARMIN_ACTIVITIES:
        start = datetime(now.year, now.month, now.day, start_hour, rng.randint(0, 30), tzinfo=tz) \
            - timedelta(days=days_ago)
        if start > now:
            continue
        dur_s = dur_min * 60
        speed = rng.uniform(1.3, 1.7) if sport == "walking" else rng.uniform(2.6, 3.2)
        dt = 2
        n_pts = dur_s // dt
        pts = generate_polyline(GPS_CENTER[0] + rng.uniform(-0.01, 0.01),
                                GPS_CENTER[1] + rng.uniform(-0.01, 0.01),
                                n_pts, speed, dt_s=dt, rng=rng)

        base_hr = 88 if sport == "walking" else 135
        tp_rows, hr_rows = [], []
        hrs, alts, cads = [], [], []
        total_dist = 0.0
        prev_lat, prev_lon = pts[0]
        for j, (lat, lon) in enumerate(pts):
            t = start + timedelta(seconds=j * dt)
            hr = base_hr + int(rng.uniform(-12, 18))
            cad = rng.randint(70, 84) if sport == "walking" else rng.randint(150, 172)
            alt = 60 + 20 * math.sin(j / 80.0) + rng.uniform(-2, 2)
            seg = math.hypot((lat - prev_lat) * 111000,
                             (lon - prev_lon) * 111000 * math.cos(math.radians(lat)))
            total_dist += seg
            tp_rows.append((
                t, deg_to_semicircles(lat), deg_to_semicircles(lon),
                round(alt, 2), hr, cad, round(speed + rng.uniform(-0.2, 0.2), 3),
                int(total_dist), rng.randint(22, 26),
            ))
            hr_rows.append((t, hr))
            hrs.append(hr)
            alts.append(alt)
            cads.append(cad)
            prev_lat, prev_lon = lat, lon

        avg_hr = int(sum(hrs) / len(hrs))
        max_hr = max(hrs)
        avg_cad = int(sum(cads) / len(cads))
        max_cad = max(cads)
        dist_m = int(total_dist)
        gain = int(sum(max(0, alts[k] - alts[k - 1]) for k in range(1, len(alts))))
        loss = int(sum(max(0, alts[k - 1] - alts[k]) for k in range(1, len(alts))))
        strides = int(avg_cad / 60 * dur_s)
        fit_path = f"<demo>/activity_{start.strftime('%Y%m%d')}_{sport}.fit"
        fit_hash = hashlib.sha256(fit_path.encode()).hexdigest()
        end = start + timedelta(seconds=dur_s)

        # Laps: split into ~1 km chunks (capped at 8).
        n_laps_this = max(1, min(8, dist_m // 1000)) or 1
        lap_dur = dur_s // n_laps_this
        lap_rows = []
        for li in range(n_laps_this):
            ls = start + timedelta(seconds=li * lap_dur)
            chunk = lap_dur if li < n_laps_this - 1 else dur_s - li * lap_dur
            le = ls + timedelta(seconds=chunk)
            lap_rows.append((
                li + 1, ls, le, chunk, chunk, dist_m // n_laps_this,
                int((dist_m // n_laps_this) * 0.055), avg_hr, max_hr,
                round(speed, 3), round(speed + 0.3, 3), gain // n_laps_this,
                loss // n_laps_this,
            ))

        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO activities (source, activity_type, sub_sport, start_ts, end_ts, "
                "duration_s, timer_time_s, distance_m, calories, avg_hr, max_hr, avg_cadence, "
                "max_cadence, avg_speed_mps, max_speed_mps, elevation_gain_m, elevation_loss_m, "
                "avg_temperature_c, training_effect_aerobic, training_effect_anaerobic, "
                "total_strides, avg_vertical_oscillation_mm, avg_ground_contact_time_ms, "
                "avg_stride_length_cm, fit_file_path, fit_file_hash, raw_json) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (source, start_ts) DO UPDATE SET "
                "  duration_s=EXCLUDED.duration_s, distance_m=EXCLUDED.distance_m "
                "RETURNING id",
                ("garmin", sport, None, start, end, dur_s, dur_s, dist_m,
                 int(dist_m * 0.055), avg_hr, max_hr, avg_cad, max_cad,
                 round(speed, 3), round(speed + 0.3, 3), gain, loss, 24.0,
                 round(rng.uniform(1.5, 3.0), 1), round(rng.uniform(0.5, 1.5), 1),
                 strides, round(rng.uniform(6, 10), 1), rng.randint(220, 260),
                 round(dist_m / max(strides, 1) * 100, 1), fit_path, fit_hash, None),
            )
            aid = cur.fetchone()["id"]
            cur.executemany(
                "INSERT INTO activity_trackpoints (activity_id, ts, lat_semicircles, lon_semicircles, "
                "altitude_m, hr, cadence, speed_mps, distance_m, temperature_c) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                [(aid,) + row for row in tp_rows],
            )
            cur.executemany(
                "INSERT INTO activity_hr (activity_id, ts, hr) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
                [(aid,) + row for row in hr_rows],
            )
            cur.executemany(
                "INSERT INTO activity_laps (activity_id, lap_index, start_ts, end_ts, duration_s, "
                "timer_time_s, distance_m, calories, avg_hr, max_hr, avg_speed_mps, max_speed_mps, "
                "elevation_gain_m, elevation_loss_m) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT DO NOTHING",
                [(aid,) + row for row in lap_rows],
            )
            cur.execute(
                "INSERT INTO garmin_fit_ingest (file_path, file_hash, file_size_bytes, file_mtime, "
                "activity_id, record_count, error) VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                (fit_path, fit_hash, 0, start, aid, n_pts, None),
            )
        conn.commit()
        n_activities += 1
        n_tp += len(tp_rows)
        n_ahr += len(hr_rows)
        n_laps += len(lap_rows)

    counts["activities"] = n_activities
    counts["trackpoints"] = n_tp
    counts["activity_hr"] = n_ahr
    counts["laps"] = n_laps


def main() -> int:
    ap = argparse.ArgumentParser(description="Seed demo data for screenshot capture.")
    ap.add_argument("--days", type=int, default=DEFAULT_DAYS)
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()

    conn = _connect()
    try:
        counts = seed(conn, days=args.days, rng_seed=args.seed)
    finally:
        conn.close()

    print(f"Seeded demo data ({args.days} days, seed={args.seed}):")
    for k, v in counts.items():
        print(f"  {k:>16}: {v}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
