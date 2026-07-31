"""Garmin FIT file parser.

Parses .fit files dumped from a Garmin Forerunner 745 (via USB) and
emits structured records for ingestion into Postgres. Phase 1 scope:

- **Activity files** (`Garmin/Activity/*.fit`): full session + lap +
  record (trackpoint + HR) data. This is the main payload.
- **Monitoring b files** (`Garmin/Metrics/*.fit`): daily summaries
  (steps, HR, HRV, sleep, stress). Deferred — these use newer FIT
  SDK message types (global_id 229, 232, 281, 284, etc.) that
  ``fitparse``/``fitparser`` don't have profiles for. Can be added
  in Phase 1.5 by hardcoding the field-id→semantic mapping.
- **Sleep files** (`Garmin/Sleep/*.fit`): same constraint as Metrics.

Activity files use the standard FIT ``session``/``lap``/``record``
messages which all FIT parsers handle.

**Why Python (not Rust) for Phase 1:** faster to ship, ``fitparse`` is
mature, no compile cycle. The dedupe + analytics pipeline is already
Python. Phase 2 (Gadgetbridge BLE or private ongoing sync) is where
Rust earns its keep — a single binary running on the HTPC.

**Coordinate handling:** GPS coordinates come in as FIT "semicircles"
(sint32 where 1 = 180/2^31 degrees). We store the raw semicircles
in ``activity_trackpoints`` and convert to degrees at the API
boundary — this matches the FIT fidelity and avoids float precision
loss in storage.
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Iterator, Optional

from fitparse import FitFile

log = logging.getLogger(__name__)


# FIT sport enum → our activity_type strings. From the FIT SDK
# profile/Types.h sport enum. Only the ones we actually expect to
# see for the 745's user (per the Sport/ directory listing).
_SPORT_MAP: dict[str, str] = {
    "running": "running",
    "walking": "walking",
    "cycling": "cycling",
    "hiking": "hiking",
    "mountain_biking": "cycling",
    "road_biking": "cycling",
    "gravel_cycling": "cycling",
    "indoor_cycling": "cycling",
    "trail_running": "running",
    "treadmill_running": "running",
    "track_running": "running",
    "ultra_running": "running",
    "virtual_run": "running",
    "swimming": "swimming",
    "open_water": "swimming",
    "lap_swimming": "swimming",
    "hike": "hiking",
    "resort_skiing_snowboarding": "skiing",
    "backcountry_skiing": "skiing",
    "snowboarding": "snowboarding",
    "snowshoeing": "snowshoeing",
    "rowing": "rowing",
    "indoor_rowing": "rowing",
    "elliptical": "elliptical",
    "stair_climbing": "elliptical",
    "yoga": "yoga",
    "pilates": "yoga",
    "strength_training": "strength_training",
    "cardio_training": "cardio_training",
    "hiit": "hiit",
    "breathwork": "breathwork",
    "kayaking": "kayaking",
    "sup": "kayaking",
    "tennis": "tennis",
    "pickleball": "pickleball",
    "padel": "padel",
    "bouldering": "climbing",
    "climbing": "climbing",
    "indoor_climbing": "climbing",
    "floor_climb": "climbing",
    "generic": "other",
    "other": "other",
}


def _sport_label(msg) -> tuple[str, str]:
    """Return (activity_type, sub_sport) from a session/lap message."""
    sport = msg.get_value("sport")
    sub = msg.get_value("sub_sport")
    sport_str = str(sport) if sport is not None else "generic"
    sub_str = str(sub) if sub is not None else "generic"
    return _SPORT_MAP.get(sport_str, "other"), sub_str


@dataclass
class ParsedTrackpoint:
    """One second-resolution record from a FIT record message."""
    ts: datetime
    lat_semicircles: Optional[int] = None
    lon_semicircles: Optional[int] = None
    altitude_m: Optional[float] = None
    hr: Optional[int] = None
    cadence: Optional[int] = None
    speed_mps: Optional[float] = None
    distance_m: Optional[float] = None
    temperature_c: Optional[int] = None


@dataclass
class ParsedLap:
    """One lap from a FIT lap message."""
    lap_index: int
    start_ts: datetime
    end_ts: Optional[datetime]
    duration_s: int
    timer_time_s: Optional[int]
    distance_m: Optional[float]
    calories: Optional[int]
    avg_hr: Optional[int]
    max_hr: Optional[int]
    avg_cadence: Optional[int]
    max_cadence: Optional[int]
    avg_speed_mps: Optional[float]
    max_speed_mps: Optional[float]
    elevation_gain_m: Optional[int]
    elevation_loss_m: Optional[int]


@dataclass
class ParsedActivity:
    """One full activity session (1 FIT file → 1 row in `activities`)."""
    start_ts: datetime
    end_ts: Optional[datetime]
    activity_type: str
    sub_sport: str
    duration_s: Optional[int]
    timer_time_s: Optional[int]
    distance_m: Optional[float]
    calories: Optional[int]
    avg_hr: Optional[int]
    max_hr: Optional[int]
    avg_cadence: Optional[int]
    max_cadence: Optional[int]
    avg_speed_mps: Optional[float]
    max_speed_mps: Optional[float]
    elevation_gain_m: Optional[int]
    elevation_loss_m: Optional[int]
    avg_temperature_c: Optional[float]
    training_effect_aerobic: Optional[float]
    training_effect_anaerobic: Optional[float]
    total_strides: Optional[int]
    avg_vertical_oscillation_mm: Optional[float]
    avg_ground_contact_time_ms: Optional[int]
    avg_stride_length_cm: Optional[float]
    laps: list[ParsedLap] = field(default_factory=list)
    trackpoints: list[ParsedTrackpoint] = field(default_factory=list)
    record_count: int = 0


def _i(v) -> Optional[int]:
    if v is None: return None
    if isinstance(v, bool): return int(v)
    if isinstance(v, (int, float)): return int(v)
    return None


def _f(v) -> Optional[float]:
    if v is None: return None
    if isinstance(v, bool): return float(v)
    if isinstance(v, (int, float)): return float(v)
    return None


def _semirings(v) -> Optional[int]:
    """FIT coordinates are sint32 semicircles. fitparse decodes them
    to int (or float if the value happens to land on a .5 boundary
    — though that shouldn't happen for a 32-bit int). Cast safely."""
    return _i(v)


def _is_activity_file(path: Path) -> bool:
    """Cheap pre-check: skip Settings, Sports, Workouts, etc."""
    name = path.parent.name.lower()
    return name in ("activity", "summary") or path.parent.parent.name.lower() in ("activity", "summary")


def parse_fit_file(path: Path) -> Optional[ParsedActivity]:
    """Parse a single .fit file. Returns None for non-activity files.

    The 745 produces a few kinds of files; we only want Activity +
    Summary. Other types (Settings, Sports, Workouts, Metrics,
    Sleep) are silently skipped — they'll be handled in later phases.
    """
    if not _is_activity_file(path):
        return None

    try:
        fit = FitFile(str(path))
    except Exception as e:
        log.warning(f"  {path.name}: failed to open ({e})")
        return None

    # First pass: collect the session + laps.
    session_msg = None
    laps: list[ParsedLap] = []
    for msg in fit.get_messages():
        if msg.name == "session":
            session_msg = msg
        elif msg.name == "lap":
            laps.append(_parse_lap(msg))

    if session_msg is None:
        log.warning(f"  {path.name}: no session message, skipping")
        return None

    # Second pass: trackpoints + HR. Trackpoint + HR come from the
    # same `record` message; we emit them separately because the
    # activity_hr table is 1Hz-HR-only (lighter, no GPS).
    trackpoints: list[ParsedTrackpoint] = []
    for msg in fit.get_messages("record"):
        tp = _parse_record(msg)
        if tp is not None:
            trackpoints.append(tp)

    activity = _parse_session(session_msg, laps, trackpoints, len(trackpoints))
    return activity


def _parse_lap(msg) -> ParsedLap:
    return ParsedLap(
        lap_index=_i(msg.get_value("message_index")) or 0,
        start_ts=msg.get_value("start_time"),
        end_ts=msg.get_value("timestamp"),
        duration_s=_i(msg.get_value("total_elapsed_time")) or 0,
        timer_time_s=_i(msg.get_value("total_timer_time")),
        distance_m=_f(msg.get_value("total_distance")),
        calories=_i(msg.get_value("total_calories")),
        avg_hr=_i(msg.get_value("avg_heart_rate")),
        max_hr=_i(msg.get_value("max_heart_rate")),
        avg_cadence=_i(msg.get_value("avg_cadence")),
        max_cadence=_i(msg.get_value("max_cadence")),
        avg_speed_mps=_f(msg.get_value("enhanced_avg_speed")) or _f(msg.get_value("avg_speed")),
        max_speed_mps=_f(msg.get_value("enhanced_max_speed")) or _f(msg.get_value("max_speed")),
        elevation_gain_m=_i(msg.get_value("total_ascent")),
        elevation_loss_m=_i(msg.get_value("total_descent")),
    )


def _parse_record(msg) -> Optional[ParsedTrackpoint]:
    ts = msg.get_value("timestamp")
    if ts is None:
        return None
    return ParsedTrackpoint(
        ts=ts,
        lat_semicircles=_semirings(msg.get_value("position_lat")),
        lon_semicircles=_semirings(msg.get_value("position_long")),
        altitude_m=_f(msg.get_value("enhanced_altitude")) or _f(msg.get_value("altitude")),
        hr=_i(msg.get_value("heart_rate")),
        cadence=_i(msg.get_value("cadence")),
        speed_mps=_f(msg.get_value("enhanced_speed")) or _f(msg.get_value("speed")),
        distance_m=_f(msg.get_value("distance")),
        temperature_c=_i(msg.get_value("temperature")),
    )


def _parse_session(
    msg,
    laps: list[ParsedLap],
    trackpoints: list[ParsedTrackpoint],
    record_count: int,
) -> ParsedActivity:
    activity_type, sub_sport = _sport_label(msg)
    return ParsedActivity(
        start_ts=msg.get_value("start_time"),
        end_ts=msg.get_value("timestamp"),
        activity_type=activity_type,
        sub_sport=sub_sport,
        duration_s=_i(msg.get_value("total_elapsed_time")),
        timer_time_s=_i(msg.get_value("total_timer_time")),
        distance_m=_f(msg.get_value("total_distance")),
        calories=_i(msg.get_value("total_calories")),
        avg_hr=_i(msg.get_value("avg_heart_rate")),
        max_hr=_i(msg.get_value("max_heart_rate")),
        avg_cadence=_i(msg.get_value("avg_cadence")),
        max_cadence=_i(msg.get_value("max_cadence")),
        avg_speed_mps=_f(msg.get_value("enhanced_avg_speed")) or _f(msg.get_value("avg_speed")),
        max_speed_mps=_f(msg.get_value("enhanced_max_speed")) or _f(msg.get_value("max_speed")),
        elevation_gain_m=_i(msg.get_value("total_ascent")),
        elevation_loss_m=_i(msg.get_value("total_descent")),
        avg_temperature_c=_f(msg.get_value("avg_temperature")),
        training_effect_aerobic=_f(msg.get_value("total_training_effect")),
        training_effect_anaerobic=_f(msg.get_value("total_anaerobic_training_effect")),
        total_strides=_i(msg.get_value("total_strides")),
        avg_vertical_oscillation_mm=_f(msg.get_value("avg_vertical_oscillation")),
        avg_ground_contact_time_ms=_i(msg.get_value("avg_ground_contact_time")),
        avg_stride_length_cm=_f(msg.get_value("avg_step_length")),
        laps=laps,
        trackpoints=trackpoints,
        record_count=record_count,
    )


# ─── File discovery + hashing ──────────────────────────────────────────────


def file_hash(path: Path) -> str:
    """SHA-256 of a FIT file. Idempotency key — re-ingesting the same
    file (even at a different path) is a no-op."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def discover_fit_files(directory: Path) -> Iterator[Path]:
    """Yield Activity + Summary .fit files under ``directory``.

    Walks the directory recursively but only returns files in
    Activity/ or Summary/ subdirs (these contain the structured
    sport sessions; other dirs hold settings/sports/workouts/metrics
    which are out of Phase 1 scope).
    """
    if not directory.exists():
        return
    for path in sorted(directory.rglob("*.fit")):
        if _is_activity_file(path):
            yield path
    for path in sorted(directory.rglob("*.FIT")):
        if _is_activity_file(path):
            yield path
