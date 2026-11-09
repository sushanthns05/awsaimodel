"""Environment driven configuration.

Values are read once per container invocation. Secrets are never stored in
source control; they are loaded from AWS Secrets Manager when configured.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

CONFIG_DIR = Path(__file__).resolve().parent.parent / "config"


def env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def load_json_file(name: str) -> dict[str, Any]:
    path = CONFIG_DIR / name
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


@dataclass
class Settings:
    env: str = field(default_factory=lambda: os.getenv("ENVIRONMENT", "dev"))
    region: str = field(default_factory=lambda: os.getenv("AWS_REGION", "ap-south-1"))
    stage: str = field(default_factory=lambda: os.getenv("STAGE", "dev"))

    applicants_table: str = field(default_factory=lambda: os.getenv("APPLICANTS_TABLE", "sbg-applicants"))
    evaluations_table: str = field(default_factory=lambda: os.getenv("EVALUATIONS_TABLE", "sbg-evaluations"))
    audit_table: str = field(default_factory=lambda: os.getenv("AUDIT_TABLE", "sbg-audit"))
    config_table: str = field(default_factory=lambda: os.getenv("CONFIG_TABLE", "sbg-config"))
    reports_table: str = field(default_factory=lambda: os.getenv("REPORTS_TABLE", "sbg-reports"))

    resume_bucket: str = field(default_factory=lambda: os.getenv("RESUME_BUCKET", "sbg-resumes-local"))
    report_bucket: str = field(default_factory=lambda: os.getenv("REPORT_BUCKET", "sbg-reports-local"))
    resume_kms_key: str = field(default_factory=lambda: os.getenv("RESUME_KMS_KEY", ""))
    report_kms_key: str = field(default_factory=lambda: os.getenv("REPORT_KMS_KEY", ""))

    processing_queue_url: str = field(default_factory=lambda: os.getenv("PROCESSING_QUEUE_URL", ""))
    state_machine_arn: str = field(default_factory=lambda: os.getenv("STATE_MACHINE_ARN", ""))

    ai_base_url: str = field(default_factory=lambda: os.getenv("AI_BASE_URL", "https://api.deepseek.com/v1"))
    ai_model: str = field(default_factory=lambda: os.getenv("AI_MODEL", "deepseek-flash"))
    ai_secret_arn: str = field(default_factory=lambda: os.getenv("AI_SECRET_ARN", ""))
    ai_api_key: str = field(default_factory=lambda: os.getenv("AI_API_KEY", ""))
    ai_timeout_seconds: float = field(default_factory=lambda: env_float("AI_TIMEOUT_SECONDS", 90.0))
    ai_max_retries: int = field(default_factory=lambda: env_int("AI_MAX_RETRIES", 4))
    ai_max_concurrency: int = field(default_factory=lambda: env_int("AI_MAX_CONCURRENCY", 8))
    ai_temperature: float = field(default_factory=lambda: env_float("AI_TEMPERATURE", 0.1))
    ai_max_input_chars: int = field(default_factory=lambda: env_int("AI_MAX_INPUT_CHARS", 60000))

    intake_secret_arn: str = field(default_factory=lambda: os.getenv("INTAKE_SECRET_ARN", ""))
    intake_key: str = field(default_factory=lambda: os.getenv("INTAKE_KEY", ""))
    intake_signature_required: bool = field(default_factory=lambda: env_bool("INTAKE_SIGNATURE_REQUIRED", True))
    intake_signature_tolerance_seconds: int = field(
        default_factory=lambda: env_int("INTAKE_SIGNATURE_TOLERANCE_SECONDS", 900)
    )
    max_submission_bytes: int = field(default_factory=lambda: env_int("MAX_SUBMISSION_BYTES", 8 * 1024 * 1024))
    max_document_bytes: int = field(default_factory=lambda: env_int("MAX_DOCUMENT_BYTES", 6 * 1024 * 1024))
    max_documents: int = field(default_factory=lambda: env_int("MAX_DOCUMENTS", 8))

    cognito_user_pool_id: str = field(default_factory=lambda: os.getenv("COGNITO_USER_POOL_ID", ""))
    cognito_client_id: str = field(default_factory=lambda: os.getenv("COGNITO_CLIENT_ID", ""))
    cognito_region: str = field(default_factory=lambda: os.getenv("COGNITO_REGION", os.getenv("AWS_REGION", "ap-south-1")))
    auth_disabled: bool = field(default_factory=lambda: env_bool("AUTH_DISABLED", False))

    use_local_store: bool = field(default_factory=lambda: env_bool("USE_LOCAL_STORE", False))
    local_store_path: str = field(
        default_factory=lambda: os.getenv("LOCAL_STORE_PATH", str(Path(__file__).resolve().parents[3] / "backend" / ".local-store"))
    )
    textract_enabled: bool = field(default_factory=lambda: env_bool("TEXTRACT_ENABLED", True))
    malware_scan_enabled: bool = field(default_factory=lambda: env_bool("MALWARE_SCAN_ENABLED", False))
    malware_scan_lambda: str = field(default_factory=lambda: os.getenv("MALWARE_SCAN_LAMBDA", ""))
    report_signed_url_seconds: int = field(default_factory=lambda: env_int("REPORT_SIGNED_URL_SECONDS", 900))
    reports_worker_function: str = field(default_factory=lambda: os.getenv("REPORTS_WORKER_FUNCTION", ""))
    local_inline_processing: bool = field(default_factory=lambda: env_bool("LOCAL_INLINE_PROCESSING", True))
    document_signed_url_seconds: int = field(default_factory=lambda: env_int("DOCUMENT_SIGNED_URL_SECONDS", 300))
    cors_origin: str = field(default_factory=lambda: os.getenv("CORS_ORIGIN", "*"))
    org_name: str = field(default_factory=lambda: os.getenv("ORG_NAME", "AWS Student Builder Group"))
    institution: str = field(default_factory=lambda: os.getenv("INSTITUTION", "SJB Institute of Technology"))
    cycle: str = field(default_factory=lambda: os.getenv("RECRUITMENT_CYCLE", "2026-27"))
    ai_provider: str = field(default_factory=lambda: os.getenv("AI_PROVIDER", "deepseek"))
    schema_version: int = 1

    @property
    def is_local(self) -> bool:
        return self.use_local_store or self.env in ("local", "test")


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()


def reset_settings_cache() -> None:
    get_settings.cache_clear()
