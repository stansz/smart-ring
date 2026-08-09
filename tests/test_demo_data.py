"""Tests for the demo-data seeder (``scripts/seed_demo_data.py``).

Two layers, matching the repo convention (pure-function tests + DB-backed):
  1. Pure generator tests — no DB. Pin plausible ranges, cadence counts,
     Ohayon sleep norms, and the FIT semicircle round-trip (wrong scale would
     corrupt the Garmin map silently).
  2. DB-backed integration — seed into the ephemeral test DB, run the real
     analytics scorers against it, assert raw + score tables are populated.
     Proves the demo data is "analytics-complete" (dashboard won't blank).
"""
from __future__ import annotations

import math
import random
from collections import defaultdict
from datetime import datetime, timedelta, timezone

import pytest

from scripts import seed_demo_data as sd


# ---------------------------------------------------------------------------
# Pure generator tests
# ---------------------------------------------------------------------------

@pytest.fixture
def rng():
    return random.Random(42)


class TestCircadianHR:
    def test_overnight_is_resting_range(self, rng):
        """04:00-06:00 HR should be low (resting), well under daytime peak."""
        overnight = [sd.circadian_hr(h, rng=rng) for h in (4.0, 5.0, 6.0) for _ in range(20)]
        afternoon = [sd.circadian_hr(h, rng=rng) for h in (15.0, 16.0, 17.0) for _ in range(20)]
        assert max(overnight) < 70, overnight
        assert min(afternoon) > 60, afternoon
        assert sum(afternoon) / len(afternoon) > sum(overnight) / len(overnight)

    def test_activity_window_elevates_hr(self, rng):
        idle = sd.circadian_hr(15.0, in_activity=False, rng=rng)
        active = sd.circadian_hr(15.0, in_activity=True, rng=rng)
        assert active > idle + 20

    def test_always_positive_and_reasonable(self, rng):
        for h in range(24):
            for _ in range(10):
                v = sd.circadian_hr(h + 0.5, rng=rng)
                assert 40 <= v <= 150


class TestHRV:
    def test_overnight_higher_than_daytime(self, rng):
        """HRV should peak overnight (parasympathetic dominance during sleep)."""
        overnight = [sd.hrv_for_time(4.0, rng=rng) for _ in range(20)]
        midday = [sd.hrv_for_time(15.0, rng=rng) for _ in range(20)]
        assert sum(overnight) / len(overnight) > sum(midday) / len(midday) + 8

    def test_always_positive(self, rng):
        for h in range(24):
            for _ in range(10):
                assert sd.hrv_for_time(h + 0.3, rng=rng) > 0


class TestSteps:
    def test_overnight_zero(self, rng):
        for h in (0, 1, 2, 3, 4, 5, 23):
            assert sd.steps_for_slot(h, rng) == 0

    def test_burst_windows_nonzero(self, rng):
        for h in (7, 8, 18, 19):
            vals = [sd.steps_for_slot(h, rng) for _ in range(20)]
            assert min(vals) > 0

    def test_middays_light(self, rng):
        for h in (10, 12, 14, 16):
            vals = [sd.steps_for_slot(h, rng) for _ in range(20)]
            assert max(vals) < 300


class TestStressAndVitals:
    def test_stress_in_range(self, rng):
        for h in range(24):
            for _ in range(10):
                v = sd.stress_for_time(h + 0.3, rng=rng)
                assert 0 <= v <= 99

    def test_stress_activity_spike(self, rng):
        idle = sd.stress_for_time(15.0, in_activity=False, rng=rng)
        active = sd.stress_for_time(15.0, in_activity=True, rng=rng)
        assert active > idle

    def test_spo2_physiological(self, rng):
        for _ in range(50):
            assert 90 <= sd.spo2_value(rng) <= 100

    def test_skin_temp_range(self, rng):
        for h in range(24):
            v = sd.skin_temp_for_time(h + 0.3, rng=rng)
            assert 29.0 <= v <= 34.0


class TestSemicircles:
    def test_roundtrip(self):
        for deg in (-179.9, -45.5, 0.0, 43.6532, 90.0, 179.9):
            assert abs(sd.semicircles_to_deg(sd.deg_to_semicircles(deg)) - deg) < 1e-6

    def test_known_value(self):
        # 1 degree = 2^31 / 180 semicircles ≈ 11930464.7
        assert sd.deg_to_semicircles(1.0) == 11930465


class TestPolyline:
    def test_correct_length_and_moves(self, rng):
        pts = sd.generate_polyline(43.65, -79.38, 100, 1.4, rng=rng)
        assert len(pts) == 100
        assert pts[0] != pts[-1]  # actually moved
        # no point is absurdly far from the start (< 5 km for a walk)
        lat0, lon0 = pts[0]
        for lat, lon in pts:
            assert abs(lat - lat0) < 0.05 and abs(lon - lon0) < 0.05

    def test_meandering_not_jagged(self, rng):
        """Bearing changes are smoothed — consecutive segments don't reverse."""
        pts = sd.generate_polyline(43.65, -79.38, 200, 1.4, rng=rng)
        # Compute bearing changes between consecutive segments; none should
        # be a full reversal (≈π) which would indicate jagged zig-zag.
        bearings = []
        for i in range(1, len(pts)):
            dlat = pts[i][0] - pts[i - 1][0]
            dlon = pts[i][1] - pts[i - 1][1]
            bearings.append(math.atan2(dlon, dlat))
        for i in range(1, len(bearings)):
            delta = abs(bearings[i] - bearings[i - 1])
            delta = min(delta, 2 * math.pi - delta)
            assert delta < 1.0, f"jagged at segment {i}: {delta:.2f} rad"


class TestSleepStages:
    @pytest.fixture
    def night(self, rng):
        bed = datetime(2026, 8, 7, 23, 15, tzinfo=timezone.utc)
        wake = datetime(2026, 8, 8, 6, 45, tzinfo=timezone.utc)
        return sd.sleep_stages_for_night(bed, wake, rng)

    def test_fills_full_window(self, night):
        total = sum(b["duration_minutes"] for b in night)
        # 23:15 → 06:45 = 450 min
        assert 440 <= total <= 450

    def test_stages_within_ohayon_norms(self, night):
        mins = defaultdict(int)
        for b in night:
            mins[b["stage"]] += b["duration_minutes"]
        sleep = sum(mins[s] for s in ("deep", "rem", "light"))
        if sleep == 0:
            pytest.skip("no sleep stages")
        deep_pct = mins["deep"] / sleep * 100
        rem_pct = mins["rem"] / sleep * 100
        assert 10 <= deep_pct <= 26, f"deep {deep_pct:.0f}%"
        assert 15 <= rem_pct <= 30, f"rem {rem_pct:.0f}%"

    def test_blocks_contiguous(self, night):
        for i in range(1, len(night)):
            assert night[i]["start_ts"] == night[i - 1]["end_ts"], f"gap at block {i}"

    def test_valid_stage_names(self, night):
        for b in night:
            assert b["stage"] in ("deep", "rem", "light", "awake")

    def test_too_short_returns_empty(self, rng):
        bed = datetime(2026, 8, 7, 23, 15, tzinfo=timezone.utc)
        wake = bed + timedelta(minutes=20)
        assert sd.sleep_stages_for_night(bed, wake, rng) == []


# ---------------------------------------------------------------------------
# DB-backed integration test
# ---------------------------------------------------------------------------

class TestSeedAndAnalytics:
    """Seed demo data, run the real analytics scorers, assert output populated.

    Uses the shared ``db_dict`` fixture (ephemeral DB from db/init.sql).
    """

    def test_seed_populates_raw_tables(self, db_dict):
        counts = sd.seed(db_dict, days=15, rng_seed=7)
        with db_dict.cursor() as cur:
            for tbl, col in [
                ("raw_heart_rate", "bpm"), ("raw_hrv", "hrv_value"),
                ("raw_steps", "steps"), ("raw_spo2", "spo2_pct"),
                ("raw_stress", "stress_value"), ("raw_temperature", "temp_c"),
                ("raw_sleep", "duration_minutes"),
            ]:
                cur.execute(f"SELECT COUNT(*) FROM {tbl}")
                assert cur.fetchone()["count"] > 0, f"{tbl} empty"

    def test_seed_is_idempotent(self, db_dict):
        """Re-running seed on the same DB doesn't duplicate (ON CONFLICT DO NOTHING)."""
        sd.seed(db_dict, days=10, rng_seed=1)
        with db_dict.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM raw_heart_rate")
            n1 = cur.fetchone()["count"]
        sd.seed(db_dict, days=10, rng_seed=1)
        with db_dict.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM raw_heart_rate")
            n2 = cur.fetchone()["count"]
        assert n1 == n2

    def test_seed_then_analytics_populates_scores(self, db_dict):
        """The headline test: demo data → real scorers → score tables filled.

        Proves the demo data is analytics-complete (no blank dashboard charts).
        """
        sd.seed(db_dict, days=20, rng_seed=99)
        # Run the scorers directly (same contract as analytics.main.run_all,
        # but via the shared conn so there's no env/import-order fragility).
        from collector.analytics import (
            circadian, current_status, daily_activity, dedupe,
            heart_rate_zones, hrv, readiness, sleep, strain_trend, stress,
        )
        dedupe.dedupe_sources(db_dict)
        hrv.compute_hrv_recovery(db_dict)
        sleep.compute_sleep_quality(db_dict)
        stress.compute_stress(db_dict)
        circadian.compute_circadian_hr(db_dict)
        daily_activity.compute_daily_activity(db_dict)
        heart_rate_zones.compute_heart_rate_zones(db_dict)
        strain_trend.compute_strain_trend(db_dict)
        readiness.compute_readiness_score(db_dict)
        current_status.compute_current_status(db_dict)

        with db_dict.cursor() as cur:
            for tbl in [
                "daily_recovery", "sleep_quality", "circadian_hr",
                "daily_activity", "heart_rate_zones", "readiness_score",
                "current_status",
            ]:
                cur.execute(f"SELECT COUNT(*) FROM {tbl}")
                n = cur.fetchone()["count"]
                assert n > 0, f"{tbl} empty after analytics"

    def test_seed_garmin_activities(self, db_dict):
        sd.seed(db_dict, days=30, rng_seed=5)
        with db_dict.cursor() as cur:
            cur.execute("SELECT COUNT(*) FROM activities")
            assert cur.fetchone()["count"] >= 4
            cur.execute("SELECT COUNT(*) FROM activity_trackpoints")
            assert cur.fetchone()["count"] > 100
            cur.execute("SELECT COUNT(*) FROM activity_hr")
            assert cur.fetchone()["count"] > 100
            cur.execute("SELECT COUNT(*) FROM activity_laps")
            assert cur.fetchone()["count"] > 0
            # GPS coords are within the arbitrary anchor vicinity (not null).
            cur.execute(
                "SELECT lat_semicircles, lon_semicircles FROM activity_trackpoints "
                "WHERE lat_semicircles IS NOT NULL LIMIT 1"
            )
            row = cur.fetchone()
            assert row is not None
            assert sd.semicircles_to_deg(row["lat_semicircles"]) != 0
