"""Shared pytest fixtures.

Every test runs against an isolated file-backed repository and local object
store so no test can observe another test's data. Environment variables are
set before the application package is imported: the pipeline must never call
a real AI provider or AWS service during the unit test run.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Configure the application before importing it.
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

from backend.src.common.config import Settings, get_settings, reset_settings_cache  # noqa: E402
from backend.src.common.repository import LocalRepository, reset_repository  # noqa: E402
from backend.src.documents.storage import Storage, reset_storage  # noqa: E402


@pytest.fixture(autouse=True)
def isolated_environment(tmp_path, monkeypatch):
    """Reset all process-global singletons around every test."""
    for name in (
        "PROCESSING_QUEUE_URL",
        "STATE_MACHINE_ARN",
        "REPORTS_WORKER_FUNCTION",
        "AI_SECRET_ARN",
        "AI_API_KEY",
        "INTAKE_KEY",
        "COGNITO_USER_POOL_ID",
        "COGNITO_CLIENT_ID",
    ):
        monkeypatch.delenv(name, raising=False)

    reset_settings_cache()
    settings = Settings()
    settings.local_store_path = str(tmp_path / "data")

    repo = LocalRepository(str(tmp_path / "repo"))
    storage = Storage(settings)
    reset_repository(repo)
    reset_storage(storage)

    yield settings

    reset_repository(None)
    reset_storage(None)
    reset_settings_cache()


@pytest.fixture
def settings(isolated_environment) -> Settings:
    return isolated_environment


@pytest.fixture
def repo(isolated_environment):
    from backend.src.common.repository import get_repository

    return get_repository()


@pytest.fixture
def storage(isolated_environment):
    from backend.src.documents.storage import get_storage

    return get_storage()


@pytest.fixture
def runtime(settings, repo, storage):
    class Runtime:
        pass

    value = Runtime()
    value.settings = settings
    value.repo = repo
    value.storage = storage
    return value


@pytest.fixture
def app_settings():
    """Settings instance from the cached accessor, used for auth tests."""
    return get_settings()
