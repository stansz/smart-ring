#!/usr/bin/env python3
import asyncio
import sys
sys.path.insert(0, "/home/sz/Code/smart-ring")
from collector.sync_ring import main
asyncio.run(main())