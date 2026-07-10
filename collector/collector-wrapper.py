#!/usr/bin/env python3
import asyncio
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from collector.sync_ring import main

# Force --forget so the R09 reconnect-bug workaround is always applied.
# Without this, sync_ring.main() won't do forget_and_repair before connecting
# or forget after disconnect, and the next sync will hit the stale-GATT bug.
if "--forget" not in sys.argv:
    sys.argv.append("--forget")

asyncio.run(main())