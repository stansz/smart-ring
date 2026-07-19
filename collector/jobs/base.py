from abc import ABC, abstractmethod
import subprocess
from pathlib import Path
from typing import Tuple


class SyncJob(ABC):
    """Abstract job executed by the poller.
    
    Each job encapsulates a subprocess invocation. The poller claims
    sync_requests rows and delegates to the appropriate job.
    """

    def __init__(self, python: Path, project_root: Path):
        self.python = python
        self.project_root = project_root

    @abstractmethod
    def run(self) -> Tuple[int, str, str]:
        """Execute the job. Returns (returncode, stdout, stderr)."""
        raise NotImplementedError

    def _run_subprocess(
        self, script: Path, timeout: int
    ) -> Tuple[int, str, str]:
        proc = subprocess.run(
            [str(self.python), str(script)],
            capture_output=True,
            text=True,
            cwd=str(self.project_root),
            timeout=timeout,
        )
        return proc.returncode, proc.stdout, proc.stderr
