"""Dashboard aggregation service."""

from __future__ import annotations

from typing import Any, Optional

from ..common.models import Applicant, iso, utcnow
from ..common.repository import Repository, get_repository
from ..reports.data import collect_rows
from ..scoring.engine import score_distribution

PENDING_STATUSES = {"RECEIVED", "QUEUED", "EXTRACTING", "EXTRACTED", "EVALUATING", "SCORING"}
DONE_STATUSES = {"COMPLETED", "NEEDS_REVIEW"}


def applicant_brief(applicant: Applicant) -> dict[str, Any]:
    return {
        "applicantId": applicant.applicant_id,
        "fullName": applicant.full_name,
        "email": applicant.email,
        "usn": applicant.usn,
        "department": applicant.department,
        "yearOfStudy": applicant.year_of_study,
        "roles": applicant.roles,
        "submittedAt": iso(applicant.submitted_at),
        "processingStatus": applicant.processing_status,
        "totalScore": applicant.total_score,
        "recommendation": applicant.recommendation,
        "eligibilityStatus": applicant.eligibility_status,
        "reviewStatus": applicant.review_status,
        "urgentReview": applicant.urgent_review,
        "documents": len(applicant.documents),
        "rubricVersion": applicant.rubric_version,
    }


def overview(
    *,
    repo: Optional[Repository] = None,
    rubric: dict[str, Any],
    roles_config: dict[str, Any],
    organization: dict[str, Any],
    limit: int = 10_000,
) -> dict[str, Any]:
    repo = repo or get_repository()
    rows = collect_rows(repo, include_evaluations=False, limit=limit)
    applicants = [row.applicant for row in rows]

    processed = sum(1 for a in applicants if a.processing_status in DONE_STATUSES)
    pending = sum(1 for a in applicants if a.processing_status in PENDING_STATUSES)
    failed = sum(1 for a in applicants if a.processing_status == "FAILED")
    eligible = sum(1 for a in applicants if a.eligibility_status == "PASS")
    ineligible = sum(1 for a in applicants if a.eligibility_status == "FAIL")
    needs_review = sum(
        1
        for a in applicants
        if a.recommendation in ("NEEDS_REVIEW", "ELIGIBILITY_REVIEW", "MANUAL_REVIEW")
        or a.review_status == "MANUAL_REVIEW"
        or a.processing_status == "NEEDS_REVIEW"
    )
    approved = sum(1 for a in applicants if a.review_status == "APPROVED")
    strong = sum(1 for a in applicants if a.recommendation == "STRONG_INTERVIEW")
    consideration = sum(1 for a in applicants if a.recommendation == "INTERVIEW_CONSIDERATION")

    scored = [a.total_score for a in applicants if a.processing_status in DONE_STATUSES]
    average = round(sum(scored) / len(scored), 2) if scored else 0.0
    highest = max(scored) if scored else 0.0

    role_stats = []
    for role in roles_config.get("roles", []):
        role_id = str(role["id"])
        subset = [a for a in applicants if role_id in a.roles]
        scores = [a.total_score for a in subset if a.processing_status in DONE_STATUSES]
        role_stats.append(
            {
                "roleId": role_id,
                "name": role.get("name", role_id),
                "applicants": len(subset),
                "processed": sum(1 for a in subset if a.processing_status in DONE_STATUSES),
                "eligible": sum(1 for a in subset if a.eligibility_status == "PASS"),
                "shortlisted": sum(1 for a in subset if a.review_status == "APPROVED"),
                "averageScore": round(sum(scores) / len(scores), 2) if scores else 0.0,
                "strongRecommendations": sum(1 for a in subset if a.recommendation == "STRONG_INTERVIEW"),
            }
        )
    role_stats.sort(key=lambda r: r["applicants"], reverse=True)

    status_counts: dict[str, int] = {}
    for applicant in applicants:
        status_counts[applicant.processing_status] = status_counts.get(applicant.processing_status, 0) + 1

    recent = sorted(applicants, key=lambda a: a.submitted_at, reverse=True)[:8]
    top = sorted(
        [a for a in applicants if a.processing_status in DONE_STATUSES],
        key=lambda a: (-a.total_score, a.full_name.lower()),
    )[:8]

    return {
        "stats": {
            "totalApplications": len(applicants),
            "processed": processed,
            "pending": pending,
            "failed": failed,
            "eligible": eligible,
            "ineligible": ineligible,
            "needsReview": needs_review,
            "approvedShortlist": approved,
            "strongRecommendations": strong,
            "interviewConsideration": consideration,
            "averageScore": average,
            "highestScore": highest,
        },
        "roleStats": role_stats,
        "scoreDistribution": score_distribution(scored, rubric),
        "processingStatus": [{"status": status, "count": count} for status, count in sorted(status_counts.items())],
        "recentApplicants": [applicant_brief(a) for a in recent],
        "topApplicants": [applicant_brief(a) for a in top],
        "organization": organization,
        "truncated": len(applicants) >= limit,
        "generatedAt": iso(utcnow()),
    }
