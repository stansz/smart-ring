"""Regression net for api/main.py:mobile_sync — pins current behavior
before the Step 4 refactor (generic upsert_many dispatch).

Each test sends a known payload to /api/mobile/sync via TestClient and
asserts (a) the HTTP response shape and (b) the resulting DB state.

These tests pin behavior, including one known quirk:
  - `accepted` counter increments per attempt, not per actually-inserted
    row. ON CONFLICT DO NOTHING doesn't raise, so duplicate ts in one
    payload counts as 2 accepted even though only 1 row exists in the DB.
    Step 4 may fix this by checking cursor.rowcount; until then, this
    test documents the current contract.
"""
from __future__ import annotations

import pytest

# Canonical timestamps / device ids used across tests
TS = "2026-07-20T14:00:00Z"
SYNCED_AT = "2026-07-20T14:00:00Z"
DEVICE_ID = "test-device"


def _payload(records: dict, battery_pct: int | None = None) -> dict:
    """Build a minimal valid MobileSyncRequest payload."""
    p = {
        "device_id": DEVICE_ID,
        "records": records,
        "synced_at": SYNCED_AT,
    }
    if battery_pct is not None:
        p["battery_pct"] = battery_pct
    return p


# ----------------------------------------------------------------------------
# Empty payload
# ----------------------------------------------------------------------------


def test_mobile_sync_empty_records(api_client, db):
    """Empty records dict: zero accepted, no errors, sync_log row still created."""
    response = api_client.post("/api/mobile/sync", json=_payload({}))
    assert response.status_code == 200
    assert response.json() == {"accepted": 0, "skipped": 0, "errors": []}

    # sync_log row is created even on empty payload (records_synced=0)
    with db.cursor() as cur:
        cur.execute("SELECT records_synced, status, current_step FROM sync_log")
        rows = cur.fetchall()
    assert len(rows) == 1
    assert rows[0] == (0, "ok", "phone sync")


# ----------------------------------------------------------------------------
# Point types — one record each
# ----------------------------------------------------------------------------


def test_mobile_sync_heart_rate(api_client, db):
    response = api_client.post("/api/mobile/sync", json=_payload({
        "heart_rate": [{"ts": TS, "bpm": 70}],
    }))
    assert response.status_code == 200
    assert response.json()["accepted"] == 1

    with db.cursor() as cur:
        cur.execute("SELECT source, bpm FROM raw_heart_rate")
        assert cur.fetchone() == ("phone", 70)
        assert cur.fetchone() is None


def test_mobile_sync_spo2(api_client, db):
    response = api_client.post("/api/mobile/sync", json=_payload({
        "spo2": [{"ts": TS, "spo2_pct": 97}],
    }))
    assert response.status_code == 200
    assert response.json()["accepted"] == 1

    with db.cursor() as cur:
        cur.execute("SELECT source, spo2_pct FROM raw_spo2")
        assert cur.fetchone() == ("phone", 97)


def test_mobile_sync_temperature(api_client, db):
    response = api_client.post("/api/mobile/sync", json=_payload({
        "temperature": [{"ts": TS, "temp_c": 36.50}],
    }))
    assert response.status_code == 200
    assert response.json()["accepted"] == 1

    with db.cursor() as cur:
        cur.execute("SELECT source, temp_c FROM raw_temperature")
        row = cur.fetchone()
        assert row[0] == "phone"
        assert float(row[1]) == 36.50


def test_mobile_sync_stress(api_client, db):
    response = api_client.post("/api/mobile/sync", json=_payload({
        "stress": [{"ts": TS, "stress_value": 30}],
    }))
    assert response.status_code == 200
    assert response.json()["accepted"] == 1

    with db.cursor() as cur:
        cur.execute("SELECT source, stress_value FROM raw_stress")
        assert cur.fetchone() == ("phone", 30)


def test_mobile_sync_steps_with_optional_fields(api_client, db):
    """steps has optional calories + distance columns — verify they flow through."""
    response = api_client.post("/api/mobile/sync", json=_payload({
        "steps": [{"ts": TS, "steps": 100, "calories": 5, "distance": 80}],
    }))
    assert response.status_code == 200
    assert response.json()["accepted"] == 1

    with db.cursor() as cur:
        cur.execute("SELECT source, steps, calories, distance FROM raw_steps")
        assert cur.fetchone() == ("phone", 100, 5, 80)


def test_mobile_sync_steps_without_optional_fields(api_client, db):
    """steps without calories/distance: NULL is acceptable, not an error."""
    response = api_client.post("/api/mobile/sync", json=_payload({
        "steps": [{"ts": TS, "steps": 100}],
    }))
    assert response.status_code == 200
    assert response.json()["accepted"] == 1

    with db.cursor() as cur:
        cur.execute("SELECT calories, distance FROM raw_steps")
        assert cur.fetchone() == (None, None)


# ----------------------------------------------------------------------------
# HRV — special conflict clause (ts, hrv_type, source)
# ----------------------------------------------------------------------------


def test_mobile_sync_hrv_with_explicit_type(api_client, db):
    """hrv_type defaults to 'composite' in the API; explicit value should pass through."""
    response = api_client.post("/api/mobile/sync", json=_payload({
        "hrv": [{"ts": TS, "hrv_value": 50.0, "hrv_type": "rmssd"}],
    }))
    assert response.status_code == 200
    assert response.json()["accepted"] == 1

    with db.cursor() as cur:
        cur.execute("SELECT source, hrv_type, hrv_value FROM raw_hrv")
        row = cur.fetchone()
        assert row[0] == "phone"
        assert row[1] == "rmssd"
        assert float(row[2]) == 50.0


def test_mobile_sync_hrv_default_type(api_client, db):
    """Missing hrv_type defaults to 'composite' per mobile_sync code."""
    response = api_client.post("/api/mobile/sync", json=_payload({
        "hrv": [{"ts": TS, "hrv_value": 50.0}],
    }))
    assert response.status_code == 200

    with db.cursor() as cur:
        cur.execute("SELECT hrv_type FROM raw_hrv")
        assert cur.fetchone()[0] == "composite"


# ----------------------------------------------------------------------------
# Sleep — special conflict clause (start_ts, stage, source), day-based
# ----------------------------------------------------------------------------


def test_mobile_sync_sleep_record(api_client, db):
    """raw_sleep has a different shape from point tables; verify it inserts cleanly."""
    response = api_client.post("/api/mobile/sync", json=_payload({
        "sleep": [{
            "day": "2026-07-20",
            "stage": "deep",
            "start_ts": "2026-07-20T01:00:00Z",
            "end_ts":   "2026-07-20T02:00:00Z",
            "duration_minutes": 60,
        }],
    }))
    assert response.status_code == 200
    assert response.json()["accepted"] == 1

    with db.cursor() as cur:
        cur.execute(
            "SELECT source, stage, duration_minutes FROM raw_sleep "
            "WHERE day = '2026-07-20'"
        )
        assert cur.fetchone() == ("phone", "deep", 60)


# ----------------------------------------------------------------------------
# Goals — singleton dict, not a list; no source column
# ----------------------------------------------------------------------------


def test_mobile_sync_goals_singleton(api_client, db):
    """goals is a single dict (not a list) and goes to ring_goals (no source col)."""
    response = api_client.post("/api/mobile/sync", json=_payload({
        "goals": {
            "steps_goal": 10000,
            "calories_goal": 2500,
            "distance_m_goal": 8000,
            "sport_min_goal": 30,
            "sleep_min_goal": 480,
        },
    }))
    assert response.status_code == 200
    assert response.json()["accepted"] == 1

    with db.cursor() as cur:
        cur.execute("SELECT steps_goal, sleep_min_goal FROM ring_goals")
        assert cur.fetchone() == (10000, 480)


# ----------------------------------------------------------------------------
# Duplicate-ts in same payload — pins the current per-attempt counting
# ----------------------------------------------------------------------------


def test_mobile_sync_duplicate_ts_in_one_payload_counts_both_accepted(api_client, db):
    """KNOWN QUIRK: `accepted` increments per attempt, not per row inserted.

    Two HR records at the same ts in one payload: the second hits
    ON CONFLICT (ts, source) DO NOTHING — 0 rows inserted, no exception,
    so `accepted += 1` still fires. Result: accepted=2, but only 1 row
    in the DB.

    Step 4 may fix this by checking cursor.rowcount. Until then, this
    test documents the contract.
    """
    response = api_client.post("/api/mobile/sync", json=_payload({
        "heart_rate": [
            {"ts": TS, "bpm": 70},
            {"ts": TS, "bpm": 72},  # same ts — second is dropped by ON CONFLICT
        ],
    }))
    assert response.status_code == 200
    body = response.json()
    assert body["accepted"] == 2  # current per-attempt behavior
    assert body["skipped"] == 0
    assert body["errors"] == []

    with db.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM raw_heart_rate WHERE source='phone'")
        assert cur.fetchone()[0] == 1  # only 1 row actually persisted


# ----------------------------------------------------------------------------
# Battery + sync_log auxiliary writes
# ----------------------------------------------------------------------------


def test_mobile_sync_battery_pct_writes_ring_status(api_client, db):
    """battery_pct in the request should write a ring_status row."""
    response = api_client.post("/api/mobile/sync", json=_payload(
        {"heart_rate": [{"ts": TS, "bpm": 70}]},
        battery_pct=72,
    ))
    assert response.status_code == 200

    with db.cursor() as cur:
        cur.execute("SELECT battery_pct FROM ring_status")
        assert cur.fetchone()[0] == 72


def test_mobile_sync_writes_sync_log_row_with_record_count(api_client, db):
    """sync_log should reflect the count of accepted records."""
    response = api_client.post("/api/mobile/sync", json=_payload({
        "heart_rate": [
            {"ts": "2026-07-20T14:00:00Z", "bpm": 70},
            {"ts": "2026-07-20T14:05:00Z", "bpm": 71},
            {"ts": "2026-07-20T14:10:00Z", "bpm": 72},
        ],
    }))
    assert response.status_code == 200
    assert response.json()["accepted"] == 3

    with db.cursor() as cur:
        cur.execute("SELECT records_synced, status FROM sync_log")
        row = cur.fetchone()
        assert row == (3, "ok")


def test_mobile_sync_battery_pct_none_skips_ring_status(api_client, db):
    """No battery_pct in request -> no ring_status row written."""
    response = api_client.post("/api/mobile/sync", json=_payload({}))
    assert response.status_code == 200

    with db.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM ring_status")
        assert cur.fetchone()[0] == 0


# ----------------------------------------------------------------------------
# Sync requests — analytics trigger
# ----------------------------------------------------------------------------


def test_mobile_sync_queues_analytics_request(api_client, db):
    """mobile_sync queues a sync_requests row so the poller runs analytics."""
    response = api_client.post("/api/mobile/sync", json=_payload({}))
    assert response.status_code == 200

    with db.cursor() as cur:
        cur.execute(
            "SELECT requested_by, status FROM sync_requests "
            "WHERE requested_by = 'phone-analytics'"
        )
        row = cur.fetchone()
        assert row is not None
        assert row == ("phone-analytics", "pending")
