"""Tests for data_quality freshness (empirically calibrated rules).

Pins real false-alarm cases from production (Jul–Aug 2026):
  - evening steps stop 1–2h before last HR → ok
  - stress ends hours before last HR → ok
  - HRV 2h gap (p99) → ok
  - HR logger stall (peers fresh, HR frozen) → stale
  - steps multi-hour stall while worn daytime → stale
  - no phantom phone rows when phone never synced
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from collector.analytics import data_quality as dq

TZ = ZoneInfo("America/Vancouver")


# ----------------------------------------------------------------------------
# Pure classify_status
# ----------------------------------------------------------------------------


def _pt(year, month, day, hour, minute=0):
    """Wall-clock America/Vancouver → aware datetime."""
    return datetime(year, month, day, hour, minute, tzinfo=TZ)


def _now_local(hour=15, minute=0):
    """Fixed afternoon 'now' in PT for deterministic hour-window tests."""
    return _pt(2026, 8, 1, hour, minute)


def test_thresholds_constants():
    assert dq.HR_STALL_LAG_MIN == 90
    assert dq.HRV_SPO2_AGE_MIN == 150
    assert dq.STEPS_STALL_MIN == 300
    assert dq.WORN_WINDOW_MIN == 180


def _cls(**kwargs):
    """classify_status with day_freshest defaulting to hr_last or now."""
    defaults = dict(
        peer_last_ts=None,
        day_freshest_ts=kwargs.get("hr_last_ts") or kwargs.get("now"),
    )
    defaults.update(kwargs)
    if "day_freshest_ts" not in kwargs and kwargs.get("last_ts"):
        # Freshest is max of last_ts and hr if both present
        hr = kwargs.get("hr_last_ts")
        last = kwargs.get("last_ts")
        peer = kwargs.get("peer_last_ts")
        cands = [t for t in (hr, last, peer) if t is not None]
        if cands:
            defaults["day_freshest_ts"] = max(cands)
    return dq.classify_status(**defaults)


def test_temp_today_pending_ok():
    status, reason = _cls(
        data_type="temperature", cnt=0, last_ts=None, is_today=True,
        worn=True, now=_now_local(), tz=TZ, hr_last_ts=_now_local(),
        hr_cnt=50,
    )
    assert status == "ok"
    assert reason == "temp_pending"


def test_steps_evening_stop_before_hr_is_ok():
    """Steps last 22:00, evaluate at 23:45 local — old rule false-alarmed."""
    now = _pt(2026, 8, 1, 23, 45)
    steps_last = _pt(2026, 8, 1, 22, 0)
    status, reason = _cls(
        data_type="steps", cnt=15, last_ts=steps_last, is_today=True,
        worn=True, now=now, tz=TZ, hr_last_ts=now, hr_cnt=90,
        day_freshest_ts=now,
    )
    assert status == "ok", f"evening steps stop must not alarm, got {status}/{reason}"


def test_steps_3h_afternoon_gap_is_ok():
    """Max observed same-day gap 4h; 3h under 5h threshold → ok."""
    now = _now_local(15)
    steps_last = now - timedelta(hours=3)
    status, _ = _cls(
        data_type="steps", cnt=10, last_ts=steps_last, is_today=True,
        worn=True, now=now, tz=TZ, hr_last_ts=now - timedelta(minutes=10),
        hr_cnt=40, day_freshest_ts=now - timedelta(minutes=10),
    )
    assert status == "ok"


def test_steps_6h_daytime_stall_is_stale():
    now = _now_local(16)
    steps_last = now - timedelta(hours=6)
    freshest = now - timedelta(minutes=10)
    status, reason = _cls(
        data_type="steps", cnt=5, last_ts=steps_last, is_today=True,
        worn=True, now=now, tz=TZ, hr_last_ts=freshest,
        hr_cnt=40, day_freshest_ts=freshest,
    )
    assert status == "stale"
    assert reason == "lag"


def test_stress_ends_hours_before_hr_is_ok():
    """Production 07-31: stress 13:00, HR 23:45 — must not flag."""
    now = _pt(2026, 7, 31, 23, 45)
    stress_last = _pt(2026, 7, 31, 13, 0)
    status, _ = _cls(
        data_type="stress", cnt=20, last_ts=stress_last, is_today=True,
        worn=True, now=now, tz=TZ, hr_last_ts=now, hr_cnt=90,
        day_freshest_ts=now,
    )
    assert status == "ok"


def test_hrv_120min_gap_is_ok():
    """HRV lags freshest by 120 min (p99) → still ok under 150 threshold."""
    now = _now_local(15)
    freshest = now - timedelta(minutes=10)
    hrv_last = freshest - timedelta(minutes=120)
    status, _ = _cls(
        data_type="hrv", cnt=10, last_ts=hrv_last, is_today=True,
        worn=True, now=now, tz=TZ, hr_last_ts=freshest, hr_cnt=40,
        day_freshest_ts=freshest,
    )
    assert status == "ok"


def test_hrv_180min_lag_while_worn_is_stale():
    now = _now_local(15)
    freshest = now - timedelta(minutes=10)
    hrv_last = freshest - timedelta(minutes=180)
    status, reason = _cls(
        data_type="hrv", cnt=5, last_ts=hrv_last, is_today=True,
        worn=True, now=now, tz=TZ, hr_last_ts=freshest, hr_cnt=40,
        day_freshest_ts=freshest,
    )
    assert status == "stale"
    assert reason == "lag"


def test_hrv_absolute_age_without_lag_is_ok():
    """Hours after last sync: all types equally old → no false lag alarm."""
    now = _now_local(21)
    # Last sync left everything ending ~3h ago; freshest == hrv last
    last = now - timedelta(hours=3)
    status, _ = _cls(
        data_type="hrv", cnt=10, last_ts=last, is_today=True,
        worn=False, now=now, tz=TZ, hr_last_ts=last, hr_cnt=40,
        day_freshest_ts=last,
    )
    assert status == "ok"


def test_hr_logger_stall():
    """HR frozen 3h, HRV peer 10 min ago → stale."""
    now = _now_local(15)
    hr_last = now - timedelta(hours=3)
    peer = now - timedelta(minutes=10)
    status, reason = _cls(
        data_type="heart_rate", cnt=20, last_ts=hr_last, is_today=True,
        worn=True, now=now, tz=TZ, hr_last_ts=hr_last, hr_cnt=20,
        peer_last_ts=peer, day_freshest_ts=peer,
    )
    assert status == "stale"
    assert reason == "hr_logger_stall"


def test_hr_75min_natural_gap_ok():
    now = _now_local(15)
    hr_last = now - timedelta(minutes=75)
    status, _ = _cls(
        data_type="heart_rate", cnt=50, last_ts=hr_last, is_today=True,
        worn=True, now=now, tz=TZ, hr_last_ts=hr_last, hr_cnt=50,
        peer_last_ts=hr_last, day_freshest_ts=hr_last,
    )
    assert status == "ok"


def test_absent_steps_while_worn_stale():
    now = _now_local(15)
    status, reason = _cls(
        data_type="steps", cnt=0, last_ts=None, is_today=True,
        worn=True, now=now, tz=TZ, hr_last_ts=now - timedelta(minutes=5),
        hr_cnt=40,
    )
    assert status == "stale"
    assert reason == "absent"


def test_not_worn_absent_is_ok():
    now = _now_local(15)
    old = now - timedelta(hours=6)
    status, reason = _cls(
        data_type="steps", cnt=0, last_ts=None, is_today=True,
        worn=False, now=now, tz=TZ, hr_last_ts=old, hr_cnt=5,
    )
    assert status == "ok"
    assert reason == "not_worn"


def test_stress_absent_early_day_ok():
    """Few HR samples + no stress yet → not full-day absence."""
    now = _now_local(9)
    status, reason = _cls(
        data_type="stress", cnt=0, last_ts=None, is_today=True,
        worn=True, now=now, tz=TZ, hr_last_ts=now - timedelta(minutes=5),
        hr_cnt=8,
    )
    assert status == "ok"
    assert reason == "stress_sparse_ok"


def test_stress_absent_full_day_stale():
    now = _now_local(18)
    status, reason = _cls(
        data_type="stress", cnt=0, last_ts=None, is_today=True,
        worn=True, now=now, tz=TZ, hr_last_ts=now - timedelta(minutes=5),
        hr_cnt=50,
    )
    assert status == "stale"
    assert reason == "absent"


# ----------------------------------------------------------------------------
# DB-backed
# ----------------------------------------------------------------------------


def _insert_hr(conn, ts_list, source="ring"):
    with conn.cursor() as cur:
        for ts in ts_list:
            cur.execute(
                "INSERT INTO raw_heart_rate (ts, bpm, source) VALUES (%s, %s, %s)",
                (ts, 70, source),
            )
    conn.commit()


def _insert_steps(conn, ts_list, source="ring"):
    with conn.cursor() as cur:
        for ts in ts_list:
            cur.execute(
                "INSERT INTO raw_steps (ts, steps, calories, distance, source) "
                "VALUES (%s, %s, 0, 0, %s)",
                (ts, 100, source),
            )
    conn.commit()


def _insert_hrv(conn, ts_list, source="ring"):
    with conn.cursor() as cur:
        for ts in ts_list:
            cur.execute(
                "INSERT INTO raw_hrv (ts, hrv_value, hrv_type, source) "
                "VALUES (%s, %s, %s, %s)",
                (ts, 40, "sdnn", source),
            )
    conn.commit()


def _status(conn, data_type, source="ring", day="today"):
    day_expr = "CURRENT_DATE" if day == "today" else "CURRENT_DATE - 1"
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT status, reason FROM data_quality "
            f"WHERE data_type = %s AND day = {day_expr} AND source = %s",
            (data_type, source),
        )
        row = cur.fetchone()
    if not row:
        return None, None
    return row["status"], row["reason"]


def _row_exists(conn, data_type, source, day="today"):
    day_expr = "CURRENT_DATE" if day == "today" else "CURRENT_DATE - 1"
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT 1 FROM data_quality "
            f"WHERE data_type = %s AND source = %s AND day = {day_expr}",
            (data_type, source),
        )
        return cur.fetchone() is not None


def test_db_zero_steps_while_hr_marks_stale(db_dict):
    now = datetime.now(timezone.utc)
    _insert_hr(db_dict, [now - timedelta(minutes=5)])
    dq.compute_data_quality(db_dict)
    status, reason = _status(db_dict, "steps")
    assert status == "stale"
    assert reason == "absent"
    assert _status(db_dict, "heart_rate")[0] == "ok"


def test_db_temp_today_ok(db_dict):
    now = datetime.now(timezone.utc)
    _insert_hr(db_dict, [now - timedelta(minutes=5)])
    dq.compute_data_quality(db_dict)
    status, reason = _status(db_dict, "temperature")
    assert status == "ok"
    assert reason == "temp_pending"


def test_db_no_phone_phantom_when_phone_never_synced(db_dict):
    now = datetime.now(timezone.utc)
    _insert_hr(db_dict, [now - timedelta(minutes=5)])
    dq.compute_data_quality(db_dict)
    assert _status(db_dict, "heart_rate", "ring")[0] == "ok"
    assert not _row_exists(db_dict, "heart_rate", "phone")


def test_db_phone_emitted_when_phone_has_data(db_dict):
    now = datetime.now(timezone.utc)
    _insert_hr(db_dict, [now - timedelta(minutes=5)], "ring")
    _insert_hr(db_dict, [now - timedelta(minutes=10)], "phone")
    dq.compute_data_quality(db_dict)
    assert _status(db_dict, "heart_rate", "ring")[0] == "ok"
    assert _status(db_dict, "heart_rate", "phone")[0] == "ok"


def test_db_hr_logger_stall(db_dict):
    now = datetime.now(timezone.utc)
    _insert_hr(db_dict, [now - timedelta(hours=3)])
    _insert_hrv(db_dict, [now - timedelta(minutes=10)])
    dq.compute_data_quality(db_dict)
    status, reason = _status(db_dict, "heart_rate")
    assert status == "stale"
    assert reason == "hr_logger_stall"


def test_db_historical_day_no_lag_flag(db_dict):
    now = datetime.now(timezone.utc)
    yesterday = now - timedelta(days=1)
    _insert_hr(db_dict, [yesterday.replace(hour=12, minute=0, second=0, microsecond=0)
                          if yesterday.tzinfo else yesterday])
    # Simpler: just insert relative
    y_hr = now - timedelta(days=1, hours=1)
    y_steps = now - timedelta(days=1, hours=5)
    with db_dict.cursor() as cur:
        cur.execute("DELETE FROM raw_heart_rate")
        cur.execute("DELETE FROM raw_steps")
    db_dict.commit()
    _insert_hr(db_dict, [y_hr, now - timedelta(minutes=5)])
    _insert_steps(db_dict, [y_steps])
    dq.compute_data_quality(db_dict)
    # Yesterday steps present → ok (no lag on historical)
    assert _status(db_dict, "steps", day="yesterday")[0] == "ok"


def test_db_empty_day_no_rows(db_dict):
    now = datetime.now(timezone.utc)
    _insert_hr(db_dict, [now - timedelta(days=1, minutes=5)])
    dq.compute_data_quality(db_dict)
    assert not _row_exists(db_dict, "heart_rate", "ring", "today")
