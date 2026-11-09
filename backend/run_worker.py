"""Render Background Worker entry point."""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
PARENT = ROOT.parent
if str(PARENT) not in sys.path:
    sys.path.insert(0, str(PARENT))

from backend.workers.sqs_worker import main

if __name__ == "__main__":
    print("Starting AWS Student Builder AI Recruitment Background Worker...")
    main()

