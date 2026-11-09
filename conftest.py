"""Root pytest configuration and shared fixtures."""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Configure the application before importing it so no module attempts network calls to AWS.
os.environ["ENVIRONMENT"] = "test"
os.environ["USE_LOCAL_STORE"] = "true"
os.environ["AUTH_DISABLED"] = "true"
os.environ["AI_PROVIDER"] = "mock"
os.environ["TEXTRACT_ENABLED"] = "false"
os.environ["MALWARE_SCAN_ENABLED"] = "false"
os.environ["LOCAL_INLINE_PROCESSING"] = "true"
os.environ.setdefault("LOG_FORMAT", "text")
for _secret in ("AI_API_KEY", "AI_SECRET_ARN", "INTAKE_KEY", "INTAKE_SECRET_ARN"):
    os.environ.pop(_secret, None)

from backend.tests.conftest import *  # noqa: F403
