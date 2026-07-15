import os
from contextlib import asynccontextmanager
from datetime import date, datetime

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from pydantic_settings import BaseSettings
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import sessionmaker, DeclarativeBase

DASHBOARD_DIR = os.path.join(os.path.dirname(__file__), "..", "dashboard")


class Settings(BaseSettings):
    database_url: str = os.getenv("DATABASE_URL", "postgresql://smart_ring:changeme@localhost:5432/smart_ring")
    api_host: str = "0.0.0.0"
    api_port: int = 8000


settings = Settings()
engine = create_engine(settings.database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
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
    with SessionLocal() as db:
        rows = db.execute(text("""
            SELECT day, rmssd, baseline_rmssd, z_score, readiness_text
            FROM daily_recovery
            WHERE day >= CURRENT_DATE - INTERVAL ':days days'
            ORDER BY day ASC
        """), {"days": days}).mappings().all()
    return [dict(r) for r in rows]


@app.get("/api/daily-activity")
def get_daily_activity(days: int = 14):
    """Per-day activity aggregates (server-computed in local tz).
    Powers the activity dials + 24h day ring + steps timeline, replacing
    flaky client-side day filtering of raw records."""
    with SessionLocal() as db:
        rows = db.execute(text("""
            SELECT day, steps_total, distance_m, calories_raw,
                   hr_avg, hr_min, hr_max, hr_samples, worn_minutes,
                   first_hr_ts, last_hr_ts, hourly_steps, hourly_worn
            FROM daily_activity
            WHERE day >= CURRENT_DATE - INTERVAL ':days days'
            ORDER BY day ASC
        """), {"days": days}).mappings().all()
    return [dict(r) for r in rows]


@app.get("/api/readiness")
def get_readiness(days: int = 7):
    """Unified readiness score (0-100 Oura-style) with sub-scores + context."""
    with SessionLocal() as db:
        rows = db.execute(text("""
            SELECT day, score, hrv_score, sleep_score, activity_score, rhr_score,
                   hrv_zscore, steps, resting_hr, hrv_rmssd,
                   sleep_total_min, rhr_baseline, contributors
            FROM readiness_score
            WHERE day >= CURRENT_DATE - INTERVAL ':days days'
            ORDER BY day DESC
        """), {"days": days}).mappings().all()
    return [dict(r) for r in rows]


@app.get("/api/sleep")
def get_sleep(days: int = 30):
    """Sleep quality scores from persisted analytics."""
    with SessionLocal() as db:
        rows = db.execute(text("""
            SELECT day, score, deep_pct, rem_pct, light_pct, wake_pct,
                   temp_drop_c, total_sleep_minutes,
                   deep_min, rem_min, light_min, awake_min,
                   sleep_start_ts, sleep_end_ts
            FROM sleep_quality
            WHERE day >= CURRENT_DATE - INTERVAL ':days days'
            ORDER BY day DESC
        """), {"days": days}).mappings().all()
    return [dict(r) for r in rows]


@app.get("/api/hrv-trends")
def get_hrv_trends(days: int = 60):
    with SessionLocal() as db:
        rows = db.execute(text("""
            SELECT day, rmssd_7d, rmssd_28d, pnn50_7d
            FROM hrv_trends
            WHERE day >= CURRENT_DATE - INTERVAL ':days days'
            ORDER BY day DESC
        """), {"days": days}).mappings().all()
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
    with SessionLocal() as db:
        rows = db.execute(text("""
            SELECT day, morning_rmssd, noon_rmssd, evening_rmssd, classification
            FROM stress_classification
            WHERE day >= CURRENT_DATE - INTERVAL ':days days'
            ORDER BY day DESC
        """), {"days": days}).mappings().all()
    return [dict(r) for r in rows]


@app.get("/api/resting-hr")
def get_resting_hr(days: int = 30):
    """Daily resting HR: average bpm between 1:00–5:00 AM local time."""
    # Timezone from env var or system /etc/timezone, fallback to America/Vancouver
    tz = os.getenv("TZ", "")
    if not tz:
        try:
            with open("/etc/timezone") as f:
                tz = f.read().strip()
        except Exception:
            tz = "America/Vancouver"
    with SessionLocal() as db:
        rows = db.execute(text(f"""
            SELECT
                (ts AT TIME ZONE '{tz}')::date AS day,
                ROUND(AVG(bpm))::int AS resting_hr,
                COUNT(*) AS samples
            FROM raw_heart_rate
            WHERE
                EXTRACT(HOUR FROM ts AT TIME ZONE '{tz}') BETWEEN 1 AND 5
                AND ts >= NOW() - INTERVAL ':days days'
            GROUP BY 1
            ORDER BY 1 DESC
        """), {"days": days}).mappings().all()
    return [dict(r) for r in rows]


@app.get("/api/raw/heart-rate")
def get_raw_hr(hours: int = 48, limit: int = 1000):
    with SessionLocal() as db:
        rows = db.execute(text("""
            SELECT ts, bpm FROM raw_heart_rate
            WHERE ts >= NOW() - INTERVAL ':hours hours'
            ORDER BY ts DESC LIMIT :limit
        """), {"hours": hours, "limit": limit}).mappings().all()
    return [dict(r) for r in rows]


@app.get("/api/raw/steps")
def get_raw_steps(hours: int = 168, limit: int = 1000):
    with SessionLocal() as db:
        rows = db.execute(text("""
            SELECT ts, steps, calories, distance FROM raw_steps
            WHERE ts >= NOW() - INTERVAL ':hours hours'
            ORDER BY ts DESC LIMIT :limit
        """), {"hours": hours, "limit": limit}).mappings().all()
    return [dict(r) for r in rows]


@app.get("/api/raw/stress")
def get_raw_stress(hours: int = 168, limit: int = 500):
    with SessionLocal() as db:
        rows = db.execute(text("""
            SELECT ts, stress_value FROM raw_stress
            WHERE ts >= NOW() - INTERVAL ':hours hours'
            ORDER BY ts DESC LIMIT :limit
        """), {"hours": hours, "limit": limit}).mappings().all()
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


@app.get("/api/raw/sleep")
def get_raw_sleep(hours: int = 168, limit: int = 200):
    with SessionLocal() as db:
        rows = db.execute(text("""
            SELECT day, stage, start_ts, end_ts, duration_minutes FROM raw_sleep s
            WHERE start_ts >= NOW() - INTERVAL ':hours hours'
              AND source = CASE WHEN EXISTS (
                    SELECT 1 FROM raw_sleep r WHERE r.day = s.day AND r.source = 'ring'
                  ) THEN 'ring' ELSE 'phone' END
            ORDER BY start_ts DESC LIMIT :limit
        """), {"hours": hours, "limit": limit}).mappings().all()
    return [dict(r) for r in rows]


@app.get("/api/raw/spo2")
def get_raw_spo2(hours: int = 168, limit: int = 200):
    with SessionLocal() as db:
        rows = db.execute(text("""
            SELECT ts, spo2_pct FROM raw_spo2
            WHERE ts >= NOW() - INTERVAL ':hours hours'
            ORDER BY ts DESC LIMIT :limit
        """), {"hours": hours, "limit": limit}).mappings().all()
    return [dict(r) for r in rows]


@app.get("/api/raw/hrv")
def get_raw_hrv(hours: int = 168, limit: int = 500):
    with SessionLocal() as db:
        rows = db.execute(text("""
            SELECT ts, hrv_value FROM raw_hrv
            WHERE ts >= NOW() - INTERVAL ':hours hours'
            ORDER BY ts DESC LIMIT :limit
        """), {"hours": hours, "limit": limit}).mappings().all()
    return [dict(r) for r in rows]


@app.get("/api/raw/temperature")
def get_raw_temp(hours: int = 48, limit: int = 1000):
    with SessionLocal() as db:
        rows = db.execute(text("""
            SELECT ts, temp_c FROM raw_temperature
            WHERE ts >= NOW() - INTERVAL ':hours hours'
            ORDER BY ts DESC LIMIT :limit
        """), {"hours": hours, "limit": limit}).mappings().all()
    return [dict(r) for r in rows]


# Web Bluetooth mobile sync endpoint
class MobileSyncRequest(BaseModel):
    device_id: str
    records: dict  # {heart_rate: [...], spo2: [...], hrv: [...], sleep: [...], temperature: [...], steps: [...], stress: [...], goals: {...}}
    synced_at: datetime
    battery_pct: int | None = None


def _dedupe_sources(db):
    """Delete phone records that duplicate ring records (ring is canonical).

    Phone sync fills gaps the ring missed; where both captured the same slot we
    keep the ring row and drop the redundant phone copy. Per-row `source` is
    preserved on every surviving row.
    """
    point = [
        ("raw_heart_rate", "r.ts = p.ts"),
        ("raw_spo2",       "r.ts = p.ts"),
        ("raw_temperature","r.ts = p.ts"),
        ("raw_stress",     "r.ts = p.ts"),
        ("raw_steps",      "r.ts = p.ts"),
        ("raw_hrv",        "r.ts = p.ts AND r.hrv_type = p.hrv_type"),
    ]
    for table, on_clause in point:
        db.execute(text(f"""
            DELETE FROM {table} p
            WHERE p.source = 'phone'
              AND EXISTS (SELECT 1 FROM {table} r WHERE r.source = 'ring' AND {on_clause})
        """))
    db.execute(text("""
        DELETE FROM raw_sleep p
        WHERE p.source = 'phone'
          AND EXISTS (SELECT 1 FROM raw_sleep r WHERE r.source = 'ring' AND r.day = p.day)
    """))


@app.post("/api/mobile/sync")
def mobile_sync(req: MobileSyncRequest):
    """Receive ring data from phone via Web Bluetooth and store it."""
    with SessionLocal() as db:
        accepted = 0
        skipped = 0
        errors = []

        # Heart rate
        for r in req.records.get("heart_rate", []):
            try:
                db.execute(text("""
                    INSERT INTO raw_heart_rate (ts, bpm, source)
                    VALUES (:ts, :bpm, 'phone')
                    ON CONFLICT (ts, source) DO NOTHING
                """), {"ts": r["ts"], "bpm": r["bpm"]})
                accepted += 1
            except Exception as e:
                errors.append(f"hr: {e}")
                skipped += 1

        # SpO2
        for r in req.records.get("spo2", []):
            try:
                db.execute(text("""
                    INSERT INTO raw_spo2 (ts, spo2_pct, source)
                    VALUES (:ts, :spo2_pct, 'phone')
                    ON CONFLICT (ts, source) DO NOTHING
                """), {"ts": r["ts"], "spo2_pct": r["spo2_pct"]})
                accepted += 1
            except Exception as e:
                errors.append(f"spo2: {e}")
                skipped += 1

        # HRV
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

        # Sleep
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

        # Temperature
        for r in req.records.get("temperature", []):
            try:
                db.execute(text("""
                    INSERT INTO raw_temperature (ts, temp_c, source)
                    VALUES (:ts, :temp_c, 'phone')
                    ON CONFLICT (ts, source) DO NOTHING
                """), {"ts": r["ts"], "temp_c": r["temp_c"]})
                accepted += 1
            except Exception as e:
                errors.append(f"temp: {e}")
                skipped += 1

        # Stress
        for r in req.records.get("stress", []):
            try:
                db.execute(text("""
                    INSERT INTO raw_stress (ts, stress_value, source)
                    VALUES (:ts, :stress_value, 'phone')
                    ON CONFLICT (ts, source) DO NOTHING
                """), {"ts": r["ts"], "stress_value": r["stress_value"]})
                accepted += 1
            except Exception as e:
                errors.append(f"stress: {e}")
                skipped += 1

        # Steps
        for r in req.records.get("steps", []):
            try:
                db.execute(text("""
                    INSERT INTO raw_steps (ts, steps, calories, distance, source)
                    VALUES (:ts, :steps, :calories, :distance, 'phone')
                    ON CONFLICT (ts, source) DO NOTHING
                """), {"ts": r["ts"], "steps": r["steps"], "calories": r.get("calories"), "distance": r.get("distance")})
                accepted += 1
            except Exception as e:
                errors.append(f"steps: {e}")
                skipped += 1

        # Goals
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

        # Drop phone records that duplicate ring (ring canonical; phone fills gaps)
        try:
            _dedupe_sources(db)
        except Exception as e:
            errors.append(f"dedupe: {e}")

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


@app.get("/api/raw/temperature")
def get_raw_temp(hours: int = 48, limit: int = 1000):
    with SessionLocal() as db:
        rows = db.execute(text("""
            SELECT ts, temp_c FROM raw_temperature
            WHERE ts >= NOW() - INTERVAL ':hours hours'
            ORDER BY ts DESC LIMIT :limit
        """), {"hours": hours, "limit": limit}).mappings().all()
    return [dict(r) for r in rows]


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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=settings.api_host, port=settings.api_port)