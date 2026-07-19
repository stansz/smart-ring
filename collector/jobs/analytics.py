import logging
from pathlib import Path
from .base import SyncJob

log = logging.getLogger(__name__)


class AnalyticsJob(SyncJob):
    """Recompute analytics metrics after a sync or phone upload."""

    def __init__(self, python: Path, project_root: Path):
        super().__init__(python, project_root)
        self.script = project_root / "collector" / "analytics.py"

    def run(self) -> tuple[int, str, str]:
        log.info("Running analytics (compute metrics)...")
        return self._run_subprocess(self.script, timeout=300)
