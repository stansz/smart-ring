import os
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase
from pydantic_settings import BaseSettings
from datetime import date, datetime
from typing import Optional, List
from pydantic import BaseModel

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
    with SessionLocal() as db:
        rows = db.execute(text("""
            SELECT day, rmssd, baseline_rmssd, z_score, readiness_text
            FROM daily_recovery
            WHERE day >= CURRENT_DATE - INTERVAL ':days days'
            ORDER BY day DESC
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
            SELECT hour, avg_hr, min_hr, max_hr, sample_count
            FROM circadian_hr
            ORDER BY hour
        """)).mappings().all()
    return [dict(r) for r in rows]


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


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=settings.api_host, port=settings.api_port)