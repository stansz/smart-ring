import os
from contextlib import asynccontextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import List

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from pydantic_settings import BaseSettings
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker

from upsert import upsert_many

DASHBOARD_DIR = os.path.join(os.path.dirname(__file__), "..", "dashboard", "dist")


class Settings(BaseSettings):
    database_url: str = os.getenv("DATABASE_URL", "postgresql://smart_ring:changeme@localhost:5432/smart_ring")
    api_host: str = "0.0.0.0"
    api_port: int = 8000


settings = Settings()
engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield


app = FastAPI(title="Smart Ring API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=DASHBOARD_DIR), name="static")

@app.get("/")
def root():
    return FileResponse(
        os.path.join(DASHBOARD_DIR, "index.html"),
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


@app.get("/health")
def health():
    with SessionLocal() as db:
        db.execute(text("SELECT 1"))
    return {"status": "ok", "db": "connected"}


@app.get("/api/recovery")
def get_recovery(days: int = 30):
    """Daily HRV recovery from persisted analytics (z-score + readiness)."""
    cutoff_date = date.today() - timedelta(days=days)
    with SessionLocal() as db:
        rows = db.execute(text("""
            SELECT day, rmssd, baseline_rmssd, z_score, readiness_text
            FROM daily_recovery
            WHERE day >= :cutoff_date
            ORDER BY day ASC
        """), {"cutoff_date": cutoff_date}).mappings().all()
    return [dict(r) for r in rows]


@app.get("/api/daily-activity")
def get_daily_activity(days: int = 14):
    """Per-day activity aggregates (server-computed in local tz).
    Powers the activity dials + 24h day ring + steps timeline, replacing
    flaky client-side day filtering of raw records."""
    cutoff_date = date.today() - timedelta(days=days)
    with SessionLocal() as db:
        rows = db.execute(text("""
            SELECT day, steps_total, distance_m, calories_raw,
                   hr_avg, hr_min, hr_max, hr_samples, worn_minutes,
                   first_hr_ts, last_hr_ts, hourly_steps, hourly_worn
            FROM daily_activity
            WHERE day >= :cutoff_date
            ORDER BY day ASC
        """), {"cutoff_date": cutoff_date}).mappings().all()
    return [dict(r) for r in rows]


@app.get("/api/heart-rate-zones")
def get_heart_rate_zones(days: int = 14):
    """Per-day heart rate zones and Edwards TRIMP strain scores."""
    cutoff_date = date.today() - timedelta(days=days)
    with SessionLocal() as db:
        rows = db.execute(text("""
            SELECT day, rhr_used, max_hr_used,
                   zone1_min, zone2_min, zone3_min, zone4_min, zone5_min,
                   below_zone_min, elevated_min, peak_zone,
                   trimp, strain_score, hr_samples, computed_at
            FROM heart_rate_zones
            WHERE day >= :cutoff_date
            ORDER BY day ASC
        """), {"cutoff_date": cutoff_date}).mappings().all()
    return [dict(r) for r in rows]


@app.get("/api/strain-trend")
def get_strain_trend(days: int = 14):
    """Per-day strain trend, ACWR, and load labels."""
    cutoff_date = date.today() - timedelta(days=days)
    with SessionLocal() as db:
        rows = db.execute(text("""
            SELECT day, strain_today, load_label,
                   strain_7d_sum, strain_7d_avg, strain_28d_avg,
                   acwr, trend_direction, days_with_data, computed_at
            FROM strain_trend
            WHERE day >= :cutoff_date
            ORDER BY day ASC
        """), {"cutoff_date": cutoff_date}).mappings().all()
    return [dict(r) for r in rows]


@app.get("/api/readiness")
def get_readiness(days: int = 7):
    """Unified readiness score (0-100 WHOOP-style) with sub-scores + context.

    `frozen_at` is non-NULL once the morning lock has been applied (first
    analytics pass at/after 6 AM local). Today's row may be NULL (preliminary,
    still updating) or non-NULL (locked for the day).
    """
    cutoff_date = date.today() - timedelta(days=days)
    with SessionLocal() as db:
        rows = db.execute(text("""
            SELECT day, score, hrv_score, sleep_score, rhr_score,
                   hrv_zscore, resting_hr, hrv_rmssd,
                   sleep_total_min, rhr_baseline, contributors,
                   confidence, missing_components, frozen_at
            FROM readiness_score
            WHERE day >= :cutoff_date
            ORDER BY day DESC
        """), {"cutoff_date": cutoff_date}).mappings().all()
    return [dict(r) for r in rows]


@app.get("/api/current-status")
def get_current_status(hours: int = 168):
    """Current Status snapshots (live intra-day score), latest first.

    One row per analytics pass. Default window is 168h (7 days) so the
    dashboard can filter to any selected day client-side (matches the
    raw_* endpoints). The latest row of a given day is that day's most
    recent snapshot; earlier rows that day drive the intra-day sparkline.

    Components (each 0-100, may be NULL if input data missing):
      hrv_component    — recent HRV z-score vs 7-day baseline
      hr_component     — recent HR delta from RHR baseline
      stress_component — recent raw stress (inverted)
      trend_component  — HRV slope over last 3h

    Raw values exposed for the vitals panel UI:
      hrv_zscore       — z-score of recent HRV vs ln-normal 7-day baseline
      hr_delta         — recent HR − RHR baseline (bpm)
      stress_recent    — raw 0-99 stress reading (last 3h avg)
      hrv_trend        — HRV slope (per hour) over last 3h

    `confidence` is 'partial' if any component is missing, 'full' otherwise.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    with SessionLocal() as db:
        rows = db.execute(text("""
            SELECT ts, score, hrv_component, hr_component, stress_component,
                   trend_component, hrv_zscore, hr_delta, stress_recent,
                   hrv_trend, samples, confidence, computed_at
            FROM current_status
            WHERE ts >= :cutoff
            ORDER BY ts DESC
        """), {"cutoff": cutoff}).mappings().all()
    return [dict(r) for r in rows]


@app.get("/api/sleep")
def get_sleep(days: int = 30):
    """Sleep quality scores from persisted analytics."""
    cutoff_date = date.today() - timedelta(days=days)
    with SessionLocal() as db:
        rows = db.execute(text("""
            SELECT day, score, deep_pct, rem_pct, light_pct, wake_pct,
                   temp_drop_c, total_sleep_minutes,
                   deep_min, rem_min, light_min, awake_min,
                   sleep_start_ts, sleep_end_ts
            FROM sleep_quality
            WHERE day >= :cutoff_date
            ORDER BY day DESC
        """), {"cutoff_date": cutoff_date}).mappings().all()
    return [dict(r) for r in rows]


@app.get("/api/hrv-trends")
def get_hrv_trends(days: int = 60):
    cutoff_date = date.today() - timedelta(days=days)
    with SessionLocal() as db:
        rows = db.execute(text("""
            SELECT day, rmssd_7d, rmssd_28d, pnn50_7d
            FROM hrv_trends
            WHERE day >= :cutoff_date
            ORDER BY day DESC
        """), {"cutoff_date": cutoff_date}).mappings().all()
    return [dict(r) for r in rows]


@app.get("/api/circadian-hr")
def get_circadian_hr():
    with SessionLocal() as db:
        rows = db.execute(text("""
            SELECT day, hour, avg_hr, min_hr, max_hr, sample_count
            FROM circadian_hr
            ORDER BY day, hour
        """)).mappings().all()
    dates = db.execute(text("""
        SELECT MIN(day)::text as min_day, MAX(day)::text as max_day
        FROM circadian_hr
    """)).mappings().first()
    result = [dict(r) for r in rows]
    result.append({"_range": dict(dates) if dates else {}})
    return result


@app.get("/api/stress")
def get_stress(days: int = 30):
    cutoff_date = date.today() - timedelta(days=days)
    with SessionLocal() as db:
        rows = db.execute(text("""
            SELECT day, morning_rmssd, noon_rmssd, evening_rmssd, classification
            FROM stress_classification
            WHERE day >= :cutoff_date
            ORDER BY day DESC
        """), {"cutoff_date": cutoff_date}).mappings().all()
    return [dict(r) for r in rows]


@app.get("/api/data-quality")
def get_data_quality(days: int = 7, source: str | None = None):
    """Per-type data freshness status (ok | stale) with optional reason.

    Optional ``source`` filter — when set, only rows for that source
    are returned. The dashboard sensor strip uses ``?source=ring``.
    """
    cutoff_date = date.today() - timedelta(days=days)
    with SessionLocal() as db:
        if source:
            rows = db.execute(text("""
                SELECT day, data_type, source, last_ts, sample_count,
                       status, reason, checked_at
                FROM data_quality
                WHERE day >= :cutoff_date AND source = :source
                ORDER BY day DESC, data_type
            """), {"cutoff_date": cutoff_date, "source": source}).mappings().all()
        else:
            rows = db.execute(text("""
                SELECT day, data_type, source, last_ts, sample_count,
                       status, reason, checked_at
                FROM data_quality
                WHERE day >= :cutoff_date
                ORDER BY day DESC, data_type
            """), {"cutoff_date": cutoff_date}).mappings().all()
    return [dict(r) for r in rows]


@app.get("/api/resting-hr")
def get_resting_hr(days: int = 30):
    """Daily resting HR: average bpm between 1:00–5:00 AM local time."""
    # Timezone from env var or system /etc/timezone, fallback to America/Vancouver.
    tz = os.getenv("TZ", "")
    if not tz:
        try:
            with open("/etc/timezone") as f:
                tz = f.read().strip()
        except Exception:
            tz = "America/Vancouver"
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    with SessionLocal() as db:
        rows = db.execute(text("""
            SELECT
                (ts AT TIME ZONE :tz)::date AS day,
                ROUND(AVG(bpm))::int AS resting_hr,
                COUNT(*) AS samples
            FROM raw_heart_rate
            WHERE
                EXTRACT(HOUR FROM ts AT TIME ZONE :tz) BETWEEN 1 AND 5
                AND ts >= :cutoff
            GROUP BY 1
            ORDER BY 1 DESC
        """), {"tz": tz, "cutoff": cutoff}).mappings().all()
    return [dict(r) for r in rows]


@app.get("/api/raw/heart-rate")
def get_raw_hr(hours: int = 48, limit: int = 1000, start: str | None = None, end: str | None = None):
    if start and end:
        # Parse dates in local timezone (America/Vancouver) and convert to UTC
        from zoneinfo import ZoneInfo
        local_tz = ZoneInfo("America/Vancouver")
        start_local = datetime.strptime(start, "%Y-%m-%d").replace(tzinfo=local_tz)
        end_local = datetime.strptime(end, "%Y-%m-%d").replace(hour=23, minute=59, second=59, tzinfo=local_tz)
        start_utc = start_local.astimezone(timezone.utc)
        end_utc = end_local.astimezone(timezone.utc)
        where_clause = "ts BETWEEN :start AND :end"
        params = {"start": start_utc, "end": end_utc, "limit": limit}
    else:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        where_clause = "ts >= :cutoff"
        params = {"cutoff": cutoff, "limit": limit}
    with SessionLocal() as db:
        rows = db.execute(text(f"""
            SELECT ts, bpm FROM raw_heart_rate
            WHERE {where_clause}
            ORDER BY ts DESC LIMIT :limit
        """), params).mappings().all()
    return [dict(r) for r in rows]


@app.get("/api/raw/steps")
def get_raw_steps(hours: int = 168, limit: int = 1000, start: str | None = None, end: str | None = None):
    if start and end:
        # Parse dates in local timezone (America/Vancouver) and convert to UTC
        from zoneinfo import ZoneInfo
        local_tz = ZoneInfo("America/Vancouver")
        start_local = datetime.strptime(start, "%Y-%m-%d").replace(tzinfo=local_tz)
        end_local = datetime.strptime(end, "%Y-%m-%d").replace(hour=23, minute=59, second=59, tzinfo=local_tz)
        start_utc = start_local.astimezone(timezone.utc)
        end_utc = end_local.astimezone(timezone.utc)
        where_clause = "ts BETWEEN :start AND :end"
        params = {"start": start_utc, "end": end_utc, "limit": limit}
    else:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        where_clause = "ts >= :cutoff"
        params = {"cutoff": cutoff, "limit": limit}
    with SessionLocal() as db:
        rows = db.execute(text(f"""
            SELECT ts, steps, calories, distance FROM raw_steps
            WHERE {where_clause}
            ORDER BY ts DESC LIMIT :limit
        """), params).mappings().all()
    return [dict(r) for r in rows]


@app.get("/api/raw/stress")
def get_raw_stress(hours: int = 168, limit: int = 500, start: str | None = None, end: str | None = None):
    if start and end:
        # Parse dates in local timezone (America/Vancouver) and convert to UTC
        from zoneinfo import ZoneInfo
        local_tz = ZoneInfo("America/Vancouver")
        start_local = datetime.strptime(start, "%Y-%m-%d").replace(tzinfo=local_tz)
        end_local = datetime.strptime(end, "%Y-%m-%d").replace(hour=23, minute=59, second=59, tzinfo=local_tz)
        start_utc = start_local.astimezone(timezone.utc)
        end_utc = end_local.astimezone(timezone.utc)
        where_clause = "ts BETWEEN :start AND :end"
        params = {"start": start_utc, "end": end_utc, "limit": limit}
    else:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        where_clause = "ts >= :cutoff"
        params = {"cutoff": cutoff, "limit": limit}
    with SessionLocal() as db:
        rows = db.execute(text(f"""
            SELECT ts, stress_value FROM raw_stress
            WHERE {where_clause}
            ORDER BY ts DESC LIMIT :limit
        """), params).mappings().all()
    return [dict(r) for r in rows]


@app.get("/api/goals")
def get_goals():
    with SessionLocal() as db:
        row = db.execute(text("""
            SELECT steps_goal, calories_goal, distance_m_goal,
                   sport_min_goal, sleep_min_goal
            FROM ring_goals ORDER BY ts DESC LIMIT 1
        """)).mappings().first()
    return dict(row) if row else {}


# ─── User-set goals (NOT the firmware-stored ring_goals) ─────────────────────
# These are the user's own targets, edited from the dashboard. Stored as
# key/value so we can add new goal types without schema changes. Defaults
# applied on read if a key is missing — no need to seed the table.
DEFAULT_USER_GOALS = {
    "steps_goal": 5000,
    "sleep_min_goal": 480,  # 8 hours
}


@app.get("/api/user-goals")
def get_user_goals():
    with SessionLocal() as db:
        rows = db.execute(text("SELECT key, value FROM user_goals")).mappings().all()
    stored = {r["key"]: r["value"] for r in rows}
    # Merge defaults under stored values so the frontend always sees full shape
    return {**DEFAULT_USER_GOALS, **stored}


@app.post("/api/user-goals")
def update_user_goal(body: dict):
    """Partial update — accepts one or more {key: value} pairs."""
    allowed = set(DEFAULT_USER_GOALS.keys())
    updates = {k: int(v) for k, v in body.items() if k in allowed and isinstance(v, (int, float, str)) and str(v).strip().lstrip("-").isdigit()}
    if not updates:
        return {"updated": 0, "error": "no valid keys supplied"}
    with SessionLocal() as db:
        for key, value in updates.items():
            db.execute(text("""
                INSERT INTO user_goals (key, value, updated_at)
                VALUES (:key, :value, NOW())
                ON CONFLICT (key) DO UPDATE SET
                    value = EXCLUDED.value,
                    updated_at = EXCLUDED.updated_at
            """), {"key": key, "value": value})
        db.commit()
    return {"updated": len(updates), "values": updates}


@app.get("/api/raw/sleep")
def get_raw_sleep(hours: int = 168, limit: int = 200):
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    with SessionLocal() as db:
        rows = db.execute(text("""
            SELECT day, stage, start_ts, end_ts, duration_minutes FROM raw_sleep s
            WHERE start_ts >= :cutoff
              AND source = CASE WHEN EXISTS (
                    SELECT 1 FROM raw_sleep r WHERE r.day = s.day AND r.source = 'ring'
                  ) THEN 'ring' ELSE 'phone' END
            ORDER BY start_ts DESC LIMIT :limit
        """), {"cutoff": cutoff, "limit": limit}).mappings().all()
    return [dict(r) for r in rows]


@app.get("/api/raw/spo2")
def get_raw_spo2(hours: int = 168, limit: int = 200, start: str | None = None, end: str | None = None):
    if start and end:
        # Parse dates in local timezone (America/Vancouver) and convert to UTC
        from zoneinfo import ZoneInfo
        local_tz = ZoneInfo("America/Vancouver")
        start_local = datetime.strptime(start, "%Y-%m-%d").replace(tzinfo=local_tz)
        end_local = datetime.strptime(end, "%Y-%m-%d").replace(hour=23, minute=59, second=59, tzinfo=local_tz)
        start_utc = start_local.astimezone(timezone.utc)
        end_utc = end_local.astimezone(timezone.utc)
        where_clause = "ts BETWEEN :start AND :end"
        params = {"start": start_utc, "end": end_utc, "limit": limit}
    else:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        where_clause = "ts >= :cutoff"
        params = {"cutoff": cutoff, "limit": limit}
    with SessionLocal() as db:
        rows = db.execute(text(f"""
            SELECT ts, spo2_pct FROM raw_spo2
            WHERE {where_clause}
            ORDER BY ts DESC LIMIT :limit
        """), params).mappings().all()
    return [dict(r) for r in rows]


@app.get("/api/raw/hrv")
def get_raw_hrv(hours: int = 168, limit: int = 500, start: str | None = None, end: str | None = None):
    if start and end:
        # Parse dates in local timezone (America/Vancouver) and convert to UTC
        from zoneinfo import ZoneInfo
        local_tz = ZoneInfo("America/Vancouver")
        start_local = datetime.strptime(start, "%Y-%m-%d").replace(tzinfo=local_tz)
        end_local = datetime.strptime(end, "%Y-%m-%d").replace(hour=23, minute=59, second=59, tzinfo=local_tz)
        start_utc = start_local.astimezone(timezone.utc)
        end_utc = end_local.astimezone(timezone.utc)
        where_clause = "ts BETWEEN :start AND :end"
        params = {"start": start_utc, "end": end_utc, "limit": limit}
    else:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        where_clause = "ts >= :cutoff"
        params = {"cutoff": cutoff, "limit": limit}
    with SessionLocal() as db:
        rows = db.execute(text(f"""
            SELECT ts, hrv_value FROM raw_hrv
            WHERE {where_clause}
            ORDER BY ts DESC LIMIT :limit
        """), params).mappings().all()
    return [dict(r) for r in rows]


@app.get("/api/raw/temperature")
def get_raw_temp(hours: int = 48, limit: int = 1000, start: str | None = None, end: str | None = None):
    if start and end:
        # Parse dates in local timezone (America/Vancouver) and convert to UTC
        from zoneinfo import ZoneInfo
        local_tz = ZoneInfo("America/Vancouver")
        start_local = datetime.strptime(start, "%Y-%m-%d").replace(tzinfo=local_tz)
        end_local = datetime.strptime(end, "%Y-%m-%d").replace(hour=23, minute=59, second=59, tzinfo=local_tz)
        start_utc = start_local.astimezone(timezone.utc)
        end_utc = end_local.astimezone(timezone.utc)
        where_clause = "ts BETWEEN :start AND :end"
        params = {"start": start_utc, "end": end_utc, "limit": limit}
    else:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        where_clause = "ts >= :cutoff"
        params = {"cutoff": cutoff, "limit": limit}
    with SessionLocal() as db:
        rows = db.execute(text(f"""
            SELECT ts, temp_c FROM raw_temperature
            WHERE {where_clause}
            ORDER BY ts DESC LIMIT :limit
        """), params).mappings().all()
    return [dict(r) for r in rows]


# Web Bluetooth mobile sync endpoint
class MobileSyncRequest(BaseModel):
    device_id: str
    records: dict  # {heart_rate: [...], spo2: [...], hrv: [...], sleep: [...], temperature: [...], steps: [...], stress: [...], goals: {...}}
    synced_at: datetime
    battery_pct: int | None = None


@app.post("/api/mobile/sync")
def mobile_sync(req: MobileSyncRequest):
    """Receive ring data from phone via Web Bluetooth and store it."""
    with SessionLocal() as db:
        accepted = 0
        skipped = 0
        errors: list[str] = []

        # Simple point tables — generic dispatch.
        # Adding a new simple type = one row here, not a copy-pasted block.
        # Tables with non-standard shape (hrv, sleep, goals) stay inline below.
        simple_point_tables = [
            # (payload_key, table,          required_cols,     optional_cols)
            ("heart_rate",  "raw_heart_rate",  ["bpm"],          []),
            ("spo2",        "raw_spo2",        ["spo2_pct"],     []),
            ("temperature", "raw_temperature", ["temp_c"],        []),
            ("stress",      "raw_stress",      ["stress_value"],  []),
            ("steps",       "raw_steps",       ["steps"],         ["calories", "distance"]),
        ]
        for payload_key, table, req_cols, opt_cols in simple_point_tables:
            a, s, e = upsert_many(
                db,
                table=table,
                required_cols=req_cols,
                optional_cols=opt_cols,
                records=req.records.get(payload_key, []),
            )
            accepted += a
            skipped += s
            errors.extend(e)

        # HRV — special: hrv_type defaults to 'composite', conflict clause
        # includes hrv_type so two readings at the same ts with different
        # types both survive.
        for r in req.records.get("hrv", []):
            try:
                db.execute(text("""
                    INSERT INTO raw_hrv (ts, hrv_value, hrv_type, source)
                    VALUES (:ts, :hrv_value, :hrv_type, 'phone')
                    ON CONFLICT (ts, hrv_type, source) DO NOTHING
                """), {"ts": r["ts"], "hrv_value": r["hrv_value"], "hrv_type": r.get("hrv_type", "composite")})
                accepted += 1
            except Exception as e:
                errors.append(f"hrv: {e}")
                skipped += 1

        # Sleep — special: day-based schema, conflict on (start_ts, stage, source)
        for r in req.records.get("sleep", []):
            try:
                db.execute(text("""
                    INSERT INTO raw_sleep (day, stage, start_ts, end_ts, duration_minutes, source)
                    VALUES (:day, :stage, :start_ts, :end_ts, :duration_minutes, 'phone')
                    ON CONFLICT (start_ts, stage, source) DO NOTHING
                """), {"day": r["day"], "stage": r["stage"], "start_ts": r["start_ts"],
                       "end_ts": r["end_ts"], "duration_minutes": r["duration_minutes"]})
                accepted += 1
            except Exception as e:
                errors.append(f"sleep: {e}")
                skipped += 1

        # Goals — singleton (not a list), no source column
        goals = req.records.get("goals")
        if goals:
            try:
                db.execute(text("""
                    INSERT INTO ring_goals (steps_goal, calories_goal, distance_m_goal, sport_min_goal, sleep_min_goal)
                    VALUES (:steps, :calories, :distance, :sport, :sleep)
                """), {
                    "steps": goals.get("steps_goal"),
                    "calories": goals.get("calories_goal"),
                    "distance": goals.get("distance_m_goal"),
                    "sport": goals.get("sport_min_goal"),
                    "sleep": goals.get("sleep_min_goal"),
                })
                accepted += 1
            except Exception as e:
                errors.append(f"goals: {e}")
                skipped += 1

        # Record the phone sync in sync_log so it appears in the dashboard
        try:
            db.execute(text("""
                INSERT INTO sync_log (started_at, completed_at, records_synced, battery_pct, status, current_step)
                VALUES (:started, NOW(), :n, :bat, 'ok', 'phone sync')
            """), {"started": req.synced_at, "n": accepted, "bat": req.battery_pct})
        except Exception as e:
            errors.append(f"sync_log: {e}")

        # Store battery reading in ring_status (keeps nav bar indicator fresh)
        if req.battery_pct is not None:
            try:
                db.execute(text("""
                    INSERT INTO ring_status (ts, battery_pct)
                    VALUES (NOW(), :bat)
                """), {"bat": req.battery_pct})
            except Exception as e:
                errors.append(f"ring_status: {e}")

        db.commit()

        # Ask the host poller to recompute analytics. The container can't run
        # collector/analytics.py (host venv + BLE collector deps), so we queue a
        # request the host picks up. IntegrityError = a sync is already
        # pending/running, which runs analytics too — harmless to skip.
        try:
            db.execute(text("""
                INSERT INTO sync_requests (requested_by, status)
                VALUES ('phone-analytics', 'pending')
            """))
            db.commit()
        except IntegrityError:
            db.rollback()

        return {
            "accepted": accepted,
            "skipped": skipped,
            "errors": errors[:10],
        }


@app.get("/api/sync-log")
def get_sync_log(limit: int = 50):
    with SessionLocal() as db:
        rows = db.execute(text("""
            SELECT started_at, completed_at, records_synced, battery_pct,
                   clock_drift_ms, status, error
            FROM sync_log
            ORDER BY started_at DESC LIMIT :limit
        """), {"limit": limit}).mappings().all()
    return [dict(r) for r in rows]


# ---------------------------- Admin endpoints ----------------------------
# These power the Admin tab in the dashboard. They do NOT directly run the
# collector (the API lives in a container without BLE access). Instead, sync
# requests are queued in the `sync_requests` table; a host-side poller
# (collector/sync_request_poller.py) picks them up and runs the collector.

@app.get("/api/admin/ring-status")
def get_ring_status():
    """Latest ring battery / firmware / connection info."""
    with SessionLocal() as db:
        row = db.execute(text("""
            SELECT ts, battery_pct, clock_drift_ms, firmware_version
            FROM ring_status
            ORDER BY ts DESC LIMIT 1
        """)).mappings().first()
        # Latest sync info too
        sync = db.execute(text("""
            SELECT completed_at, records_synced, status
            FROM sync_log
            WHERE completed_at IS NOT NULL
            ORDER BY completed_at DESC LIMIT 1
        """)).mappings().first()
    return {
        "ring": dict(row) if row else None,
        "last_sync": dict(sync) if sync else None,
    }


@app.get("/api/admin/health")
def admin_health():
    """Deeper health check: DB, recent sync, pending requests, container info."""
    health = {"db": "unknown", "ring_status_rows": 0,
              "sync_log_rows": 0, "pending_requests": 0,
              "container_host": os.uname().nodename if hasattr(os, "uname") else "unknown"}
    try:
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
            health["db"] = "connected"
            health["ring_status_rows"] = db.execute(
                text("SELECT COUNT(*) FROM ring_status")).scalar() or 0
            health["sync_log_rows"] = db.execute(
                text("SELECT COUNT(*) FROM sync_log")).scalar() or 0
            health["pending_requests"] = db.execute(
                text("SELECT COUNT(*) FROM sync_requests WHERE status = 'pending'")).scalar() or 0
    except Exception as e:
        health["db"] = f"error: {e}"
    return health


@app.get("/api/admin/sync-log")
def admin_sync_log(limit: int = 50):
    """Detailed sync log for the admin view (more rows than the dashboard widget)."""
    with SessionLocal() as db:
        rows = db.execute(text("""
            SELECT id, started_at, completed_at, records_synced, battery_pct,
                   clock_drift_ms, status, error
            FROM sync_log
            ORDER BY started_at DESC LIMIT :limit
        """), {"limit": limit}).mappings().all()
    return [dict(r) for r in rows]


@app.get("/api/admin/clock-alert")
def admin_clock_alert():
    """Clock health: future rows count (ring buffer phantom entries).

    The old drift metric was removed — it measured max(HR ts) - now(),
    which conflated sampling lag with clock error. Time sync is now
    verified via the ring's ack to the set_time command (stored as
    clock_drift_ms: 1=acked, 0=no ack, NULL=unknown). See sync log.
    """
    with SessionLocal() as db:
        future_hr = db.execute(text(
            "SELECT count(*) FROM raw_heart_rate WHERE ts > now()"
        )).scalar() or 0
        future_steps = db.execute(text(
            "SELECT count(*) FROM raw_steps WHERE ts > now()"
        )).scalar() or 0
        future_spo2 = db.execute(text(
            "SELECT count(*) FROM raw_spo2 WHERE ts > now()"
        )).scalar() or 0
        future_temp = db.execute(text(
            "SELECT count(*) FROM raw_temperature WHERE ts > now()"
        )).scalar() or 0
    return {
        "future_rows": future_hr + future_steps + future_spo2 + future_temp,
        "future_hr": future_hr,
    }


class SyncRequest(BaseModel):
    requested_by: str = "admin-ui"


@app.post("/api/admin/sync")
def queue_sync(req: SyncRequest):
    """Queue a sync. The host-side poller will pick this up within ~60s."""
    with SessionLocal() as db:
        try:
            row = db.execute(text("""
                INSERT INTO sync_requests (requested_by, status)
                VALUES (:by, 'pending')
                RETURNING id, requested_at, status
            """), {"by": req.requested_by}).mappings().first()
            db.commit()
        except IntegrityError:
            db.rollback()
            raise HTTPException(
                status_code=409,
                detail="A sync is already pending or running. Check recent requests for details.",
            )
    return dict(row)


@app.post("/api/admin/cancel-sync")
def cancel_sync():
    """Cancel any pending/running sync request — resets dashboard sync state."""
    with SessionLocal() as db:
        reqs = db.execute(text("""
            UPDATE sync_requests
            SET status = 'cancelled', completed_at = NOW(), error = 'cancelled by user'
            WHERE status IN ('pending', 'running')
            RETURNING id
        """)).fetchall()
        logs = db.execute(text("""
            UPDATE sync_log
            SET status = 'error', completed_at = NOW(), error = 'cancelled by user'
            WHERE status = 'running'
            RETURNING id
        """)).fetchall()
        db.commit()
    return {"cancelled": len(reqs), "sync_log_cleared": len(logs)}


@app.get("/api/admin/sync-requests")
def list_sync_requests(limit: int = 20):
    """Recent sync requests (pending/running/completed/failed)."""
    with SessionLocal() as db:
        rows = db.execute(text("""
            SELECT id, requested_at, requested_by, status, started_at,
                   completed_at, sync_log_id, result, error
            FROM sync_requests
            ORDER BY requested_at DESC LIMIT :limit
        """), {"limit": limit}).mappings().all()
    return [dict(r) for r in rows]


@app.get("/api/admin/sync-progress")
def get_sync_progress():
    """Latest sync's current_step and started_at for real-time progress display."""
    with SessionLocal() as db:
        row = db.execute(text("""
            SELECT current_step, started_at
            FROM sync_log
            ORDER BY started_at DESC LIMIT 1
        """)).mappings().first()
    if not row:
        return {"current_step": None, "started_at": None}
    return dict(row)


# ---------------------------- Garmin activity endpoints --------------------
# Read-only views over the Garmin-only `activities` table (Phase 1 ingest).
# These power the dashboard's Garmin tab. No write paths here — activity
# ingest happens via the `python -m collector.garmin.ingest` CLI on the host.

# FIT semicircles → degrees. 1 semicircle = 180/2^31 degrees.
_SEMICIRCLES_TO_DEG = 180.0 / (2 ** 31)


def _semicircles_to_deg(raw: int | None) -> float | None:
    if raw is None:
        return None
    return round(raw * _SEMICIRCLES_TO_DEG, 7)


@app.get("/api/activities")
def get_activities(days: int = 30, sport: str | None = None, limit: int = 30):
    """List of recent Garmin activities, newest first.

    Optional ``sport`` filter matches ``activity_type`` (e.g. 'walking',
    'running', 'cycling'). Limit defaults to 30 (≈ 1 month of daily walks).
    """
    cutoff_date = date.today() - timedelta(days=days)
    params = {"cutoff_date": cutoff_date, "limit": min(limit, 200)}
    where = "WHERE start_ts >= :cutoff_date"
    if sport:
        where += " AND activity_type = :sport"
        params["sport"] = sport
    with SessionLocal() as db:
        rows = db.execute(text(f"""
            SELECT a.id, a.activity_type, a.sub_sport,
                   a.start_ts, a.end_ts, a.duration_s, a.timer_time_s,
                   a.distance_m, a.calories, a.avg_hr, a.max_hr,
                   a.avg_cadence, a.max_cadence,
                   a.avg_speed_mps, a.max_speed_mps,
                   a.elevation_gain_m, a.elevation_loss_m,
                   a.avg_temperature_c,
                   a.training_effect_aerobic, a.training_effect_anaerobic,
                   a.total_strides,
                   (SELECT count(*) FROM activity_laps l WHERE l.activity_id = a.id) AS lap_count
            FROM activities a
            {where}
            ORDER BY a.start_ts DESC
            LIMIT :limit
        """), params).mappings().all()
    return [dict(r) for r in rows]


@app.get("/api/activities/{activity_id}")
def get_activity_detail(activity_id: int):
    """Single activity session metadata."""
    with SessionLocal() as db:
        row = db.execute(text("""
            SELECT id, activity_type, sub_sport,
                   start_ts, end_ts, duration_s, timer_time_s,
                   distance_m, calories, avg_hr, max_hr,
                   avg_cadence, max_cadence,
                   avg_speed_mps, max_speed_mps,
                   elevation_gain_m, elevation_loss_m,
                   avg_temperature_c,
                   training_effect_aerobic, training_effect_anaerobic,
                   total_strides, avg_vertical_oscillation_mm,
                   avg_ground_contact_time_ms, avg_stride_length_cm,
                   fit_file_path
            FROM activities
            WHERE id = :id
        """), {"id": activity_id}).mappings().first()
    if not row:
        raise HTTPException(status_code=404, detail=f"activity {activity_id} not found")
    return dict(row)


@app.get("/api/activities/{activity_id}/trackpoints")
def get_activity_trackpoints(activity_id: int, max_points: int = 5000):
    """1-Hz GPS + HR + cadence + altitude trackpoints.

    Long activities (multi-hour walks = 10,000+ points) are downsampled
    by striding through the rows. The downsampling preserves the first
    + last point and the overall shape; HR chart and route map both
    work fine at 5000 points.
    """
    # First check the activity exists (gives a clean 404)
    with SessionLocal() as db:
        exists = db.execute(text(
            "SELECT 1 FROM activities WHERE id = :id"
        ), {"id": activity_id}).scalar()
    if not exists:
        raise HTTPException(status_code=404, detail=f"activity {activity_id} not found")

    with SessionLocal() as db:
        # Pull raw rows. For activities < max_points this is the whole set.
        rows = db.execute(text("""
            SELECT ts, lat_semicircles, lon_semicircles,
                   altitude_m, hr, cadence, speed_mps, distance_m, temperature_c
            FROM activity_trackpoints
            WHERE activity_id = :id
            ORDER BY ts
        """), {"id": activity_id}).mappings().all()

    if not rows:
        return []

    # Downsample if over the cap. Stride keeps the first + last + even steps.
    if len(rows) > max_points:
        stride = len(rows) // max_points
        sampled = [rows[0]] + rows[1:-1:stride] + [rows[-1]]
        # dedupe + sort by ts
        seen = set()
        deduped = []
        for r in sampled:
            if r["ts"] not in seen:
                seen.add(r["ts"])
                deduped.append(r)
        deduped.sort(key=lambda r: r["ts"])
        rows = deduped

    # Convert semicircles → degrees at the API boundary (storage stays FIT-native)
    return [
        {
            "ts": r["ts"],
            "lat": _semicircles_to_deg(r["lat_semicircles"]),
            "lon": _semicircles_to_deg(r["lon_semicircles"]),
            "altitude_m": r["altitude_m"],
            "hr": r["hr"],
            "cadence": r["cadence"],
            "speed_mps": r["speed_mps"],
            "distance_m": r["distance_m"],
            "temperature_c": r["temperature_c"],
        }
        for r in rows
    ]


@app.get("/api/activities/{activity_id}/hr")
def get_activity_hr(activity_id: int, max_points: int = 5000):
    """1-Hz HR samples for the per-activity HR chart.

    Separate from /trackpoints so the chart can pull just HR (lighter)
    without the GPS payload. Same downsampling rule.
    """
    with SessionLocal() as db:
        exists = db.execute(text(
            "SELECT 1 FROM activities WHERE id = :id"
        ), {"id": activity_id}).scalar()
    if not exists:
        raise HTTPException(status_code=404, detail=f"activity {activity_id} not found")

    with SessionLocal() as db:
        rows = db.execute(text("""
            SELECT ts, hr FROM activity_hr
            WHERE activity_id = :id ORDER BY ts
        """), {"id": activity_id}).mappings().all()

    if not rows:
        return []
    if len(rows) > max_points:
        stride = len(rows) // max_points
        sampled = [rows[0]] + rows[1:-1:stride] + [rows[-1]]
        seen = set()
        deduped = []
        for r in sampled:
            if r["ts"] not in seen:
                seen.add(r["ts"])
                deduped.append(r)
        deduped.sort(key=lambda r: r["ts"])
        rows = deduped

    return [dict(r) for r in rows]


@app.get("/api/activities/{activity_id}/laps")
def get_activity_laps(activity_id: int):
    """Lap splits for the activity."""
    with SessionLocal() as db:
        # Existence check via the laps themselves — no point in a 404 if
        # the activity exists but has 0 laps.
        rows = db.execute(text("""
            SELECT l.lap_index, l.start_ts, l.end_ts,
                   l.duration_s, l.timer_time_s,
                   l.distance_m, l.calories, l.avg_hr, l.max_hr,
                   l.avg_cadence, l.max_cadence,
                   l.avg_speed_mps, l.max_speed_mps,
                   l.elevation_gain_m, l.elevation_loss_m
            FROM activity_laps l
            WHERE l.activity_id = :id
            ORDER BY l.lap_index
        """), {"id": activity_id}).mappings().all()
    return [dict(r) for r in rows]


# ─── Garmin Upload ──────────────────────────────────────────────────────

# Raw FIT files from the 745 live under /garmin-raw (mounted from
# /opt/smart-ring/data/garmin/raw on the host).  Web uploads land in
# /garmin-raw/uploads/<timestamp>/; manual USB dumps go in
# /garmin-raw/manual/.  The ingest code scans both trees.
GARMIN_RAW_DIR = Path(os.environ.get("GARMIN_RAW_DIR", "/garmin-raw"))


@app.post("/api/admin/garmin-upload")
async def garmin_upload(
    files: List[UploadFile] = File(...),
    paths: str = Form(...),
):
    """Accept a Garmin folder (selected via webkitdirectory), write the
    files to persistent storage, and run FIT ingest on them.

    ``paths`` is a JSON array of relative paths (one per file), in the
    same order as ``files``.  The server reconstructs the folder tree
    under ``GARMIN_RAW_DIR/uploads/<timestamp>/`` so that
    ``discover_fit_files()`` can find Activity/ and Summary/ subdirs.
    """
    import json

    try:
        relative_paths: list[str] = json.loads(paths)
    except json.JSONDecodeError:
        raise HTTPException(400, "paths must be a JSON array of strings")

    if len(relative_paths) != len(files):
        raise HTTPException(
            400,
            f"paths/file count mismatch: {len(relative_paths)} vs {len(files)}",
        )
    if not files:
        return {"found": 0, "inserted": 0, "skipped": 0, "error": 0}

    # Create a timestamped upload directory
    ts = datetime.now(tz=timezone.utc).strftime("%Y%m%d-%H%M%S")
    upload_dir = GARMIN_RAW_DIR / "uploads" / ts
    upload_dir.mkdir(parents=True, exist_ok=True)

    # Write each file preserving its relative path structure
    for upload_file, rel_path_str in zip(files, relative_paths):
        rel_path = Path(rel_path_str)
        # Security: reject any path that escapes the upload directory
        target = (upload_dir / rel_path).resolve()
        if not str(target).startswith(str(upload_dir.resolve())):
            raise HTTPException(400, f"Invalid path: {rel_path_str}")
        target.parent.mkdir(parents=True, exist_ok=True)
        content = await upload_file.read()
        target.write_bytes(content)

    # Run ingest
    from collector.garmin.ingest import _connect, ingest_directory

    conn = _connect()
    try:
        summary = ingest_directory(upload_dir, conn)
    finally:
        conn.close()

    return {
        **summary,
        "upload_dir": str(upload_dir),
        "timestamp": ts,
        "total_files_received": len(files),
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=settings.api_host, port=settings.api_port)