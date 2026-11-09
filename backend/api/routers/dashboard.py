"""Recruitment dashboard overview analytics router."""

from __future__ import annotations

from typing import Any, Dict
from fastapi import APIRouter, Depends

from ...src.common.auth import Principal
from ...src.common.config_store import organization_config, roles_config, rubric
from ...src.common.repository import Repository
from ...src.services.dashboard import overview
from ..deps import get_current_repo, require_permission

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


@router.get("/overview")
async def get_dashboard_overview(
    principal: Principal = Depends(require_permission("read")),
    repo: Repository = Depends(get_current_repo),
) -> Dict[str, Any]:
    """Retrieve top-level KPI metrics, role distributions, score bands, and processing status."""
    return overview(
        repo=repo,
        rubric=rubric(repo),
        roles_config=roles_config(repo),
        organization=organization_config(repo),
    )

