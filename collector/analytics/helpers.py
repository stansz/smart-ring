"""Scoring helpers — pure functions, no DB.

These are the math primitives used by individual scorers. Kept separate
from scorer modules so they can be unit-tested without a DB connection.
"""
from __future__ import annotations

from typing import Optional


def trap_score(value: float, optimal_low: float, optimal_high: float,
               zero_low: float, zero_high: float) -> float:
    """Score 0-100 using a trapezoidal function.

    Full credit (100) within [optimal_low, optimal_high].
    Linear decline to 0 at [zero_low] and [zero_high].
    """
    if optimal_low <= value <= optimal_high:
        return 100.0
    if value < optimal_low:
        if value <= zero_low:
            return 0.0
        return (value - zero_low) / (optimal_low - zero_low) * 100
    # value > optimal_high
    if value >= zero_high:
        return 0.0
    return (zero_high - value) / (zero_high - optimal_high) * 100


def readiness_text(z: Optional[float]) -> str:
    """Map z-score to readiness label (Altini thresholds)."""
    if z is None:
        return "Building baseline..."
    if z > 1.0:
        return "Excellent"
    if z > 0.5:
        return "Good"
    if z > -0.5:
        return "Fair"
    if z > -1.0:
        return "Poor"
    return "Very Poor"
