"""Tests for strain_trend analytics scorer and pure helpers.

Pure helpers need no DB. compute_strain_trend uses the ephemeral DB fixture.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from collector.analytics import strain_trend as st


# ---------------------------------------------------------------------------
# Pure helper tests
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "strain, expected_label",
    [
        (0.0, "rest"),
        (3.9, "rest"),
        (4.0, "rest"),
        (4.1, "light"),
        (7.9, "light"),
        (8.0, "light"),
        (8.1, "moderate"),
        (12.0, "moderate"),
        (12.1, "hard"),
        (16.0, "hard"),
        (16.1, "very_hard"),
        (21.0, "very_hard"),
    ],
)
def test_load_label_from_strain(strain: float, expected_label: str) -> None:
    assert st.load_label_from_strain(strain) == expected_label


def test_acwr_from_loads() -> None:
    assert st.acwr_from_loads(50.0, 10.0) == 5.0
    assert st.acwr_from_loads(50.0, 0.0) is None
    assert st.acwr_from_loads(50.0, None) is None


def test_trend_direction_from_series() -> None:
    # Increasing
    assert st.trend_direction_from_series([15.0, 15.0, 15.0], [10.0, 10.0, 10.0, 10.0]) == "increasing"
    # Decreasing
    assert st.trend_direction_from_series([5.0, 5.0, 5.0], [10.0, 10.0, 10.0, 10.0]) == "decreasing"
    # Stable
    assert st.trend_direction_from_series([10.0, 10.0, 10.0], [10.0, 10.0, 10.0, 10.0]) == "stable"
    # Insufficient data
    assert st.trend_direction_from_series([], [10.0]) == "stable"


def test_compute_rolling_metrics_window() -> None:
    today = date(2026, 7, 26)
    all_strains = {
        today - timedelta(days=i): 10.0 for i in range(35)
    }
    metrics = st.compute_rolling_metrics(all_strains, today)
    assert metrics["strain_today"] == 10.0
    assert metrics["load_label"] == "moderate"
    assert metrics["strain_7d_sum"] == 70.0
    assert metrics["strain_7d_avg"] == 10.0
    assert metrics["strain_28d_avg"] == 10.0
    assert metrics["acwr"] == 70.0 / 10.0  # 7.0 (with uniform 10.0 loads)
    assert metrics["trend_direction"] == "stable"
    assert metrics["days_with_data"] == 7


# ---------------------------------------------------------------------------
# DB-backed scorer tests
# ---------------------------------------------------------------------------


def _get_db_today(conn) -> date:
    with conn.cursor() as cur:
        cur.execute("SELECT CURRENT_DATE AS today")
        return cur.fetchone()["today"]


def _seed_zone(conn, day: date, strain: float) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO heart_rate_zones (day, rhr_used, max_hr_used, strain_score) "
            "VALUES (%s, 55, 185, %s) "
            "ON CONFLICT (day) DO UPDATE SET strain_score=EXCLUDED.strain_score",
            (day, strain),
        )
    conn.commit()


def test_compute_strain_trend_acwr_placeholder_when_under_28d(db_dict) -> None:
    db_today = _get_db_today(db_dict)
    # Seed only 10 days of history (< 28 days required for chronic baseline)
    for i in range(10):
        _seed_zone(db_dict, db_today - timedelta(days=i), 10.0)

    st.compute_strain_trend(db_dict, days=3)

    with db_dict.cursor() as cur:
        cur.execute("SELECT * FROM strain_trend WHERE day = %s", (db_today,))
        row = cur.fetchone()

    assert row is not None
    assert float(row["strain_today"]) == 10.0
    assert row["load_label"] == "moderate"
    assert row["strain_28d_avg"] is None
    assert row["acwr"] is None  # Placeholder active!
    assert row["days_with_data"] == 7


def test_compute_strain_trend_upsert_idempotent(db_dict) -> None:
    db_today = _get_db_today(db_dict)
    _seed_zone(db_dict, db_today, 12.5)

    st.compute_strain_trend(db_dict, days=3)
    st.compute_strain_trend(db_dict, days=3)

    with db_dict.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM strain_trend WHERE day = %s", (db_today,))
        assert cur.fetchone()["n"] == 1
