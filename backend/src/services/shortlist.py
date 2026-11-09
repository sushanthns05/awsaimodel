"""Shortlisting and ranking service."""

from __future__ import annotations

from typing import Any, Optional

from ..common.models import Applicant
from ..common.repository import Repository, get_repository
from ..reports.data import ReportRow, collect_rows


def _effective_score(applicant: Applicant, role: str) -> float:
    if role:
        return float(applicant.role_scores.get(role, applicant.total_score))
    if applicant.role_scores:
        return max(float(v) for v in applicant.role_scores.values())
    return float(applicant.total_score)


def build_shortlist(
    role: str = "",
    *,
    min_score: Optional[float] = None,
    max_score: Optional[float] = None,
    include_failed: bool = False,
    limit: int = 300,
    repo: Optional[Repository] = None,
) -> dict[str, Any]:
    repo = repo or get_repository()
    rows = collect_rows(repo, role=role, limit=max(limit, 300))
    items: list[dict[str, Any]] = []
    for row in rows:
        applicant = row.applicant
        if applicant.processing_status == "DELETED":
            continue
        if not include_failed and applicant.processing_status not in ("COMPLETED", "NEEDS_REVIEW"):
            continue
        score = _effective_score(applicant, role)
        if min_score is not None and score < min_score:
            continue
        if max_score is not None and score > max_score:
            continue
        evaluation = row.evaluation
        items.append(
            {
                "applicantId": applicant.applicant_id,
                "fullName": applicant.full_name,
                "email": applicant.email,
                "usn": applicant.usn,
                "department": applicant.department,
                "yearOfStudy": applicant.year_of_study,
                "roles": applicant.roles,
                "roleScore": round(score, 2),
                "totalScore": applicant.total_score,
                "recommendation": applicant.recommendation,
                "eligibilityStatus": applicant.eligibility_status,
                "eligibilityFailures": applicant.eligibility_failures,
                "reviewStatus": applicant.review_status,
                "reviewDecision": applicant.review_decision,
                "reviewedBy": applicant.reviewed_by,
                "strongestEvidence": (evaluation.strengths[:2] if evaluation else []),
                "concerns": (evaluation.weaknesses[:2] if evaluation else []),
                "urgentReview": applicant.urgent_review,
                "documents": len(applicant.documents),
            }
        )
    items.sort(key=lambda item: (-item["roleScore"], item["fullName"].lower()))
    for index, item in enumerate(items, start=1):
        item["rank"] = index
    return {
        "items": items[:limit],
        "total": len(items),
        "role": role,
        "minScore": min_score,
        "maxScore": max_score,
    }
