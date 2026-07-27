"""Strain trend & training load analytics (ACWR, rolling loads, load labels).

Computes rolling 7-day acute load, 28-day chronic load (Acute:Chronic Workload
Ratio - Gabbett 2016), daily load labels (WHOOP-style rest/light/moderate/hard/
very_hard), and 7-day trend direction.

Reads from heart_rate_zones and persists to strain_trend.
"""
from __future__ import annotations

import logging
import statistics
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

log = logging.getLogger(__name__)

# Load label thresholds based on daily strain (0.0 - 21.0)
LOAD_THRESHOLDS = [
    (4.0, "rest"),
    (8.0, "light"),
    (12.0, "moderate"),
    (16.0, "hard"),
    (21.0, "very_hard"),
]

LOOKBACK_DAYS = 14
CHRONIC_WINDOW_DAYS = 28
ACUTE_WINDOW_DAYS = 7
MIN_CHRONIC_DAYS_REQUIRED = 28
TREND_DELTA_THRESHOLD = 1.5


def load_label_from_strain(strain: float) -> str:
    """Map daily strain (0-21) to descriptive load label."""
    for threshold, label in LOAD_THRESHOLDS:
        if strain <= threshold:
            return label
    return "very_hard"


def acwr_from_loads(acute_sum: float, chronic_avg: Optional[float]) -> Optional[float]:
    """Compute Acute:Chronic Workload Ratio (ACWR = 7d_sum / 28d_avg).

    Returns None if chronic baseline is missing or zero.
    """
    if chronic_avg is None or chronic_avg <= 0:
        return None
    return round(acute_sum / chronic_avg, 2)


def trend_direction_from_series(recent_3d: List[float], prior_4d: List[float]) -> str:
    """Determine trend direction ('increasing', 'stable', 'decreasing').

    Compares mean of last 3 days against mean of prior 4 days (within 7-day window).
    Defaults to 'stable' if insufficient data points.
    """
    if not recent_3d or not prior_4d:
        return "stable"
    recent_mean = statistics.mean(recent_3d)
    prior_mean = statistics.mean(prior_4d)
    diff = recent_mean - prior_mean
    if diff > TREND_DELTA_THRESHOLD:
        return "increasing"
    if diff < -TREND_DELTA_THRESHOLD:
        return "decreasing"
    return "stable"


def compute_rolling_metrics(
    all_strains: Dict[date, float],
    target_day: date,
) -> Dict:
    """Compute rolling 7d acute sum, 28d chronic avg, ACWR, and trend direction.

    `all_strains` is a dict of {date: strain_score} spanning past history.
    """
    # 28-day window ending on target_day (inclusive)
    chronic_start = target_day - timedelta(days=CHRONIC_WINDOW_DAYS - 1)
    chronic_values = [
        all_strains[d]
        for d in (chronic_start + timedelta(days=i) for i in range(CHRONIC_WINDOW_DAYS))
        if d in all_strains
    ]

    # 7-day window ending on target_day (inclusive)
    acute_start = target_day - timedelta(days=ACUTE_WINDOW_DAYS - 1)
    acute_dates = [acute_start + timedelta(days=i) for i in range(ACUTE_WINDOW_DAYS)]
    acute_values_with_gaps = [all_strains.get(d, 0.0) for d in acute_dates]
    days_with_data = sum(1 for d in acute_dates if d in all_strains)

    strain_today = all_strains.get(target_day, 0.0)
    strain_7d_sum = round(sum(acute_values_with_gaps), 1)
    strain_7d_avg = round(statistics.mean(acute_values_with_gaps), 1) if acute_values_with_gaps else 0.0

    # Chronic avg (only populated if we have enough distinct days in the 28d window)
    strain_28d_avg = (
        round(statistics.mean(chronic_values), 1)
        if len(chronic_values) >= MIN_CHRONIC_DAYS_REQUIRED
        else None
    )

    acwr = acwr_from_loads(strain_7d_sum, strain_28d_avg)

    # Trend direction: recent 3 days vs prior 4 days within the 7-day window
    recent_3d = [all_strains.get(target_day - timedelta(days=i), 0.0) for i in range(3)]
    prior_4d = [all_strains.get(target_day - timedelta(days=3 + i), 0.0) for i in range(4)]
    trend = trend_direction_from_series(recent_3d, prior_4d) if days_with_data >= 3 else "stable"

    return {
        "strain_today": strain_today,
        "load_label": load_label_from_strain(strain_today),
        "strain_7d_sum": strain_7d_sum,
        "strain_7d_avg": strain_7d_avg,
        "strain_28d_avg": strain_28d_avg,
        "acwr": acwr,
        "trend_direction": trend,
        "days_with_data": days_with_data,
    }


def compute_strain_trend(conn, days: int = LOOKBACK_DAYS) -> None:
    """Compute and upsert strain_trend for the last N days."""
    log.info("Computing strain trend & training load...")

    # We need up to 28 + LOOKBACK_DAYS of history for chronic baselines
    history_cutoff = date.today() - timedelta(days=CHRONIC_WINDOW_DAYS + LOOKBACK_DAYS)
    recompute_cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    with conn.cursor() as cur:
        cur.execute("""
            SELECT day, strain_score
            FROM heart_rate_zones
            WHERE day >= %s
            ORDER BY day ASC
        """, (history_cutoff,))
        rows = cur.fetchall()

    all_strains: Dict[date, float] = {r["day"]: float(r["strain_score"]) for r in rows}

    # Days to compute/upsert
    with conn.cursor() as cur:
        cur.execute("""
            SELECT day FROM heart_rate_zones
            WHERE day >= %s
            ORDER BY day ASC
        """, (recompute_cutoff.date(),))
        days_to_compute = [r["day"] for r in cur.fetchall()]

    count = 0
    for d in days_to_compute:
        metrics = compute_rolling_metrics(all_strains, d)

        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO strain_trend
                    (day, strain_today, load_label,
                     strain_7d_sum, strain_7d_avg, strain_28d_avg,
                     acwr, trend_direction, days_with_data, computed_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
                ON CONFLICT (day) DO UPDATE SET
                    strain_today=EXCLUDED.strain_today,
                    load_label=EXCLUDED.load_label,
                    strain_7d_sum=EXCLUDED.strain_7d_sum,
                    strain_7d_avg=EXCLUDED.strain_7d_avg,
                    strain_28d_avg=EXCLUDED.strain_28d_avg,
                    acwr=EXCLUDED.acwr,
                    trend_direction=EXCLUDED.trend_direction,
                    days_with_data=EXCLUDED.days_with_data,
                    computed_at=NOW()
            """, (
                d,
                metrics["strain_today"],
                metrics["load_label"],
                metrics["strain_7d_sum"],
                metrics["strain_7d_avg"],
                metrics["strain_28d_avg"],
                metrics["acwr"],
                metrics["trend_direction"],
                metrics["days_with_data"],
            ))
        count += 1

    conn.commit()
    if count:
        log.info(f"  Strain trend: {count} days updated")
