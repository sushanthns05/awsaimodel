"""System settings, rubric, roles, field mapping, AI testing, and admin users router."""

from __future__ import annotations

from typing import Any, Dict, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status

from ...src.common.auth import Principal
from ...src.common.config_store import ai_config, field_mapping, processing_config, roles_config, rubric
from ...src.common.errors import ValidationError
from ...src.common.repository import Repository
from ...src.services import settings_service
from ...schemas import AdminChangeRequest
from ..deps import get_current_repo, require_permission

router = APIRouter(tags=["Settings"])


@router.get("/settings")
async def get_settings_data(
    principal: Principal = Depends(require_permission("settings")),
    repo: Repository = Depends(get_current_repo),
) -> Dict[str, Any]:
    """Retrieve active system configuration: rubric, eligibility, roles, and field mappings."""
    return settings_service.read_settings(repo=repo)


@router.put("/settings/{key}")
async def update_settings_key(
    key: str,
    payload: Dict[str, Any],
    principal: Principal = Depends(require_permission("settings")),
    repo: Repository = Depends(get_current_repo),
) -> Dict[str, Any]:
    """Update a specific configuration section (rubric, eligibility, roles, field_mapping, processing, ai)."""
    actor = principal.email or principal.username
    try:
        return settings_service.update_settings(key, payload, actor=actor, repo=repo)
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/settings/ai/test")
async def test_ai_connection(
    principal: Principal = Depends(require_permission("settings")),
    repo: Repository = Depends(get_current_repo),
) -> Dict[str, Any]:
    """Execute live connectivity, latency, and JSON parsing validation probe against the AI provider."""
    return settings_service.test_ai_connection(repo=repo)


@router.get("/settings/health")
async def get_system_health(
    testAi: Optional[bool] = Query(False, description="Whether to probe AI API during health check"),
    principal: Principal = Depends(require_permission("read")),
    repo: Repository = Depends(get_current_repo),
) -> Dict[str, Any]:
    """Inspect underlying S3 buckets, DynamoDB tables, and AI provider connectivity."""
    return {
        "storage": settings_service.storage_health(),
        "ai": settings_service.test_ai_connection(repo=repo) if testAi else None,
    }


@router.get("/form/mapping")
async def get_form_mapping_preview(
    principal: Principal = Depends(require_permission("read")),
    repo: Repository = Depends(get_current_repo),
) -> Dict[str, Any]:
    """Preview Google Form field mapping bindings against canonical candidate fields."""
    return {
        "fieldMapping": field_mapping(repo),
        "roles": roles_config(repo),
        "rubric": rubric(repo),
        "ai": {k: v for k, v in ai_config(repo).items() if k != "api_key"},
        "processing": processing_config(repo),
    }


@router.get("/admins")
async def list_admins(
    principal: Principal = Depends(require_permission("settings")),
) -> Dict[str, Any]:
    """List administrative users and assigned role-based groups."""
    return settings_service.list_admins()


@router.post("/admins")
async def add_admin(
    payload: AdminChangeRequest,
    principal: Principal = Depends(require_permission("admin")),
    repo: Repository = Depends(get_current_repo),
) -> Dict[str, Any]:
    """Grant recruitment administrator, reviewer, or viewer privileges to a user."""
    actor = principal.email or principal.username
    return settings_service.change_admin(
        payload.email,
        payload.group,
        "add",
        actor=actor,
        repo=repo,
    )


@router.delete("/admins")
async def remove_admin(
    payload: AdminChangeRequest,
    principal: Principal = Depends(require_permission("admin")),
    repo: Repository = Depends(get_current_repo),
) -> Dict[str, Any]:
    """Revoke administrative privileges from a user account."""
    actor = principal.email or principal.username
    return settings_service.change_admin(
        payload.email,
        payload.group,
        "remove",
        actor=actor,
        repo=repo,
    )

