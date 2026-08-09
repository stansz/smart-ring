"""Smoke tests for collector.analytics.dedupe.dedupe_sources.

Verifies the canonical dedupe contract:
  - At the same timestamp, ring is canonical and phone is removed
  - Different timestamps => both survive (phone fills gaps)
  - raw_hrv dedupes on (ts, hrv_type), not just ts
  - raw_sleep dedupes on day, not ts
  - dedupe_sources is idempotent (running twice == running once)
  - phone-only rows always survive (no ring to dedupe against)
  - Phase 0: N-source contract — when ring + garmin + phone overlap
    at the same ts, the highest-priority source wins and the rest
    are dropped. Configurable via priority_map parameter.

Uses the ephemeral test DB fixtures from conftest.py.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from collector.analytics.dedupe import dedupe_sources


# ----------------------------------------------------------------------------
# Core case: phone+ring at same ts -> phone dies, ring lives
# ----------------------------------------------------------------------------


def test_dedupe_heart_rate_same_ts_drops_phone_keeps_ring(db):
    """The canonical case straight from CLEANUP_PLAN.md item 3."""
    ts = datetime(2026, 7, 20, 14, 30, 0, tzinfo=timezone.utc)
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO raw_heart_rate (ts, bpm, source) VALUES "
            "(%s, 70, 'ring'), "
            "(%s, 72, 'phone')",
            (ts, ts),
        )
    db.commit()

    dedupe_sources(db)

    with db.cursor() as cur:
        cur.execute(
            "SELECT source, bpm FROM raw_heart_rate WHERE ts = %s ORDER BY source",
            (ts,),
        )
        rows = cur.fetchall()
    assert len(rows) == 1, f"expected 1 row, got {rows}"
    assert rows[0] == ("ring", 70)


# ----------------------------------------------------------------------------
# No overlap: phone fills gaps ring missed
# ----------------------------------------------------------------------------


def test_dedupe_heart_rate_no_overlap_both_survive(db):
    """Phone fills slots ring missed; dedupe must not touch those."""
    ring_ts = datetime(2026, 7, 20, 14, 0, 0, tzinfo=timezone.utc)
    phone_ts = datetime(2026, 7, 20, 14, 5, 0, tzinfo=timezone.utc)
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO raw_heart_rate (ts, bpm, source) VALUES "
            "(%s, 70, 'ring'), "
            "(%s, 72, 'phone')",
            (ring_ts, phone_ts),
        )
    db.commit()

    dedupe_sources(db)

    with db.cursor() as cur:
        cur.execute(
            "SELECT source, COUNT(*) FROM raw_heart_rate GROUP BY source ORDER BY source"
        )
        counts = dict(cur.fetchall())
    assert counts == {"phone": 1, "ring": 1}


def test_dedupe_phone_only_row_survives(db):
    """Phone row with no ring counterpart at the same ts must survive."""
    ts = datetime(2026, 7, 20, 14, 0, 0, tzinfo=timezone.utc)
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO raw_heart_rate (ts, bpm, source) VALUES (%s, 72, 'phone')",
            (ts,),
        )
    db.commit()

    dedupe_sources(db)

    with db.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM raw_heart_rate WHERE ts = %s", (ts,))
        assert cur.fetchone()[0] == 1


def test_dedupe_ring_only_row_survives(db):
    """Ring row with no phone counterpart at the same ts must survive."""
    ts = datetime(2026, 7, 20, 14, 0, 0, tzinfo=timezone.utc)
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO raw_heart_rate (ts, bpm, source) VALUES (%s, 70, 'ring')",
            (ts,),
        )
    db.commit()

    dedupe_sources(db)

    with db.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM raw_heart_rate WHERE ts = %s", (ts,))
        assert cur.fetchone()[0] == 1


# ----------------------------------------------------------------------------
# Other point tables (sanity that the loop covers them)
# ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "table, insert_sql",
    [
        ("raw_spo2",        "INSERT INTO raw_spo2 (ts, spo2_pct, source) VALUES (%s, 97, 'ring'), (%s, 96, 'phone')"),
        ("raw_temperature", "INSERT INTO raw_temperature (ts, temp_c, source) VALUES (%s, 36.50, 'ring'), (%s, 36.55, 'phone')"),
        ("raw_stress",      "INSERT INTO raw_stress (ts, stress_value, source) VALUES (%s, 30, 'ring'), (%s, 35, 'phone')"),
        ("raw_steps",       "INSERT INTO raw_steps (ts, steps, source) VALUES (%s, 100, 'ring'), (%s, 105, 'phone')"),
    ],
)
def test_dedupe_point_tables(db, table, insert_sql):
    """Each point table in the dedupe loop should drop phone on ts collision."""
    ts = datetime(2026, 7, 20, 14, 0, 0, tzinfo=timezone.utc)
    with db.cursor() as cur:
        cur.execute(insert_sql, (ts, ts))
    db.commit()

    dedupe_sources(db)

    with db.cursor() as cur:
        cur.execute(f"SELECT source FROM {table} WHERE ts = %s", (ts,))
        rows = cur.fetchall()
    assert rows == [("ring",)], f"{table}: expected only ring row to survive, got {rows}"


# ----------------------------------------------------------------------------
# raw_hrv: dedupes on (ts, hrv_type), not just ts
# ----------------------------------------------------------------------------


def test_dedupe_hrv_same_ts_same_type_drops_phone(db):
    """HRV with same ts AND same hrv_type: phone dies."""
    ts = datetime(2026, 7, 20, 14, 0, 0, tzinfo=timezone.utc)
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO raw_hrv (ts, hrv_value, hrv_type, source) VALUES "
            "(%s, 50.0, 'rmssd', 'ring'), "
            "(%s, 51.0, 'rmssd', 'phone')",
            (ts, ts),
        )
    db.commit()

    dedupe_sources(db)

    with db.cursor() as cur:
        cur.execute("SELECT source FROM raw_hrv WHERE ts = %s", (ts,))
        assert cur.fetchall() == [("ring",)]


def test_dedupe_hrv_same_ts_different_type_both_survive(db):
    """HRV with same ts but different hrv_type: both survive (not duplicates)."""
    ts = datetime(2026, 7, 20, 14, 0, 0, tzinfo=timezone.utc)
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO raw_hrv (ts, hrv_value, hrv_type, source) VALUES "
            "(%s, 50.0, 'rmssd', 'ring'), "
            "(%s, 30.0, 'sdnn', 'phone')",
            (ts, ts),
        )
    db.commit()

    dedupe_sources(db)

    with db.cursor() as cur:
        cur.execute(
            "SELECT source, hrv_type FROM raw_hrv WHERE ts = %s ORDER BY source, hrv_type",
            (ts,),
        )
        rows = cur.fetchall()
    assert len(rows) == 2
    assert ("phone", "sdnn") in rows
    assert ("ring", "rmssd") in rows


# ----------------------------------------------------------------------------
# raw_sleep: dedupes on day, not ts
# ----------------------------------------------------------------------------


def test_dedupe_sleep_same_day_drops_phone(db):
    """raw_sleep dedupes at the day level — phone night wholesale removed."""
    day = "2026-07-20"
    with db.cursor() as cur:
        # Ring's night wins wholesale if present that day
        cur.execute(
            "INSERT INTO raw_sleep (day, stage, start_ts, end_ts, duration_minutes, source) VALUES "
            "(%s, 'deep', '2026-07-20 01:00:00+00', '2026-07-20 02:00:00+00', 60, 'ring'), "
            "(%s, 'deep', '2026-07-20 01:30:00+00', '2026-07-20 02:30:00+00', 60, 'phone')",
            (day, day),
        )
    db.commit()

    dedupe_sources(db)

    with db.cursor() as cur:
        cur.execute("SELECT source FROM raw_sleep WHERE day = %s", (day,))
        rows = cur.fetchall()
    assert rows == [("ring",)]


def test_dedupe_sleep_different_day_both_survive(db):
    """Phone sleep on a day ring didn't record: both survive."""
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO raw_sleep (day, stage, duration_minutes, source) VALUES "
            "('2026-07-19', 'deep', 60, 'ring'), "
            "('2026-07-20', 'deep', 60, 'phone')"
        )
    db.commit()

    dedupe_sources(db)

    with db.cursor() as cur:
        cur.execute(
            "SELECT source, COUNT(*) FROM raw_sleep GROUP BY source ORDER BY source"
        )
        counts = dict(cur.fetchall())
    assert counts == {"phone": 1, "ring": 1}


# ----------------------------------------------------------------------------
# Idempotency
# ----------------------------------------------------------------------------


def test_dedupe_is_idempotent(db):
    """Running dedupe twice == running once. No side effects on second pass."""
    ts = datetime(2026, 7, 20, 14, 0, 0, tzinfo=timezone.utc)
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO raw_heart_rate (ts, bpm, source) VALUES "
            "(%s, 70, 'ring'), "
            "(%s, 72, 'phone')",
            (ts, ts),
        )
    db.commit()

    dedupe_sources(db)
    dedupe_sources(db)  # Second pass should be a no-op

    with db.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM raw_heart_rate")
        assert cur.fetchone()[0] == 1


# ----------------------------------------------------------------------------
# Phase 0: N-source contract
#
# These tests verify the generalized behavior. With only ring+phone
# data, the result is identical to the old hardcoded behavior — the
# old tests above already cover that. The new tests focus on the
# N-source case (3+ sources at one ts) and the custom priority_map
# parameter.
# ----------------------------------------------------------------------------


def test_three_sources_at_same_ts_keeps_highest_priority(db):
    """Ring + garmin + phone at the same ts → only ring survives.

    Default priority is ring > garmin > phone. The other two are
    dropped — exactly one row per slot for the scorers to read.
    """
    ts = datetime(2026, 7, 20, 14, 30, 0, tzinfo=timezone.utc)
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO raw_heart_rate (ts, bpm, source) VALUES "
            "(%s, 70, 'ring'), "
            "(%s, 71, 'garmin'), "
            "(%s, 72, 'phone')",
            (ts, ts, ts),
        )
    db.commit()

    dedupe_sources(db)

    with db.cursor() as cur:
        cur.execute(
            "SELECT source, bpm FROM raw_heart_rate WHERE ts = %s ORDER BY source",
            (ts,),
        )
        rows = cur.fetchall()
    assert rows == [("ring", 70)], f"only ring should survive, got {rows}"


def test_garmin_and_phone_at_same_ts_keeps_garmin(db):
    """No ring at the ts → garmin wins, phone dropped."""
    ts = datetime(2026, 7, 20, 14, 30, 0, tzinfo=timezone.utc)
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO raw_heart_rate (ts, bpm, source) VALUES "
            "(%s, 71, 'garmin'), "
            "(%s, 72, 'phone')",
            (ts, ts),
        )
    db.commit()

    dedupe_sources(db)

    with db.cursor() as cur:
        cur.execute(
            "SELECT source, bpm FROM raw_heart_rate WHERE ts = %s",
            (ts,),
        )
        rows = cur.fetchall()
    assert rows == [("garmin", 71)], f"only garmin should survive, got {rows}"


def test_phone_only_three_source_slot_survives(db):
    """Phone alone at a ts where ring+garmin are absent → survives.

    Important: we don't drop data just because it's the lowest-
    priority source. The scorer should still see the phone value.
    """
    ring_ts = datetime(2026, 7, 20, 14, 0, 0, tzinfo=timezone.utc)
    garmin_ts = datetime(2026, 7, 20, 14, 5, 0, tzinfo=timezone.utc)
    phone_ts = datetime(2026, 7, 20, 14, 10, 0, tzinfo=timezone.utc)
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO raw_heart_rate (ts, bpm, source) VALUES "
            "(%s, 70, 'ring'), "
            "(%s, 71, 'garmin'), "
            "(%s, 72, 'phone')",
            (ring_ts, garmin_ts, phone_ts),
        )
    db.commit()

    dedupe_sources(db)

    with db.cursor() as cur:
        cur.execute("SELECT source FROM raw_heart_rate ORDER BY source")
        rows = cur.fetchall()
    assert rows == [("garmin",), ("phone",), ("ring",)], (
        f"all 3 different-ts rows should survive, got {rows}"
    )


def test_custom_priority_map_garmin_first_drops_ring(db):
    """Pass a custom priority_map where garmin beats ring.

    The priority_map parameter lets future per-metric rules (e.g.
    activity-window HR prefers Garmin) override the global default
    without code changes.
    """
    ts = datetime(2026, 7, 20, 14, 30, 0, tzinfo=timezone.utc)
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO raw_heart_rate (ts, bpm, source) VALUES "
            "(%s, 70, 'ring'), "
            "(%s, 71, 'garmin'), "
            "(%s, 72, 'phone')",
            (ts, ts, ts),
        )
    db.commit()

    custom_priority = {
        "heart_rate":   ("garmin", "ring", "phone"),
        "spo2":         ("garmin", "ring", "phone"),
        "temperature":  ("garmin", "ring", "phone"),
        "hrv":          ("garmin", "ring", "phone"),
        "steps":        ("garmin", "ring", "phone"),
        "stress":       ("garmin", "ring", "phone"),
        "sleep":        ("garmin", "ring", "phone"),
    }
    dedupe_sources(db, priority_map=custom_priority)

    with db.cursor() as cur:
        cur.execute(
            "SELECT source, bpm FROM raw_heart_rate WHERE ts = %s",
            (ts,),
        )
        rows = cur.fetchall()
    assert rows == [("garmin", 71)], f"garmin should win under custom priority, got {rows}"


def test_three_source_hrv_keeps_only_highest_priority(db):
    """HRV dedupes on (ts, hrv_type). Three sources at same slot → ring wins."""
    ts = datetime(2026, 7, 20, 14, 0, 0, tzinfo=timezone.utc)
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO raw_hrv (ts, hrv_value, hrv_type, source) VALUES "
            "(%s, 50.0, 'rmssd', 'ring'), "
            "(%s, 51.0, 'rmssd', 'garmin'), "
            "(%s, 52.0, 'rmssd', 'phone')",
            (ts, ts, ts),
        )
    db.commit()

    dedupe_sources(db)

    with db.cursor() as cur:
        cur.execute("SELECT source FROM raw_hrv WHERE ts = %s", (ts,))
        rows = cur.fetchall()
    assert rows == [("ring",)], f"only ring should survive for HRV, got {rows}"


def test_three_source_sleep_keeps_only_highest_priority(db):
    """Sleep dedupes on day. Three sources on the same day → ring wins."""
    day = "2026-07-20"
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO raw_sleep (day, stage, start_ts, end_ts, duration_minutes, source) VALUES "
            "(%s, 'deep', '2026-07-20 01:00:00+00', '2026-07-20 02:00:00+00', 60, 'ring'), "
            "(%s, 'deep', '2026-07-20 01:00:00+00', '2026-07-20 02:00:00+00', 60, 'garmin'), "
            "(%s, 'deep', '2026-07-20 01:00:00+00', '2026-07-20 02:00:00+00', 60, 'phone')",
            (day, day, day),
        )
    db.commit()

    dedupe_sources(db)

    with db.cursor() as cur:
        cur.execute("SELECT source FROM raw_sleep WHERE day = %s", (day,))
        rows = cur.fetchall()
    assert rows == [("ring",)], f"only ring should survive for sleep, got {rows}"


def test_mixed_garmin_present_on_some_slots_only(db):
    """Garmin has data at 14:00 but not 14:05; ring has both.

    Slot 14:00: ring + garmin → ring wins, garmin dropped.
    Slot 14:05: ring alone → ring stays.
    Garbage test for the multi-source case where the N-source overlap
    is partial, not uniform.
    """
    ts1 = datetime(2026, 7, 20, 14, 0, 0, tzinfo=timezone.utc)
    ts2 = datetime(2026, 7, 20, 14, 5, 0, tzinfo=timezone.utc)
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO raw_heart_rate (ts, bpm, source) VALUES "
            "(%s, 70, 'ring'), "
            "(%s, 71, 'garmin'), "
            "(%s, 72, 'ring')",
            (ts1, ts1, ts2),
        )
    db.commit()

    dedupe_sources(db)

    with db.cursor() as cur:
        cur.execute(
            "SELECT ts, source, bpm FROM raw_heart_rate ORDER BY ts, source"
        )
        rows = cur.fetchall()
    # ts1: only ring (garmin dropped). ts2: only ring (no garmin there).
    assert rows == [
        (ts1, "ring", 70),
        (ts2, "ring", 72),
    ], f"got {rows}"


def test_unknown_source_preserved_when_known_sources_present(db):
    """An unknown source (e.g. 'oura') at a ts with ring+garmin → preserved.

    We don't know its quality, so we don't auto-drop it. The scorer
    can decide what to do. (Could be a feature: a future scorer
    might prefer oura over garmin for sleep.)
    """
    ts = datetime(2026, 7, 20, 14, 0, 0, tzinfo=timezone.utc)
    with db.cursor() as cur:
        cur.execute(
            "INSERT INTO raw_heart_rate (ts, bpm, source) VALUES "
            "(%s, 70, 'ring'), "
            "(%s, 71, 'garmin'), "
            "(%s, 73, 'oura')",
            (ts, ts, ts),
        )
    db.commit()

    dedupe_sources(db)

    with db.cursor() as cur:
        cur.execute(
            "SELECT source FROM raw_heart_rate WHERE ts = %s ORDER BY source",
            (ts,),
        )
        rows = cur.fetchall()
    assert rows == [("oura",), ("ring",)], (
        f"ring wins, oura preserved (unknown), garmin dropped, got {rows}"
    )
