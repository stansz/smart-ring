"""Data quality — per-type, per-source freshness check.

Flag stale/missing data:
- For each (day, data_type, source), if the source has 0 records on a
  day when some OTHER source for the same data_type has records →
  'stale' for that source. (E.g. garmin HRV hasn't synced today but
  ring HRV is fresh — garmin row is stale, ring row is ok.)
- For each (day, data_type, source), if NO source has records on a
  day when some other type has any data → 'missing' (not worn / no
  sync that day for that source).
- Otherwise → 'ok', UNLESS today's intra-day freshness gap fires:
  a (day, data_type, source) with samples today but whose `last_ts`
  lags the day's freshest sample by more than a per-type threshold
  while a peer is fresh (ring is actively being worn) → 'stale'.
  Catches the "steps stalled at 4 PM while HR is current" case that
  the cnt==0 check alone misses.

Temperature has a 1-day publish cadence (history buffer exposes
completed days only), so today's temp is normally pending — not
stale. Temp is also exempt from the intra-day freshness check for
the same reason.

``source`` is part of the key so each device's freshness is tracked
separately. This is the foundation for cross-device data fusion
(Garmin phase): if garmin stops reporting but ring is fine, the
ring row stays 'ok' and the garmin row flips to 'stale' instead of
both being lumped together.
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


# Sources we emit data_quality rows for. Today = ['ring', 'phone'].
# Adding 'garmin' is a one-line change once the Phase 1 collector lands
# — the data-quality scorer will start emitting garmin rows automatically
# because it reads source from the raw_* tables.
KNOWN_QUALITY_SOURCES: tuple[str, ...] = ("ring", "phone")


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
        # day_type_source: (day, data_type, source) -> {cnt, last_ts}
        # Populated from raw_* tables. We also emit rows for
        # known-but-absent (type, source) combos so the dashboard
        # can show "ring: ok, garmin: stale" side by side.
        day_type_source: dict[tuple[str, str, str], dict] = {}

        for data_type, table in types.items():
            cur.execute(f"""
                SELECT DATE(ts) AS day,
                       source,
                       COUNT(*) AS cnt,
                       MAX(ts) AS last_ts
                FROM {table}
                WHERE ts >= %s
                GROUP BY 1, 2
            """, (cutoff,))
            for row in cur.fetchall():
                d = str(row["day"])
                src = row["source"]
                day_type_source[(d, data_type, src)] = {
                    "cnt": row["cnt"],
                    "last_ts": row["last_ts"],
                }

        # Group by (day, type) and figure out which (day, type) pairs
        # have any data at all.
        day_type: dict[tuple[str, str], set[str]] = {}
        for (d, data_type, source), v in day_type_source.items():
            if v["cnt"] > 0:
                day_type.setdefault((d, data_type), set()).add(source)

        # Days with any (type, source) with data — used to distinguish
        # 'stale' (some data on day, but not for this type) from
        # 'missing' (no data at all on day — ring not worn / no sync).
        day_has_any_data: set[str] = {d for (d, _) in day_type.keys()}

        # Build the set of (day, type, source) rows to emit:
        # - Every (day, type, source) that has rows
        # - For each (day, type) with at least one source, every known
        #   source (so the "this source is stale/missing" rows show)
        # - For days with other-type data but no data for this type,
        #   also emit a row for every known source of that type
        #   (the "type-missing" case — same as the old "cnt==0 stale"
        #   rule, but per-source)
        rows_to_emit: set[tuple[str, str, str]] = set(day_type_source.keys())
        for (d, data_type) in day_type:
            for src in KNOWN_QUALITY_SOURCES:
                rows_to_emit.add((d, data_type, src))
        # Type-missing case: day has data from OTHER types but not this
        # one → emit a 'stale' row per known source for this (day, type).
        for d in day_has_any_data:
            for data_type in types:
                if (d, data_type) not in day_type:
                    for src in KNOWN_QUALITY_SOURCES:
                        rows_to_emit.add((d, data_type, src))

        today_str = max(
            (d for (d, _, _) in rows_to_emit), default=None
        )
        now = datetime.now(timezone.utc)
        stale_types_seen: set[str] = set()

        for (d, data_type, source) in sorted(rows_to_emit):
            counts = day_type_source.get((d, data_type, source), {"cnt": 0, "last_ts": None})
            cnt = counts["cnt"]
            last_ts = counts["last_ts"]

            any_data_on_day = d in day_has_any_data

            # 'missing' is reserved for the case where the WHOLE DAY
            # has no data (ring not worn / not synced). When the day
            # has some data but a particular (type, source) has 0, the
            # row is 'stale' instead — preserving the original
            # "type-has-no-data-but-other-types-do" semantics from
            # pre-Phase-0.
            if not any_data_on_day:
                status = "missing"
            elif cnt == 0:
                # No data for THIS source on a day with overall data
                # → stale for this source.
                if data_type == "temperature" and d == today_str:
                    status = "ok"
                else:
                    status = "stale"
            else:
                status = "ok"
                # Intra-day freshness gap: today only, peer-relative.
                # Compare THIS source's last_ts to the freshest sample
                # across ALL (type, source) pairs today — if it's
                # lagging by more than the per-type threshold while a
                # peer is fresh (some device just reported), flag
                # stale. Catches the "steps stalled at 4 PM while HR
                # is current" case at the per-source level.
                is_today = d == today_str
                if is_today and data_type in FRESHNESS_GAP_MINUTES:
                    # Find freshest sample today across all (type, source)
                    max_last_ts = None
                    for (k_d, k_t, k_s), v in day_type_source.items():
                        if k_d != d or v["last_ts"] is None:
                            continue
                        if max_last_ts is None or v["last_ts"] > max_last_ts:
                            max_last_ts = v["last_ts"]
                    peer_fresh = (
                        max_last_ts is not None
                        and (now - max_last_ts).total_seconds()
                            <= PEER_FRESH_WINDOW_MIN * 60
                    )
                    if (
                        peer_fresh
                        and (max_last_ts - last_ts).total_seconds()
                            > FRESHNESS_GAP_MINUTES[data_type] * 60
                    ):
                        status = "stale"

            if status == "stale":
                stale_types_seen.add(data_type)

            cur.execute("""
                INSERT INTO data_quality (day, data_type, source, last_ts,
                                          sample_count, status, checked_at)
                VALUES (%s, %s, %s, %s, %s, %s, NOW())
                ON CONFLICT (day, data_type, source) DO UPDATE SET
                    last_ts = EXCLUDED.last_ts,
                    sample_count = EXCLUDED.sample_count,
                    status = EXCLUDED.status,
                    checked_at = EXCLUDED.checked_at
            """, (d, data_type, source, last_ts, cnt, status))
        conn.commit()
        if stale_types_seen:
            log.info(f"  Data quality: stale types = {sorted(stale_types_seen)}, "
                     f"checked {len(rows_to_emit)} (day,type,source) rows")
        else:
            log.info(f"  Data quality: all types fresh ({len(rows_to_emit)} rows)")
