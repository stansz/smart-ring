import logging
from pathlib import Path
from .base import SyncJob

log = logging.getLogger(__name__)


class RingSyncJob(SyncJob):
    """Run the ring collector (sync_ring.py) as a subprocess."""

    def __init__(self, python: Path, project_root: Path, script: Path):
        super().__init__(python, project_root)
        self.script = script

    def run(self) -> tuple[int, str, str]:
        log.info(f"Running: {self.python} {self.script}")
        return self._run_subprocess(self.script, timeout=600)
