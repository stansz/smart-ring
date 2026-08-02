"""Data quality — per-type, per-source freshness (empirically calibrated).

Answers: is each stream arriving as expected for this source today?

**Not** a plausibility checker (stuck HR, range violations) — that is a
separate trust layer for later.

## Observed R09 cadences (production, Jul–Aug 2026)

| Type   | Docs used to say | Observed p50 | p99 same-day gap |
|--------|------------------|--------------|------------------|
| HR     | 5 min            | **15 min**   | 75 min           |
| HRV    | 30 min           | **60 min**   | 120 min          |
| SpO₂   | hourly           | 60 min       | 120 min          |
| Steps  | 15-min slots     | ~60 min when moving; zero hours **omitted** | 240 min |
| Stress | 30 min           | 30 min when publishing | ends 3–11h before last HR nightly |
| Temp   | completed days   | 30 min on completed days | today usually empty |

## Rules (today only for lag; historical days = presence only)

1. Emit rows only for sources that actually have raw data in the window
   (no phantom phone stale rows).
2. ``today`` = calendar today in the analytics session TZ.
3. **Worn** = HR sample within WORN_WINDOW_MIN of ``now``.
4. **Temp today cnt=0** → ok (``temp_pending``).
5. **Absent** (cnt=0) while worn → stale (except temp today).
6. **HR logger stall**: HR lags max(HRV, SpO₂, stress) by > HR_STALL_LAG_MIN
   while those peers have data → stale.
7. **HRV / SpO₂** lag behind day's freshest > 150 min while worn → stale.
8. **Steps**: lag behind freshest > STEPS_STALL_MIN (5h) only in waking
   hours 08–21. Evening stop before last HR is ok.
9. **Stress**: no peer-lag vs HR (ends hours early every night). Flag
   only full-day absence while worn with substantial HR.
10. Lag is **peer-relative** (vs day's freshest sample), not wall-clock
    age — so hours after last sync with no new data stay ok.

DATE() uses session TZ set in db.connect.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import Optional
from zoneinfo import ZoneInfo

log = logging.getLogger(__name__)

# ─── Thresholds (minutes) — calibrated from production gaps ───────────────

# HR sample within this window ⇒ ring is considered worn.
WORN_WINDOW_MIN = 180

# HR logger stall: HR behind freshest of {hrv, spo2, stress}.
HR_STALL_LAG_MIN = 90

# HRV / SpO₂ absolute age while worn (p99 gap 120 + margin).
HRV_SPO2_AGE_MIN = 150

# Steps: only during waking hours; threshold above max observed same-day gap (240).
STEPS_STALL_MIN = 300
STEPS_WAKING_HOURS = range(8, 22)  # local 08:00–21:59

# Full-day stress absence: need this many HR samples to call "worn all day".
STRESS_ABSENT_MIN_HR_SAMPLES = 20

# Preferred source always emitted for type-missing when that source has
# *any* data on the day (other types). Other sources only if they appear
# in raw_* for the window.
PRIMARY_SOURCE = "ring"

TYPES: dict[str, str] = {
    "heart_rate": "raw_heart_rate",
    "spo2": "raw_spo2",
    "temperature": "raw_temperature",
    "hrv": "raw_hrv",
    "steps": "raw_steps",
    "stress": "raw_stress",
}


def _ensure_aware(ts: datetime, fallback_tz: ZoneInfo) -> datetime:
    if ts.tzinfo is None:
        return ts.replace(tzinfo=fallback_tz)
    return ts


def age_minutes(now: datetime, last_ts: Optional[datetime], tz: ZoneInfo) -> Optional[float]:
    if last_ts is None:
        return None
    last = _ensure_aware(last_ts, tz)
    now_a = _ensure_aware(now, tz)
    return (now_a - last).total_seconds() / 60.0


def lag_minutes(newer: Optional[datetime], older: Optional[datetime], tz: ZoneInfo) -> Optional[float]:
    if newer is None or older is None:
        return None
    n = _ensure_aware(newer, tz)
    o = _ensure_aware(older, tz)
    return (n - o).total_seconds() / 60.0


def is_worn(hr_last_ts: Optional[datetime], now: datetime, tz: ZoneInfo) -> bool:
    age = age_minutes(now, hr_last_ts, tz)
    return age is not None and age <= WORN_WINDOW_MIN


def local_hour(ts: datetime, tz: ZoneInfo) -> int:
    return _ensure_aware(ts, tz).astimezone(tz).hour


def classify_status(
    *,
    data_type: str,
    cnt: int,
    last_ts: Optional[datetime],
    is_today: bool,
    worn: bool,
    now: datetime,
    tz: ZoneInfo,
    hr_last_ts: Optional[datetime],
    hr_cnt: int,
    peer_last_ts: Optional[datetime],  # max of hrv/spo2/stress (HR stall peers)
    day_freshest_ts: Optional[datetime],  # max last_ts any type same source today
) -> tuple[str, str]:
    """Return (status, reason) for one (day, type, source) row.

    Pure function — fully unit-testable without a DB.

    Lag rules use **peer lag** (vs day's freshest sample), not wall-clock
    age alone. Analytics often runs hours after the last sync; absolute
    age would false-alarm every idle evening even when the last sync was
    healthy.
    """
    # Temperature today is completed-days-only on the R09.
    if data_type == "temperature" and is_today and cnt == 0:
        return "ok", "temp_pending"

    if cnt == 0:
        if not is_today:
            # Historical type-missing on a day that had other data.
            return "stale", "absent"
        if data_type == "stress":
            # Only full-day absence with substantial HR (not early morning).
            if worn and hr_cnt >= STRESS_ABSENT_MIN_HR_SAMPLES:
                return "stale", "absent"
            return "ok", "stress_sparse_ok"
        if worn:
            return "stale", "absent"
        return "ok", "not_worn"

    # Has samples — historical days: presence is enough.
    if not is_today:
        return "ok", "ok"

    # ── Today lag rules (peer-relative, not wall-clock age) ────────────
    # lag_behind_freshest: how far this type trails the newest sample today.
    lag_f = lag_minutes(day_freshest_ts, last_ts, tz)

    if data_type == "heart_rate":
        # Logger stall: HRV/SpO₂/stress still publishing, HR frozen.
        lag = lag_minutes(peer_last_ts, last_ts, tz)
        if lag is not None and lag > HR_STALL_LAG_MIN:
            return "stale", "hr_logger_stall"
        return "ok", "ok"

    if data_type in ("hrv", "spo2"):
        # p99 gap 120 min; require lag behind freshest > 150 while worn.
        if worn and lag_f is not None and lag_f > HRV_SPO2_AGE_MIN:
            return "stale", "lag"
        return "ok", "ok"

    if data_type == "steps":
        # Zero-suppress + evening stop before last HR are normal.
        # Flag only multi-hour stall vs freshest during waking hours.
        if (
            worn
            and last_ts is not None
            and local_hour(now, tz) in STEPS_WAKING_HOURS
            and lag_f is not None
            and lag_f > STEPS_STALL_MIN
        ):
            return "stale", "lag"
        return "ok", "ok"

    if data_type == "stress":
        # Nightly early stop is normal — never peer-lag vs HR.
        return "ok", "ok"

    if data_type == "temperature":
        return "ok", "ok"

    return "ok", "ok"


def compute_data_quality(conn, days: int = 7) -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    log.info(f"Computing data quality over last {days} days...")

    with conn.cursor() as cur:
        # Session TZ (set by analytics db.connect); fallback for tests.
        cur.execute("SHOW timezone")
        tz_name = cur.fetchone()
        if isinstance(tz_name, dict):
            tz_name = tz_name.get("TimeZone") or tz_name.get("timezone")
        else:
            tz_name = tz_name[0] if tz_name else None
        try:
            tz = ZoneInfo(str(tz_name or "America/Vancouver"))
        except Exception:
            tz = ZoneInfo("America/Vancouver")

        cur.execute("SELECT CURRENT_DATE AS d")
        row = cur.fetchone()
        today = row["d"] if isinstance(row, dict) else row[0]
        if isinstance(today, datetime):
            today = today.date()
        today_str = today.isoformat() if hasattr(today, "isoformat") else str(today)

        now = datetime.now(timezone.utc)

        # (day, data_type, source) -> {cnt, last_ts}
        day_type_source: dict[tuple[str, str, str], dict] = {}
        sources_seen: set[str] = set()

        for data_type, table in TYPES.items():
            cur.execute(
                f"""
                SELECT DATE(ts) AS day,
                       source,
                       COUNT(*) AS cnt,
                       MAX(ts) AS last_ts
                FROM {table}
                WHERE ts >= %s
                GROUP BY 1, 2
                """,
                (cutoff,),
            )
            for r in cur.fetchall():
                d = str(r["day"])
                src = r["source"]
                sources_seen.add(src)
                day_type_source[(d, data_type, src)] = {
                    "cnt": int(r["cnt"]),
                    "last_ts": r["last_ts"],
                }

        # Days / types that have any data
        day_has_any: set[str] = set()
        day_type_has: set[tuple[str, str]] = set()
        for (d, data_type, source), v in day_type_source.items():
            if v["cnt"] > 0:
                day_has_any.add(d)
                day_type_has.add((d, data_type))

        # Rows to emit: every real (day,type,source) with data, plus
        # type-missing rows for sources that appear on that day (any type).
        sources_on_day: dict[str, set[str]] = {}
        for (d, data_type, source), v in day_type_source.items():
            if v["cnt"] > 0:
                sources_on_day.setdefault(d, set()).add(source)

        rows_to_emit: set[tuple[str, str, str]] = set(day_type_source.keys())
        for d in day_has_any:
            day_sources = sources_on_day.get(d, set()) | {PRIMARY_SOURCE}
            for data_type in TYPES:
                if (d, data_type) not in day_type_has:
                    for src in day_sources:
                        # Only emit primary or sources that already exist
                        # somewhere on this day (no global phone spam).
                        if src == PRIMARY_SOURCE or src in sources_on_day.get(d, set()):
                            rows_to_emit.add((d, data_type, src))

        stale_types_seen: set[str] = set()

        for (d, data_type, source) in sorted(rows_to_emit):
            counts = day_type_source.get(
                (d, data_type, source), {"cnt": 0, "last_ts": None}
            )
            cnt = counts["cnt"]
            last_ts = counts["last_ts"]

            hr = day_type_source.get((d, "heart_rate", source), {"cnt": 0, "last_ts": None})
            # Worn / peers: prefer same source; fall back to primary ring HR
            # for worn signal when evaluating phone-only gaps.
            hr_ring = day_type_source.get(
                (d, "heart_rate", PRIMARY_SOURCE), {"cnt": 0, "last_ts": None}
            )
            hr_last = hr["last_ts"] or hr_ring["last_ts"]
            hr_cnt = int(hr["cnt"] or hr_ring["cnt"] or 0)

            peer_candidates = []
            for pt in ("hrv", "spo2", "stress"):
                p = day_type_source.get((d, pt, source), {}).get("last_ts")
                if p is None and source != PRIMARY_SOURCE:
                    p = day_type_source.get((d, pt, PRIMARY_SOURCE), {}).get("last_ts")
                if p is not None:
                    peer_candidates.append(p)
            peer_last = max(peer_candidates) if peer_candidates else None

            # Freshest sample today for this source (any type) — lag baseline.
            freshest_candidates = []
            for tname in TYPES:
                ft = day_type_source.get((d, tname, source), {}).get("last_ts")
                if ft is not None:
                    freshest_candidates.append(ft)
            day_freshest = max(freshest_candidates) if freshest_candidates else None

            is_today = d == today_str
            worn = is_worn(hr_last, now, tz)

            status, reason = classify_status(
                data_type=data_type,
                cnt=cnt,
                last_ts=last_ts,
                is_today=is_today,
                worn=worn,
                now=now,
                tz=tz,
                hr_last_ts=hr_last,
                hr_cnt=hr_cnt,
                peer_last_ts=peer_last,
                day_freshest_ts=day_freshest,
            )

            if status == "stale":
                stale_types_seen.add(f"{data_type}:{source}")

            cur.execute(
                """
                INSERT INTO data_quality (day, data_type, source, last_ts,
                                          sample_count, status, reason, checked_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (day, data_type, source) DO UPDATE SET
                    last_ts = EXCLUDED.last_ts,
                    sample_count = EXCLUDED.sample_count,
                    status = EXCLUDED.status,
                    reason = EXCLUDED.reason,
                    checked_at = EXCLUDED.checked_at
                """,
                (d, data_type, source, last_ts, cnt, status, reason),
            )

        # Drop phantom rows (e.g. old phone cnt=0) not re-emitted this pass.
        days_touched = sorted({d for (d, _, _) in rows_to_emit})
        for d in days_touched:
            keep_pairs = [(t, s) for (dd, t, s) in rows_to_emit if dd == d]
            if not keep_pairs:
                continue
            cur.execute(
                """
                DELETE FROM data_quality
                WHERE day = %s::date
                  AND (data_type, source) NOT IN %s
                """,
                (d, tuple(keep_pairs)),
            )

        conn.commit()
        if stale_types_seen:
            log.info(
                f"  Data quality: stale = {sorted(stale_types_seen)}, "
                f"checked {len(rows_to_emit)} rows"
            )
        else:
            log.info(f"  Data quality: all fresh ({len(rows_to_emit)} rows)")
