"""Analytics package.

Phase 4 split: each scorer lives in its own module. Entry point is
`collector/analytics/__init__.py:main()` which sets up the DB connection
and timezone, then calls each scorer in order.
"""
from .main import main

__all__ = ["main"]
