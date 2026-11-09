"""Typed access to editable configuration with validation.

Packaged JSON files provide defaults. Administrators can override any
configuration at runtime; overrides are stored in DynamoDB with a version
number and every change is auditable.
"""

from __future__ import annotations

import copy
from typing import Any, Optional

from .config import load_json_file
from .errors import ValidationError
from .models import iso, utcnow
from .repository import Repository, get_repository

CONFIG_KEYS = {
    "rubric": "rubric",
    "eligibility": "eligibility",
    "roles": "roles",
    "field_mapping": "field_mapping",
    "ai": "ai",
    "processing": "processing",
    "organization": "organization",
}

DEFAULT_FILES = {
    "rubric": "rubric.json",
    "eligibility": "eligibility.json",
    "roles": "roles.json",
    "field_mapping": "field-mapping.json",
}

DEFAULT_AI_CONFIG: dict[str, Any] = {
    "provider": "deepseek",
    "model": "deepseek-flash",
    "base_url": "https://api.deepseek.com/v1",
    "timeout_seconds": 90,
    "max_retries": 4,
    "temperature": 0.1,
    "enabled": True,
    "max_input_chars": 60000,
    "store_prompts": False,
}

DEFAULT_PROCESSING_CONFIG: dict[str, Any] = {
    "max_document_bytes": 10485760,
    "max_documents": 8,
    "allowed_extensions": ["pdf", "docx", "doc", "png", "jpg", "jpeg"],
    "textract_enabled": True,
    "malware_scan_enabled": False,
    "min_extracted_chars": 40,
    "auto_reprocess_failed": False,
    "reprocess_max_attempts": 3,
}


def _default(key: str) -> dict[str, Any]:
    if key in DEFAULT_FILES:
        return load_json_file(DEFAULT_FILES[key])
    if key == "ai":
        from .config import get_settings

        settings = get_settings()
        return {
            "provider": settings.ai_provider,
            "model": settings.ai_model,
            "base_url": settings.ai_base_url,
            "timeout_seconds": settings.ai_timeout_seconds,
            "max_retries": settings.ai_max_retries,
            "temperature": settings.ai_temperature,
            "enabled": True,
            "max_input_chars": settings.ai_max_input_chars,
            "store_prompts": False,
        }
    if key == "processing":
        return copy.deepcopy(DEFAULT_PROCESSING_CONFIG)
    if key == "organization":
        return {
            "name": "AWS Student Builder Group",
            "institution": "SJB Institute of Technology",
            "cycle": "2026-27",
        }
    raise ValidationError(f"Unknown configuration key: {key}")


def get_config(key: str, repo: Optional[Repository] = None) -> dict[str, Any]:
    if key not in CONFIG_KEYS:
        raise ValidationError(f"Unknown configuration key: {key}")
    repo = repo or get_repository()
    stored = repo.get_config(key)
    if stored and isinstance(stored.get("value"), dict):
        value = copy.deepcopy(stored["value"])
        value.setdefault("_version", stored.get("version", 1))
        return value
    default = _default(key)
    default["_version"] = 0
    return default


def get_config_meta(key: str, repo: Optional[Repository] = None) -> dict[str, Any]:
    repo = repo or get_repository()
    stored = repo.get_config(key)
    return {
        "key": key,
        "version": stored["version"] if stored else 0,
        "updated_at": stored["updated_at"] if stored else None,
        "updated_by": stored["updated_by"] if stored else "default",
        "source": "dynamodb" if stored else "packaged_default",
    }


def validate_config(key: str, value: Any) -> None:
    if not isinstance(value, dict):
        raise ValidationError("Configuration must be a JSON object")
    if key == "rubric":
        criteria = value.get("criteria")
        if not isinstance(criteria, list) or not criteria:
            raise ValidationError("Rubric must contain at least one criterion")
        ids = set()
        total = 0.0
        for criterion in criteria:
            cid = str(criterion.get("id", "")).strip()
            if not cid or cid in ids:
                raise ValidationError("Criterion ids must be present and unique")
            ids.add(cid)
            try:
                max_score = float(criterion.get("max_score"))
            except (TypeError, ValueError) as exc:
                raise ValidationError(f"Criterion {cid} has an invalid max_score") from exc
            if max_score <= 0 or max_score > 100:
                raise ValidationError(f"Criterion {cid} max_score must be between 0 and 100")
            total += max_score
        declared = float(value.get("total_points", 100))
        if abs(total - declared) > 0.001:
            raise ValidationError(f"Criterion maximums sum to {total}, expected {declared}")
        thresholds = value.get("recommendation_thresholds")
        if not isinstance(thresholds, list) or not thresholds:
            raise ValidationError("recommendation_thresholds must be a non-empty list")
        previous = 1e9
        for band in thresholds:
            score = float(band.get("min_score", 0))
            if score > previous:
                raise ValidationError("Recommendation thresholds must be in descending order")
            previous = score
    elif key == "eligibility":
        rules = value.get("rules")
        if not isinstance(rules, list) or not rules:
            raise ValidationError("Eligibility configuration must contain rules")
        for rule in rules:
            for field in ("id", "label", "field", "type"):
                if not rule.get(field):
                    raise ValidationError(f"Eligibility rule missing {field}")
            if rule["type"] not in (
                "required", "pattern", "min_number", "max_number", "one_of", "contains", "boolean_true",
            ):
                raise ValidationError(f"Unsupported eligibility rule type: {rule['type']}")
    elif key == "roles":
        roles = value.get("roles")
        if not isinstance(roles, list) or not roles:
            raise ValidationError("At least one role must be configured")
        ids = set()
        for role in roles:
            rid = str(role.get("id", "")).strip()
            if not rid or rid in ids:
                raise ValidationError("Role ids must be present and unique")
            ids.add(rid)
            weights = role.get("weights")
            if not isinstance(weights, dict) or not weights:
                raise ValidationError(f"Role {rid} must define weights")
            total = sum(float(v) for v in weights.values())
            if abs(total - 100.0) > 0.01:
                raise ValidationError(f"Role {rid} weights sum to {total}, expected 100")
    elif key == "field_mapping":
        fields = value.get("fields")
        if not isinstance(fields, list) or not fields:
            raise ValidationError("Field mapping must contain fields")
        seen = set()
        for item in fields:
            canonical = item.get("canonical")
            if not canonical or canonical in seen:
                raise ValidationError("Field mapping canonical names must be present and unique")
            seen.add(canonical)
    elif key == "programme" or key == "organization":
        pass
    elif key == "ai":
        if value.get("enabled") is not None and not isinstance(value["enabled"], bool):
            raise ValidationError("ai.enabled must be boolean")
    elif key == "processing":
        pass


def put_config(key: str, value: dict[str, Any], actor: str, repo: Optional[Repository] = None) -> dict[str, Any]:
    if key not in CONFIG_KEYS:
        raise ValidationError(f"Unknown configuration key: {key}")
    validate_config(key, value)
    repo = repo or get_repository()
    clean = {k: v for k, v in value.items() if not k.startswith("_")}
    return repo.put_config(key, clean, actor=actor)


def rubric(repo: Optional[Repository] = None) -> dict[str, Any]:
    return get_config("rubric", repo)


def eligibility_config(repo: Optional[Repository] = None) -> dict[str, Any]:
    return get_config("eligibility", repo)


def roles_config(repo: Optional[Repository] = None) -> dict[str, Any]:
    return get_config("roles", repo)


def field_mapping(repo: Optional[Repository] = None) -> dict[str, Any]:
    return get_config("field_mapping", repo)


def ai_config(repo: Optional[Repository] = None) -> dict[str, Any]:
    return get_config("ai", repo)


def processing_config(repo: Optional[Repository] = None) -> dict[str, Any]:
    return get_config("processing", repo)


def organization_config(repo: Optional[Repository] = None) -> dict[str, Any]:
    return get_config("organization", repo)


def public_settings(repo: Optional[Repository] = None) -> dict[str, Any]:
    """Settings payload for the dashboard. Never includes secrets."""
    repo = repo or get_repository()
    return {
        "rubric": rubric(repo),
        "eligibility": eligibility_config(repo),
        "roles": roles_config(repo),
        "field_mapping": field_mapping(repo),
        "processing": processing_config(repo),
        "organization": organization_config(repo),
        "meta": {key: get_config_meta(key, repo) for key in CONFIG_KEYS},
        "generated_at": iso(utcnow()),
    }
