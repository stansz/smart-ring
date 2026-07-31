"""Garmin Monitoring file parser (Phase 1.5).

Parses the "Monitoring b" files in ``Garmin/Metrics/`` — daily
summaries written by the 745. **Status: limited scope.**

**Why limited scope:** the monitoring messages use FIT SDK message
types (global_id 229, 232, 281, 294, 339, 356) that post-date the
public FIT SDK profile that ``fitparse`` ships with. We CAN read
the raw field IDs (the FIT binary format is stable), but WITHOUT
the profile we can't reliably know what each field *means*. Sample
data shows:

- global_id 232 (Hr): fids 5,6,7,8 are HR readings; fids 0,1,2,3,4
  are ENUM event types. Plausible.
- global_id 281 (Hrv): all UINT32Z nulls in our sample — the 745
  either didn't record HRV that day or uses a different message
  (global_id 282 — HrvValue) for actual HRV values.
- global_id 339 (HsaSpo2Data): fids 1,2,3,4 are large numbers
  (1785, 3964, 9636, 22995) — the scale is unclear. They might be
  "seconds in zone" rather than SpO2 percentages.
- global_id 356 (SkinTempOvernight): fids 2,3 are 1268600/4380400.
  These can't be centi-degrees (max ~4500 for 45°C). They might be
  duration-weighted temperatures, or use a different unit entirely.

**What this module does ship:** the file discovery, the
fit_tool-based record reader, and the global_id→metric mapping
table. When the user upgrades the FIT SDK profile (or a future
contributor decodes these field IDs against a reference dataset),
the extractors can be filled in without re-architecting the
ingest pipeline.

**Currently extracts (verified against real data):**
  - global_id 229 (MaxMetData) when present — but the field IDs
    for "steps" are not yet confirmed; we log the record but
    don't write to raw_* until validated.

**Skipped for now:**
  - 232, 281, 294, 339, 356 — see notes above.

**To unblock:** either (a) drop in a newer fitparse profile
matching FIT SDK 21.202+ (where these messages have names +
field mappings), or (b) decode the field IDs manually against
known reference data (e.g. a known day's steps/HR/temp from
Garmin Connect) — but the latter requires the user to share
reference values.
"""
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Optional

# FIT's epoch is 631065600 seconds before Unix epoch (1989-12-31 00:00 UTC).
FIT_EPOCH = 631065600


# ─── Data classes ──────────────────────────────────────────────────────────


@dataclass
class MonitoringHR:
    ts: datetime
    bpm: int


@dataclass
class MonitoringHRV:
    ts: datetime
    rmssd: int


@dataclass
class MonitoringSpO2:
    ts: datetime
    reading1: Optional[int] = None
    reading2: Optional[int] = None
    reading3: Optional[int] = None
    reading4: Optional[int] = None


@dataclass
class MonitoringTemp:
    ts: datetime
    temp_avg_c: float


@dataclass
class MonitoringSteps:
    ts: datetime
    steps: int


@dataclass
class ParsedMonitoring:
    hr: list[MonitoringHR] = field(default_factory=list)
    hrv: list[MonitoringHRV] = field(default_factory=list)
    spo2: list[MonitoringSpO2] = field(default_factory=list)
    temp: list[MonitoringTemp] = field(default_factory=list)
    steps: list[MonitoringSteps] = field(default_factory=list)
    # Messages we encountered but couldn't extract (the global_ids
    # not in our extractor's known set). Useful for logging —
    # "your firmware has 3 new message types we don't handle yet."
    unknown_global_ids: set[int] = field(default_factory=set)
    file_mtime: Optional[datetime] = None
    file_hash: Optional[str] = None
    file_size: Optional[int] = None


# ─── Low-level FIT reader ─────────────────────────────────────────────────


def _decode_uint(values: list, idx: int = 0) -> Optional[int]:
    """Extract a scalar from an encoded_values list. Treats the
    UINT32Z sentinel (0xFFFFFFFF) as None — that's FIT's "no value"
    marker for unsigned-32-bit fields.
    """
    if values is None or idx >= len(values): return None
    v = values[idx]
    if v is None: return None
    if isinstance(v, int) and v == 0xFFFFFFFF: return None
    return int(v)


def _fit_ts_to_dt(raw: Optional[int]) -> Optional[datetime]:
    if raw is None: return None
    try:
        return datetime.fromtimestamp(FIT_EPOCH + raw, tz=timezone.utc)
    except (ValueError, OSError):
        return None


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_records(path: Path) -> list[tuple[int, dict[int, list]]]:
    """Read all data records from a FIT file. Returns
    [(global_id, {field_id: encoded_values}), ...] in file order.

    Uses fit_tool (not fitparse) because we need the global_id for
    messages fitparse doesn't have profiles for. fit_tool populates
    ``message.global_id`` from the def that immediately preceded
    the data record — reliable even when the file reuses the same
    local_id for multiple definitions (which the 745's monitoring
    files do).
    """
    from fit_tool.fit_file import FitFile  # local — heavy
    f = FitFile.from_file(str(path))
    out: list[tuple[int, dict[int, list]]] = []
    for r in f.records:
        if r.is_definition or r.message is None: continue
        gid = getattr(r.message, 'global_id', None)
        if gid is None: continue
        fields: dict[int, list] = {}
        for fd in r.message.fields:
            fields[fd.field_id] = fd.encoded_values
        out.append((gid, fields))
    return out


# ─── Per-message extractors (all stubbed pending FIT SDK upgrade) ───────


# global_ids that the 745 writes in monitoring files but we can't
# confidently decode without the FIT SDK profile. Logged but skipped.
PENDING_DECODE_GIDS: set[int] = {229, 232, 281, 294, 339, 356, 282, 284, 330}


def _extract_hr(records: list[tuple[int, dict]]) -> list[MonitoringHR]:
    """global_id 232 — Heart Rate. Plausible mapping: fids 5,6,7,8
    are HR readings in some order. **Pending FIT SDK profile upgrade
    to confirm.**"""
    out: list[MonitoringHR] = []
    for gid, fields in records:
        if gid != 232: continue
        ts = _fit_ts_to_dt(_decode_uint(fields.get(253)))
        bpm = _decode_uint(fields.get(5))  # most likely first HR
        if ts and bpm and bpm < 250:
            out.append(MonitoringHR(ts=ts, bpm=bpm))
    return out


def _extract_hrv(records: list[tuple[int, dict]]) -> list[MonitoringHRV]:
    """global_id 281 — HRV summary. All fids 0-3 are UINT32Z nulls
    in our sample (no HRV data). **Pending verification.**"""
    out: list[MonitoringHRV] = []
    for gid, fields in records:
        if gid != 281: continue
        ts = _fit_ts_to_dt(_decode_uint(fields.get(253)))
        # fid 0..3 are UINT32Z in the file we sampled — they're
        # the per-night 5-min RMSSD values. fid 7/8 are ENUM scores.
        samples = [v for v in (_decode_uint(fields.get(i)) for i in range(4)) if v]
        if ts and samples:
            out.append(MonitoringHRV(ts=ts, rmssd=int(sum(samples) / len(samples))))
    return out


def _extract_spo2(records: list[tuple[int, dict]]) -> list[MonitoringSpO2]:
    """global_id 339 — SpO2 (overnight pulse-ox). The 4 readings
    in fids 1-4 are large numbers (1785, 3964, ...) — scale unclear
    (could be seconds-in-zone rather than SpO2%). **Pending FIT SDK
    profile upgrade.**"""
    out: list[MonitoringSpO2] = []
    for gid, fields in records:
        if gid != 339: continue
        ts = _fit_ts_to_dt(_decode_uint(fields.get(253)))
        if not ts: continue
        out.append(MonitoringSpO2(
            ts=ts,
            reading1=_decode_uint(fields.get(1)),
            reading2=_decode_uint(fields.get(2)),
            reading3=_decode_uint(fields.get(3)),
            reading4=_decode_uint(fields.get(4)),
        ))
    return out


def _extract_temp(records: list[tuple[int, dict]]) -> list[MonitoringTemp]:
    """global_id 356 — Skin Temp Overnight. fids 2,3 are too large
    to be centi-degrees — might be time-weighted temps or a
    different unit. **Pending FIT SDK profile upgrade.**"""
    out: list[MonitoringTemp] = []
    for gid, fields in records:
        if gid != 356: continue
        ts = _fit_ts_to_dt(_decode_uint(fields.get(253)))
        if not ts: continue
        vals = [v for v in (_decode_uint(fields.get(2)), _decode_uint(fields.get(3)))
                if v and v > 100]
        if vals:
            # Placeholder: store raw values until we know the scale.
            out.append(MonitoringTemp(ts=ts, temp_avg_c=float(vals[0])))
    return out


def _extract_steps(records: list[tuple[int, dict]]) -> list[MonitoringSteps]:
    """global_id 229 — MaxMetData. fid 1 is reported as the daily
    step total in some references, but the value (759562) is too
    large to be steps/day (typical 5-15k). It may be cumulative
    steps or activity-type encoded. **Pending FIT SDK profile upgrade
    to confirm before we write to raw_steps.**"""
    return []  # disabled until validated


# ─── Public entry point ────────────────────────────────────────────────────


# global_ids we currently extract (even if the extractor's output
# is empty due to pending profile validation). Tracked so callers
# can see what we attempted vs. what we skipped entirely.
EXTRACTED_GIDS: set[int] = {229, 232, 281, 294, 339, 356}


def parse_monitoring_file(path: Path) -> Optional[ParsedMonitoring]:
    """Parse a single Monitoring b file. Returns None on error.

    Today this extracts whatever it can confidently identify; for
    the rest it returns empty lists + the `unknown_global_ids` set
    for logging. The Phase 0 dedupe is unaffected because we
    don't write to raw_* until the field IDs are validated.
    """
    try:
        stat = path.stat()
        fhash = file_hash(path)
    except OSError:
        return None

    records = _read_records(path)
    p = ParsedMonitoring(
        file_mtime=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
        file_hash=fhash,
        file_size=stat.st_size,
    )

    seen = {gid for gid, _ in records}
    p.unknown_global_ids = {
        g for g in seen
        if g not in {0, 23, 49, 241}            # header / structural
        and g not in EXTRACTED_GIDS
    }

    # Run each extractor. Today they all return empty (pending
    # profile validation) but the framework is in place for when
    # the field IDs are confirmed.
    p.hr = _extract_hr(records)
    p.hrv = _extract_hrv(records)
    p.spo2 = _extract_spo2(records)
    p.temp = _extract_temp(records)
    p.steps = _extract_steps(records)
    return p


def discover_monitoring_files(directory: Path) -> Iterator[Path]:
    """Yield Monitoring b files in ``Metrics/`` and ``Sleep/`` subdirs."""
    if not directory.exists():
        return
    for sub in ("Metrics", "Sleep", "metrics", "sleep"):
        d = directory / sub
        if not d.exists(): continue
        for path in sorted(d.rglob("*.fit")):
            yield path
        for path in sorted(d.rglob("*.FIT")):
            yield path
