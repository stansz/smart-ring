"""Shared test fixtures.

DB-backed tests use an ephemeral database created from db/init.sql.
The DB is created once per session (session-scoped fixture) and all
mobile_sync-touched tables are TRUNCATEd between tests (function-scoped
fixture) so each test sees a clean state.

Pure-function tests (trap_score, BCD) need no fixtures — they import
the helper directly and don't request `db`, so the DB machinery stays
dormant when those tests run alone.
"""
from __future__ import annotations

import importlib
import os
import re
import sys
from pathlib import Path

import psycopg2
import pytest
from psycopg2.extras import RealDictCursor

PROJECT_ROOT = Path(__file__).parent.parent
INIT_SQL = PROJECT_ROOT / "db" / "init.sql"
API_DIR = PROJECT_ROOT / "api"

# api/main.py uses script-style absolute imports (`from upsert import ...`)
# because the container runs `uvicorn main:app` from /app without package
# context. Tests import via `from api.main import app`, so we need api/ on
# sys.path for the sibling import to resolve in the test environment.
if str(API_DIR) not in sys.path:
    sys.path.insert(0, str(API_DIR))

# Tables truncated before each test for isolation. Includes raw_* (mobile_sync,
# dedupe tests), analytics output tables (readiness freeze tests), and
# operational tables (sync_log, sync_requests). Order doesn't matter — TRUNCATE
# with CASCADE handles FK references.
TABLES_TO_TRUNCATE = (
    "raw_heart_rate, raw_hrv, raw_sleep, raw_steps, "
    "raw_spo2, raw_temperature, raw_stress, "
    "ring_goals, ring_status, sync_log, sync_requests, "
    "daily_recovery, sleep_quality, daily_activity, readiness_score, "
    "current_status, hrv_trends, circadian_hr, stress_classification, data_quality"
)


@pytest.fixture(scope="session")
def test_db_url():
    """Create an ephemeral test database, yield its URL, drop on session exit.

    Uses the host/port/user from $DATABASE_URL (defaults to the project's
    local dev URL). Connects to the 'postgres' maintenance DB with the
    same credentials to issue CREATE/DROP DATABASE — requires the user
    to have CREATEDB privilege (smart_ring user does; see pg_roles).
    """
    prod_url = os.environ.get(
        "DATABASE_URL",
        "postgresql://smart_ring:changeme@localhost:5432/smart_ring",
    )
    # Rewrite the path component to point at the maintenance DB
    admin_url = re.sub(r"/[^/]+$", "/postgres", prod_url)
    test_db_name = f"smart_ring_test_{os.getpid()}"

    admin_conn = psycopg2.connect(admin_url, cursor_factory=RealDictCursor)
    admin_conn.autocommit = True
    try:
        with admin_conn.cursor() as cur:
            cur.execute(f"DROP DATABASE IF EXISTS {test_db_name}")
            cur.execute(f"CREATE DATABASE {test_db_name}")
    finally:
        admin_conn.close()

    test_url = re.sub(r"/[^/]+$", f"/{test_db_name}", prod_url)
    try:
        # Apply schema from db/init.sql (idempotent — IF NOT EXISTS everywhere)
        setup_conn = psycopg2.connect(test_url, cursor_factory=RealDictCursor)
        try:
            with setup_conn.cursor() as cur:
                cur.execute(INIT_SQL.read_text())
            setup_conn.commit()
        finally:
            setup_conn.close()
        yield test_url
    finally:
        # Tear down: kill any lingering sessions, then drop the DB
        teardown = psycopg2.connect(admin_url, cursor_factory=RealDictCursor)
        teardown.autocommit = True
        try:
            with teardown.cursor() as cur:
                cur.execute(
                    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                    "WHERE datname = %s AND pid <> pg_backend_pid()",
                    (test_db_name,),
                )
                cur.execute(f"DROP DATABASE IF EXISTS {test_db_name}")
        finally:
            teardown.close()


@pytest.fixture
def db(test_db_url):
    """Yield a psycopg2 connection to the test DB with mobile_sync tables truncated.

    Default tuple cursor (matches psycopg2 default). Each test gets a fresh
    empty state. Use this for tests that use index-based row access
    (`row[0]`, `cur.fetchone()[1]`).
    """
    conn = psycopg2.connect(test_db_url)
    try:
        with conn.cursor() as cur:
            cur.execute(f"TRUNCATE {TABLES_TO_TRUNCATE} RESTART IDENTITY CASCADE")
        conn.commit()
        yield conn
    finally:
        conn.close()


@pytest.fixture
def db_dict(test_db_url):
    """Same as `db` but with RealDictCursor (matches production analytics/db.py).

    Use this for tests that exercise analytics scorers, which expect
    dict-style row access (`row['column_name']`).
    """
    conn = psycopg2.connect(test_db_url, cursor_factory=RealDictCursor)
    try:
        with conn.cursor() as cur:
            cur.execute(f"TRUNCATE {TABLES_TO_TRUNCATE} RESTART IDENTITY CASCADE")
        conn.commit()
        yield conn
    finally:
        conn.close()


@pytest.fixture(scope="session")
def api_client(test_db_url):
    """Yield a FastAPI TestClient bound to the ephemeral test DB.

    api/main.py reads DATABASE_URL at import time to construct its
    SQLAlchemy engine. We set the env var BEFORE the first import so
    the engine binds to our ephemeral DB. If api.main was already
    imported (e.g., by another test module), reload it so the new
    env var takes effect.

    Session-scoped because TestClient + app startup is expensive, and
    the underlying test DB is already session-scoped.
    """
    os.environ["DATABASE_URL"] = test_db_url
    if "api.main" in sys.modules:
        importlib.reload(sys.modules["api.main"])
    from api.main import app
    from fastapi.testclient import TestClient

    with TestClient(app) as client:
        yield client
