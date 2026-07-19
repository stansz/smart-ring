"""DB connection + session timezone setup.

Single place to manage the DB connection that every scorer shares.
The session TZ is set here so all `DATE()` / `EXTRACT(HOUR FROM ts)`
expressions in downstream scorers use local time without per-query casts.
"""
from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from typing import Iterator

import psycopg2
from psycopg2.extras import RealDictCursor

log = logging.getLogger(__name__)

DATABASE_URL = os.getenv(
    "DATABASE_URL", "postgresql://smart_ring:changeme@localhost:5432/smart_ring"
)


@contextmanager
def connect() -> Iterator[psycopg2.extensions.connection]:
    """Open a DB connection with the session timezone set from $TZ.

    Yields the connection. Caller is responsible for commit/rollback.
    """
    conn = psycopg2.connect(DATABASE_URL, cursor_factory=RealDictCursor)
    try:
        tz = os.getenv("TZ", "") or _read_etc_timezone() or "America/Vancouver"
        with conn.cursor() as cur:
            cur.execute("SET TIME ZONE %s", (tz,))
        conn.commit()
        log.info(f"Analytics DB session timezone: {tz}")
        yield conn
    finally:
        conn.close()


def _read_etc_timezone() -> str:
    """Read /etc/timezone. Returns '' if unavailable."""
    try:
        with open("/etc/timezone") as f:
            return f.read().strip()
    except Exception:
        return ""
