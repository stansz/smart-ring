import logging
import subprocess
from pathlib import Path
from .base import SyncJob

log = logging.getLogger(__name__)


class AnalyticsJob(SyncJob):
    """Recompute analytics metrics after a sync or phone upload."""

    def run(self) -> tuple[int, str, str]:
        log.info("Running analytics (compute metrics)...")
        proc = subprocess.run(
            [str(self.python), "-m", "collector.analytics"],
            capture_output=True,
            text=True,
            cwd=str(self.project_root),
            timeout=300,
        )
        return proc.returncode, proc.stdout, proc.stderr
