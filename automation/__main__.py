"""Allow `python -m automation` to run the daily pipeline (PLAN §9.1)."""
from __future__ import annotations

import sys

from .orchestrator import main

if __name__ == "__main__":
    sys.exit(main())
