"""Shared data collection helpers for report generation."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from ..common.models import Applicant, AuditEntry, Evaluation, utcnow
from ..common.repository import ApplicantFilters, Repository

MAX_REPORT_APPLICANTS = 20_000


@dataclass
class ReportRow:
    applicant: Applicant
    evaluation: Optional[Evaluation] = None


@dataclass
class ReportData:
    rows: list[ReportRow] = field(default_factory=list)
    audit: list[AuditEntry] = field(default_factory=list)
    generated_at: datetime = field(default_factory=utcnow)
    rubric_version: str = ""
    organization: dict[str, Any] = field(default_factory=dict)
    truncated: bool = False
    roles: list[dict[str, Any]] = field(default_factory=list)
    score_bands: list[dict[str, Any]] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.rows)

    def applicant(self, applicant_id: str) -> Optional[ReportRow]:
        return next((r for r in self.rows if r.applicant.applicant_id == applicant_id), None)


def collect_rows(
    repo: Repository,
    *,
    role: str = "",
    applicant_ids: Optional[list[str]] = None,
    include_evaluations: bool = True,
    limit: int = MAX_REPORT_APPLICANTS,
) -> list[ReportRow]:
    rows: list[ReportRow] = []
    if applicant_ids:
        for applicant_id in applicant_ids:
            try:
                applicant = repo.get_applicant(applicant_id)
            except Exception:  # noqa: BLE001
                continue
            rows.append(ReportRow(applicant, repo.get_latest_evaluation(applicant_id) if include_evaluations else None))
        return rows

    cursor = ""
    seen = 0
    per_page = 100
    while seen < limit:
        page = repo.list_applicants(
            ApplicantFilters(role=role, sort="submitted_at", page_size=per_page, cursor=cursor)
        )
        for applicant in page.items:
            rows.append(
                ReportRow(applicant, repo.get_latest_evaluation(applicant.applicant_id) if include_evaluations else None)
            )
            seen += 1
            if seen >= limit:
                break
        cursor = page.next_cursor or ""
        if not page.next_cursor:
            break
    rows.sort(key=lambda r: (-r.applicant.total_score, r.applicant.full_name.lower()))
    return rows


def collect_report_data(
    repo: Repository,
    *,
    role: str = "",
    applicant_ids: Optional[list[str]] = None,
    organization: Optional[dict[str, Any]] = None,
    rubric_version: str = "",
    rubric: Optional[dict[str, Any]] = None,
    roles_config: Optional[dict[str, Any]] = None,
    audit_limit: int = 5000,
) -> ReportData:
    rows = collect_rows(repo, role=role, applicant_ids=applicant_ids)
    audit_rows = repo.list_audit("", limit=audit_limit)
    return ReportData(
        rows=rows,
        audit=audit_rows,
        rubric_version=rubric_version,
        organization=organization or {},
        truncated=len(rows) >= MAX_REPORT_APPLICANTS,
        roles=list((roles_config or {}).get("roles", [])),
        score_bands=list((rubric or {}).get("score_bands", [])),
    )


def role_shortlist(rows: list[ReportRow], role_id: str) -> list[ReportRow]:
    filtered = [r for r in rows if role_id in r.applicant.roles]
    filtered.sort(key=lambda r: (-r.applicant.total_score, r.applicant.full_name.lower()))
    return filtered


def manual_review_rows(rows: list[ReportRow]) -> list[ReportRow]:
    return [
        r
        for r in rows
        if r.applicant.recommendation in ("NEEDS_REVIEW", "ELIGIBILITY_REVIEW", "MANUAL_REVIEW")
        or r.applicant.review_status == "MANUAL_REVIEW"
        or r.applicant.eligibility_status == "FAIL"
        or r.applicant.processing_status in ("FAILED", "NEEDS_REVIEW")
    ]


def shortlisted_rows(rows: list[ReportRow]) -> list[ReportRow]:
    return [r for r in rows if r.applicant.review_status == "APPROVED"]


def summary_stats(rows: list[ReportRow]) -> dict[str, Any]:
    total = len(rows)
    processed = sum(1 for r in rows if r.applicant.processing_status == "COMPLETED")
    pending = sum(1 for r in rows if r.applicant.processing_status in ("RECEIVED", "QUEUED", "EXTRACTING", "EXTRACTED", "EVALUATING", "SCORING"))
    failed = sum(1 for r in rows if r.applicant.processing_status == "FAILED")
    eligible = sum(1 for r in rows if r.applicant.eligibility_status == "PASS")
    ineligible = sum(1 for r in rows if r.applicant.eligibility_status == "FAIL")
    review = len(manual_review_rows(rows))
    recommended = sum(1 for r in rows if r.applicant.review_status == "APPROVED")
    strong = sum(1 for r in rows if r.applicant.recommendation == "STRONG_INTERVIEW")
    scores = [r.applicant.total_score for r in rows if r.applicant.processing_status in ("COMPLETED", "NEEDS_REVIEW")]
    average = round(sum(scores) / len(scores), 2) if scores else 0.0
    return {
        "total": total,
        "processed": processed,
        "pending": pending,
        "failed": failed,
        "eligible": eligible,
        "ineligible": ineligible,
        "needs_review": review,
        "shortlisted": recommended,
        "strong_interview": strong,
        "average_score": average,
    }
