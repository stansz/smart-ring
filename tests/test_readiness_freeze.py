"""Tests for the readiness freeze logic (WHOOP-style morning lock).

Pure-function tests for should_freeze() at hour boundaries + DB-backed
integration tests verifying the freeze gate actually skips recomputation
and the COALESCE preserves the original frozen_at timestamp.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from collector.analytics.readiness import FREEZE_HOUR, should_freeze


# ----------------------------------------------------------------------------
# Pure: should_freeze decision tree
# ----------------------------------------------------------------------------


def test_should_freeze_before_freeze_hour_returns_false() -> None:
    """Pre-6 AM: don't freeze, even for today's row."""
    assert should_freeze(
        is_today=True,
        existing_frozen_at=None,
        current_local_hour=FREEZE_HOUR - 1,
        freeze_hour=FREEZE_HOUR,
    ) is False


def test_should_freeze_at_exact_freeze_hour_returns_true() -> None:
    """At 6 AM exactly: freeze (>= comparison)."""
    assert should_freeze(
        is_today=True,
        existing_frozen_at=None,
        current_local_hour=FREEZE_HOUR,
        freeze_hour=FREEZE_HOUR,
    ) is True


def test_should_freeze_after_freeze_hour_returns_true() -> None:
    """Late morning (9 AM): freeze."""
    assert should_freeze(
        is_today=True,
        existing_frozen_at=None,
        current_local_hour=9,
        freeze_hour=FREEZE_HOUR,
    ) is True


def test_should_freeze_already_frozen_returns_false() -> None:
    """Already frozen today: don't re-freeze (preserves original timestamp)."""
    already = datetime(2026, 7, 20, 6, 0, 0, tzinfo=timezone.utc)
    assert should_freeze(
        is_today=True,
        existing_frozen_at=already,
        current_local_hour=10,
        freeze_hour=FREEZE_HOUR,
    ) is False


def test_should_freeze_historical_day_returns_false() -> None:
    """Yesterday or earlier: never needs a new freeze stamp (history is immutable)."""
    assert should_freeze(
        is_today=False,
        existing_frozen_at=None,
        current_local_hour=10,
        freeze_hour=FREEZE_HOUR,
    ) is False


def test_should_freeze_custom_freeze_hour() -> None:
    """Custom freeze_hour parameter respected (e.g., shift workers)."""
    assert should_freeze(
        is_today=True,
        existing_frozen_at=None,
        current_local_hour=4,
        freeze_hour=4,
    ) is True


# ----------------------------------------------------------------------------
# DB-backed: compute_readiness_score respects freeze gate
# ----------------------------------------------------------------------------


def _seed_minimal_readiness_data(conn) -> None:
    """Helper: insert minimal sleep/HRV/activity rows so readiness has something to score."""
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO sleep_quality (day, score, total_sleep_minutes)
            VALUES (CURRENT_DATE, 75, 420), (CURRENT_DATE - 1, 70, 400)
        """)
        cur.execute("""
            INSERT INTO daily_recovery (day, rmssd, baseline_rmssd, z_score)
            VALUES (CURRENT_DATE, 42.0, 41.0, 0.5),
                   (CURRENT_DATE - 1, 41.0, 40.0, 0.3)
        """)
        cur.execute("""
            INSERT INTO daily_activity (day, hr_min)
            VALUES (CURRENT_DATE, 53), (CURRENT_DATE - 1, 55)
        """)
    conn.commit()


def test_compute_readiness_does_not_freeze_when_freeze_hour_not_reached(db_dict, monkeypatch):
    """If FREEZE_HOUR is set above the current local hour, today's row stays unfrozen.

    We can't easily mock the DB's NOW() — instead we monkey-patch FREEZE_HOUR
    to a value higher than any possible hour (25), guaranteeing the
    `current_local_hour >= freeze_hour` check is False regardless of when
    the test runs.
    """
    from collector.analytics import readiness

    monkeypatch.setattr(readiness, "FREEZE_HOUR", 25)

    _seed_minimal_readiness_data(db_dict)

    readiness.compute_readiness_score(db_dict)

    with db_dict.cursor() as cur:
        cur.execute("SELECT frozen_at, score FROM readiness_score WHERE day = CURRENT_DATE")
        row = cur.fetchone()
    assert row is not None
    assert row["frozen_at"] is None, "freeze-hour-not-reached pass must not freeze"
    assert row["score"] is not None


def test_compute_readiness_freezes_when_freeze_hour_reached(db_dict, monkeypatch):
    """FREEZE_HOUR=0 means any local hour qualifies → today's row freezes on this pass."""
    from collector.analytics import readiness

    monkeypatch.setattr(readiness, "FREEZE_HOUR", 0)

    _seed_minimal_readiness_data(db_dict)

    readiness.compute_readiness_score(db_dict)

    with db_dict.cursor() as cur:
        cur.execute("SELECT frozen_at FROM readiness_score WHERE day = CURRENT_DATE")
        row = cur.fetchone()
    assert row is not None
    assert row["frozen_at"] is not None, "freeze-hour-reached pass must set frozen_at"


def test_compute_readiness_skips_already_frozen_today(db_dict):
    """Once frozen, subsequent passes skip recomputing today's row entirely."""
    from collector.analytics import readiness

    # Seed minimal data
    with db_dict.cursor() as cur:
        cur.execute("""
            INSERT INTO sleep_quality (day, score, total_sleep_minutes)
            VALUES (CURRENT_DATE, 75, 420)
        """)
        cur.execute("""
            INSERT INTO daily_recovery (day, rmssd, baseline_rmssd, z_score)
            VALUES (CURRENT_DATE, 42.0, 41.0, 0.5)
        """)
        cur.execute("""
            INSERT INTO daily_activity (day, hr_min)
            VALUES (CURRENT_DATE, 53)
        """)
        # Mark today as already frozen
        cur.execute("""
            INSERT INTO readiness_score (day, score, frozen_at)
            VALUES (CURRENT_DATE, 99, NOW())
        """)
    db_dict.commit()

    # Run compute — should skip today entirely (preserve score=99)
    readiness.compute_readiness_score(db_dict)

    with db_dict.cursor() as cur:
        cur.execute("SELECT score FROM readiness_score WHERE day = CURRENT_DATE")
        row = cur.fetchone()
    assert row is not None
    assert row["score"] == 99, "already-frozen today must not be recomputed"
