"""Applicants management, profiles, reviews, manual scoring, and audit router."""

from __future__ import annotations

from typing import Any, Dict, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, Response, status as http_status

from ...src.common.auth import Principal
from ...src.common.config import Settings
from ...src.common.errors import AppError, ForbiddenError, NotFoundError, ValidationError
from ...src.common.repository import ApplicantFilters, Repository
from ...src.pipeline.queue import enqueue_processing
from ...src.services import applicants as applicant_service
from ...schemas import EraseApplicantRequest, ManualScoreOverrideRequest, ReviewApplicantRequest
from ..deps import get_current_principal, get_current_repo, get_current_settings, require_permission

router = APIRouter(prefix="/applicants", tags=["Applicants"])


@router.get("")
async def list_applicants(
    q: Optional[str] = Query("", description="Full-text search query across name, USN, email"),
    role: Optional[str] = Query("", description="Filter by applied role"),
    status: Optional[str] = Query("", description="Filter by processing status"),
    eligibility: Optional[str] = Query("", description="Filter by PASS, FAIL, UNKNOWN"),
    recommendation: Optional[str] = Query("", description="Filter by AI recommendation band"),
    reviewStatus: Optional[str] = Query("", description="Filter by human review status"),
    department: Optional[str] = Query("", description="Filter by academic department"),
    minScore: Optional[float] = Query(None, description="Minimum score threshold"),
    maxScore: Optional[float] = Query(None, description="Maximum score threshold"),
    urgent: Optional[bool] = Query(None, description="Filter urgently flagged applicants"),
    sort: Optional[str] = Query("submitted_at", description="Sort order: submitted_at, score, name"),
    pageSize: int = Query(25, ge=1, le=100, description="Items per page"),
    cursor: Optional[str] = Query("", description="Pagination cursor"),
    principal: Principal = Depends(require_permission("read")),
    repo: Repository = Depends(get_current_repo),
) -> Dict[str, Any]:
    """Retrieve paginated applicant list with multi-criteria filtering and sorting."""
    if sort not in ("submitted_at", "score", "name"):
        raise HTTPException(
            status_code=http_status.HTTP_400_BAD_REQUEST,
            detail={"code": "VALIDATION_ERROR", "message": "sort must be submitted_at, score or name"},
        )

    filters = ApplicantFilters(
        q=q or "",
        role=role or "",
        status=status or "",
        eligibility=eligibility or "",
        recommendation=recommendation or "",
        review_status=reviewStatus or "",
        department=department or "",
        min_score=minScore,
        max_score=maxScore,
        urgent=urgent,
        sort=sort or "submitted_at",
        page_size=pageSize,
        cursor=cursor or "",
    )

    try:
        return applicant_service.list_applicants(filters, repo=repo)
    except AppError as exc:
        raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/{applicant_id}")
async def get_applicant_detail(
    applicant_id: str,
    principal: Principal = Depends(require_permission("read")),
    repo: Repository = Depends(get_current_repo),
) -> Dict[str, Any]:
    """Retrieve full applicant profile including resume extractions, AI evaluation, and audit trail."""
    try:
        return applicant_service.get_applicant_detail(applicant_id, repo=repo)
    except NotFoundError as exc:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail={"code": "NOT_FOUND", "message": str(exc)},
        ) from exc
    except AppError as exc:
        raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/{applicant_id}/documents/{document_id}/url")
async def get_document_download_url(
    applicant_id: str,
    document_id: str,
    principal: Principal = Depends(require_permission("read")),
    repo: Repository = Depends(get_current_repo),
) -> Dict[str, Any]:
    """Generate short-lived pre-signed download URL for an uploaded resume."""
    try:
        return applicant_service.get_document_url(applicant_id, document_id, repo=repo)
    except NotFoundError as exc:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post("/{applicant_id}/review")
async def review_applicant(
    applicant_id: str,
    payload: ReviewApplicantRequest,
    principal: Principal = Depends(require_permission("review")),
    repo: Repository = Depends(get_current_repo),
) -> Dict[str, Any]:
    """Record an official human reviewer decision (APPROVED, REJECTED, MANUAL_REVIEW) with audit trail."""
    reviewer = principal.email or principal.username or "reviewer"
    try:
        return applicant_service.review_applicant(
            applicant_id,
            payload.model_dump(),
            reviewer=reviewer,
            repo=repo,
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.patch("/{applicant_id}/evaluation")
async def override_scores(
    applicant_id: str,
    payload: ManualScoreOverrideRequest,
    principal: Principal = Depends(require_permission("review")),
    repo: Repository = Depends(get_current_repo),
) -> Dict[str, Any]:
    """Manually adjust rubric criterion scores with mandatory justification in audit log."""
    reviewer = principal.email or principal.username or "reviewer"
    try:
        return applicant_service.manual_score_override(
            applicant_id,
            payload.model_dump(),
            reviewer=reviewer,
            repo=repo,
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=http_status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post("/{applicant_id}/reprocess", status_code=http_status.HTTP_202_ACCEPTED)
async def reprocess_applicant(
    applicant_id: str,
    response: Response,
    principal: Principal = Depends(require_permission("reprocess")),
    settings: Settings = Depends(get_current_settings),
    repo: Repository = Depends(get_current_repo),
) -> Dict[str, Any]:
    """Re-queue an application through extraction, AI evaluation, and scoring."""
    reviewer = principal.email or principal.username
    applicant_service.reset_for_reprocess(applicant_id, reviewer=reviewer, repo=repo)
    queued = enqueue_processing(applicant_id, force=True, repo=repo, settings=settings)

    result: Dict[str, Any] = {"applicantId": applicant_id, "queue": queued}
    if queued.get("mode") == "local" and settings.local_inline_processing:
        from ...src.pipeline.tasks import process_applicant_now

        result["processing"] = process_applicant_now(applicant_id, repo=repo, settings=settings)

    response.status_code = http_status.HTTP_202_ACCEPTED
    return result


@router.get("/{applicant_id}/audit")
async def get_applicant_audit(
    applicant_id: str,
    principal: Principal = Depends(require_permission("read")),
    repo: Repository = Depends(get_current_repo),
) -> Dict[str, Any]:
    """Retrieve immutable chronological audit trail for all changes to an applicant."""
    entries = repo.list_audit(applicant_id, limit=200)
    return {"items": [e.to_dict() for e in entries]}


@router.delete("/{applicant_id}")
async def erase_applicant(
    applicant_id: str,
    payload: EraseApplicantRequest,
    principal: Principal = Depends(require_permission("admin")),
    repo: Repository = Depends(get_current_repo),
) -> Dict[str, Any]:
    """Purge candidate data and documents in compliance with data privacy policies."""
    reviewer = principal.email or principal.username
    try:
        return applicant_service.erase_applicant(
            applicant_id,
            reviewer=reviewer,
            reason=payload.reason,
            repo=repo,
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=http_status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
