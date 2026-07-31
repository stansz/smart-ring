"""Source priority resolver — single source of truth for which device wins.

When two devices report the same physical measurement (HR at 14:30, sleep
for 2026-07-20, etc.), we need a deterministic answer for *which* one
the analytics pipeline should consume. The default order is
``ring > garmin > phone`` for metrics where the ring is the canonical
collector, with overrides for cases where another source is genuinely
better (e.g. activity-window HR — Garmin's Elevate v3 is more accurate
during movement than the ring's PPG).

**Why a separate module:** the resolver is a *pure function over a small
set of inputs* (the set of sources present at a slot + the metric
being scored). It is fully testable without a DB and is the single
place to read or change the policy. The dedupe SQL and the sleep
scorer's source filter both delegate to this module.

**Why not a view:** a materialized ``preferred_*`` view would require
every scorer to switch to a new table name, and would complicate the
data-quality table (which still wants per-source freshness). Deleting
non-preferred rows pre-score preserves the scorers' existing
``FROM raw_*`` queries unchanged.
"""
from __future__ import annotations

from typing import Dict, FrozenSet, Iterable, Optional

# Public source identifiers (the strings that appear in raw_*.source).
SOURCE_RING = "ring"
SOURCE_GARMIN = "garmin"
SOURCE_PHONE = "phone"

# All known sources. The dedupe loop intersects this against the
# sources actually present at a given ts, so adding a fourth source
# (e.g. ``oura``) is a one-line change in source_priority plus a new
# entry in DEFAULT_PRIORITY.
KNOWN_SOURCES: FrozenSet[str] = frozenset({SOURCE_RING, SOURCE_GARMIN, SOURCE_PHONE})

# Per-metric priority chain. First element = highest priority.
#
# Defaults follow the rules in docs/GARMIN_INTEGRATION_RESEARCH.md §9.3:
#   - Sleep / overnight HR / continuous skin temp → ring (24/7 wear)
#   - Activity-window HR / training load → garmin (Elevate v3, GPS)
#   - Steps → max of sources (handled at score time, not dedup; here
#     we just pick one — garmin activity, ring daily, phone fallback)
#   - Stress → ring (Garmin's proprietary score is comparable but not
#     identical; ring's 0-100 scale is what the stress scorer expects)
#   - SpO2 / HRV → ring (continuous, more samples)
#
# These chains are consulted by dedupe_sources() for point tables
# (HR, SpO2, temp, HRV, steps, stress) and by sleep.compute_sleep_quality
# for the day-level sleep table.
DEFAULT_PRIORITY: Dict[str, tuple] = {
    "heart_rate":   (SOURCE_RING, SOURCE_GARMIN, SOURCE_PHONE),
    "spo2":         (SOURCE_RING, SOURCE_GARMIN, SOURCE_PHONE),
    "temperature":  (SOURCE_RING, SOURCE_GARMIN, SOURCE_PHONE),
    "hrv":          (SOURCE_RING, SOURCE_GARMIN, SOURCE_PHONE),
    "steps":        (SOURCE_RING, SOURCE_GARMIN, SOURCE_PHONE),
    "stress":       (SOURCE_RING, SOURCE_GARMIN, SOURCE_PHONE),
    "sleep":        (SOURCE_RING, SOURCE_GARMIN, SOURCE_PHONE),
}

# All metrics covered by the dedupe loop. Kept in one place so dedupe.py
# and the tests can both iterate the same set without drift.
DEDUPE_METRICS: tuple = (
    "heart_rate", "spo2", "temperature", "hrv", "steps", "stress", "sleep",
)


def select_preferred_source(
    present_sources: Iterable[str],
    metric: str,
    priority_map: Optional[Dict[str, tuple]] = None,
) -> Optional[str]:
    """Return the highest-priority source from ``present_sources`` for ``metric``.

    Pure function. Returns ``None`` if no candidate matches a known
    priority entry (caller decides whether to treat that as "no
    preferred source — keep everything" or as an error; in the dedupe
    loop it means "nothing to drop").

    >>> select_preferred_source({"ring", "phone"}, "heart_rate")
    'ring'
    >>> select_preferred_source({"garmin", "phone"}, "heart_rate")
    'garmin'
    >>> select_preferred_source({"phone"}, "heart_rate")
    'phone'
    >>> select_preferred_source(set(), "heart_rate") is None
    True
    """
    chain = (priority_map or DEFAULT_PRIORITY).get(metric, ())
    for source in chain:
        if source in present_sources:
            return source
    return None


def sources_to_drop(
    present_sources: Iterable[str],
    metric: str,
    priority_map: Optional[Dict[str, tuple]] = None,
) -> tuple:
    """Return the subset of ``present_sources`` that should be deleted.

    Inverse of :func:`select_preferred_source` — everything present
    that is *not* the preferred source. Returned as a tuple (not set)
    in priority order (highest-priority drops first), so the SQL
    builder can use it as ``AND source IN (...)`` reliably and the
    output is deterministic for tests.

    If no known source is present, returns an empty tuple (nothing to
    drop). If the preferred source is missing but others are present,
    we drop nothing — better to let the scorer see multiple sources
    than to silently zero out the only available data.
    """
    preferred = select_preferred_source(present_sources, metric, priority_map)
    if preferred is None:
        return ()
    chain = (priority_map or DEFAULT_PRIORITY).get(metric, ())
    return tuple(s for s in chain if s in present_sources and s != preferred)
