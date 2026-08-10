"""Tests for the Garmin activity API endpoints.

Uses the real FIT files from /opt/smart-ring/data/garmin/raw/manual/GARMIN/Activity/
(ingested into the ephemeral test DB at setup). If the dump is missing,
the whole module skips — the tests have no fixture to run against.

The test setup ingests ONE real activity file via the same code path
the CLI uses, then exercises the 5 endpoints against it. This is an
end-to-end test of API + DB + the garmin ingest path.
"""
from __future__ import annotations

from pathlib import Path

import pytest

REAL_GARMIN_DIR = Path("/opt/smart-ring/data/garmin/raw/manual/GARMIN")
SAMPLE_ACTIVITY = REAL_GARMIN_DIR / "Activity" / "2026-07-29-17-35-53.fit"


pytestmark = pytest.mark.skipif(
    not SAMPLE_ACTIVITY.exists(),
    reason=f"sample FIT file missing: {SAMPLE_ACTIVITY}",
)


@pytest.fixture
def ingested_activity_id(db_dict):
    """Ingest one real activity file into the test DB, return its id.

    Re-ingests per test (the db_dict fixture truncates between tests).
    Cheap — ~1s for one FIT file. Returns the new activity id.
    """
    from collector.garmin.ingest import ingest_file
    status, aid = ingest_file(SAMPLE_ACTIVITY, db_dict)
    assert status == "inserted", f"setup ingest failed: {status}"
    assert aid > 0
    return aid


# ----------------------------------------------------------------------------
# GET /api/activities (list)
# ----------------------------------------------------------------------------


def test_activities_list_returns_array(api_client, ingested_activity_id):
    """List endpoint returns at least the one fixture activity."""
    response = api_client.get("/api/activities?days=365&limit=10")
    assert response.status_code == 200
    data = response.json()
    assert isinstance(data, list)
    assert len(data) >= 1
    assert any(a["id"] == ingested_activity_id for a in data)


def test_activities_list_has_expected_fields(api_client, ingested_activity_id):
    """Each row has the headline fields the dashboard needs."""
    response = api_client.get("/api/activities?days=365&limit=10")
    data = response.json()
    activity = next(a for a in data if a["id"] == ingested_activity_id)
    for field in ("id", "activity_type", "start_ts", "duration_s",
                  "distance_m", "avg_hr", "max_hr", "lap_count"):
        assert field in activity, f"missing field: {field}"
    assert activity["activity_type"] == "walking"
    assert activity["duration_s"] > 4000
    assert activity["distance_m"] > 10000


def test_activities_list_sport_filter(api_client, ingested_activity_id):
    """Sport filter narrows to matching activities."""
    # Filter to walking — should include our fixture
    r1 = api_client.get("/api/activities?days=365&sport=walking")
    assert r1.status_code == 200
    assert any(a["id"] == ingested_activity_id for a in r1.json())

    # Filter to running — our walking fixture shouldn't be there
    r2 = api_client.get("/api/activities?days=365&sport=running")
    assert r2.status_code == 200
    assert not any(a["id"] == ingested_activity_id for a in r2.json())


def test_activities_list_empty_when_no_data(api_client):
    """Empty list when no activities match the filter."""
    # days=0 used to mean "cutoff = today" but the API now bounds days
    # to >= 1. A sport filter that matches nothing is the clean way to
    # get an empty list with valid params.
    r = api_client.get("/api/activities?days=365&sport=skiing")
    assert r.status_code == 200
    assert isinstance(r.json(), list)
    assert r.json() == []


def test_activities_list_respects_limit(api_client, ingested_activity_id):
    """Limit caps the result count."""
    r = api_client.get("/api/activities?days=365&limit=1")
    assert r.status_code == 200
    assert len(r.json()) <= 1


# ----------------------------------------------------------------------------
# GET /api/activities/{id} (detail)
# ----------------------------------------------------------------------------


def test_activity_detail_returns_full_record(api_client, ingested_activity_id):
    """Detail endpoint returns more fields than the list (training effect etc.)."""
    r = api_client.get(f"/api/activities/{ingested_activity_id}")
    assert r.status_code == 200
    data = r.json()
    assert data["id"] == ingested_activity_id
    # Fields that exist on the detail endpoint but not the list
    assert "training_effect_aerobic" in data
    assert "fit_file_path" in data


def test_activity_detail_404_for_missing(api_client):
    """Unknown id → 404 with helpful message."""
    r = api_client.get("/api/activities/999999")
    assert r.status_code == 404
    assert "999999" in r.json()["detail"]


# ----------------------------------------------------------------------------
# GET /api/activities/{id}/trackpoints
# ----------------------------------------------------------------------------


def test_trackpoints_returns_1hz_data(api_client, ingested_activity_id):
    """Trackpoints are 1-Hz; should match the duration in seconds."""
    r = api_client.get(f"/api/activities/{ingested_activity_id}/trackpoints")
    assert r.status_code == 200
    tps = r.json()
    # Our fixture is a ~77 min walk = ~4600 trackpoints
    assert len(tps) > 1000
    # First trackpoint has lat/lon converted from semicircles
    tp0 = tps[0]
    assert tp0["lat"] is not None
    assert tp0["lon"] is not None
    # Lat/lon should be in degree range (-90..90 for lat, -180..180 for lon)
    assert -90 <= tp0["lat"] <= 90
    assert -180 <= tp0["lon"] <= 180


def test_trackpoints_404_for_missing_activity(api_client):
    r = api_client.get("/api/activities/999999/trackpoints")
    assert r.status_code == 404


def test_trackpoints_downsamples_when_over_cap(api_client, ingested_activity_id):
    """When max_points is set low, the response is capped."""
    r = api_client.get(
        f"/api/activities/{ingested_activity_id}/trackpoints?max_points=100"
    )
    assert r.status_code == 200
    tps = r.json()
    # 100 cap + dedup tolerance — should be ≤ ~110
    assert len(tps) <= 110


# ----------------------------------------------------------------------------
# GET /api/activities/{id}/hr
# ----------------------------------------------------------------------------


def test_hr_returns_1hz_hr_samples(api_client, ingested_activity_id):
    """HR endpoint returns 1-Hz HR samples."""
    r = api_client.get(f"/api/activities/{ingested_activity_id}/hr")
    assert r.status_code == 200
    hr = r.json()
    assert len(hr) > 1000
    # Each row has just ts + hr
    assert set(hr[0].keys()) == {"ts", "hr"}
    # HR values in physiological range
    assert 30 <= hr[0]["hr"] <= 220


def test_hr_404_for_missing_activity(api_client):
    r = api_client.get("/api/activities/999999/hr")
    assert r.status_code == 404


# ----------------------------------------------------------------------------
# GET /api/activities/{id}/laps
# ----------------------------------------------------------------------------


def test_laps_returns_per_lap_data(api_client, ingested_activity_id):
    """Laps endpoint returns lap splits (1 for this fixture)."""
    r = api_client.get(f"/api/activities/{ingested_activity_id}/laps")
    assert r.status_code == 200
    laps = r.json()
    assert len(laps) >= 1
    lap = laps[0]
    for field in ("lap_index", "duration_s", "distance_m", "avg_hr", "max_hr"):
        assert field in lap
    assert lap["lap_index"] == 0
    assert lap["distance_m"] > 10000


def test_laps_returns_empty_for_activity_without_laps(api_client, db_dict):
    """An activity with 0 laps returns an empty list (not 404)."""
    # Insert an activity row without any laps
    from datetime import datetime, timezone
    with db_dict.cursor() as cur:
        cur.execute("""
            INSERT INTO activities (source, activity_type, start_ts, duration_s)
            VALUES ('garmin', 'other', %s, 60)
            RETURNING id
        """, (datetime(2024, 1, 1, tzinfo=timezone.utc),))
        aid = cur.fetchone()["id"]
    db_dict.commit()

    r = api_client.get(f"/api/activities/{aid}/laps")
    assert r.status_code == 200
    assert r.json() == []
