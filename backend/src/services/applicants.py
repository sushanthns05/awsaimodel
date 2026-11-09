"""Applicant read/write services used by the admin API."""

from __future__ import annotations

from typing import Any, Optional

from ..common import audit
from ..common.config_store import eligibility_config, roles_config, rubric
from ..common.errors import ForbiddenError, NotFoundError, ValidationError
from ..common.models import Applicant, iso, utcnow
from ..common.repository import ApplicantFilters, Page, Repository, get_repository
from ..documents.storage import Storage, get_storage
from ..scoring.engine import ScoringError, apply_manual_scores
from .dashboard import applicant_brief

DECISIONS = {
    "SHORTLISTED": "APPROVED",
    "APPROVED": "APPROVED",
    "REJECTED": "REJECTED",
    "MANUAL_REVIEW": "MANUAL_REVIEW",
    "PENDING": "PENDING",
}


def list_applicants(filters: ApplicantFilters, *, repo: Optional[Repository] = None) -> dict[str, Any]:
    repo = repo or get_repository()
    page: Page = repo.list_applicants(filters)
    return {
        "items": [applicant_brief(a) for a in page.items],
        "nextCursor": page.next_cursor,
        "pageSize": filters.page_size,
        "count": len(page.items),
    }


def _document_payload(applicant: Applicant, storage: Storage) -> list[dict[str, Any]]:
    payload = []
    for document in applicant.documents:
        entry = document.to_dict()
        entry.pop("s3_key", None)
        try:
            entry["downloadUrl"] = storage.document_url(document.s3_key, document.filename)
        except Exception:  # noqa: BLE001
            entry["downloadUrl"] = ""
        payload.append(entry)
    return payload


def get_applicant_detail(
    applicant_id: str,
    *,
    repo: Optional[Repository] = None,
    storage: Optional[Storage] = None,
) -> dict[str, Any]:
    repo = repo or get_repository()
    storage = storage or get_storage()
    applicant = repo.get_applicant(applicant_id)
    evaluation = repo.get_latest_evaluation(applicant_id)
    history = repo.list_evaluations(applicant_id)
    audits = repo.list_audit(applicant_id, limit=100)

    return {
        "applicant": applicant.to_dict(),
        "applicantId": applicant.applicant_id,
        "brief": applicant_brief(applicant),
        "documents": _document_payload(applicant, storage),
        "evaluation": evaluation.to_dict() if evaluation else None,
        "evaluationHistory": [
            {
                "evaluationId": e.evaluation_id,
                "createdAt": iso(e.created_at),
                "totalScore": e.total_score,
                "recommendation": e.recommendation,
                "rubricVersion": e.rubric_version,
                "reviewStatus": e.review_status,
                "scoreComplete": e.score_complete,
                "model": e.model_metadata.get("model", "") if e.model_metadata else "",
                "validationErrors": e.validation_errors,
                "humanOverride": e.human_override,
            }
            for e in history
        ],
        "audit": [entry.to_dict() for entry in audits],
        "links": {
            "self": f"/applicants/{applicant_id}",
            "reports": f"/reports?applicant_id={applicant_id}",
        },
    }


def get_document_url(
    applicant_id: str,
    document_id: str,
    *,
    repo: Optional[Repository] = None,
    storage: Optional[Storage] = None,
) -> dict[str, Any]:
    repo = repo or get_repository()
    storage = storage or get_storage()
    applicant = repo.get_applicant(applicant_id)
    document = next((d for d in applicant.documents if d.document_id == document_id), None)
    if not document:
        raise NotFoundError("Document not found for this applicant")
    url = storage.document_url(document.s3_key, document.filename)
    audit.record(
        "DOCUMENT_ACCESSED",
        applicant_id=applicant_id,
        reviewer="admin",
        updated_value={"document_id": document_id, "filename": document.filename},
        repo=repo,
    )
    return {
        "documentId": document_id,
        "filename": document.filename,
        "contentType": document.content_type,
        "sizeBytes": document.size_bytes,
        "url": url,
        "expiresInSeconds": 300,
    }


def review_applicant(
    applicant_id: str,
    payload: dict[str, Any],
    *,
    reviewer: str,
    repo: Optional[Repository] = None,
) -> dict[str, Any]:
    repo = repo or get_repository()
    applicant = repo.get_applicant(applicant_id)

    decision = str(payload.get("decision") or "").strip().upper()
    if decision not in DECISIONS:
        raise ValidationError("decision must be one of SHORTLISTED, REJECTED, MANUAL_REVIEW, PENDING")
    notes = str(payload.get("notes") or "").strip()
    reason = str(payload.get("reason") or "").strip()
    if len(notes) > 4000 or len(reason) > 1000:
        raise ValidationError("Notes or reason exceed the allowed length")

    if decision == "SHORTLISTED" and (
        applicant.eligibility_status == "FAIL" or applicant.recommendation in ("NEEDS_REVIEW", "ELIGIBILITY_REVIEW")
    ):
        if not reason:
            raise ValidationError(
                "A reason is required to shortlist an applicant who is ineligible, incomplete or flagged for review"
            )

    previous = {
        "review_status": applicant.review_status,
        "review_decision": applicant.review_decision,
        "review_notes": applicant.review_notes,
    }
    applicant.review_status = DECISIONS[decision]  # type: ignore[assignment]
    applicant.review_decision = decision
    applicant.review_notes = notes
    applicant.reviewed_by = reviewer[:200]
    applicant.reviewed_at = utcnow()
    repo.save_applicant(applicant)

    audit.record(
        "REVIEW_DECISION",
        applicant_id=applicant_id,
        reviewer=reviewer,
        previous_value=previous,
        updated_value={
            "review_status": applicant.review_status,
            "review_decision": decision,
            "review_notes": notes,
        },
        reason=reason,
        repo=repo,
    )
    return {"applicantId": applicant_id, "reviewStatus": applicant.review_status, "decision": decision}


def bulk_review(
    applicant_ids: list[str],
    decision: str,
    notes: str,
    reason: str,
    *,
    reviewer: str,
    repo: Optional[Repository] = None,
) -> dict[str, Any]:
    if not isinstance(applicant_ids, list) or not applicant_ids:
        raise ValidationError("applicant_ids must be a non-empty list")
    if len(applicant_ids) > 200:
        raise ValidationError("At most 200 applicants can be updated per request")
    updated, skipped = [], []
    for applicant_id in applicant_ids:
        try:
            review_applicant(
                str(applicant_id),
                {"decision": decision, "notes": notes, "reason": reason},
                reviewer=reviewer,
                repo=repo,
            )
            updated.append(str(applicant_id))
        except (NotFoundError, ValidationError) as exc:
            skipped.append({"applicantId": str(applicant_id), "reason": str(exc)})
    return {"updated": updated, "skipped": skipped, "decision": decision}


def manual_score_override(
    applicant_id: str,
    payload: dict[str, Any],
    *,
    reviewer: str,
    repo: Optional[Repository] = None,
) -> dict[str, Any]:
    repo = repo or get_repository()
    applicant = repo.get_applicant(applicant_id)
    evaluation = repo.get_latest_evaluation(applicant_id)
    if not evaluation:
        raise NotFoundError("No evaluation exists for this applicant")

    scores = payload.get("scores")
    if not isinstance(scores, dict) or not scores:
        raise ValidationError("scores must be an object of criterion_id -> marks")
    reason = str(payload.get("reason") or "").strip()
    if len(reason) < 5 or len(reason) > 1000:
        raise ValidationError("A reason of at least 5 characters is required for a manual score override")

    rubric_cfg = rubric(repo)
    previous_total = evaluation.total_score
    try:
        updated = apply_manual_scores(evaluation, scores, reviewer=reviewer, reason=reason, rubric=rubric_cfg)
    except ScoringError as exc:
        raise ValidationError(str(exc)) from exc

    repo.save_evaluation(updated)
    applicant.total_score = updated.total_score
    applicant.recommendation = updated.recommendation
    applicant.review_status = "MANUAL_REVIEW"
    applicant.review_decision = "MANUAL_REVIEW"
    applicant.latest_evaluation_id = updated.evaluation_id
    applicant.rubric_version = updated.rubric_version
    repo.save_applicant(applicant)

    audit.record(
        "MANUAL_SCORE_OVERRIDE",
        applicant_id=applicant_id,
        reviewer=reviewer,
        previous_value={"total_score": previous_total, "scores": {c.criterion_id: c.final_score for c in evaluation.criteria}},
        updated_value={"total_score": updated.total_score, "scores": scores},
        reason=reason,
        repo=repo,
    )
    return {
        "applicantId": applicant_id,
        "evaluationId": updated.evaluation_id,
        "totalScore": updated.total_score,
        "recommendation": updated.recommendation,
        "criteria": [c.to_dict() for c in updated.criteria],
    }


def reset_for_reprocess(
    applicant_id: str,
    *,
    reviewer: str,
    repo: Optional[Repository] = None,
) -> Applicant:
    repo = repo or get_repository()
    applicant = repo.get_applicant(applicant_id)
    previous = applicant.processing_status
    applicant.processing_status = "QUEUED"
    applicant.processing_error = ""
    applicant.urgent_review = False
    for document in applicant.documents:
        if document.extraction_status not in ("DUPLICATE",):
            document.extraction_status = "PENDING"
            document.extraction_error = ""
    applicant.extracted_text_key = ""
    applicant.extracted_text_chars = 0
    repo.save_applicant(applicant)
    audit.record(
        "REPROCESS_REQUESTED",
        applicant_id=applicant_id,
        reviewer=reviewer,
        previous_value={"processing_status": previous},
        updated_value={"processing_status": "QUEUED"},
        repo=repo,
    )
    return applicant


def erase_applicant(
    applicant_id: str,
    *,
    reviewer: str,
    reason: str,
    repo: Optional[Repository] = None,
    storage: Optional[Storage] = None,
) -> dict[str, Any]:
    """Retention request: remove documents and personal data, keep an audit stub."""
    repo = repo or get_repository()
    storage = storage or get_storage()
    applicant = repo.get_applicant(applicant_id)
    removed = storage.purge_applicant(applicant_id)

    previous = {"email": applicant.email, "phone": applicant.phone, "usn": applicant.usn, "documents": len(applicant.documents)}
    applicant.full_name = "ERASED APPLICANT"
    applicant.email = ""
    applicant.phone = ""
    applicant.usn = ""
    applicant.responses = {"erased": True, "erased_at": iso(utcnow())}
    applicant.documents = []
    applicant.extracted_text_key = ""
    applicant.extracted_text_chars = 0
    applicant.review_notes = ""
    applicant.processing_status = "DELETED"
    applicant.recommendation = "NEEDS_REVIEW"
    applicant.urgent_review = False
    repo.save_applicant(applicant)

    audit.record(
        "APPLICANT_ERASED",
        applicant_id=applicant_id,
        reviewer=reviewer,
        previous_value=previous,
        updated_value={"deleted_documents": removed},
        reason=reason or "Data retention request",
        repo=repo,
    )
    return {"applicantId": applicant_id, "status": "DELETED", "documentsRemoved": removed}
