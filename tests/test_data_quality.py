"""Tests for the data_quality freshness check.

Covers both the original "total absence" stale rule and the new
peer-relative intra-day freshness rule. The intra-day rule catches the
"steps stalled at 4 PM while HR is current" case that the cnt==0 check
alone misses (the actual production bug that motivated this test file).

Phase 0 (N-source resolver): data_quality now emits one row per
(day, data_type, source). Tests below cover the per-source semantics:
  - ring HR + no phone HR → ring ok, phone stale
  - ring HR + phone HR → both ok
  - days with no data at all → no rows (the 'missing' label is gone
    in the per-source model — entire-day silence is implied by the
    absence of rows)
  - type-missing for a day where other types have data → stale for
    every known source of that type
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from collector.analytics import data_quality as dq


# ----------------------------------------------------------------------------
# DB helpers
# ----------------------------------------------------------------------------


def _insert_hr_rows(conn, ts_list):
    with conn.cursor() as cur:
        for ts in ts_list:
            cur.execute(
                "INSERT INTO raw_heart_rate (ts, bpm, source) VALUES (%s, %s, 'ring')",
                (ts, 70),
            )
    conn.commit()


def _insert_steps_rows(conn, ts_list):
    with conn.cursor() as cur:
        for ts in ts_list:
            cur.execute(
                "INSERT INTO raw_steps (ts, steps, calories, distance, source) VALUES (%s, %s, 0, 0, 'ring')",
                (ts, 100),
            )
    conn.commit()


def _status_for(conn, data_type, day="today", source="ring"):
    """Return the status column for a given (type, source) on a given day.

    The ``source`` default is ``'ring'`` to preserve the pre-Phase-0
    test assertions, which implicitly referred to the ring rows
    (the only source that produced a real row before the data_quality
    table was keyed on source). Multi-source checks can pass
    ``source='phone'`` etc.
    """
    day_expr = "CURRENT_DATE" if day == "today" else "CURRENT_DATE - 1"
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT status FROM data_quality "
            f"WHERE data_type = %s AND day = {day_expr} AND source = %s",
            (data_type, source),
        )
        row = cur.fetchone()
    return row["status"] if row else None


# ----------------------------------------------------------------------------
# Pure helpers (threshold lookup)
# ----------------------------------------------------------------------------


def test_freshness_thresholds_table_is_complete():
    """Every non-temp type has a threshold. Temp is intentionally exempt."""
    assert set(dq.FRESHNESS_GAP_MINUTES.keys()) == {
        "heart_rate", "hrv", "steps", "spo2", "stress"
    }
    assert "temperature" not in dq.FRESHNESS_GAP_MINUTES


# ----------------------------------------------------------------------------
# DB-backed: total-absence rule (existing behavior, must still pass)
# ----------------------------------------------------------------------------


def test_zero_records_today_marks_stale(db_dict):
    """Steps with zero rows today while HR has data → stale (original rule)."""
    now = datetime.now(timezone.utc)
    _insert_hr_rows(db_dict, [now - timedelta(minutes=5)])

    dq.compute_data_quality(db_dict)

    assert _status_for(db_dict, "steps", "today") == "stale"
    assert _status_for(db_dict, "heart_rate", "today") == "ok"


def test_temperature_today_zero_records_is_ok(db_dict):
    """Temp publishes completed-days-only; today's gap is normal, not stale."""
    now = datetime.now(timezone.utc)
    _insert_hr_rows(db_dict, [now - timedelta(minutes=5)])

    dq.compute_data_quality(db_dict)

    assert _status_for(db_dict, "temperature", "today") == "ok"


# ----------------------------------------------------------------------------
# DB-backed: peer-relative intra-day freshness (new rule)
# ----------------------------------------------------------------------------


def test_intraday_freshness_flags_stale_steps(db_dict):
    """Steps has samples today but lags HR by > 90 min while HR is fresh → stale.

    This is the exact production bug: steps stalled at 16:00 while HR kept
    updating through 19:15. The cnt>0 path used to mark it 'ok'; now the
    peer-relative check flips it to 'stale'.
    """
    now = datetime.now(timezone.utc)
    # HR fresh (5 min ago) → peer_fresh = True
    _insert_hr_rows(db_dict, [now - timedelta(minutes=5)])
    # Steps stale (3 hours ago, well past 90-min threshold)
    _insert_steps_rows(db_dict, [now - timedelta(hours=3)])

    dq.compute_data_quality(db_dict)

    assert _status_for(db_dict, "steps", "today") == "stale", (
        "Steps lagging HR by 3h while HR is fresh must be flagged stale"
    )


def test_intraday_freshness_ok_when_within_threshold(db_dict):
    """Steps lagging by < 90 min while peer is fresh → ok (not yet stale)."""
    now = datetime.now(timezone.utc)
    _insert_hr_rows(db_dict, [now - timedelta(minutes=5)])
    # Steps 60 min ago — under the 90-min threshold
    _insert_steps_rows(db_dict, [now - timedelta(minutes=60)])

    dq.compute_data_quality(db_dict)

    assert _status_for(db_dict, "steps", "today") == "ok"


def test_intraday_freshness_no_false_alarm_when_ring_off(db_dict):
    """If no peer is fresh (ring off), don't flag a stale type.

    Without this gate, the check would fire every night after the user
    takes the ring off: HR/Steps both stall, but steps threshold (90 min)
    fires first while HR (30 min) hasn't been checked yet. The peer-fresh
    gate requires at least one type updating within PEER_FRESH_WINDOW_MIN.
    """
    now = datetime.now(timezone.utc)
    # Both HR and steps last seen 5 hours ago — ring was taken off
    five_h_ago = now - timedelta(hours=5)
    _insert_hr_rows(db_dict, [five_h_ago])
    _insert_steps_rows(db_dict, [five_h_ago])

    dq.compute_data_quality(db_dict)

    # max_last_ts is 5h old → peer_fresh=False → no intra-day flag
    assert _status_for(db_dict, "steps", "today") == "ok"
    assert _status_for(db_dict, "heart_rate", "today") == "ok"


def test_intraday_freshness_skips_historical_days(db_dict):
    """Freshness check is today-only; historical days are immutable."""
    now = datetime.now(timezone.utc)
    yesterday = now - timedelta(days=1)

    # Yesterday: HR fresh, steps ancient — but it's historical, so no flag
    _insert_hr_rows(db_dict, [yesterday - timedelta(minutes=5)])
    _insert_steps_rows(db_dict, [yesterday - timedelta(hours=3)])
    # Today: tiny bit of HR so today_str resolves correctly
    _insert_hr_rows(db_dict, [now - timedelta(minutes=5)])

    dq.compute_data_quality(db_dict)

    assert _status_for(db_dict, "steps", "yesterday") == "ok"


# ----------------------------------------------------------------------------
# Phase 0: per-source data_quality rows
# ----------------------------------------------------------------------------


def _insert_hr_rows_for_source(conn, ts_list, source):
    with conn.cursor() as cur:
        for ts in ts_list:
            cur.execute(
                "INSERT INTO raw_heart_rate (ts, bpm, source) VALUES (%s, %s, %s)",
                (ts, 70, source),
            )
    conn.commit()


def _row_count_for(conn, data_type, source, day="today"):
    """Count data_quality rows for a (type, source, day) — used to
    verify emission rather than querying status by hand."""
    day_expr = "CURRENT_DATE" if day == "today" else "CURRENT_DATE - 1"
    with conn.cursor() as cur:
        cur.execute(
            f"SELECT COUNT(*) AS cnt FROM data_quality "
            f"WHERE data_type = %s AND source = %s AND day = {day_expr}",
            (data_type, source),
        )
        return cur.fetchone()["cnt"]


def test_ring_only_data_emits_ring_ok_and_phone_stale(db_dict):
    """Ring has data, phone has no data → ring row ok, phone row stale.

    The phone row appears (rather than being absent) because other
    sources for that type have data — the cross-source staleness is
    now a first-class data_quality signal.
    """
    now = datetime.now(timezone.utc)
    _insert_hr_rows_for_source(db_dict, [now - timedelta(minutes=5)], "ring")

    dq.compute_data_quality(db_dict)

    assert _status_for(db_dict, "heart_rate", "today", "ring") == "ok"
    assert _status_for(db_dict, "heart_rate", "today", "phone") == "stale"


def test_both_sources_present_both_ok(db_dict):
    """Both ring and phone have HR data today → both rows ok."""
    now = datetime.now(timezone.utc)
    _insert_hr_rows_for_source(db_dict, [now - timedelta(minutes=5)], "ring")
    _insert_hr_rows_for_source(db_dict, [now - timedelta(minutes=10)], "phone")

    dq.compute_data_quality(db_dict)

    assert _status_for(db_dict, "heart_rate", "today", "ring") == "ok"
    assert _status_for(db_dict, "heart_rate", "today", "phone") == "ok"


def test_no_data_today_emits_no_rows(db_dict):
    """A day with no data at all → no data_quality rows.

    Pre-Phase-0 this used to emit a 'missing' row. With the per-source
    model, 'missing' is reserved for type-on-day-without-data and the
    day-of-silence case is just "no rows for that day at all" — the
    absence is the signal.
    """
    now = datetime.now(timezone.utc)
    yesterday = now - timedelta(days=1)
    # Yesterday has data (so today_str resolves correctly)
    _insert_hr_rows_for_source(db_dict, [yesterday - timedelta(minutes=5)], "ring")
    # Today has nothing

    dq.compute_data_quality(db_dict)

    assert _row_count_for(db_dict, "heart_rate", "ring", "today") == 0
    assert _row_count_for(db_dict, "heart_rate", "phone", "today") == 0


def test_type_missing_today_emits_stale_for_every_known_source(db_dict):
    """HR has data, but steps has none → both ring+phone steps rows are stale.

    This preserves the pre-Phase-0 'type has no data' rule, just
    generalized: every known source for the missing type gets its own
    stale row.
    """
    now = datetime.now(timezone.utc)
    _insert_hr_rows_for_source(db_dict, [now - timedelta(minutes=5)], "ring")

    dq.compute_data_quality(db_dict)

    assert _status_for(db_dict, "steps", "today", "ring") == "stale"
    assert _status_for(db_dict, "steps", "today", "phone") == "stale"
