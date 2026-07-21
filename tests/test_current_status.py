"""Pure-function tests for the Current Status formula.

Boundary cases for each component helper + the weighted aggregate +
the vibe label mapping. No DB needed.
"""
from __future__ import annotations

import math

import pytest

from collector.analytics.current_status import (
    DEFAULT_WEIGHTS,
    hrv_component_score,
    hr_component_score,
    status_label,
    stress_component_score,
    trend_component_score,
    weighted_score,
)


# ----------------------------------------------------------------------------
# HRV component (z-score -> 0-100)
# ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "z, expected",
    [
        # Below -1.0: floor at 10
        (-3.0, 10.0),
        (-1.5, 10.0),
        (-1.0, 25.0),     # >= -1.0 boundary
        (-0.7, 25.0),
        (-0.5, 40.0),     # >= -0.5 boundary
        (-0.2, 40.0),
        (0.0, 55.0),      # >= 0.0 boundary (exactly at baseline)
        (0.3, 55.0),
        (0.5, 70.0),      # >= 0.5
        (0.9, 70.0),
        (1.0, 80.0),      # >= 1.0
        (1.3, 80.0),
        (1.5, 90.0),      # >= 1.5
        (1.8, 90.0),
        (2.0, 95.0),      # >= 2.0
        (2.9, 95.0),
        (3.0, 100.0),     # >= 3.0
        (5.0, 100.0),     # ceiling
    ],
)
def test_hrv_component_score(z: float, expected: float) -> None:
    assert math.isclose(hrv_component_score(z), expected, rel_tol=1e-9)


def test_hrv_component_score_none() -> None:
    assert hrv_component_score(None) is None


# ----------------------------------------------------------------------------
# HR component (delta bpm from RHR -> 0-100)
# ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "delta, expected",
    [
        (-10, 100.0),  # below baseline (asleep?) — clamped to 100
        (0,   100.0),  # exactly at RHR — fully at rest
        (10,  80.0),   # 10 bpm over
        (25,  50.0),   # halfway
        (50,   0.0),   # 50 over — intense activity, floor
        (100,  0.0),   # way over — still clamped to 0
    ],
)
def test_hr_component_score(delta: int, expected: float) -> None:
    assert math.isclose(hr_component_score(delta), expected, rel_tol=1e-9)


def test_hr_component_score_none() -> None:
    assert hr_component_score(None) is None


# ----------------------------------------------------------------------------
# Stress component (raw 0-99 inverted -> 0-100 score)
# ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "stress, expected",
    [
        (0,  100.0),  # perfectly relaxed
        (10,  90.0),
        (50,  50.0),  # halfway
        (99,   1.0),  # near-max
        (100,  0.0),  # at or above scale max — clamped
        (150,  0.0),  # over-range — clamped
    ],
)
def test_stress_component_score(stress: int, expected: float) -> None:
    assert math.isclose(stress_component_score(stress), expected, rel_tol=1e-9)


def test_stress_component_score_none() -> None:
    assert stress_component_score(None) is None


# ----------------------------------------------------------------------------
# Trend component (HRV slope per hour -> 0-100)
# ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "slope, expected",
    [
        (-2.0,   0.0),    # strongly falling — clamped
        (-1.0,   0.0),    # lower bound
        (-0.5,  25.0),    # falling moderately
        (0.0,   50.0),    # stable
        (0.5,   75.0),    # rising moderately
        (1.0,  100.0),    # upper bound
        (2.0,  100.0),    # strongly rising — clamped
    ],
)
def test_trend_component_score(slope: float, expected: float) -> None:
    assert math.isclose(trend_component_score(slope), expected, rel_tol=1e-9)


def test_trend_component_score_none() -> None:
    assert trend_component_score(None) is None


# ----------------------------------------------------------------------------
# Weighted aggregate
# ----------------------------------------------------------------------------


def test_weighted_score_all_present() -> None:
    """All 4 components present: uses default weights, renormalizes over 1.0."""
    components = {"hrv": 80.0, "hr": 60.0, "stress": 70.0, "trend": 50.0}
    # Expected: 80*.4 + 60*.25 + 70*.2 + 50*.15 = 32+15+14+7.5 = 68.5
    # Python's round() uses banker's rounding (half-to-even): 68.5 -> 68
    assert weighted_score(components) == 68


def test_weighted_score_one_missing_renormalizes() -> None:
    """Missing component: weights renormalize over available total."""
    components = {"hrv": 80.0, "hr": 60.0, "stress": 70.0, "trend": None}
    available_weight = 0.40 + 0.25 + 0.20  # 0.85
    expected = (80 * 0.40 + 60 * 0.25 + 70 * 0.20) / available_weight
    assert weighted_score(components) == round(expected)


def test_weighted_score_all_missing_returns_none() -> None:
    """No components available: returns None (insufficient data)."""
    components = {"hrv": None, "hr": None, "stress": None, "trend": None}
    assert weighted_score(components) is None


def test_weighted_score_only_one_present() -> None:
    """Single component: returns that component's value (renormalized to 1.0)."""
    components = {"hrv": 75.0, "hr": None, "stress": None, "trend": None}
    assert weighted_score(components) == 75


def test_weighted_score_custom_weights() -> None:
    """Custom weights override defaults."""
    components = {"hrv": 100.0, "hr": 0.0}
    weights = {"hrv": 0.9, "hr": 0.1, "stress": 0.0, "trend": 0.0}
    # Expected: (100*.9 + 0*.1) / 1.0 = 90
    assert weighted_score(components, weights) == 90


def test_default_weights_sum_to_one() -> None:
    """Sanity: default weights must sum to 1.0 (so full-component case is well-defined)."""
    assert math.isclose(sum(DEFAULT_WEIGHTS.values()), 1.0, rel_tol=1e-9)


# ----------------------------------------------------------------------------
# Vibe label
# ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "score, expected",
    [
        (100, "Locked In"),
        (80,  "Locked In"),
        (79,  "Solid"),
        (60,  "Solid"),
        (59,  "Vibing"),
        (40,  "Vibing"),
        (39,  "Winded"),
        (20,  "Winded"),
        (19,  "Gassed"),
        (0,   "Gassed"),
    ],
)
def test_status_label(score: int, expected: str) -> None:
    assert status_label(score) == expected


def test_status_label_none() -> None:
    assert status_label(None) is None
