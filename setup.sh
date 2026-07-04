#!/usr/bin/env python3
"""
Setup script for Smart Ring pipeline.
Installs dependencies, configures environment, and sets up cron jobs.
"""
import os
import subprocess
import sys
import time
import logging
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.FileHandler(SCRIPT_DIR / "setup.log"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

PROJECT_ROOT = SCRIPT_DIR
COLMI_CLIENT_DIR = PROJECT_ROOT / "colmi_client"

def run_command(cmd, check=True, capture=True):
    """Run shell command."""
    log.info(f"Running: {cmd}")
    try:
        if capture:
            result = subprocess.run(cmd, shell=True, check=check, capture_output=True, text=True)
            return result.returncode, result.stdout, result.stderr
        else:
            subprocess.run(cmd, shell=True, check=check, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            return 0, "", ""
    except subprocess.CalledProcessError as e:
        log.error(f"Command failed: {cmd}")
        log.error(f"Exit code: {e.returncode}")
        if e.stdout:
            log.error(f"Stdout: {e.stdout}")
        if e.stderr:
            log.error(f"Stderr: {e.stderr}")
        raise

def setup_python_dependencies():
    """Set up Python virtual environment and install dependencies."""
    log.info("Setting up Python dependencies...")

    venv_path = PROJECT_ROOT / "venv"

    if not venv_path.exists():
        log.info("Creating Python virtual environment...")
        run_command(f"python3 -m venv {venv_path}")

    python_path = venv_path / "bin" / "python3"

    log.info("Installing Python packages...")
    run_command(f"{python_path} -m pip install --upgrade pip")

    # Requirements for collector
    collector_req = PROJECT_ROOT / "collector" / "requirements.txt"
    if collector_req.exists():
        run_command(f"{python_path} -m pip install -r {collector_req}")

    # colmi-r02-client
    log.info("Installing colmi-r02-client...")
    run_command(f"{python_path} -m pip install git+https://github.com/tahnok/colmi_r02_client.git")

    # Additional packages for analytics
    run_command(f"{python_path} -m pip install numpy")

    return python_path

def setup_postgres():
    """Initialize Postgres database."""
    log.info("Setting up Postgres database...")

    # Install PostgreSQL client if needed
    run_command("apt-get update && apt-get install -y postgresql-client 2>/dev/null || true")

    env_file = PROJECT_ROOT / ".env"
    env_example = PROJECT_ROOT / ".env.example"

    if not env_file.exists() and env_example.exists():
        log.info("Creating .env file from .env.example...")
        import shutil
        shutil.copy(env_example, env_file)
    elif not env_file.exists():
        log.info("Creating .env file...")
        with open(env_file, "w") as f:
            f.write("DATABASE_URL=postgresql://smart_ring:changeme@localhost:5432/smart_ring\n")
            f.write("RING_ADDRESS=\n")
            f.write("POSTGRES_PASSWORD=changeme\n")

    # Wait for PostgreSQL
    log.info("Waiting for PostgreSQL to be ready...")
    for i in range(30):
        rc, _, _ = run_command("pg_isready -U smart_ring -d smart_ring 2>/dev/null", check=False)
        if rc == 0:
            log.info("PostgreSQL is ready")
            break
        time.sleep(1)
    else:
        log.warning("PostgreSQL did not become ready within 30s — continuing anyway")

    # Run initialization script
    init_file = PROJECT_ROOT / "db" / "init.sql"
    if init_file.exists():
        run_command(f"psql -U smart_ring -d smart_ring -f {init_file}")

def setup_collector_cron(python_path: str):
    """Set up cron job for ring collector."""
    log.info("Setting up collector cron job...")

    # Create collector script wrapper if it doesn't exist
    script_path = PROJECT_ROOT / "collector" / "collector-wrapper.py"
    if not script_path.exists():
        with open(script_path, "w") as f:
            f.write("""#!/usr/bin/env python3
import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from collector.sync_ring import main
asyncio.run(main())
""")
        os.chmod(script_path, 0o755)
        log.info("Created collector-wrapper.py")

    # Add to crontab: every 2 hours at minute 0
    cron_cmd = f"{python_path} {script_path}"
    run_command(f"(crontab -l 2>/dev/null; echo '0 */2 * * * {cron_cmd}') | crontab -")

    log.info("Collector cron setup: every 2 hours at minute 0")

def setup_analytics_cron(python_path: str):
    """Set up cron job for analytics."""
    log.info("Setting up analytics cron job...")

    # Create analytics script wrapper if it doesn't exist
    script_path = PROJECT_ROOT / "collector" / "analytics-wrapper.py"
    if not script_path.exists():
        with open(script_path, "w") as f:
            f.write("""#!/usr/bin/env python3
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from collector.analytics import main
main()
""")
        os.chmod(script_path, 0o755)
        log.info("Created analytics-wrapper.py")

    # Add to crontab (run 2 minutes after collector)
    cron_cmd = f"{python_path} {script_path}"
    run_command(f"(crontab -l 2>/dev/null; echo '2 */2 * * * {cron_cmd}') | crontab -")

    log.info("Analytics cron setup: every 2 hours at minute 2 (after collector)")

def create_test_data_script(python_path: str):
    """Create script for testing open questions if it doesn't exist."""
    script_path = PROJECT_ROOT / "collector" / "test_open_questions.py"

    if not script_path.exists():
        with open(script_path, "w") as f:
            f.write("""#!/usr/bin/env python3
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
""")

        os.chmod(script_path, 0o755)
        log.info("Created test script for open questions")

def main():
    """Main setup function."""
    log.info("=== Smart Ring Pipeline Setup ===")

    try:
        # Setup Python environment
        python_path = setup_python_dependencies()

        # Setup database
        setup_postgres()

        # Setup cron jobs
        setup_collector_cron(python_path)
        setup_analytics_cron(python_path)

        # Create test scripts
        create_test_data_script(python_path)

        log.info("=== Setup complete ===")
        log.info("Next steps:")
        log.info("1. Scan for ring: python3 collector/sync_ring.py scan")
        log.info("2. Set RING_ADDRESS in .env file")
        log.info("3. Start services: podman-compose -f docker-compose.yml up -d")
        log.info("4. Run first sync: python3 collector/sync_ring.py")
        log.info("5. Test open questions: python3 collector/test_open_questions.py")
        log.info("6. Monitor logs: collector/collector.log collector/analytics.log")

    except Exception as e:
        log.exception("Setup failed")
        sys.exit(1)

if __name__ == "__main__":
    main()
