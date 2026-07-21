"""Readiness score (WHOOP-style, 3-pillar, morning-frozen).

HRV 44% / Sleep 37% / RHR 19%. Activity (same-day steps) intentionally
removed — circular to score "readiness for today" using today's activity.

RHR uses daily_activity.hr_min (overnight minimum) as the resting-HR proxy,
NOT a 1-5 AM average.

FREEZE LOGIC (WHOOP-style morning lock):
  Today's row updates freely until the first analytics pass at/after 6 AM
  local time, at which point `frozen_at` is set and subsequent passes skip
  recomputing today. Yesterday and earlier are always treated as frozen
  (their `frozen_at` was set when they were today).

  Edge cases handled by should_freeze():
  - First sync of the day is at 3 AM: no freeze yet, recompute happens.
  - First sync is at 9 AM: freeze immediately with whatever data is there.
  - No sync until 2 PM: 2 PM compute freezes (delayed but correct).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Optional

log = logging.getLogger(__name__)

# Hour (local time) at which today's readiness locks.
FREEZE_HOUR = 6


def should_freeze(
    is_today: bool,
    existing_frozen_at: Optional[datetime],
    current_local_hour: int,
    freeze_hour: int,
) -> bool:
    """Pure helper: decide whether to freeze today's readiness on this pass.

    Returns True if:
      - the row being computed is for today (history never unfreezes)
      - AND the row is not already frozen
      - AND the current local hour is at or past the freeze hour

    Returns False otherwise (still pre-freeze hour, or already frozen, or
    a historical row that doesn't need a new freeze stamp).

    `freeze_hour` is required (no default) so callers must read FREEZE_HOUR
    at call time — that makes monkey-patching FREEZE_HOUR in tests work.
    """
    if not is_today:
        return False
    if existing_frozen_at is not None:
        return False
    return current_local_hour >= freeze_hour


def compute_readiness_score(conn, days: int = 30) -> None:
    log.info("Computing readiness scores...")
    # Local hour comes from the DB session TZ (set in db.connect via $TZ env).
    with conn.cursor() as cur:
        cur.execute("SELECT EXTRACT(HOUR FROM NOW())::int AS hr, CURRENT_DATE AS today")
        row = cur.fetchone()
        current_local_hour = row["hr"]
        today = row["today"]
        # Existing frozen_at per day so we can preserve original timestamps.
        cur.execute("SELECT day, frozen_at FROM readiness_score")
        existing_frozen = {row["day"]: row["frozen_at"] for row in cur.fetchall()}

        cur.execute("""
            WITH days AS (
                SELECT day FROM sleep_quality WHERE day >= CURRENT_DATE - INTERVAL '%s days'
                UNION
                SELECT day FROM daily_recovery WHERE day >= CURRENT_DATE - INTERVAL '%s days'
                UNION
                SELECT day FROM daily_activity WHERE day >= CURRENT_DATE - INTERVAL '%s days'
            )
            SELECT d.day,
                   sq.score AS sleep_score,
                   sq.total_sleep_minutes AS sleep_total_min,
                   dr.z_score AS hrv_zscore,
                   dr.rmssd AS hrv_rmssd,
                   da.hr_min AS resting_hr_approx
            FROM days d
            LEFT JOIN sleep_quality sq ON d.day = sq.day
            LEFT JOIN daily_recovery dr ON d.day = dr.day
            LEFT JOIN daily_activity da ON d.day = da.day
            ORDER BY d.day
        """, (days, days, days))
        rows = cur.fetchall()

    rhr_vals = [r['resting_hr_approx'] for r in rows if r['resting_hr_approx']]
    rhr_baseline = sorted(rhr_vals)[len(rhr_vals)//2] if rhr_vals else 60

    def _hrv_to_score(z):
        if z is None: return 50
        if z >= 3.0:  return 100
        if z >= 2.0:  return 95
        if z >= 1.5:  return 90
        if z >= 1.0:  return 80
        if z >= 0.5:  return 70
        if z >= 0.0:  return 55
        if z >= -0.5: return 40
        if z >= -1.0: return 25
        return 10

    count = 0
    frozen_count = 0
    skipped_frozen = 0
    weights = {"hrv": 0.44, "sleep": 0.37, "rhr": 0.19}
    for r in rows:
        day = r['day']

        # Freeze gate: skip recomputing rows that are already frozen for today.
        # (Historical rows can still be upserted — they're already frozen, the
        # COALESCE in the ON CONFLICT branch preserves their frozen_at.)
        is_today = (day == today)
        existing_frozen_at = existing_frozen.get(day)
        if is_today and existing_frozen_at is not None:
            skipped_frozen += 1
            continue

        has_hrv      = r['hrv_zscore'] is not None
        has_sleep    = r['sleep_score'] is not None
        has_rhr      = r['resting_hr_approx'] is not None
        available_weight = sum(
            w for k, w in weights.items()
            if {"hrv": has_hrv, "sleep": has_sleep, "rhr": has_rhr}[k]
        )

        hrv  = _hrv_to_score(r['hrv_zscore']) if has_hrv else None
        slp  = int(r['sleep_score']) if has_sleep else None
        rhr_s = None
        if has_rhr:
            delta = r['resting_hr_approx'] - rhr_baseline
            rhr_s  = max(0, min(100, 60 - delta * 3))

        sub_scores = [
            (hrv, weights["hrv"]),
            (slp, weights["sleep"]),
            (rhr_s, weights["rhr"]),
        ]
        if available_weight > 0:
            score = round(sum(s * w for s, w in sub_scores if s is not None)
                          / available_weight)
        else:
            score = 0

        missing = [
            k for k, v in {"hrv": has_hrv, "sleep": has_sleep, "rhr": has_rhr}.items()
            if not v
        ]
        confidence = "partial" if missing else "full"

        contrib = {}
        if hrv is not None:
            contrib["hrv"] = round((hrv - 50) * weights["hrv"])
        if slp is not None:
            contrib["sleep"] = round((slp - 50) * weights["sleep"])
        if rhr_s is not None:
            contrib["rhr"] = round((rhr_s - 50) * weights["rhr"])

        # Freeze decision: lock today's row on the first pass at/after 6 AM local.
        # Read FREEZE_HOUR at call time so tests can monkey-patch it.
        freeze_now = should_freeze(
            is_today=is_today,
            existing_frozen_at=existing_frozen_at,
            current_local_hour=current_local_hour,
            freeze_hour=FREEZE_HOUR,
        )

        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO readiness_score
                    (day, score, hrv_score, sleep_score, rhr_score,
                     hrv_zscore, resting_hr, hrv_rmssd,
                     sleep_total_min, rhr_baseline, contributors,
                     confidence, missing_components, frozen_at, computed_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
                ON CONFLICT (day) DO UPDATE SET
                    score=EXCLUDED.score, hrv_score=EXCLUDED.hrv_score,
                    sleep_score=EXCLUDED.sleep_score,
                    rhr_score=EXCLUDED.rhr_score, hrv_zscore=EXCLUDED.hrv_zscore,
                    resting_hr=EXCLUDED.resting_hr,
                    hrv_rmssd=EXCLUDED.hrv_rmssd,
                    sleep_total_min=EXCLUDED.sleep_total_min,
                    rhr_baseline=EXCLUDED.rhr_baseline,
                    contributors=EXCLUDED.contributors,
                    confidence=EXCLUDED.confidence,
                    missing_components=EXCLUDED.missing_components,
                    frozen_at=COALESCE(readiness_score.frozen_at, EXCLUDED.frozen_at),
                    computed_at=EXCLUDED.computed_at
            """, (day, score, hrv, slp, rhr_s,
                  r['hrv_zscore'], r['resting_hr_approx'],
                  r['hrv_rmssd'], r['sleep_total_min'], rhr_baseline,
                  json.dumps(contrib), confidence, missing,
                  datetime.now() if freeze_now else None))
        count += 1
        if freeze_now:
            frozen_count += 1
    conn.commit()
    if count or skipped_frozen:
        partial = sum(1 for r in rows if r.get('resting_hr_approx') is None or r.get('hrv_zscore') is None)
        msg = f"  Readiness: {count} days updated (baseline RHR={rhr_baseline} bpm)"
        if frozen_count:
            msg += f", {frozen_count} frozen"
        if skipped_frozen:
            msg += f", {skipped_frozen} already-frozen skipped"
        msg += (f", {partial} with partial confidence" if partial else "")
        log.info(msg)
