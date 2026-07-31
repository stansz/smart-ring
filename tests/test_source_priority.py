"""Pure-function tests for collector.analytics.source_priority.

These tests cover the priority resolver without a DB. The resolver
is the single source of truth for "which source wins" — if it
returns the wrong answer, dedupe and the sleep scorer both produce
the wrong answer. Pin the contract here, exhaustively.
"""
from __future__ import annotations

import pytest

from collector.analytics.source_priority import (
    DEFAULT_PRIORITY,
    DEDUPE_METRICS,
    KNOWN_SOURCES,
    SOURCE_GARMIN,
    SOURCE_PHONE,
    SOURCE_RING,
    select_preferred_source,
    sources_to_drop,
)


# ----------------------------------------------------------------------------
# select_preferred_source: canonical cases
# ----------------------------------------------------------------------------


def test_ring_wins_when_present():
    """The canonical ring > garmin > phone case."""
    assert select_preferred_source({"ring", "garmin", "phone"}, "heart_rate") == "ring"


def test_garmin_wins_when_ring_absent():
    """If ring is missing, garmin is next."""
    assert select_preferred_source({"garmin", "phone"}, "heart_rate") == "garmin"


def test_phone_wins_when_only_phone_present():
    """Phone alone beats nothing."""
    assert select_preferred_source({"phone"}, "heart_rate") == "phone"


def test_empty_returns_none():
    """No sources at all → no preferred source (caller drops nothing)."""
    assert select_preferred_source(set(), "heart_rate") is None


def test_unknown_source_only_returns_none():
    """A source that isn't in the priority chain → no preferred source.

    Conservative: we don't know its quality, so we don't auto-pick it
    over known sources. Dedup leaves it alone, the scorer sees it.
    """
    assert select_preferred_source({"oura"}, "heart_rate") is None


def test_unknown_source_ignored_when_known_present():
    """If both unknown and known sources are present, known wins."""
    assert select_preferred_source({"oura", "ring"}, "heart_rate") == "ring"


# ----------------------------------------------------------------------------
# sources_to_drop: the inverse function
# ----------------------------------------------------------------------------


def test_sources_to_drop_keeps_only_preferred():
    """sources_to_drop returns everything except the preferred source."""
    assert sources_to_drop({"ring", "garmin", "phone"}, "heart_rate") == ("garmin", "phone")


def test_sources_to_drop_empty_when_single_source():
    """Single source → nothing to drop."""
    assert sources_to_drop({"ring"}, "heart_rate") == ()


def test_sources_to_drop_empty_when_no_known_sources():
    """All unknown sources → drop nothing (conservative)."""
    assert sources_to_drop({"oura"}, "heart_rate") == ()


def test_sources_to_drop_empty_when_none_present():
    """Empty input → empty output."""
    assert sources_to_drop(set(), "heart_rate") == ()


# ----------------------------------------------------------------------------
# DEFAULT_PRIORITY structure
# ----------------------------------------------------------------------------


def test_default_priority_covers_all_dedupe_metrics():
    """Every metric in DEDUPE_METRICS has a priority entry."""
    for metric in DEDUPE_METRICS:
        assert metric in DEFAULT_PRIORITY, f"missing priority for {metric}"


def test_default_priority_starts_with_ring():
    """Ring is highest priority in every metric (default privacy-preserving)."""
    for metric, chain in DEFAULT_PRIORITY.items():
        assert chain[0] == "ring", f"{metric} should have ring first, got {chain[0]}"


def test_default_priority_contains_all_known_sources():
    """Every default chain includes ring, garmin, and phone (in some order)."""
    for metric, chain in DEFAULT_PRIORITY.items():
        for src in (SOURCE_RING, SOURCE_GARMIN, SOURCE_PHONE):
            assert src in chain, f"{metric} missing {src} from {chain}"


def test_known_sources_is_a_frozenset():
    """KNOWN_SOURCES should be immutable so callers can't mutate it."""
    assert isinstance(KNOWN_SOURCES, frozenset)


def test_known_sources_contains_the_three_pillars():
    """The three known sources today: ring, garmin, phone."""
    assert KNOWN_SOURCES == frozenset({"ring", "garmin", "phone"})


# ----------------------------------------------------------------------------
# Custom priority_map (parameterized)
# ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "chain, expected",
    [
        # phone-first chain (unusual but valid)
        ((SOURCE_PHONE, SOURCE_RING, SOURCE_GARMIN), "phone"),
        # garmin-only chain
        ((SOURCE_GARMIN,), "garmin"),
        # garmin > ring (Garmin preferred for activity)
        ((SOURCE_GARMIN, SOURCE_RING), "garmin"),
    ],
)
def test_custom_priority_respected(chain, expected):
    """Custom priority_map overrides the default — used by per-metric
    source-preference logic (e.g. activity-window HR could prefer
    garmin over ring)."""
    custom = {"heart_rate": chain}
    assert select_preferred_source({"ring", "garmin", "phone"}, "heart_rate", custom) == expected


def test_custom_priority_for_unknown_metric_falls_back_to_empty():
    """If a metric isn't in the custom map, no source is preferred."""
    custom = {"foo": ("ring", "phone")}
    assert select_preferred_source({"ring"}, "heart_rate", custom) is None
