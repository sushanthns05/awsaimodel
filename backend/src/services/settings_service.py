"""Settings API service. Secrets are never returned to the client."""

from __future__ import annotations

import time
from typing import Any, Optional

from ..ai.client import AIClient, get_ai_client, load_api_key
from ..common import audit
from ..common.config import Settings, get_settings
from ..common.config_store import CONFIG_KEYS, get_config_meta, public_settings, put_config
from ..common.errors import ValidationError
from ..common.repository import Repository, get_repository
from ..documents.storage import get_storage
from ..common.models import iso, utcnow


def read_settings(repo: Optional[Repository] = None, settings: Optional[Settings] = None) -> dict[str, Any]:
    repo = repo or get_repository()
    settings = settings or get_settings()
    payload = public_settings(repo)
    ai = payload.get("ai") or {}
    payload["aiPublic"] = {
        "provider": ai.get("provider", settings.ai_provider),
        "model": ai.get("model", settings.ai_model),
        "baseUrl": ai.get("base_url", settings.ai_base_url),
        "enabled": bool(ai.get("enabled", True)),
        "timeoutSeconds": ai.get("timeout_seconds", settings.ai_timeout_seconds),
        "maxRetries": ai.get("max_retries", settings.ai_max_retries),
        "temperature": ai.get("temperature", settings.ai_temperature),
        "apiKeyConfigured": bool(settings.ai_api_key or settings.ai_secret_arn or load_api_key(settings)),
    }
    payload["environment"] = {
        "stage": settings.stage,
        "region": settings.region,
        "organization": settings.org_name,
        "institution": settings.institution,
        "cycle": settings.cycle,
        "localMode": settings.is_local,
        "googleFormConnected": bool(settings.intake_key),
        "processingQueueConfigured": bool(settings.processing_queue_url or settings.state_machine_arn),
        "resumeBucketConfigured": bool(settings.resume_bucket),
        "textractEnabled": settings.textract_enabled,
        "malwareScanEnabled": settings.malware_scan_enabled,
    }
    payload["meta"] = {key: get_config_meta(key, repo) for key in CONFIG_KEYS}
    payload["serverTime"] = iso(utcnow())
    return payload


def update_settings(
    key: str,
    value: dict[str, Any],
    *,
    actor: str,
    repo: Optional[Repository] = None,
) -> dict[str, Any]:
    repo = repo or get_repository()
    if key not in CONFIG_KEYS:
        raise ValidationError(f"Unknown settings section '{key}'")
    if key == "ai" and "api_key" in value:
        raise ValidationError("API keys must be stored in AWS Secrets Manager, not sent to the settings API")
    previous = repo.get_config(key)
    result = put_config(key, value, actor, repo)
    audit.record(
        "CONFIG_UPDATED",
        reviewer=actor,
        previous_value={"version": previous["version"] if previous else 0},
        updated_value={"key": key, "version": result["version"]},
        repo=repo,
    )
    return result


def test_ai_connection(
    *,
    repo: Optional[Repository] = None,
    settings: Optional[Settings] = None,
) -> dict[str, Any]:
    repo = repo or get_repository()
    settings = settings or get_settings()
    from ..common.config_store import ai_config

    config = ai_config(repo)
    client = get_ai_client(settings, config)
    if not isinstance(client, AIClient) or not client.enabled:
        return {
            "ok": False,
            "message": "AI provider is not configured. Add the API key to AWS Secrets Manager and set AI_SECRET_ARN.",
        }
    started = time.monotonic()
    try:
        result = client.chat(
            [
                {"role": "system", "content": "Return a JSON object only."},
                {"role": "user", "content": 'Return exactly {"ok": true} as JSON.'},
            ]
        )
        return {
            "ok": True,
            "model": result.model,
            "latencyMs": int((time.monotonic() - started) * 1000),
            "message": "AI provider responded successfully.",
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "message": "AI provider test failed.",
            "error": type(exc).__name__,
            "latencyMs": int((time.monotonic() - started) * 1000),
        }


def storage_health(settings: Optional[Settings] = None) -> dict[str, Any]:
    settings = settings or get_settings()
    storage = get_storage()
    try:
        if settings.is_local:
            return {"ok": True, "mode": "local", "bucket": settings.resume_bucket}
        import boto3

        s3 = boto3.client("s3", region_name=settings.region)
        s3.head_bucket(Bucket=settings.resume_bucket)
        s3.head_bucket(Bucket=settings.report_bucket)
        return {"ok": True, "mode": "s3", "bucket": settings.resume_bucket}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "mode": "s3" if not settings.is_local else "local", "error": type(exc).__name__}


ADMIN_GROUPS = ["sbg-admins", "sbg-reviewers", "sbg-viewers"]


def _cognito(settings: Settings):
    import boto3

    return boto3.client("cognito-idp", region_name=settings.cognito_region)


def list_admins(
    *,
    settings: Optional[Settings] = None,
    repo: Optional[Repository] = None,
) -> dict[str, Any]:
    settings = settings or get_settings()
    if settings.is_local or not settings.cognito_user_pool_id:
        return {
            "items": [
                {
                    "username": "local.admin",
                    "email": "local.admin@sbg.example",
                    "status": "CONFIRMED",
                    "groups": ["sbg-admins"],
                }
            ],
            "groups": ADMIN_GROUPS,
            "note": "Cognito is not configured in local mode. Showing the local development administrator.",
        }

    users: dict[str, dict[str, Any]] = {}
    client = _cognito(settings)
    for group in ADMIN_GROUPS:
        paginator = client.get_paginator("list_users_in_group")
        for page in paginator.paginate(UserPoolId=settings.cognito_user_pool_id, GroupName=group):
            for user in page.get("Users", []):
                username = user.get("Username", "")
                entry = users.setdefault(
                    username,
                    {
                        "username": username,
                        "email": next(
                            (attr["Value"] for attr in user.get("Attributes", []) if attr["Name"] == "email"),
                            "",
                        ),
                        "status": user.get("UserStatus", ""),
                        "groups": [],
                    },
                )
                if group not in entry["groups"]:
                    entry["groups"].append(group)
    return {"items": sorted(users.values(), key=lambda u: u["email"]), "groups": ADMIN_GROUPS}


def _find_username(client: Any, pool_id: str, email: str) -> str:
    response = client.list_users(
        UserPoolId=pool_id,
        Filter=f'email = "{email}"',
        Limit=2,
    )
    users = response.get("Users", [])
    if not users:
        raise ValidationError("No Cognito user exists with that email address. Invite the user first.")
    return str(users[0]["Username"])


def change_admin(
    email: str,
    group: str,
    action: str,
    *,
    actor: str,
    repo: Optional[Repository] = None,
    settings: Optional[Settings] = None,
) -> dict[str, Any]:
    settings = settings or get_settings()
    repo = repo or get_repository()
    email = email.strip().lower()
    if not email or "@" not in email:
        raise ValidationError("A valid email address is required")
    if group not in ADMIN_GROUPS:
        raise ValidationError(f"group must be one of {', '.join(ADMIN_GROUPS)}")
    if action not in ("add", "remove"):
        raise ValidationError("action must be add or remove")
    if settings.is_local or not settings.cognito_user_pool_id:
        audit.record(
            "ADMIN_GROUP_CHANGE",
            reviewer=actor,
            updated_value={"email": email, "group": group, "action": action, "mode": "local"},
            repo=repo,
        )
        return {"status": "SIMULATED", "email": email, "group": group}

    client = _cognito(settings)
    username = _find_username(client, settings.cognito_user_pool_id, email)
    if action == "add":
        client.admin_add_user_to_group(
            UserPoolId=settings.cognito_user_pool_id, Username=username, GroupName=group
        )
    else:
        if group == "sbg-admins":
            raise ValidationError("The administrators group cannot be removed through the dashboard")
        client.admin_remove_user_from_group(
            UserPoolId=settings.cognito_user_pool_id, Username=username, GroupName=group
        )
    audit.record(
        "ADMIN_GROUP_CHANGE",
        reviewer=actor,
        updated_value={"email": email, "group": group, "action": action},
        repo=repo,
    )
    return {"status": "UPDATED", "email": email, "group": group}
