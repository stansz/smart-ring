"""Heart-rate zones + Edwards TRIMP-based strain score.

Scores cardiovascular load from raw_heart_rate 5-min samples. Zone boundaries
use Karvonen heart-rate reserve. Strain is scaled 0-21 like WHOOP's product
surface, but derived from a transparent Edwards TRIMP, not WHOOP's proprietary
formula.

No same-day circularity: RHR baseline uses the previous 7 days of daily_activity.hr_min,
never today. Empty or unworn days are skipped.
"""
from __future__ import annotations

import logging
import os
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional, Tuple

log = logging.getLogger(__name__)

# Karvonen HRR zone boundaries: lower bound of each zone.
# Z1 50-60%, Z2 60-70%, Z3 70-80%, Z4 80-90%, Z5 90-100%
ZONE_BOUNDS = (
    (1, 0.50, 0.60),
    (2, 0.60, 0.70),
    (3, 0.70, 0.80),
    (4, 0.80, 0.90),
    (5, 0.90, 1.00),
)

# Edwards TRIMP zone weights (1..5).
ZONE_WEIGHTS = {1: 1, 2: 2, 3: 3, 4: 4, 5: 5}

# Sample width for raw_heart_rate 5-min history (minutes).
SAMPLE_WIDTH_MIN = 5

# Soft cap at which TRIMP maps to strain 21.
STRAIN_TRIMP_CAP = 450.0

DEFAULT_USER_AGE = 35
RHR_FALLBACK = 60
LOOKBACK_DAYS = 14
RHR_LOOKBACK_DAYS = 7


def _get_user_age() -> int:
    try:
        age = int(os.getenv("USER_AGE", DEFAULT_USER_AGE))
        if 13 <= age <= 110:
            return age
    except (ValueError, TypeError):
        pass
    return DEFAULT_USER_AGE


def karvonen_bounds(rhr: int, max_hr: int) -> Dict[int, Tuple[int, int]]:
    """Return {(zone): (lower_bpm_inclusive, upper_bpm_exclusive)}.

    Values are rounded to nearest bpm. Max zone has no upper bound (uses max_hr
    as the inclusive upper edge).
    """
    hrr = max(1, max_hr - rhr)
    bounds: Dict[int, Tuple[int, int]] = {}
    for zone, lo_pct, hi_pct in ZONE_BOUNDS:
        lo = round(rhr + hrr * lo_pct)
        hi = round(rhr + hrr * hi_pct)
        bounds[zone] = (lo, hi)
    return bounds


def zone_for_bpm(bpm: int, bounds: Dict[int, Tuple[int, int]]) -> Optional[int]:
    """Return zone 1-5 or None if below Z1."""
    for zone, (lo, hi) in bounds.items():
        if lo <= bpm < hi:
            return zone
    # Above Z5 inclusive
    _, hi_five = bounds[5]
    if bpm >= hi_five:
        return 5
    return None


def edwards_trimp(zone_minutes: Dict[int, int]) -> float:
    """Raw TRIMP = sum(zone_minutes * weight)."""
    return sum(zone_minutes.get(z, 0) * ZONE_WEIGHTS[z] for z in ZONE_WEIGHTS)


def scale_strain(trimp: float, cap: float = STRAIN_TRIMP_CAP) -> float:
    """Scale TRIMP to 0.0-21.0."""
    return round(min(21.0, 21.0 * trimp / cap), 1) if cap > 0 else 0.0


def rhr_baseline(hr_mins: List[int]) -> Optional[int]:
    """Median of prior-day resting HR proxies. None if empty."""
    values = sorted(hr_mins)
    if not values:
        return None
    mid = len(values) // 2
    if len(values) % 2 == 1:
        return values[mid]
    return (values[mid - 1] + values[mid]) // 2


def compute_day_zones(
    samples: List[Dict[str, int]],
    rhr: int,
    max_hr: int,
    sample_width: int = SAMPLE_WIDTH_MIN,
) -> Dict:
    """Pure helper: count zone minutes from HR samples and compute strain.

    `samples` is a list of dicts with a 'bpm' key. BPM <= 0 is ignored.
    Returns a dict matching the heart_rate_zones row columns.
    """
    bounds = karvonen_bounds(rhr, max_hr)
    zone_minutes: Dict[int, int] = {z: 0 for z in ZONE_WEIGHTS}
    below_zone_min = 0
    hr_count = 0
    peak_zone: Optional[int] = None

    for s in samples:
        bpm = s.get("bpm") or 0
        if bpm <= 0:
            continue
        hr_count += 1
        zone = zone_for_bpm(bpm, bounds)
        if zone is not None:
            zone_minutes[zone] += sample_width
            if peak_zone is None or zone > peak_zone:
                peak_zone = zone
        else:
            below_zone_min += sample_width

    trimp = edwards_trimp(zone_minutes)
    strain = scale_strain(trimp)
    elevated_min = sum(zone_minutes[z] for z in (2, 3, 4, 5))

    return {
        "rhr_used": rhr,
        "max_hr_used": max_hr,
        "zone1_min": zone_minutes[1],
        "zone2_min": zone_minutes[2],
        "zone3_min": zone_minutes[3],
        "zone4_min": zone_minutes[4],
        "zone5_min": zone_minutes[5],
        "below_zone_min": below_zone_min,
        "elevated_min": elevated_min,
        "peak_zone": peak_zone or 0,
        "trimp": trimp,
        "strain_score": strain,
        "hr_samples": hr_count,
    }


def compute_heart_rate_zones(conn, days: int = LOOKBACK_DAYS) -> None:
    """Compute and upsert heart_rate_zones for the last N days."""
    log.info("Computing heart rate zones...")
    age = _get_user_age()

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    rhr_cutoff_date = date.today() - timedelta(days=RHR_LOOKBACK_DAYS)

    with conn.cursor() as cur:
        # Prior-day RHR proxies (exclude today).
        cur.execute("""
            SELECT hr_min FROM daily_activity
            WHERE day >= %s AND day < CURRENT_DATE AND hr_min IS NOT NULL
            ORDER BY day DESC
        """, (rhr_cutoff_date,))
        rhr_min_history = [r["hr_min"] for r in cur.fetchall()]
        rhr = rhr_baseline(rhr_min_history) or RHR_FALLBACK

        # Observed max over last 30d (bootstrap to population formula if higher).
        cur.execute("""
            SELECT MAX(bpm)::int AS observed_max
            FROM raw_heart_rate
            WHERE ts >= NOW() - INTERVAL '30 days' AND bpm > 0
        """)
        row = cur.fetchone()
        observed_max = row["observed_max"] or 0
        max_hr = max(observed_max, 220 - age, rhr + 1)

        # Fetch per-day 5-min samples to score.
        cur.execute("""
            SELECT DATE(ts) AS day, bpm
            FROM raw_heart_rate
            WHERE ts >= %s AND bpm > 0
            ORDER BY ts
        """, (cutoff,))
        rows = cur.fetchall()

    samples_by_day: Dict[date, List[Dict[str, int]]] = {}
    for r in rows:
        samples_by_day.setdefault(r["day"], []).append({"bpm": r["bpm"]})

    with conn.cursor() as cur:
        cur.execute("""
            SELECT day FROM daily_activity
            WHERE day >= CURRENT_DATE - %s::int AND hr_samples > 0
        """, (days,))
        days_to_score = set(r["day"] for r in cur.fetchall()) | set(samples_by_day.keys())



    count = 0
    for d in sorted(days_to_score):
        samples = samples_by_day.get(d, [])
        if not samples:
            continue
        result = compute_day_zones(samples, rhr, max_hr)

        with conn.cursor() as cur:
            cur.execute("""
                INSERT INTO heart_rate_zones
                    (day, rhr_used, max_hr_used,
                     zone1_min, zone2_min, zone3_min, zone4_min, zone5_min,
                     below_zone_min, elevated_min, peak_zone,
                     trimp, strain_score, hr_samples, computed_at)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,NOW())
                ON CONFLICT (day) DO UPDATE SET
                    rhr_used=EXCLUDED.rhr_used, max_hr_used=EXCLUDED.max_hr_used,
                    zone1_min=EXCLUDED.zone1_min, zone2_min=EXCLUDED.zone2_min,
                    zone3_min=EXCLUDED.zone3_min, zone4_min=EXCLUDED.zone4_min,
                    zone5_min=EXCLUDED.zone5_min, below_zone_min=EXCLUDED.below_zone_min,
                    elevated_min=EXCLUDED.elevated_min, peak_zone=EXCLUDED.peak_zone,
                    trimp=EXCLUDED.trimp, strain_score=EXCLUDED.strain_score,
                    hr_samples=EXCLUDED.hr_samples, computed_at=NOW()
            """, (
                d,
                result["rhr_used"], result["max_hr_used"],
                result["zone1_min"], result["zone2_min"], result["zone3_min"],
                result["zone4_min"], result["zone5_min"],
                result["below_zone_min"], result["elevated_min"], result["peak_zone"],
                result["trimp"], result["strain_score"], result["hr_samples"],
            ))
        count += 1

    conn.commit()
    if count:
        log.info(f"  Heart rate zones: {count} days updated (RHR={rhr}, maxHR={max_hr})")
