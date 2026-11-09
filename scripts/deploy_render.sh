#!/usr/bin/env bash
# =============================================================================
# Deploy FastAPI Backend and Background Worker to Render
# =============================================================================
set -e

echo "[1/3] Running automated backend test suite..."
pytest tests/test_fastapi_endpoints.py

echo "[2/3] Checking git branch status..."
git status -s

echo "[3/3] Deployment trigger:"
echo "Push your commits to your GitHub/GitLab repository connected to Render."
echo "Render will automatically build and deploy both services from render.yaml:"
echo "  - Web Service: sbg-recruitment-api"
echo "  - Background Worker: sbg-recruitment-worker"
echo "Monitor logs at: https://dashboard.render.com"

