"""Current Status — live intra-day recovery score.

Complementary to readiness_score (which is morning-frozen). Uses recent
raw data to answer "how is my body doing right now?" — updates on every
analytics pass, naturally drifts during the day (that's the point).

Components (each 0-100, weighted to composite):
  - HRV   (40%): recent HRV z-score vs 7-day baseline (same source as daily)
  - HR    (25%): recent HR delta from RHR baseline (0 bpm over = 100, 50 over = 0)
  - Stress(20%): inverted raw stress (0 raw = 100, 99 raw = 1)
  - Trend (15%): HRV slope over last 2h (rising = recovering = higher score)

Each component returns None if input data missing. Weighted aggregate
renormalizes over available components. 'confidence' field mirrors the
readiness pattern: 'full' when all 4 present, 'partial' otherwise.

Labels (the "vibe" indicator, easy to retheme):
  80-100 Locked In | 60-79 Solid | 40-59 Vibing | 20-39 Winded | 0-19 Gassed
"""
from __future__ import annotations

import logging
import math
from typing import Optional

log = logging.getLogger(__name__)


# Default weights for the 4 components (must sum to 1.0)
DEFAULT_WEIGHTS = {"hrv": 0.40, "hr": 0.25, "stress": 0.20, "trend": 0.15}

# Score thresholds for the vibe label, descending.
LABELS = [
    (80, "Locked In"),
    (60, "Solid"),
    (40, "Vibing"),
    (20, "Winded"),
    (0, "Gassed"),
]


# ----------------------------------------------------------------------------
# Pure helpers (unit-tested without DB)
# ----------------------------------------------------------------------------


def hrv_component_score(recent_hrv_z: Optional[float]) -> Optional[float]:
    """Map HRV z-score to 0-100 using the readiness-style discrete mapping.

    Same thresholds as readiness._hrv_to_score so the two scores are
    comparable on the HRV axis.
    """
    if recent_hrv_z is None:
        return None
    if recent_hrv_z >= 3.0:  return 100.0
    if recent_hrv_z >= 2.0:  return 95.0
    if recent_hrv_z >= 1.5:  return 90.0
    if recent_hrv_z >= 1.0:  return 80.0
    if recent_hrv_z >= 0.5:  return 70.0
    if recent_hrv_z >= 0.0:  return 55.0
    if recent_hrv_z >= -0.5: return 40.0
    if recent_hrv_z >= -1.0: return 25.0
    return 10.0


def hr_component_score(hr_delta: Optional[int]) -> Optional[float]:
    """Map (current HR - RHR baseline) to 0-100.

    0 bpm over baseline = 100 (fully at rest)
    50 bpm over baseline = 0 (intense activity)
    Linear between, clamped to [0, 100].
    """
    if hr_delta is None:
        return None
    return max(0.0, min(100.0, 100.0 - hr_delta * 2.0))


def stress_component_score(stress_recent: Optional[int]) -> Optional[float]:
    """Invert raw stress reading (0-99) to 0-100 score.

    0 raw stress = 100 (perfectly relaxed)
    99 raw stress = 1 (maxed out)
    """
    if stress_recent is None:
        return None
    return max(0.0, min(100.0, 100.0 - float(stress_recent)))


def trend_component_score(hrv_slope: Optional[float]) -> Optional[float]:
    """Map HRV slope (per hour) to 0-100.

    slope >= +1.0 (strongly rising HRV): 100
    slope = 0.0 (stable): 50
    slope <= -1.0 (strongly falling HRV): 0
    Linear between, clamped.
    """
    if hrv_slope is None:
        return None
    return max(0.0, min(100.0, 50.0 + hrv_slope * 50.0))


def weighted_score(
    components: dict[str, Optional[float]],
    weights: dict[str, float] = DEFAULT_WEIGHTS,
) -> Optional[int]:
    """Combine component scores with weights. Renormalizes over available.

    Returns None if no components present (insufficient data).
    """
    available = {k: v for k, v in components.items() if v is not None}
    if not available:
        return None
    total_weight = sum(weights[k] for k in available)
    return round(sum(available[k] * weights[k] for k in available) / total_weight)


def status_label(score: Optional[int]) -> Optional[str]:
    """Map 0-100 score to vibe label. None if score is None."""
    if score is None:
        return None
    for threshold, label in LABELS:
        if score >= threshold:
            return label
    return LABELS[-1][1]


# ----------------------------------------------------------------------------
# Scorer entry point
# ----------------------------------------------------------------------------


def compute_current_status(conn) -> None:
    """Compute current status snapshot and append to current_status table.

    Queries last 2h of raw HRV/HR/stress + 7-day HRV baseline + RHR baseline.
    Appends one row per call (history retained for v2 trend chart).

    Returns silently if no input data at all (skip insert).
    """
    log.info("Computing current status...")
    with conn.cursor() as cur:
        # 1. HRV baseline — 7-day, ln-space, completed prior days only.
        #    Same source as hrv.compute_hrv_recovery's per-day baseline.
        cur.execute("""
            WITH daily AS (
                SELECT DATE(ts) AS day, AVG(hrv_value) AS avg_hrv
                FROM raw_hrv
                WHERE hrv_value > 0
                  AND ts >= NOW() - INTERVAL '8 days'
                  AND DATE(ts) < CURRENT_DATE
                GROUP BY 1
            )
            SELECT AVG(LN(avg_hrv)) AS mean,
                   STDDEV(LN(avg_hrv)) AS sd
            FROM daily
            WHERE avg_hrv > 0
        """)
        baseline = cur.fetchone()
        baseline_mean = baseline["mean"] if baseline else None
        baseline_sd = baseline["sd"] if baseline else None

        # 2. Recent HRV (last 2h) + slope (trend component)
        cur.execute("""
            SELECT AVG(hrv_value) AS avg_hrv,
                   REGR_SLOPE(hrv_value, EXTRACT(EPOCH FROM ts) / 3600.0) AS slope
            FROM raw_hrv
            WHERE hrv_value > 0 AND ts >= NOW() - INTERVAL '2 hours'
        """)
        recent_hrv_row = cur.fetchone()
        recent_hrv = recent_hrv_row["avg_hrv"] if recent_hrv_row else None
        hrv_slope = recent_hrv_row["slope"] if recent_hrv_row else None

        # 3. Recent HR (last 30 min) — short window so "current" feels live
        cur.execute("""
            SELECT AVG(bpm)::int AS avg_hr
            FROM raw_heart_rate
            WHERE ts >= NOW() - INTERVAL '30 minutes'
        """)
        recent_hr_row = cur.fetchone()
        recent_hr = recent_hr_row["avg_hr"] if recent_hr_row else None

        # 4. Recent stress (last 2h)
        cur.execute("""
            SELECT AVG(stress_value)::int AS avg_stress
            FROM raw_stress
            WHERE ts >= NOW() - INTERVAL '2 hours'
        """)
        recent_stress_row = cur.fetchone()
        recent_stress = recent_stress_row["avg_stress"] if recent_stress_row else None

        # 5. RHR baseline — median of daily_activity.hr_min over last 14 days
        cur.execute("""
            SELECT PERCENTILE_CONT(0.5) WITHIN GROUP (ORDER BY hr_min) AS rhr_baseline
            FROM daily_activity
            WHERE day >= CURRENT_DATE - INTERVAL '14 days'
              AND day < CURRENT_DATE
              AND hr_min IS NOT NULL
        """)
        rhr_row = cur.fetchone()
        rhr_baseline = int(rhr_row["rhr_baseline"]) if rhr_row and rhr_row["rhr_baseline"] else None

        # 6. Sample count for diagnostics + confidence signals
        cur.execute("""
            SELECT
                (SELECT COUNT(*) FROM raw_hrv WHERE hrv_value > 0 AND ts >= NOW() - INTERVAL '2 hours')
              + (SELECT COUNT(*) FROM raw_heart_rate WHERE ts >= NOW() - INTERVAL '30 minutes')
              + (SELECT COUNT(*) FROM raw_stress WHERE ts >= NOW() - INTERVAL '2 hours') AS total
        """)
        samples = cur.fetchone()["total"]

    # Compute derived values
    recent_hrv_z: Optional[float] = None
    if (
        recent_hrv is not None and recent_hrv > 0
        and baseline_mean is not None and baseline_sd is not None
        and float(baseline_sd) > 0
    ):
        recent_hrv_z = (math.log(recent_hrv) - float(baseline_mean)) / float(baseline_sd)

    hr_delta: Optional[int] = None
    if recent_hr is not None and rhr_baseline is not None:
        hr_delta = recent_hr - rhr_baseline

    # Component scores
    components = {
        "hrv":    hrv_component_score(recent_hrv_z),
        "hr":     hr_component_score(hr_delta),
        "stress": stress_component_score(recent_stress),
        "trend":  trend_component_score(hrv_slope if hrv_slope is not None else None),
    }
    score = weighted_score(components)
    missing = [k for k, v in components.items() if v is None]
    confidence = "full" if not missing else "partial"

    if score is None:
        log.info("  Current status: insufficient data (no components available)")
        return

    # Insert one row per analytics pass
    with conn.cursor() as cur:
        cur.execute("""
            INSERT INTO current_status (
                score, hrv_component, hr_component, stress_component, trend_component,
                hrv_zscore, hr_delta, stress_recent, hrv_trend, samples, confidence
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            score,
            components["hrv"], components["hr"], components["stress"], components["trend"],
            round(recent_hrv_z, 2) if recent_hrv_z is not None else None,
            hr_delta,
            recent_stress,
            round(float(hrv_slope), 3) if hrv_slope is not None else None,
            samples,
            confidence,
        ))
    conn.commit()

    label = status_label(score)
    log.info(
        f"  Current status: {score}/100 ({label}) — "
        f"hrv={components['hrv']} hr={components['hr']} "
        f"stress={components['stress']} trend={components['trend']} "
        f"[{samples} samples, {confidence}]"
    )
