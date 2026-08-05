"""Tests for the Garmin Monitoring file parser (Phase 1.5).

The Monitoring b files (Garmin/Metrics/) use FIT SDK message types
that post-date the public FIT SDK profile. The parser framework
is in place but the per-message-type extractors are stubbed
pending either (a) a FIT SDK profile upgrade, or (b) reference
data decoding.

What this test file pins:
- File discovery walks Metrics/ + Sleep/ subdirs
- file_hash is deterministic
- parse_monitoring_file returns a ParsedMonitoring with
  correct metadata (mtime, size, hash)
- The file_id global_ids (0, 23, 49) and MonitoringInfo (241)
  are not in unknown_global_ids
- PENDING_DECODE_GIDS are correctly tracked as unknown
- The framework returns empty lists for now (the extractors
  are stubbed) — this is the contract a future contributor
  will fill in
"""
from __future__ import annotations

from pathlib import Path

import pytest

from collector.garmin.monitoring import (
    EXTRACTED_GIDS,
    PENDING_DECODE_GIDS,
    ParsedMonitoring,
    discover_monitoring_files,
    file_hash,
    parse_monitoring_file,
)


REAL_GARMIN_DIR = Path("/opt/smart-ring/data/garmin/raw/manual/GARMIN")
pytestmark = pytest.mark.skipif(
    not REAL_GARMIN_DIR.exists(),
    reason=f"real Garmin dump not present at {REAL_GARMIN_DIR}",
)


# ─── File discovery ──────────────────────────────────────────────────────


def test_discover_finds_metrics_files():
    files = list(discover_monitoring_files(REAL_GARMIN_DIR))
    metrics = [p for p in files if "/metrics/" in str(p).lower()]
    assert len(metrics) > 0, "should find at least one metrics file"


def test_discover_finds_sleep_files():
    files = list(discover_monitoring_files(REAL_GARMIN_DIR))
    sleep = [p for p in files if "/sleep/" in str(p).lower()]
    # Only 1 sleep file in our dump
    assert len(sleep) >= 1


def test_discover_skips_activity_files():
    """The monitoring parser is for daily summaries, not activities."""
    files = list(discover_monitoring_files(REAL_GARMIN_DIR))
    activity = [p for p in files if "/activity/" in str(p).lower()]
    assert len(activity) == 0


def test_discover_handles_missing_directory(tmp_path):
    """If the directory doesn't exist, returns empty iterator (no error)."""
    files = list(discover_monitoring_files(tmp_path / "nope"))
    assert files == []


# ─── file_hash ────────────────────────────────────────────────────────────


def test_file_hash_is_deterministic():
    """Same file → same hash, always."""
    f = next(REAL_GARMIN_DIR.glob("Metrics/*.fit"))
    h1 = file_hash(f)
    h2 = file_hash(f)
    assert h1 == h2
    assert len(h1) == 64  # sha256 hex digest


# ─── parse_monitoring_file ───────────────────────────────────────────────


def test_parse_returns_pdataclass():
    """The parser returns a ParsedMonitoring (not None) for a valid file."""
    f = REAL_GARMIN_DIR / "Metrics" / "G6U00141.fit"  # the file with HR/HRV/SpO2
    result = parse_monitoring_file(f)
    assert result is not None
    assert isinstance(result, ParsedMonitoring)


def test_parse_captures_file_metadata():
    """The result includes mtime, size, hash from the filesystem."""
    f = REAL_GARMIN_DIR / "Metrics" / "G6U00141.fit"
    stat = f.stat()
    result = parse_monitoring_file(f)
    assert result.file_size == stat.st_size
    assert result.file_hash is not None
    assert result.file_mtime is not None


def test_parse_returns_none_for_missing_file():
    """Missing file → None (not exception)."""
    result = parse_monitoring_file(REAL_GARMIN_DIR / "Metrics" / "does-not-exist.fit")
    assert result is None


def test_parse_does_not_include_header_global_ids_in_unknown():
    """file_id (0), file_creator (49), device_info (23), and
    MonitoringInfo (241) are structural/header — they should
    not appear in unknown_global_ids (even though we don't
    extract them)."""
    f = REAL_GARMIN_DIR / "Metrics" / "G6U00141.fit"
    result = parse_monitoring_file(f)
    assert result is not None
    assert 0 not in result.unknown_global_ids
    assert 23 not in result.unknown_global_ids
    assert 49 not in result.unknown_global_ids
    assert 241 not in result.unknown_global_ids


def test_parse_extracts_known_metrics_when_present():
    """When the file has global_id 232 (Hr) the parser attempts
    to extract HR. The actual values may be empty if the HR
    readings are sentinels (UINT32Z), but the extractor runs
    and returns a list."""
    f = REAL_GARMIN_DIR / "Metrics" / "G6U00141.fit"  # has 232
    result = parse_monitoring_file(f)
    assert result is not None
    assert isinstance(result.hr, list)
    assert isinstance(result.hrv, list)
    assert isinstance(result.spo2, list)
    assert isinstance(result.temp, list)
    assert isinstance(result.steps, list)


def test_parse_logs_unknown_global_ids():
    """Global IDs in the file that aren't in our extracted-set
    show up in unknown_global_ids (for future expansion)."""
    # G6U00141.fit has 232, 281, 294, 339, 356 (all in EXTRACTED_GIDS)
    # — no unknowns expected
    f = REAL_GARMIN_DIR / "Metrics" / "G6U00141.fit"
    result = parse_monitoring_file(f)
    assert result is not None
    assert result.unknown_global_ids == set()


def test_parse_handles_step_file():
    """Files with global_id 229 (MaxMetData with steps) parse
    cleanly even though the steps extractor is stubbed today."""
    # G7600158.fit has 229
    f = REAL_GARMIN_DIR / "Metrics" / "G7600158.fit"
    result = parse_monitoring_file(f)
    assert result is not None
    # Steps extractor is stubbed (returns []) — see module docstring
    assert result.steps == []


def test_parse_handles_sleep_file():
    """The one Sleep file in our dump parses without error."""
    sleep_files = list((REAL_GARMIN_DIR / "Sleep").glob("*.fit"))
    if not sleep_files:
        pytest.skip("no sleep files in dump")
    result = parse_monitoring_file(sleep_files[0])
    assert result is not None


# ─── Module-level constants ──────────────────────────────────────────────


def test_pending_decode_gids_set_is_well_known():
    """PENDING_DECODE_GIDS lists the global_ids we know are in the
    745's monitoring files but can't decode yet. If a new global_id
    appears in a future firmware dump, the parser's
    unknown_global_ids will surface it and a future contributor
    can add it here + write the extractor."""
    expected = {232, 281, 294, 339, 356, 282, 284, 330}
    assert expected.issubset(PENDING_DECODE_GIDS)


def test_extracted_gids_subset_of_pending():
    """Every global_id we extract should be in PENDING_DECODE_GIDS
    (so we have a single place to add new ones)."""
    for gid in EXTRACTED_GIDS:
        assert gid in PENDING_DECODE_GIDS, (
            f"global_id {gid} is in EXTRACTED_GIDS but not PENDING_DECODE_GIDS"
        )
