"""Data quality — per-type freshness check.

Flag stale/missing data:
- For each day, if ANY type has data (ring worn + synced) but a specific
  type has 0 records → 'stale'
- Days with zero records across ALL types → 'missing' (not worn / no sync)
- Otherwise → 'ok', UNLESS today's intra-day freshness gap fires:
  a type with samples today but whose `last_ts` lags the day's freshest
  type by more than a per-type threshold while a peer is fresh (ring is
  actively being worn) → 'stale'. Catches the "steps stalled at 4 PM
  while HR is current" case that the cnt==0 check alone misses.

Temperature has a 1-day publish cadence (history buffer exposes completed
days only), so today's temp is normally pending — not stale. Temp is also
exempt from the intra-day freshness check for the same reason.
DATE() uses session TZ set in db.connect.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

log = logging.getLogger(__name__)

# Per-type intra-day freshness thresholds (minutes). A type is flagged stale
# when its last_ts lags the day's freshest type by more than this AND at least
# one peer is fresh (within PEER_FRESH_WINDOW_MIN of now → ring is worn).
# Calibrated from each type's native publish cadence (see docs/RING_BEHAVIOR.md).
FRESHNESS_GAP_MINUTES: dict[str, int] = {
    "heart_rate": 30,   # 5-min cadence
    "hrv": 90,          # 30-min cadence
    "steps": 90,        # 15-min cadence (zero-suppressed per hour)
    "spo2": 180,        # hourly cadence
    "stress": 90,       # 30-min cadence
    # temperature: exempt — completed-days-only
}
PEER_FRESH_WINDOW_MIN = 30  # ring counts as "currently worn" if any type updated within this


def compute_data_quality(conn, days: int = 7) -> None:
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    log.info(f"Computing data quality over last {days} days...")
    types = {
        "heart_rate":   "raw_heart_rate",
        "spo2":         "raw_spo2",
        "temperature":  "raw_temperature",
        "hrv":          "raw_hrv",
        "steps":        "raw_steps",
        "stress":       "raw_stress",
    }
    with conn.cursor() as cur:
        day_counts: dict = {}  # day -> {type: count}
        for data_type, table in types.items():
            cur.execute(f"""
                SELECT DATE(ts) AS day,
                       COUNT(*) AS cnt, MAX(ts) AS last_ts
                FROM {table}
                WHERE ts >= %s
                GROUP BY 1
            """, (cutoff,))
            for row in cur.fetchall():
                d = str(row["day"])
                day_counts.setdefault(d, {})[data_type] = row["cnt"]
                day_counts[d].setdefault(f"{data_type}_last_ts", row["last_ts"])

        today_str = max(day_counts.keys()) if day_counts else None
        now = datetime.now(timezone.utc)
        stale_types_seen: set[str] = set()

        for d, counts in day_counts.items():
            any_data = any(counts.get(t, 0) > 0 for t in types)

            # Peer-relative freshness window (today only). max_last_ts = the
            # freshest sample across all types today. peer_fresh = True when
            # the ring is actively being worn (some type updated very recently).
            is_today = (d == today_str)
            max_last_ts = None
            if is_today and any_data:
                for t in types:
                    t_ts = counts.get(f"{t}_last_ts")
                    if t_ts is not None and (max_last_ts is None or t_ts > max_last_ts):
                        max_last_ts = t_ts
            peer_fresh = (
                max_last_ts is not None
                and (now - max_last_ts).total_seconds() <= PEER_FRESH_WINDOW_MIN * 60
            )

            for data_type in types:
                cnt = counts.get(data_type, 0)
                last_ts = counts.get(f"{data_type}_last_ts")
                if any_data and cnt == 0:
                    if data_type == "temperature" and is_today:
                        status = "ok"
                    else:
                        status = "stale"
                elif not any_data:
                    status = "missing"
                else:
                    status = "ok"
                    # Intra-day freshness gap: today only, peer-relative.
                    # If HR/HRV/stress are fresh but steps is hours behind,
                    # something is wrong with the steps fetch path (e.g.
                    # queue pollution — see collector/protocol/parsers/steps.py).
                    if (
                        is_today
                        and peer_fresh
                        and data_type in FRESHNESS_GAP_MINUTES
                        and last_ts is not None
                        and (max_last_ts - last_ts).total_seconds()
                            > FRESHNESS_GAP_MINUTES[data_type] * 60
                    ):
                        status = "stale"

                if status == "stale":
                    stale_types_seen.add(data_type)

                cur.execute("""
                    INSERT INTO data_quality (day, data_type, last_ts,
                                              sample_count, status, checked_at)
                    VALUES (%s, %s, %s, %s, %s, NOW())
                    ON CONFLICT (day, data_type) DO UPDATE SET
                        last_ts = EXCLUDED.last_ts,
                        sample_count = EXCLUDED.sample_count,
                        status = EXCLUDED.status,
                        checked_at = EXCLUDED.checked_at
                """, (d, data_type, last_ts, cnt, status))
        conn.commit()
        if stale_types_seen:
            log.info(f"  Data quality: stale types = {sorted(stale_types_seen)}, "
                     f"checked {len(day_counts)} days")
        else:
            log.info(f"  Data quality: all types fresh ({len(day_counts)} days)")
