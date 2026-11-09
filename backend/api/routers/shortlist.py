"""Candidate shortlisting and bulk interview approval router."""

from __future__ import annotations

from typing import Any, Dict, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status

from ...src.common.auth import Principal
from ...src.common.errors import ValidationError
from ...src.common.repository import Repository
from ...src.services import applicants as applicant_service
from ...src.services.shortlist import build_shortlist
from ...schemas import BulkReviewRequest
from ..deps import get_current_repo, require_permission

router = APIRouter(prefix="/shortlist", tags=["Shortlisting"])


@router.get("")
async def get_shortlist(
    role: Optional[str] = Query("", description="Filter candidate rankings by specific team/role"),
    minScore: Optional[float] = Query(None, description="Minimum qualifying score"),
    maxScore: Optional[float] = Query(None, description="Maximum qualifying score"),
    includeFailed: Optional[bool] = Query(False, description="Include ineligible candidates in list"),
    limit: int = Query(200, ge=1, le=500, description="Maximum candidates returned"),
    principal: Principal = Depends(require_permission("read")),
    repo: Repository = Depends(get_current_repo),
) -> Dict[str, Any]:
    """Retrieve ranked candidate leaderboard for committee shortlisting decisions."""
    return build_shortlist(
        role=role or "",
        min_score=minScore,
        max_score=maxScore,
        include_failed=bool(includeFailed),
        limit=limit,
        repo=repo,
    )


@router.post("/bulk")
async def bulk_review_shortlist(
    payload: BulkReviewRequest,
    principal: Principal = Depends(require_permission("shortlist")),
    repo: Repository = Depends(get_current_repo),
) -> Dict[str, Any]:
    """Batch approve or reject selected candidates for interview stages with audit history."""
    reviewer = principal.email or principal.username
    try:
        return applicant_service.bulk_review(
            applicant_ids=payload.applicantIds,
            decision=payload.decision.upper(),
            notes=payload.notes or "",
            reason=payload.reason or "",
            reviewer=reviewer,
            repo=repo,
        )
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

