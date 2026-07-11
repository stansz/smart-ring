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
    return FileResponse(os.path.join(DASHBOARD_DIR, "index.html"))

@app.get("/health")
def health():
    with SessionLocal() as db:
        db.execute(text("SELECT 1"))
    return {"status": "ok", "db": "connected"}


@app.get("/api/recovery")
def get_recovery(days: int = 30):
    """Daily HRV averages from raw composite data (proxy for recovery trend)."""
    with SessionLocal() as db:
        rows = db.execute(text("""
            SELECT DATE(ts) as day,
                   ROUND(AVG(hrv_value)::numeric, 1) as avg_hrv,
                   MIN(hrv_value) as min_hrv,
                   MAX(hrv_value) as max_hrv,
                   COUNT(*) as samples
            FROM raw_hrv
            WHERE hrv_value > 0
              AND ts >= NOW() - INTERVAL ':days days'
            GROUP BY DATE(ts)
            ORDER BY day ASC
        """), {"days": days}).mappings().all()
    return [dict(r) for r in rows]


@app.get("/api/sleep")
def get_sleep(days: int = 30):
    with SessionLocal() as db:
        rows = db.execute(text("""
            SELECT day, score, deep_pct, rem_pct, light_pct, wake_pct,
                   temp_drop_c, total_sleep_minutes
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
            SELECT day, stage, start_ts, end_ts, duration_minutes FROM raw_sleep
            WHERE start_ts >= NOW() - INTERVAL ':hours hours'
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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=settings.api_host, port=settings.api_port)