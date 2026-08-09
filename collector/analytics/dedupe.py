"""Source dedup — collapse N overlapping sources to one row per slot.

This is the single source of truth for source-dedup. The redundant copy
that used to live in api/main.py:_dedupe_sources was dropped in the API
cleanup (Step 2); phone-sync now relies on this running before scorers.

**N-source contract:** for each timestamp (or sleep day) where
multiple sources report, keep the highest-priority source (per
``source_priority.DEFAULT_PRIORITY``) and delete the rest. The default
order is ``ring > garmin > phone``. Every downstream query and score
sees one measurement per slot.

**Backwards compatibility:** when only ``ring`` and ``phone`` rows
exist, the result is identical to the old hardcoded
``ring > phone`` behaviour. No existing scorer needs to change.
"""
from __future__ import annotations

import logging
from typing import Dict, Optional, Tuple

from .source_priority import DEFAULT_PRIORITY, DEDUPE_METRICS

log = logging.getLogger(__name__)


# Metric -> (table, slot_keys). slot_keys is the tuple of columns that
# defines a "same physical slot" for the dedupe (ts alone, or
# ts + hrv_type, or day for sleep). Sleep is the odd one out
# (deduped at the day level, not point level) so it gets its own
# entry below.
_DEDUPE_TABLE_SLOT: Dict[str, Tuple[str, Tuple[str, ...]]] = {
    "heart_rate":   ("raw_heart_rate",   ("ts",)),
    "spo2":         ("raw_spo2",         ("ts",)),
    "temperature":  ("raw_temperature",  ("ts",)),
    "hrv":          ("raw_hrv",          ("ts", "hrv_type")),
    "steps":        ("raw_steps",        ("ts",)),
    "stress":       ("raw_stress",       ("ts",)),
    "sleep":        ("raw_sleep",        ("day",)),
}


def _drop_non_preferred(
    cur,
    table: str,
    slot_keys: Tuple[str, ...],
    priority: tuple,
) -> int:
    """Delete every row in ``table`` whose source isn't the highest-
    priority one for its slot. Generic across point tables (single
    ts key) and sleep (single day key) and HRV (composite key).

    SQL strategy (one CTE chain, two stages):
      1. For each slot, collect the distinct sources that reported
         there (filtered to known sources — unknown sources sort last
         and are not eligible to be "kept").
      2. For each slot that has >1 source, pick the preferred one
         using array_position(priority_array, source) — lower index =
         higher priority.
      3. DELETE all rows in the slot whose source is in the multi-
         source set and is not the preferred one.

    The priority array is materialised in a CTE so the correlated
    subquery inside ``preferred`` can reference it (Postgres parameter
    binding doesn't reach into a subquery's ORDER BY).
    """
    slot_csv = ", ".join(slot_keys)
    on_clause = " AND ".join(f"t.{k} = p.{k}" for k in slot_keys)
    priority_select = ", ".join(f"'{s}'" for s in priority)

    cur.execute(f"""
        WITH priority_chain AS (
            SELECT ARRAY[{priority_select}]::text[] AS chain
        ),
        slot_sources AS (
            SELECT {slot_csv},
                   array_agg(DISTINCT t.source) AS sources
            FROM {table} t, priority_chain pc
            WHERE t.source = ANY(pc.chain)
            GROUP BY {slot_csv}
            HAVING COUNT(DISTINCT t.source) > 1
        ),
        preferred AS (
            SELECT {slot_csv},
                   sources,
                   (SELECT src
                    FROM unnest(sources) AS src
                    ORDER BY array_position((SELECT chain FROM priority_chain), src) NULLS LAST
                    LIMIT 1) AS keep_source
            FROM slot_sources
        )
        DELETE FROM {table} t
        USING preferred p
        WHERE {on_clause}
          AND t.source = ANY(p.sources)
          AND t.source <> p.keep_source
    """)
    return cur.rowcount or 0


def dedupe_sources(
    conn,
    priority_map: Optional[Dict[str, tuple]] = None,
) -> None:
    """Collapse N overlapping sources to one row per slot.

    For each metric in ``DEDUPE_METRICS`` (HR, SpO2, temp, HRV, steps,
    stress, sleep), for each distinct slot where multiple sources
    report, keep the source highest in ``priority_map[metric]`` and
    delete the others.

    ``priority_map`` defaults to ``DEFAULT_PRIORITY`` (ring > garmin >
    phone). When only ring + phone data exist, the result is
    identical to the original hardcoded ring>phone dedupe.
    """
    pm = priority_map or DEFAULT_PRIORITY
    log.info(f"Deduping sources with priority: {pm}")
    with conn.cursor() as cur:
        for metric in DEDUPE_METRICS:
            if metric not in _DEDUPE_TABLE_SLOT:
                continue  # unknown metric, skip safely
            table, slot_keys = _DEDUPE_TABLE_SLOT[metric]
            priority = pm.get(metric, ())
            if not priority:
                continue
            n = _drop_non_preferred(cur, table, slot_keys, priority)
            if n:
                log.info(f"  {table}: removed {n} non-preferred row(s)")
    conn.commit()

