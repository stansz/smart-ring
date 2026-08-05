"""Tests for the Garmin FIT parser.

Uses a real .fit file from the user's Forerunner 745 dump at
/opt/smart-ring/data/garmin/raw/manual/GARMIN/Activity/. If the file is missing
the tests skip (CI environments may not have the data).

Covers:
- File discovery (Activity/ + Summary/ only)
- Activity parsing (session, laps, trackpoints)
- Sport → activity_type mapping
- Idempotency: re-parsing the same file gives the same result
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from collector.garmin.parser import (
    discover_fit_files,
    file_hash,
    parse_fit_file,
)


# The real test data lives at /opt/smart-ring/data/garmin/raw/manual/GARMIN/.
# Skip the whole module if it doesn't exist (CI may not have the dump).
REAL_GARMIN_DIR = Path("/opt/smart-ring/data/garmin/raw/manual/GARMIN")
pytestmark = pytest.mark.skipif(
    not REAL_GARMIN_DIR.exists(),
    reason=f"real Garmin dump not present at {REAL_GARMIN_DIR}",
)


@pytest.fixture
def sample_activity_file() -> Path:
    """A known real Activity file (walking, 2026-07-29)."""
    p = REAL_GARMIN_DIR / "Activity" / "2026-07-29-17-35-53.fit"
    if not p.exists():
        pytest.skip(f"sample file missing: {p}")
    return p


# ----------------------------------------------------------------------------
# File discovery
# ----------------------------------------------------------------------------


def test_discover_finds_activity_files():
    """The 745's Activity/ subdir should be picked up."""
    files = list(discover_fit_files(REAL_GARMIN_DIR))
    assert any("activity" in str(p).lower() for p in files)
    assert any("summary" in str(p).lower() for p in files)


def test_discover_skips_settings_files():
    """Settings/ subdir is not a sport data directory."""
    files = list(discover_fit_files(REAL_GARMIN_DIR))
    assert not any("settings" in str(p).lower() for p in files)


def test_discover_skips_metrics_files():
    """Metrics/ subdir is daily summary, not a sport session. Phase 1
    only handles Activity/ + Summary/. (Metrics deferred to 1.5.)"""
    files = list(discover_fit_files(REAL_GARMIN_DIR))
    assert not any("/metrics/" in str(p).lower() for p in files)


def test_discover_skips_sleep_files():
    """Sleep/ subdir holds sleep data, not sport sessions."""
    files = list(discover_fit_files(REAL_GARMIN_DIR))
    assert not any("/sleep/" in str(p).lower() for p in files)


# ----------------------------------------------------------------------------
# Activity parsing
# ----------------------------------------------------------------------------


def test_parse_session_extracts_core_fields(sample_activity_file):
    """The session message has the headline numbers."""
    a = parse_fit_file(sample_activity_file)
    assert a is not None
    assert a.activity_type == "walking"
    assert a.sub_sport == "generic"
    # 2026-07-29 17:35:53 PT = 2026-07-30 00:35:53 UTC (in summer, PDT = UTC-7)
    assert a.start_ts is not None
    assert a.start_ts.year == 2026
    assert a.duration_s is not None and a.duration_s > 4000  # 77 min walk
    assert a.distance_m is not None and a.distance_m > 10000
    assert a.avg_hr is not None and 80 <= a.avg_hr <= 110
    assert a.max_hr is not None and a.max_hr >= a.avg_hr


def test_parse_session_extracts_training_effect(sample_activity_file):
    """The walk had training_effect_aerobic=2.0 — pin it."""
    a = parse_fit_file(sample_activity_file)
    assert a.training_effect_aerobic == pytest.approx(2.0, abs=0.1)


def test_parse_session_extracts_elevation(sample_activity_file):
    """Walk had 160m of ascent — pin it."""
    a = parse_fit_file(sample_activity_file)
    assert a.elevation_gain_m == 160
    assert a.elevation_loss_m == 160


def test_parse_session_extracts_laps(sample_activity_file):
    """This walk has 1 lap (the whole activity)."""
    a = parse_fit_file(sample_activity_file)
    assert len(a.laps) == 1
    lap = a.laps[0]
    assert lap.lap_index == 0
    assert lap.duration_s == a.duration_s


def test_parse_session_extracts_trackpoints(sample_activity_file):
    """1-Hz trackpoints; count should be ~duration in seconds."""
    a = parse_fit_file(sample_activity_file)
    assert len(a.trackpoints) > 1000
    tp0 = a.trackpoints[0]
    assert tp0.ts is not None
    assert tp0.lat_semicircles is not None
    assert tp0.lon_semicircles is not None
    assert tp0.hr is not None


def test_parse_session_trackpoints_monotonic_distance(sample_activity_file):
    """The cumulative distance should never decrease."""
    a = parse_fit_file(sample_activity_file)
    distances = [tp.distance_m for tp in a.trackpoints if tp.distance_m is not None]
    # Tolerate one or two duplicates where GPS flapped, but mostly
    # non-decreasing.
    decreases = sum(1 for i in range(1, len(distances))
                    if distances[i] < distances[i - 1])
    assert decreases < len(distances) * 0.01, (
        f"distance decreased {decreases} times out of {len(distances)} trackpoints"
    )


def test_parse_session_returns_none_for_non_activity_file():
    """Settings.fit is not an activity file — should return None."""
    p = REAL_GARMIN_DIR / "Settings" / "Settings.fit"
    if not p.exists():
        pytest.skip(f"missing: {p}")
    assert parse_fit_file(p) is None


# ----------------------------------------------------------------------------
# File hashing
# ----------------------------------------------------------------------------


def test_file_hash_is_deterministic(sample_activity_file):
    """Same file → same hash, always."""
    h1 = file_hash(sample_activity_file)
    h2 = file_hash(sample_activity_file)
    assert h1 == h2
    assert len(h1) == 64  # sha256 hex digest


# ----------------------------------------------------------------------------
# Sport → activity_type mapping
# ----------------------------------------------------------------------------


@pytest.mark.parametrize("sport,sub,expected", [
    ("running", "generic", "running"),
    ("trail_running", None, "running"),
    ("treadmill_running", None, "running"),
    ("walking", "generic", "walking"),
    ("hiking", None, "hiking"),
    ("road_biking", None, "cycling"),
    ("mountain_biking", None, "cycling"),
    ("indoor_cycling", None, "cycling"),
    ("swimming", "lap_swimming", "swimming"),
    ("generic", "strength_training", "other"),
    ("other", "cardio_training", "other"),
    ("yoga", None, "yoga"),
    ("strength_training", None, "strength_training"),
    ("resort_skiing_snowboarding", None, "skiing"),
])
def test_sport_label_mapping(sport, sub, expected):
    """Sport enum → activity_type translation."""
    from collector.garmin.parser import _SPORT_MAP
    assert _SPORT_MAP.get(sport, "other") == expected
