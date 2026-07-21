"""Analytics entry point — main() + run_all() orchestration."""
from __future__ import annotations

import logging
import sys

from . import circadian, current_status, data_quality, daily_activity, dedupe, db
from . import hrv, readiness, rhr, sleep, stress

log = logging.getLogger(__name__)


def run_all() -> None:
    """Run all analytics scorers in dependency order."""
    log.info("=== Starting analytics run ===")
    with db.connect() as conn:
        # Dedup first — every downstream scorer should see ring-canonical data.
        try:
            dedupe.dedupe_sources(conn)
        except Exception as e:
            log.error(f"Source dedup failed: {e}", exc_info=True)

        for name, fn in [
            ("HRV recovery", hrv.compute_hrv_recovery),
            ("Sleep quality", sleep.compute_sleep_quality),
            ("Stress", stress.compute_stress),
            ("Circadian HR", circadian.compute_circadian_hr),
            ("Daily activity", daily_activity.compute_daily_activity),
            ("Readiness", readiness.compute_readiness_score),
            ("Current status", current_status.compute_current_status),
            ("Resting HR", rhr.compute_resting_hr),
            ("Data quality", data_quality.compute_data_quality),
        ]:
            try:
                fn(conn)
            except Exception as e:
                log.error(f"{name} failed: {e}", exc_info=True)

    log.info("=== Analytics complete ===")


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.StreamHandler()],
    )
    try:
        log.info("Starting analytics job...")
        run_all()
        log.info("Analytics job completed successfully")
    except Exception:
        log.exception("Analytics failed")
        sys.exit(1)


if __name__ == "__main__":
    main()
