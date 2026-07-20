"""Boundary tests for trap_score — the trapezoidal scoring primitive.

trap_score(value, optimal_low, optimal_high, zero_low, zero_high) returns
0-100 with:
  - 0 at or below zero_low
  - linear ramp up from zero_low -> optimal_low (0 -> 100)
  - 100 across [optimal_low, optimal_high]
  - linear ramp down from optimal_high -> zero_high (100 -> 0)
  - 0 at or above zero_high

Test parameters use the canonical example from CLEANUP_PLAN.md:
  zero_low=4.0, optimal_low=7.0, optimal_high=9.0, zero_high=10.0
"""
from __future__ import annotations

import math

import pytest

from collector.analytics.helpers import trap_score

# Canonical trapezoid for HRV-like scoring
PARAMS = dict(optimal_low=7.0, optimal_high=9.0, zero_low=4.0, zero_high=10.0)


@pytest.mark.parametrize(
    "value, expected",
    [
        # --- Below zero_low: hard zero ---
        (3.0, 0.0),   # well below
        (0.0, 0.0),   # zero input
        (-10.0, 0.0), # negative
        (4.0, 0.0),   # exactly at zero_low (boundary, <= branch)

        # --- Ramp up: linear from 0 at 4.0 to 100 at 7.0 ---
        (5.5, 50.0),  # midpoint: (5.5-4)/(7-4) = 0.5 -> 50
        (4.0, 0.0),   # ramp start (duplicates boundary above; documents ramp)
        (7.0, 100.0), # ramp end (boundary; falls into optimal range check)

        # --- Optimal plateau: 100 across [7, 9] ---
        (7.0, 100.0), # left edge (inclusive)
        (8.0, 100.0), # midpoint
        (9.0, 100.0), # right edge (inclusive)

        # --- Ramp down: linear from 100 at 9.0 to 0 at 10.0 ---
        (9.5, 50.0),  # midpoint: (10-9.5)/(10-9) = 0.5 -> 50
        (9.0, 100.0), # ramp start (duplicates plateau edge)
        (10.0, 0.0),  # ramp end (boundary, >= branch)

        # --- Above zero_high: hard zero ---
        (10.0, 0.0),  # exactly at zero_high (boundary)
        (11.0, 0.0),  # just above
        (1000.0, 0.0),# well above
    ],
)
def test_trap_score_boundaries(value: float, expected: float) -> None:
    result = trap_score(value, **PARAMS)
    assert math.isclose(result, expected, rel_tol=1e-9, abs_tol=1e-9), (
        f"trap_score({value}, **{PARAMS}) = {result}, expected {expected}"
    )


def test_trap_score_return_type_is_float() -> None:
    """Even with int inputs, function returns float per signature."""
    result = trap_score(8, optimal_low=7, optimal_high=9, zero_low=4, zero_high=10)
    assert isinstance(result, float)
    assert result == 100.0


def test_trap_score_ramp_up_is_linear() -> None:
    """Verify the (zero_low, optimal_low) ramp is actually linear, not curved.

    Sample 5 points across the ramp and confirm the per-unit slope is constant.
    """
    samples = [4.5, 5.0, 5.5, 6.0, 6.5]
    results = [trap_score(v, **PARAMS) for v in samples]
    # Per-unit slope = dy/dx, not per-step delta
    slopes = [
        (results[i + 1] - results[i]) / (samples[i + 1] - samples[i])
        for i in range(len(results) - 1)
    ]
    # Theoretical slope: 100 / (optimal_low - zero_low) = 100 / 3
    expected_slope = 100.0 / (7.0 - 4.0)
    for s in slopes:
        assert math.isclose(s, expected_slope, rel_tol=1e-9), (
            f"Ramp not linear: per-unit slope {s} != {expected_slope}"
        )


def test_trap_score_ramp_down_is_linear() -> None:
    """Verify the (optimal_high, zero_high) ramp is actually linear."""
    samples = [9.1, 9.3, 9.5, 9.7, 9.9]
    results = [trap_score(v, **PARAMS) for v in samples]
    slopes = [
        (results[i + 1] - results[i]) / (samples[i + 1] - samples[i])
        for i in range(len(results) - 1)
    ]
    # Theoretical slope: -100 / (zero_high - optimal_high) = -100 / 1
    expected_slope = -100.0 / (10.0 - 9.0)
    for s in slopes:
        assert math.isclose(s, expected_slope, rel_tol=1e-9), (
            f"Ramp not linear: per-unit slope {s} != {expected_slope}"
        )


def test_trap_score_symmetric_trapezoid() -> None:
    """A symmetric trapezoid should give symmetric scores around the center."""
    # Symmetric params: zero_low=0, optimal_low=4, optimal_high=6, zero_high=10
    # Center is at 5.0; values 4.5 and 5.5 should give equal scores.
    sym = dict(optimal_low=4.0, optimal_high=6.0, zero_low=0.0, zero_high=10.0)
    below = trap_score(4.5, **sym)   # 0.5 into optimal_low ramp: 0.5/4 * 100 = 12.5
    above = trap_score(5.5, **sym)   # 0.5 into ramp_down slope: still in optimal plateau actually
    # 5.5 is within [4, 6] so both are 100. Use 7.5 vs 2.5 instead for symmetry test.
    left = trap_score(2.0, **sym)    # (2-0)/(4-0)*100 = 50
    right = trap_score(8.0, **sym)   # (10-8)/(10-6)*100 = 50
    assert math.isclose(left, right, rel_tol=1e-9)
    assert math.isclose(left, 50.0, rel_tol=1e-9)
