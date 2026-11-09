"""Render Web Service entry point."""

import os
import sys
from pathlib import Path

# Ensure backend root is on sys.path
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
PARENT = ROOT.parent
if str(PARENT) not in sys.path:
    sys.path.insert(0, str(PARENT))

import uvicorn
from backend.main import app

if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8000"))
    host = os.environ.get("HOST", "0.0.0.0")
    workers = int(os.environ.get("WEB_CONCURRENCY", "2"))
    print(f"Starting AWS Student Builder AI Recruitment API on {host}:{port}")
    uvicorn.run("backend.main:app", host=host, port=port, workers=workers, log_level="info")

