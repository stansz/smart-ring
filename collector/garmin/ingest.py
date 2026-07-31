"""Garmin FIT file ingest — write parsed activities into Postgres.

Idempotent: tracks ingested files by their sha256 hash in
``garmin_fit_ingest``. Re-running the same directory is a no-op
unless a file's hash changes (which it won't for FIT files; they're
immutable on the watch).

**Schema mapping (parser → DB):**

  ParsedActivity     → activities (one row, UNIQUE source+start_ts)
  ParsedActivity.laps → activity_laps (FK activity_id)
  ParsedActivity.trackpoints → activity_trackpoints (FK activity_id)
                              + activity_hr (HR-only projection)

The 1-Hz-HR projection into ``activity_hr`` is separate from
``activity_trackpoints`` so the dashboard can pull just HR (much
lighter) without GPS coordinates for the activity HR chart.

**Why INSERT ... ON CONFLICT:** we re-ingest the same historical
files on every CLI run to keep idempotency cheap. The conflict
target for activities is ``(source, start_ts)`` — a re-ingest with
the same start time overwrites the row (FIT file at a different
path but same content → same hash → no re-ingest; different content
but same start time → overwrite, which is the right thing for a
re-synced FIT).
"""
from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

import psycopg2
from psycopg2.extras import execute_values, RealDictCursor

from .parser import (
    ParsedActivity,
    ParsedLap,
    ParsedTrackpoint,
    discover_fit_files,
    file_hash,
    parse_fit_file,
)

log = logging.getLogger(__name__)


# Connection factory — same pattern as the rest of the collector.
# Reads DATABASE_URL from env, defaults to the project local.
def _connect():
    url = os.environ.get(
        "DATABASE_URL",
        "postgresql://smart_ring:changeme@localhost:5432/smart_ring",
    )
    return psycopg2.connect(url, cursor_factory=RealDictCursor)


def _is_already_ingested(cur, file_path: str, file_hash_val: str) -> Optional[int]:
    """Return activity_id if already ingested, else None.

    Two paths to "already done":
      1. Same path, same hash → skip (re-run of CLI on the same data)
      2. Different path, same hash → also skip (file moved/copied)
    The path-based lookup is the fast path; the hash lookup catches
    moves.
    """
    cur.execute(
        "SELECT activity_id FROM garmin_fit_ingest "
        "WHERE file_path = %s OR file_hash = %s LIMIT 1",
        (file_path, file_hash_val),
    )
    row = cur.fetchone()
    if row is None:
        return None
    if isinstance(row, dict):
        return row["activity_id"]
    return row[0]


def _record_ingest(
    cur,
    file_path: str,
    file_hash_val: str,
    file_size: int,
    file_mtime: Optional[datetime],
    activity_id: Optional[int],
    record_count: int,
    error: Optional[str] = None,
) -> None:
    cur.execute("""
        INSERT INTO garmin_fit_ingest
            (file_path, file_hash, file_size_bytes, file_mtime,
             activity_id, record_count, ingested_at, error)
        VALUES (%s, %s, %s, %s, %s, %s, NOW(), %s)
        ON CONFLICT (file_path) DO UPDATE SET
            file_hash = EXCLUDED.file_hash,
            file_size_bytes = EXCLUDED.file_size_bytes,
            file_mtime = EXCLUDED.file_mtime,
            activity_id = EXCLUDED.activity_id,
            record_count = EXCLUDED.record_count,
            ingested_at = NOW(),
            error = EXCLUDED.error
    """, (file_path, file_hash_val, file_size, file_mtime,
          activity_id, record_count, error))


def _insert_activity(
    cur,
    a: ParsedActivity,
    file_path: str,
    file_hash_val: str,
) -> int:
    """Insert the activities row, returning the new (or existing) id."""
    cur.execute("""
        INSERT INTO activities (
            source, activity_type, sub_sport,
            start_ts, end_ts, duration_s, timer_time_s,
            distance_m, calories, avg_hr, max_hr,
            avg_cadence, max_cadence,
            avg_speed_mps, max_speed_mps,
            elevation_gain_m, elevation_loss_m,
            avg_temperature_c,
            training_effect_aerobic, training_effect_anaerobic,
            total_strides, avg_vertical_oscillation_mm,
            avg_ground_contact_time_ms, avg_stride_length_cm,
            fit_file_path, fit_file_hash
        ) VALUES (
            'garmin', %s, %s,
            %s, %s, %s, %s,
            %s, %s, %s, %s,
            %s, %s,
            %s, %s,
            %s, %s,
            %s,
            %s, %s,
            %s, %s,
            %s, %s,
            %s, %s
        )
        ON CONFLICT (source, start_ts) DO UPDATE SET
            activity_type = EXCLUDED.activity_type,
            sub_sport = EXCLUDED.sub_sport,
            end_ts = EXCLUDED.end_ts,
            duration_s = EXCLUDED.duration_s,
            timer_time_s = EXCLUDED.timer_time_s,
            distance_m = EXCLUDED.distance_m,
            calories = EXCLUDED.calories,
            avg_hr = EXCLUDED.avg_hr,
            max_hr = EXCLUDED.max_hr,
            avg_cadence = EXCLUDED.avg_cadence,
            max_cadence = EXCLUDED.max_cadence,
            avg_speed_mps = EXCLUDED.avg_speed_mps,
            max_speed_mps = EXCLUDED.max_speed_mps,
            elevation_gain_m = EXCLUDED.elevation_gain_m,
            elevation_loss_m = EXCLUDED.elevation_loss_m,
            avg_temperature_c = EXCLUDED.avg_temperature_c,
            training_effect_aerobic = EXCLUDED.training_effect_aerobic,
            training_effect_anaerobic = EXCLUDED.training_effect_anaerobic,
            total_strides = EXCLUDED.total_strides,
            avg_vertical_oscillation_mm = EXCLUDED.avg_vertical_oscillation_mm,
            avg_ground_contact_time_ms = EXCLUDED.avg_ground_contact_time_ms,
            avg_stride_length_cm = EXCLUDED.avg_stride_length_cm,
            fit_file_path = EXCLUDED.fit_file_path,
            fit_file_hash = EXCLUDED.fit_file_hash
        RETURNING id
    """, (
        a.activity_type, a.sub_sport,
        a.start_ts, a.end_ts, a.duration_s, a.timer_time_s,
        a.distance_m, a.calories, a.avg_hr, a.max_hr,
        a.avg_cadence, a.max_cadence,
        a.avg_speed_mps, a.max_speed_mps,
        a.elevation_gain_m, a.elevation_loss_m,
        a.avg_temperature_c,
        a.training_effect_aerobic, a.training_effect_anaerobic,
        a.total_strides, a.avg_vertical_oscillation_mm,
        a.avg_ground_contact_time_ms, a.avg_stride_length_cm,
        file_path, file_hash_val,
    ))
    # cursor may be tuple- or dict-style depending on the caller's
    # psycopg2 connection; handle both.
    row = cur.fetchone()
    if isinstance(row, dict):
        return row["id"]
    return row[0]


def _insert_laps(cur, activity_id: int, laps: list[ParsedLap]) -> None:
    if not laps:
        return
    # Wipe + rewrite. Lap count for one activity is small (<100),
    # so this is cheaper than diffing. ON CONFLICT keeps the path
    # idempotent in case the file is re-ingested with the same
    # start_ts.
    cur.execute("DELETE FROM activity_laps WHERE activity_id = %s", (activity_id,))
    rows = [
        (
            activity_id,
            lap.lap_index,
            lap.start_ts,
            lap.end_ts,
            lap.duration_s,
            lap.timer_time_s,
            lap.distance_m,
            lap.calories,
            lap.avg_hr,
            lap.max_hr,
            lap.avg_cadence,
            lap.max_cadence,
            lap.avg_speed_mps,
            lap.max_speed_mps,
            lap.elevation_gain_m,
            lap.elevation_loss_m,
        )
        for lap in laps
    ]
    execute_values(cur, """
        INSERT INTO activity_laps (
            activity_id, lap_index, start_ts, end_ts,
            duration_s, timer_time_s, distance_m, calories,
            avg_hr, max_hr, avg_cadence, max_cadence,
            avg_speed_mps, max_speed_mps,
            elevation_gain_m, elevation_loss_m
        ) VALUES %s
    """, rows)


def _insert_trackpoints(cur, activity_id: int, tps: list[ParsedTrackpoint]) -> None:
    if not tps:
        return
    cur.execute("DELETE FROM activity_trackpoints WHERE activity_id = %s", (activity_id,))
    rows = [
        (
            activity_id,
            tp.ts,
            tp.lat_semicircles,
            tp.lon_semicircles,
            tp.altitude_m,
            tp.hr,
            tp.cadence,
            tp.speed_mps,
            tp.distance_m,
            tp.temperature_c,
        )
        for tp in tps
    ]
    # 1-Hz trackpoints × multi-hour activity = thousands of rows.
    # Use a larger page size for execute_values to keep the round-trip
    # count down.
    execute_values(
        cur,
        """
        INSERT INTO activity_trackpoints (
            activity_id, ts, lat_semicircles, lon_semicircles,
            altitude_m, hr, cadence, speed_mps, distance_m, temperature_c
        ) VALUES %s
        """,
        rows,
        page_size=2000,
    )


def _insert_activity_hr(cur, activity_id: int, tps: list[ParsedTrackpoint]) -> None:
    """1-Hz HR projection — separate table for the lightweight
    activity-HR chart. Only inserts rows where HR is present."""
    if not tps:
        return
    cur.execute("DELETE FROM activity_hr WHERE activity_id = %s", (activity_id,))
    rows = [
        (activity_id, tp.ts, tp.hr)
        for tp in tps
        if tp.hr is not None
    ]
    if not rows:
        return
    execute_values(
        cur,
        "INSERT INTO activity_hr (activity_id, ts, hr) VALUES %s",
        rows,
        page_size=2000,
    )


def ingest_file(path: Path, conn) -> tuple[str, int]:
    """Ingest one .fit file. Returns (status, activity_id_or_-1).

    Status is one of: 'inserted', 'updated', 'skipped', 'error'.
    """
    file_path = str(path)
    try:
        h = file_hash(path)
        stat = path.stat()
        mtime = datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc)
    except Exception as e:
        log.warning(f"  {path.name}: stat/hash failed ({e})")
        return "error", -1

    with conn.cursor() as cur:
        # Fast path: already ingested (same path or same hash).
        existing = _is_already_ingested(cur, file_path, h)
        if existing is not None:
            log.info(f"  {path.name}: skipped (already ingested, activity_id={existing})")
            conn.commit()
            return "skipped", existing

        # Parse
        activity = parse_fit_file(path)
        if activity is None:
            # Not an activity file (Settings, Sports, etc.) — record
            # the hash so we don't keep retrying, but as a no-op.
            _record_ingest(cur, file_path, h, stat.st_size, mtime,
                           None, 0, error="not an activity file")
            conn.commit()
            log.debug(f"  {path.name}: not an activity file, recorded")
            return "skipped", -1

        # Insert activity + laps + trackpoints
        activity_id = _insert_activity(cur, activity, file_path, h)
        _insert_laps(cur, activity_id, activity.laps)
        _insert_trackpoints(cur, activity_id, activity.trackpoints)
        _insert_activity_hr(cur, activity_id, activity.trackpoints)

        _record_ingest(cur, file_path, h, stat.st_size, mtime,
                       activity_id, activity.record_count)
    conn.commit()

    log.info(f"  {path.name}: {activity.activity_type} {activity.duration_s}s "
             f"{len(activity.trackpoints)} tps, activity_id={activity_id}")
    return "inserted", activity_id


def ingest_directory(directory: Path, conn) -> dict:
    """Ingest all activity FIT files under ``directory``.

    Returns a summary dict with counts.
    """
    summary = {"found": 0, "inserted": 0, "skipped": 0, "error": 0}
    log.info(f"Scanning {directory} for activity FIT files...")
    for path in discover_fit_files(directory):
        summary["found"] += 1
        status, _ = ingest_file(path, conn)
        summary[status] += 1
    log.info(
        f"Done. found={summary['found']} inserted={summary['inserted']} "
        f"skipped={summary['skipped']} error={summary['error']}"
    )
    return summary


# ─── CLI ───────────────────────────────────────────────────────────────────


def main() -> int:
    import argparse
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.StreamHandler()],
    )
    ap = argparse.ArgumentParser(
        description="Ingest Garmin 745 .fit files (from USB) into Postgres."
    )
    ap.add_argument(
        "--fit-dir", type=Path, required=True,
        help="Path to the Garmin/ directory dumped from the watch "
             "(should contain Activity/, Summary/, Metrics/, etc. subdirs).",
    )
    args = ap.parse_args()

    if not args.fit_dir.exists():
        log.error(f"--fit-dir does not exist: {args.fit_dir}")
        return 1

    conn = _connect()
    try:
        summary = ingest_directory(args.fit_dir, conn)
        return 0 if summary["error"] == 0 else 2
    finally:
        conn.close()


if __name__ == "__main__":
    import sys
    sys.exit(main())
