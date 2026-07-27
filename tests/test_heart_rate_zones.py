"""Tests for heart_rate_zones analytics scorer and pure helpers.

Pure helpers need no DB. compute_heart_rate_zones uses the ephemeral DB fixture.
"""
from __future__ import annotations

import os
from datetime import date, datetime, timedelta, timezone

import pytest

from collector.analytics import heart_rate_zones as hrz


# ---------------------------------------------------------------------------
# Pure helper tests
# ---------------------------------------------------------------------------


def test_karvonen_bounds_40_180() -> None:
    bounds = hrz.karvonen_bounds(rhr=40, max_hr=180)
    assert bounds[1] == (110, 124)
    assert bounds[5] == (166, 180)
    for i in range(1, 5):
        assert bounds[i][1] == bounds[i + 1][0]


def test_zone_for_bpm_maps_correctly() -> None:
    bounds = hrz.karvonen_bounds(rhr=50, max_hr=170)
    assert hrz.zone_for_bpm(80, bounds) is None
    assert hrz.zone_for_bpm(bounds[1][0], bounds) == 1
    assert hrz.zone_for_bpm(bounds[2][0], bounds) == 2
    assert hrz.zone_for_bpm(bounds[4][0], bounds) == 4
    assert hrz.zone_for_bpm(170, bounds) == 5


def test_edwards_trimp() -> None:
    minutes = {1: 60, 2: 30, 3: 20, 4: 10, 5: 5}
    expected = 60 * 1 + 30 * 2 + 20 * 3 + 10 * 4 + 5 * 5
    assert hrz.edwards_trimp(minutes) == expected


def test_scale_strain() -> None:
    assert hrz.scale_strain(hrz.STRAIN_TRIMP_CAP / 2) == 10.5
    assert hrz.scale_strain(hrz.STRAIN_TRIMP_CAP) == 21.0
    assert hrz.scale_strain(hrz.STRAIN_TRIMP_CAP * 2) == 21.0
    assert hrz.scale_strain(0) == 0.0


def test_rhr_baseline_odd_and_even() -> None:
    assert hrz.rhr_baseline([50, 60, 70]) == 60
    assert hrz.rhr_baseline([50, 60]) == 55
    assert hrz.rhr_baseline([]) is None


def test_compute_day_zones_counts_minutes() -> None:
    samples = [
        {"bpm": 100},
        {"bpm": 116},
        {"bpm": 116},
        {"bpm": 130},
        {"bpm": 160},
        {"bpm": 255},
        {"bpm": 0},
        {"bpm": -10},
    ]
    result = hrz.compute_day_zones(samples, rhr=50, max_hr=170)
    assert result["zone1_min"] == 10
    assert result["zone2_min"] == 5
    assert result["zone3_min"] == 0
    assert result["zone4_min"] == 0
    assert result["zone5_min"] == 10
    assert result["below_zone_min"] == 5
    assert result["elevated_min"] == 15
    assert result["peak_zone"] == 5
    assert result["hr_samples"] == 6
    assert result["trimp"] == 10 * 1 + 5 * 2 + 10 * 5
    assert 0 <= result["strain_score"] <= 21


def test_compute_day_zones_empty_returns_sensible() -> None:
    result = hrz.compute_day_zones([], rhr=50, max_hr=170)
    assert result["hr_samples"] == 0
    assert result["peak_zone"] == 0
    assert result["strain_score"] == 0.0


# ---------------------------------------------------------------------------
# DB-backed scorer tests
# ---------------------------------------------------------------------------


def _get_db_today(conn) -> date:
    with conn.cursor() as cur:
        cur.execute("SELECT CURRENT_DATE AS today")
        return cur.fetchone()["today"]


def _seed_day(conn, day: date, hr_min: int) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO daily_activity (day, hr_min, hr_samples) VALUES (%s, %s, 1) "
            "ON CONFLICT (day) DO UPDATE SET hr_min=EXCLUDED.hr_min, hr_samples=1",
            (day, hr_min),
        )
    conn.commit()


def _seed_hr(conn, ts: datetime, bpm: int) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO raw_heart_rate (ts, bpm, source) VALUES (%s, %s, 'ring')",
            (ts, bpm),
        )
    conn.commit()


@pytest.mark.parametrize("age,expected_delta", [(35, 0), (55, 20)])
def test_compute_heart_rate_zones_end_to_end(db_dict, monkeypatch, age, expected_delta) -> None:
    monkeypatch.setenv("USER_AGE", str(age))
    importlib = __import__("importlib")
    importlib.reload(hrz)

    db_today = _get_db_today(db_dict)
    _seed_day(db_dict, db_today - timedelta(days=1), 50)
    _seed_day(db_dict, db_today - timedelta(days=2), 52)
    _seed_day(db_dict, db_today, 45)

    max_hr = max(220 - age, 170, 51)
    bounds = hrz.karvonen_bounds(51, max_hr)
    z1_bpm = bounds[1][0]
    _seed_hr(db_dict, datetime.combine(db_today, datetime.min.time()), z1_bpm)

    hrz.compute_heart_rate_zones(db_dict, days=3)

    with db_dict.cursor() as cur:
        cur.execute("SELECT * FROM heart_rate_zones WHERE day = %s", (db_today,))
        row = cur.fetchone()

    assert row is not None
    assert row["rhr_used"] == 51
    assert row["max_hr_used"] == max(220 - age, 51)
    assert row["zone1_min"] == 5
    assert float(row["strain_score"]) == hrz.scale_strain(5 * 1)
    assert row["peak_zone"] == 1
    assert row["hr_samples"] == 1


def test_compute_heart_rate_zones_no_history_uses_defaults(db_dict, monkeypatch) -> None:
    monkeypatch.delenv("USER_AGE", raising=False)
    importlib = __import__("importlib")
    importlib.reload(hrz)

    db_today = _get_db_today(db_dict)
    _seed_hr(db_dict, datetime.combine(db_today, datetime.min.time()), 90)

    hrz.compute_heart_rate_zones(db_dict, days=3)

    with db_dict.cursor() as cur:
        cur.execute("SELECT * FROM heart_rate_zones WHERE day = %s", (db_today,))
        row = cur.fetchone()

    assert row is not None
    assert row["rhr_used"] == 60
    assert row["max_hr_used"] == max(220 - hrz.DEFAULT_USER_AGE, 90, 61)


def test_compute_heart_rate_zones_upsert_idempotent(db_dict, monkeypatch) -> None:
    monkeypatch.setenv("USER_AGE", "35")
    importlib = __import__("importlib")
    importlib.reload(hrz)

    db_today = _get_db_today(db_dict)
    _seed_day(db_dict, db_today - timedelta(days=1), 50)
    ts = datetime.combine(db_today, datetime.min.time())
    _seed_hr(db_dict, ts, 110)

    hrz.compute_heart_rate_zones(db_dict, days=3)
    hrz.compute_heart_rate_zones(db_dict, days=3)

    with db_dict.cursor() as cur:
        cur.execute("SELECT COUNT(*) AS n FROM heart_rate_zones WHERE day = %s", (db_today,))
        assert cur.fetchone()["n"] == 1
