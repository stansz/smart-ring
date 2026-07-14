#!/usr/bin/env python3
"""
Host-side poller for admin-triggered syncs.

The dashboard's "Sync Now" button (in the API container) inserts a row into
`sync_requests` with status='pending'. This script runs on the host (where BLE
access works) and:

  1. Polls `sync_requests` for pending rows.
  2. Marks one as 'running', invokes collector/sync_ring.py, waits for it.
  3. On success, marks the row 'completed' with the new sync_log id.
  4. On failure, marks the row 'failed' with the error.

Run as a systemd timer (every minute) or as a long-running service. See
AGENTS.md for installation.

Usage:
    python3 collector/sync_request_poller.py            # one-shot (process one pending request)
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

LOG_DIR = Path(__file__).resolve().parent
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(LOG_DIR / "sync_request_poller.log"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)

DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://smart_ring:changeme@localhost:5432/smart_ring")
PROJECT_ROOT = Path(__file__).resolve().parent.parent
COLLECTOR_WRAPPER = PROJECT_ROOT / "collector" / "collector-wrapper.py"

# Use venv Python for collector scripts (needs bleak, colmi_r02_client, etc.)
# Fall back to sys.executable if venv doesn't exist yet (will fail gracefully).
VENV_PYTHON = PROJECT_ROOT / "venv" / "bin" / "python3"
COLLECTOR_PYTHON = VENV_PYTHON if VENV_PYTHON.is_file() else sys.executable

# Map requested_by values to (script, python_path) tuples
DISPATCH = {
    "admin-ui": (COLLECTOR_WRAPPER, COLLECTOR_PYTHON),
}

# Special requested_by value: skip the collector, just recompute analytics.
# Used by the phone (Web Bluetooth) sync path — the API container inserts a
# row with this value because it can't run the host's analytics.py itself.
ANALYTICS_ONLY = "phone-analytics"


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


def run_collector(python_path: Path, script: Path):
    """Invoke a collector script. Returns (returncode, stdout, stderr)."""
    log.info(f"Running: {python_path} {script}")
    proc = subprocess.run(
        [str(python_path), str(script)],
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
        timeout=600,
    )
    return proc.returncode, proc.stdout, proc.stderr


def run_analytics(python_path: Path):
    """Run analytics to recompute daily/weekly metrics from raw_* tables."""
    log.info("Running analytics (compute metrics)...")
    proc = subprocess.run(
        [str(python_path), str(PROJECT_ROOT / "collector" / "analytics.py")],
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
        timeout=300,
    )
    return proc.returncode, proc.stdout, proc.stderr


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


def process_one(conn):
    """Claim and run one pending request. Returns True if something was processed."""
    req_id, requested_by = claim_next_request(conn)
    if req_id is None:
        return False

    # Analytics-only request (e.g. after a phone Web Bluetooth sync): the
    # container can't run analytics.py, so it queues this. Skip the collector
    # and just recompute metrics.
    if requested_by == ANALYTICS_ONLY:
        log.info(f"Claimed request id={req_id} → analytics-only")
        try:
            arc, _, _ = run_analytics(COLLECTOR_PYTHON)
            if arc == 0:
                mark_completed(conn, req_id, None, "analytics done")
                log.info(f"Request {req_id} analytics done")
            else:
                mark_failed(conn, req_id, f"analytics exit {arc}")
                log.error(f"Request {req_id} analytics exit {arc}")
        except subprocess.TimeoutExpired:
            mark_failed(conn, req_id, "analytics timed out after 300s")
            log.error(f"Request {req_id} analytics timed out")
        except Exception as e:
            mark_failed(conn, req_id, str(e))
            log.exception(f"Request {req_id} raised")
        return True

    script, python_path = DISPATCH.get(requested_by, (None, None))
    if script is None:
        mark_failed(conn, req_id, f"Unknown requested_by: {requested_by}")
        log.error(f"Request {req_id}: unknown type '{requested_by}'")
        return True

    if not script.is_file():
        mark_failed(conn, req_id, f"Script not found: {script}")
        log.error(f"Request {req_id}: script missing {script}")
        return True

    log.info(f"Claimed request id={req_id} type={requested_by} → {script.name}")
    try:
        rc, stdout, stderr = run_collector(python_path, script)
        if rc == 0:
            sync_log_id = find_latest_sync_log_id(conn)
            tail = (stdout or "").strip().splitlines()[-1] if (stdout or "").strip() else "completed"
            mark_completed(conn, req_id, sync_log_id, f"rc=0 ({tail})")
            log.info(f"Request {req_id} completed (sync_log_id={sync_log_id})")
            # Recompute derived metrics so the dashboard shows fresh data.
            try:
                arc, _, _ = run_analytics(python_path)
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
        mark_failed(conn, req_id, "Script timed out after 600s")
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
    log.info(f"Poller started (loop={args.loop}, interval={args.interval}s)")

    if args.loop:
        try:
            while True:
                try:
                    while process_one(conn):
                        pass  # drain the queue
                except psycopg2.OperationalError:
                    log.warning("DB connection lost, reconnecting...")
                    conn = psycopg2.connect(DATABASE_URL)
                time.sleep(args.interval)
        except KeyboardInterrupt:
            log.info("Shutting down")
    else:
        process_one(conn)


if __name__ == "__main__":
    main()
