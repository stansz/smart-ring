#!/usr/bin/env python3
"""
Host-side poller for admin-triggered syncs.

The dashboard's "Sync Now" button (in the API container) inserts a row into
`sync_requests` with status='pending'. This script runs on the host (where BLE
access works) and:

   1. Polls `sync_requests` for pending rows.
   2. Marks one as 'running', invokes the appropriate job, waits for it.
   3. On success, marks the row 'completed' with the new sync_log id.
   4. On failure, marks the row 'failed' with the error.

Run as a long-running systemd service. See AGENTS.md for installation.

Usage:
    python3 collector/sync_request_poller.py            # one-shot
    python3 collector/sync_request_poller.py --loop     # long-running, polls every 15s
    python3 collector/sync_request_poller.py --loop --interval 30
"""
import argparse
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

import psycopg2
from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler()],
)
log = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://smart_ring:changeme@localhost:5432/smart_ring")
PROJECT_ROOT = Path(__file__).resolve().parent.parent
COLLECTOR_SCRIPT = PROJECT_ROOT / "collector" / "sync_ring.py"

# Use venv Python for collector scripts (needs bleak, colmi_r02_client, etc.).
# Fail loudly if missing — silent fallback to sys.executable would produce
# cryptic import errors deep in the sync path.
VENV_PYTHON = PROJECT_ROOT / "venv" / "bin" / "python3"
if not VENV_PYTHON.is_file():
    log.error(
        f"Venv Python not found at {VENV_PYTHON}. "
        "Create it with: python3 -m venv venv && source venv/bin/activate && pip install -r collector/requirements.txt"
    )
    sys.exit(1)
COLLECTOR_PYTHON = VENV_PYTHON

# Request types the poller handles. Each maps to a SyncJob subclass.
from collector.jobs import AnalyticsJob, RingSyncJob  # noqa: E402

JOBS = {
    "admin-ui": lambda: RingSyncJob(COLLECTOR_PYTHON, PROJECT_ROOT, COLLECTOR_SCRIPT),
    "phone-analytics": lambda: AnalyticsJob(COLLECTOR_PYTHON, PROJECT_ROOT),
}


def set_session_timezone(conn):
    """Set the DB session timezone from $TZ (falls back to America/Vancouver)."""
    tz = os.getenv("TZ", "")
    if not tz:
        try:
            with open("/etc/timezone") as f:
                tz = f.read().strip()
        except Exception:
            tz = "America/Vancouver"
    with conn.cursor() as cur:
        cur.execute("SET TIME ZONE %s", (tz,))
    conn.commit()
    log.info(f"Poller DB session timezone: {tz}")


def claim_next_request(conn):
    """Atomically claim the oldest pending request. Returns (id, requested_by) or (None, None)."""
    with conn.cursor() as cur:
        cur.execute("""
            UPDATE sync_requests
            SET status = 'running', started_at = NOW()
            WHERE id = (
                SELECT id FROM sync_requests
                WHERE status = 'pending'
                ORDER BY requested_at ASC
                FOR UPDATE SKIP LOCKED
                LIMIT 1
            )
            RETURNING id, requested_by
        """)
        row = cur.fetchone()
        conn.commit()
        return (row[0], row[1]) if row else (None, None)


def find_latest_sync_log_id(conn):
    """The collector writes a row to sync_log on start; grab its id."""
    with conn.cursor() as cur:
        cur.execute("""
            SELECT id FROM sync_log ORDER BY started_at DESC LIMIT 1
        """)
        row = cur.fetchone()
        return row[0] if row else None


def mark_completed(conn, req_id, sync_log_id, summary):
    with conn.cursor() as cur:
        cur.execute("""
            UPDATE sync_requests
            SET status = 'completed', completed_at = NOW(),
                sync_log_id = %s, result = %s
            WHERE id = %s
        """, (sync_log_id, summary, req_id))
        conn.commit()


def mark_failed(conn, req_id, error):
    with conn.cursor() as cur:
        cur.execute("""
            UPDATE sync_requests
            SET status = 'failed', completed_at = NOW(), error = %s
            WHERE id = %s
        """, (error[:500], req_id))
        conn.commit()


def reap_stuck_rows(conn, stall_minutes: int = 10):
    """Mark sync_log / sync_requests orphans as errored if stuck in running > N min."""
    with conn.cursor() as cur:
        cur.execute("""
            UPDATE sync_log
            SET status = 'error',
                completed_at = NOW(),
                error = 'orphaned: process exited without finalizing'
            WHERE status = 'running'
              AND started_at < NOW() - (%s * interval '1 minute')
              AND completed_at IS NULL
        """, (stall_minutes,))
        n_log = cur.rowcount
        cur.execute("""
            UPDATE sync_requests
            SET status = 'error', completed_at = NOW(),
                error = 'orphaned: exceeded ' || %s || ' min timeout'
            WHERE status = 'running'
              AND started_at < NOW() - (%s * interval '1 minute')
        """, (stall_minutes, stall_minutes))
        n_req = cur.rowcount
        if n_log or n_req:
            log.info(f"Reaped {n_log} sync_log + {n_req} sync_request orphan(s)")
        conn.commit()


def process_one(conn):
    """Claim and run one pending request. Returns True if something was processed."""
    req_id, requested_by = claim_next_request(conn)
    if req_id is None:
        return False

    job_factory = JOBS.get(requested_by)
    if job_factory is None:
        mark_failed(conn, req_id, f"Unknown requested_by: {requested_by}")
        log.error(f"Request {req_id}: unknown type '{requested_by}'")
        return True

    job = job_factory()
    log.info(f"Claimed request id={req_id} type={requested_by} → {job.__class__.__name__}")
    try:
        rc, stdout, stderr = job.run()
        if rc == 0:
            sync_log_id = find_latest_sync_log_id(conn)
            tail = (stdout or "").strip().splitlines()[-1] if (stdout or "").strip() else "completed"
            mark_completed(conn, req_id, sync_log_id, f"rc=0 ({tail})")
            log.info(f"Request {req_id} completed (sync_log_id={sync_log_id})")
            # Recompute derived metrics so the dashboard shows fresh data.
            try:
                arc, _, _ = AnalyticsJob(COLLECTOR_PYTHON, PROJECT_ROOT).run()
                if arc == 0:
                    log.info(f"Request {req_id} analytics done")
                else:
                    log.warning(f"Request {req_id} analytics failed (rc={arc}) — sync still OK")
            except Exception as e:
                log.warning(f"Request {req_id} analytics raised (non-fatal): {e}")
        else:
            err = (stderr or stdout or f"exit {rc}").strip()
            mark_failed(conn, req_id, err)
            log.error(f"Request {req_id} failed: {err}")
    except subprocess.TimeoutExpired:
        mark_failed(conn, req_id, "Job timed out")
        log.error(f"Request {req_id} timed out")
    except Exception as e:
        mark_failed(conn, req_id, str(e))
        log.exception(f"Request {req_id} raised")

    return True


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--loop", action="store_true", help="Run forever, polling at --interval")
    parser.add_argument("--interval", type=int, default=15, help="Seconds between polls in --loop mode")
    args = parser.parse_args()

    conn = psycopg2.connect(DATABASE_URL)
    set_session_timezone(conn)
    log.info(f"Poller started (loop={args.loop}, interval={args.interval}s)")

    if args.loop:
        try:
            while True:
                try:
                    reap_stuck_rows(conn)
                    while process_one(conn):
                        pass  # drain the queue
                except psycopg2.OperationalError:
                    log.warning("DB connection lost, reconnecting...")
                    conn = psycopg2.connect(DATABASE_URL)
                    set_session_timezone(conn)
                time.sleep(args.interval)
        except KeyboardInterrupt:
            log.info("Shutting down")
    else:
        process_one(conn)


if __name__ == "__main__":
    main()
