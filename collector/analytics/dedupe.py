"""Source dedup — ring is canonical, phone fills gaps.

Phase 4 also marks this as the single source of truth: api/main.py's
`_dedupe_sources` is now redundant and can be dropped (Phase 5).
"""
from __future__ import annotations

import logging

log = logging.getLogger(__name__)


def dedupe_sources(conn) -> None:
    """Remove 'phone' records that duplicate 'ring' records.

    Ring is the canonical collector (Linux box). Phone sync (Web Bluetooth)
    is a fallback that fills gaps when the ring hasn't been synced. Since both
    sample the same physical slots, ~99% of phone records can duplicate ring.
    We keep ring and drop phone wherever they overlap, so every downstream
    query and score sees one measurement per slot.

    Point tables dedupe on timestamp (HRV also on hrv_type). Sleep dedupes at
    the day level (ring's night wins wholesale if present).
    """
    log.info("Deduping phone vs ring sources...")
    point_tables = [
        ("raw_heart_rate", "r.ts = p.ts"),
        ("raw_spo2",       "r.ts = p.ts"),
        ("raw_temperature","r.ts = p.ts"),
        ("raw_stress",     "r.ts = p.ts"),
        ("raw_steps",      "r.ts = p.ts"),
        ("raw_hrv",        "r.ts = p.ts AND r.hrv_type = p.hrv_type"),
    ]
    with conn.cursor() as cur:
        for table, on_clause in point_tables:
            cur.execute(f"""
                DELETE FROM {table} p
                WHERE p.source = 'phone'
                  AND EXISTS (SELECT 1 FROM {table} r
                              WHERE r.source = 'ring' AND {on_clause})
            """)
            if cur.rowcount:
                log.info(f"  {table}: removed {cur.rowcount} phone duplicate(s)")
        cur.execute("""
            DELETE FROM raw_sleep p
            WHERE p.source = 'phone'
              AND EXISTS (SELECT 1 FROM raw_sleep r
                          WHERE r.source = 'ring' AND r.day = p.day)
        """)
        if cur.rowcount:
            log.info(f"  raw_sleep: removed {cur.rowcount} phone duplicate(s)")
    conn.commit()
