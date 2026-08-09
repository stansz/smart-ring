"""Generic upsert helper for the mobile_sync endpoint.

The simple point tables (heart_rate, spo2, temperature, stress, steps)
share identical INSERT shape — only the table name and column list
differ. This module factors out the dispatch so adding a new simple
point type is one row in mobile_sync's dispatch table, not a
copy-pasted 12-line INSERT block.

Tables with non-standard semantics stay as explicit blocks in
mobile_sync:
  - raw_hrv:    hrv_type defaults to 'composite'; conflict clause
                includes hrv_type, not just (ts, source)
  - raw_sleep:  day-based schema, multiple time fields, conflict on
                (start_ts, stage, source)
  - ring_goals: singleton (not a list), no source column

Forcing these through the generic dispatcher would obscure their
per-table contracts.
"""
from __future__ import annotations

from typing import Iterable, Sequence

from sqlalchemy import text
from sqlalchemy.orm import Session


def validate_record(table: str, record: dict) -> list[str]:
    """Validate field ranges for a single record.

    Returns a list of validation errors (empty if valid). Mirrors the
    collector's range checks in collector/protocol/db.py and adds
    sensible bounds for fields the collector doesn't validate.

    Args:
        table: target table name (e.g., 'raw_heart_rate')
        record: dict with the record fields (must include 'ts' and
                required cols)

    Returns:
        List of error messages. Empty list means the record is valid.
    """
    errors: list[str] = []
    
    # BPM: mirror collector (30 < bpm < 250)
    if table == "raw_heart_rate":
        bpm = record.get("bpm")
        if bpm is not None and not (30 < bpm < 250):
            errors.append(f"bpm {bpm} out of range (30, 250)")
    
    # SpO2: 0-100 (human blood oxygen)
    elif table == "raw_spo2":
        spo2 = record.get("spo2_pct")
        if spo2 is not None and not (0 <= spo2 <= 100):
            errors.append(f"spo2_pct {spo2} out of range [0, 100]")
    
    # Temperature: skin-temp range (20-50°C, generous for ring)
    elif table == "raw_temperature":
        temp = record.get("temp_c")
        if temp is not None and not (20.0 <= temp <= 50.0):
            errors.append(f"temp_c {temp} out of range [20.0, 50.0]")
    
    # Stress: 0-99 scale (ring's domain)
    elif table == "raw_stress":
        stress = record.get("stress_value")
        if stress is not None and not (0 <= stress <= 99):
            errors.append(f"stress_value {stress} out of range [0, 99]")
    
    # Steps: 0-50000 per slot (generous upper bound)
    elif table == "raw_steps":
        steps = record.get("steps")
        if steps is not None and not (0 <= steps <= 50000):
            errors.append(f"steps {steps} out of range [0, 50000]")
    
    return errors


def upsert_many(
    db: Session,
    *,
    table: str,
    required_cols: Sequence[str],
    records: Iterable[dict],
    optional_cols: Sequence[str] | None = None,
    source: str = "phone",
) -> tuple[int, int, list[str]]:
    """Generic upsert for simple point tables.

    Executes per record:

        INSERT INTO {table} (ts, <required_cols>, <optional_cols>, source)
        VALUES (:ts, :<req>, :<opt>, :source)
        ON CONFLICT (ts, source) DO NOTHING

    Per-row semantics (preserves the original inline blocks behavior,
    pinned by tests/test_mobile_sync.py):
      - Missing 'ts' or any required col -> KeyError -> caught -> skipped
      - ON CONFLICT DO NOTHING doesn't raise -> counted as accepted
        (current per-attempt semantics; the response's `accepted` field
        counts attempts, not actually-inserted rows)
      - Any other DB error caught and reported via the errors list

    Args:
        db: SQLAlchemy session (caller owns commit/rollback)
        table: target table name (e.g., 'raw_heart_rate')
        required_cols: columns that must be present in each record
            (KeyError if missing — caught and counted as skipped)
        records: iterable of record dicts; each must contain 'ts' and
            every required column
        optional_cols: columns read via dict.get() — inserted as NULL
            when absent from the record
        source: 'phone' or 'ring' (default 'phone')

    Returns:
        (accepted, skipped, errors) — caller aggregates across types.
    """
    optional_cols = optional_cols or []
    all_cols = ["ts", *required_cols, *optional_cols, "source"]
    col_list = ", ".join(all_cols)
    param_list = ", ".join(f":{c}" for c in all_cols)
    sql = text(f"""
        INSERT INTO {table} ({col_list})
        VALUES ({param_list})
        ON CONFLICT (ts, source) DO NOTHING
    """)
    label = table.replace("raw_", "")

    accepted = 0
    skipped = 0
    errors: list[str] = []
    for r in records:
        try:
            # Validate field ranges before attempting insert
            validation_errors = validate_record(table, r)
            if validation_errors:
                errors.extend([f"{label}: {err}" for err in validation_errors])
                skipped += 1
                continue
            
            params: dict[str, object] = {"ts": r["ts"], "source": source}
            for c in required_cols:
                params[c] = r[c]  # KeyError if missing -> caught
            for c in optional_cols:
                params[c] = r.get(c)  # None if missing -> NULL
            db.execute(sql, params)
            accepted += 1
        except Exception as e:
            errors.append(f"{label}: {e}")
            skipped += 1
    return accepted, skipped, errors
