"""Processing tasks used by the Step Functions state machine.

Each task is small, retryable and idempotent:
  extract_documents -> evaluate_applicant -> score_applicant
No Lambda invocation processes more than one applicant. Resume text stays in
S3 and is never passed through the state payload beyond a character count.
"""

from __future__ import annotations

from typing import Any, Optional

from ..ai.client import AIClient, get_ai_client
from ..common import audit
from ..common.config import Settings, get_settings
from ..common.config_store import ai_config, eligibility_config, roles_config, rubric
from ..common.errors import AppError
from ..common.logging_utils import get_logger
from ..common.models import Applicant, Evaluation, iso, utcnow
from ..common.repository import Repository, get_repository
from ..documents.extractor import (
    CorruptDocumentError,
    ExtractionError,
    PasswordProtectedError,
    extract_document,
)
from ..documents.storage import Storage, get_storage
from ..scoring.engine import build_evaluation

logger = get_logger("sbg.pipeline")

MAX_COMBINED_CHARS = 80_000


def _fail(applicant: Applicant, error: str, repo: Repository) -> None:
    applicant.processing_status = "FAILED"
    applicant.processing_error = error[:1500]
    applicant.urgent_review = True
    repo.save_applicant(applicant)
    audit.record(
        "PROCESSING_FAILED",
        applicant_id=applicant.applicant_id,
        updated_value={"error": applicant.processing_error},
        repo=repo,
    )


_EXTRACTION_STATUS_BY_ERROR = {
    PasswordProtectedError: "PASSWORD_PROTECTED",
    CorruptDocumentError: "CORRUPT",
    ExtractionError: "FAILED",
}


def extract_applicant_documents(
    applicant_id: str,
    *,
    repo: Optional[Repository] = None,
    storage: Optional[Storage] = None,
    settings: Optional[Settings] = None,
) -> dict[str, Any]:
    repo = repo or get_repository()
    storage = storage or get_storage()
    settings = settings or get_settings()

    applicant = repo.get_applicant(applicant_id)
    if applicant.processing_status in ("COMPLETED", "NEEDS_REVIEW") and applicant.latest_evaluation_id:
        logger.info("Applicant %s already fully processed; skipping extraction", applicant_id)
        return {"applicant_id": applicant_id, "skipped": True, "reason": "already_processed"}

    applicant.processing_status = "EXTRACTING"
    applicant.processing_error = ""
    repo.save_applicant(applicant)

    texts: list[str] = []
    warnings: list[str] = []
    seen_text_hashes: dict[str, str] = {}
    for document in applicant.documents:
        if document.extraction_status == "DUPLICATE" and document.duplicate_of:
            continue
        try:
            data = storage.get_document(document.s3_key)
            result = extract_document(
                data,
                _kind(document.content_type, document.filename),
                filename=document.filename,
                settings=settings,
                use_textract=settings.textract_enabled,
            )
            text = result.text.strip()
            if text:
                key = str(hash(text))
                if key in seen_text_hashes:
                    document.extraction_status = "DUPLICATE"
                    document.duplicate_of = seen_text_hashes[key]
                else:
                    seen_text_hashes[key] = document.document_id
                    document.extraction_status = "EXTRACTED"
                    texts.append(f"--- {document.filename} ---\n{text}")
            else:
                document.extraction_status = "EMPTY"
                warnings.append(f"{document.filename}: no text could be extracted")
            document.page_count = result.page_count
            document.text_chars = result.chars
            document.textract_used = result.textract_used
            document.scanned = result.scanned
            document.extraction_error = "; ".join(result.warnings[:4])
            warnings.extend(result.warnings)
        except ExtractionError as exc:
            document.extraction_status = _EXTRACTION_STATUS_BY_ERROR.get(type(exc), "FAILED")
            document.extraction_error = str(exc)[:500]
            warnings.append(f"{document.filename}: {exc}")
            logger.warning("Extraction failed for %s / %s: %s", applicant_id, document.document_id, type(exc).__name__)
        except Exception as exc:  # noqa: BLE001
            document.extraction_status = "FAILED"
            document.extraction_error = "Unexpected extraction error"
            warnings.append(f"{document.filename}: extraction failed")
            logger.error("Extraction error for %s: %s", applicant_id, type(exc).__name__)

    combined = "\n\n".join(texts)[:MAX_COMBINED_CHARS]
    if combined:
        key = storage.put_extracted_text(applicant_id, combined)
        applicant.extracted_text_key = key
        applicant.extracted_text_chars = len(combined)
    applicant.extraction_summary = {
        "documents": len(applicant.documents),
        "extracted": sum(1 for d in applicant.documents if d.extraction_status == "EXTRACTED"),
        "failed": sum(1 for d in applicant.documents if d.extraction_status in ("FAILED", "CORRUPT", "PASSWORD_PROTECTED")),
        "duplicates": sum(1 for d in applicant.documents if d.extraction_status == "DUPLICATE"),
        "warnings": warnings[:10],
        "completed_at": iso(utcnow()),
    }

    if not combined:
        applicant.responses["extraction_warning"] = "No resume text available; evaluation uses application answers only."
        applicant.urgent_review = True

    applicant.processing_status = "EXTRACTED"
    repo.save_applicant(applicant)
    audit.record(
        "DOCUMENTS_EXTRACTED",
        applicant_id=applicant_id,
        updated_value=applicant.extraction_summary,
        repo=repo,
    )
    return {
        "applicant_id": applicant_id,
        "characters": len(combined),
        "documents": len(applicant.documents),
        "extraction_summary": applicant.extraction_summary,
    }


def _kind(content_type: str, filename: str) -> str:
    name = filename.lower()
    if name.endswith(".pdf"):
        return "pdf"
    if name.endswith(".docx"):
        return "docx"
    if name.endswith(".doc"):
        return "doc"
    if name.endswith(".png"):
        return "png"
    if name.endswith((".jpg", ".jpeg")):
        return "jpg"
    if "pdf" in content_type:
        return "pdf"
    if "wordprocessingml" in content_type:
        return "docx"
    return "pdf"


def _resume_text(applicant: Applicant, storage: Storage, settings: Settings) -> str:
    if applicant.extracted_text_key:
        try:
            return storage.get_extracted_text(applicant.extracted_text_key)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Unable to read extracted text for %s: %s", applicant.applicant_id, type(exc).__name__)
    # Fall back to application answers only. Never invent resume content.
    parts = []
    for key, label in (
        ("technical_skills", "Technical skills"),
        ("experience", "Experience"),
        ("projects", "Projects"),
        ("certifications", "Certifications"),
        ("leadership", "Leadership"),
        ("motivation", "Motivation"),
    ):
        value = applicant.responses.get(key)
        if value:
            parts.append(f"{label}: {value}")
    return "\n".join(parts)


def evaluate_applicant_task(
    applicant_id: str,
    *,
    repo: Optional[Repository] = None,
    storage: Optional[Storage] = None,
    settings: Optional[Settings] = None,
    client: Optional[AIClient] = None,
) -> dict[str, Any]:
    repo = repo or get_repository()
    storage = storage or get_storage()
    settings = settings or get_settings()

    applicant = repo.get_applicant(applicant_id)

    applicant.processing_status = "EVALUATING"
    repo.save_applicant(applicant)

    rubric_cfg = rubric(repo)
    roles_cfg = roles_config(repo)
    ai_cfg = ai_config(repo)
    client = client or get_ai_client(settings, ai_cfg)

    resume_text = _resume_text(applicant, storage, settings)
    try:
        ai_result, metadata = client.evaluate(
            applicant,
            resume_text,
            rubric_cfg,
            roles_cfg,
            max_input_chars=int(ai_cfg.get("max_input_chars") or settings.ai_max_input_chars),
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("AI evaluation failed for %s: %s", applicant_id, type(exc).__name__)
        raise

    coverage = {
        "resume_characters": len(resume_text),
        "documents": len(applicant.documents),
        "extracted_documents": sum(1 for d in applicant.documents if d.extraction_status == "EXTRACTED"),
        "resume_available": bool(applicant.extracted_text_key),
        "used_application_answers_only": not bool(applicant.extracted_text_key),
    }
    audit.record(
        "AI_EVALUATION_COMPLETED",
        applicant_id=applicant_id,
        updated_value={"model": metadata.get("model"), "tokens": metadata.get("prompt_tokens", 0) + metadata.get("completion_tokens", 0)},
        metadata={"provider": metadata.get("provider"), "confidence": ai_result.get("confidence")},
        repo=repo,
    )
    return {
        "applicant_id": applicant_id,
        "ai_result": ai_result,
        "metadata": metadata,
        "coverage": coverage,
        "rubric_version": str(rubric_cfg.get("version", "1.0.0")),
    }


def score_applicant_task(
    applicant_id: str,
    ai_result: dict[str, Any],
    metadata: dict[str, Any],
    coverage: dict[str, Any],
    *,
    repo: Optional[Repository] = None,
) -> dict[str, Any]:
    from ..ai.prompts import PROMPT_VERSION

    repo = repo or get_repository()
    applicant = repo.get_applicant(applicant_id)
    applicant.processing_status = "SCORING"
    repo.save_applicant(applicant)

    rubric_cfg = rubric(repo)
    roles_cfg = roles_config(repo)
    eligibility_cfg = eligibility_config(repo)

    evaluation: Evaluation = build_evaluation(
        applicant,
        ai_result,
        rubric_cfg,
        roles_cfg,
        eligibility_cfg,
        model_metadata=metadata,
        prompt_version=PROMPT_VERSION,
        document_coverage=coverage,
    )

    repo.save_evaluation(evaluation)

    previous_status = applicant.processing_status
    applicant.latest_evaluation_id = evaluation.evaluation_id
    applicant.rubric_version = evaluation.rubric_version
    applicant.total_score = evaluation.total_score
    applicant.recommendation = evaluation.recommendation
    applicant.eligibility_status = evaluation.eligibility_status
    applicant.eligibility_failures = evaluation.eligibility_failures
    applicant.role_scores = {
        str(item.get("role_id")): float(item.get("score", 0)) for item in evaluation.role_evaluations
    }
    applicant.processing_status = "NEEDS_REVIEW" if evaluation.recommendation == "NEEDS_REVIEW" else "COMPLETED"
    applicant.urgent_review = evaluation.recommendation in ("NEEDS_REVIEW", "ELIGIBILITY_REVIEW") or bool(
        evaluation.validation_errors
    )
    repo.save_applicant(applicant)

    audit.record(
        "EVALUATION_SCORED",
        applicant_id=applicant_id,
        previous_value={"processing_status": previous_status},
        updated_value={
            "total_score": evaluation.total_score,
            "recommendation": evaluation.recommendation,
            "eligibility_status": evaluation.eligibility_status,
            "rubric_version": evaluation.rubric_version,
        },
        metadata={"evaluation_id": evaluation.evaluation_id, "score_complete": evaluation.score_complete},
        repo=repo,
    )
    return {
        "applicant_id": applicant_id,
        "evaluation_id": evaluation.evaluation_id,
        "total_score": evaluation.total_score,
        "recommendation": evaluation.recommendation,
        "eligibility_status": evaluation.eligibility_status,
        "score_complete": evaluation.score_complete,
    }


def mark_failed(applicant_id: str, error: str = "", *, repo: Optional[Repository] = None) -> dict[str, Any]:
    repo = repo or get_repository()
    try:
        applicant = repo.get_applicant(applicant_id)
    except Exception:  # noqa: BLE001
        return {"applicant_id": applicant_id, "status": "NOT_FOUND"}
    _fail(applicant, error or applicant.processing_error or "Processing failed", repo)
    return {"applicant_id": applicant_id, "status": "FAILED"}


def process_applicant_now(
    applicant_id: str,
    *,
    repo: Optional[Repository] = None,
    storage: Optional[Storage] = None,
    settings: Optional[Settings] = None,
) -> dict[str, Any]:
    """Run the full pipeline synchronously. Used by local development and tests."""
    repo = repo or get_repository()
    storage = storage or get_storage()
    settings = settings or get_settings()
    try:
        extraction = extract_applicant_documents(applicant_id, repo=repo, storage=storage, settings=settings)
        if extraction.get("skipped"):
            applicant = repo.get_applicant(applicant_id)
            return {
                "applicant_id": applicant_id,
                "status": applicant.processing_status,
                "skipped": True,
            }
        evaluated = evaluate_applicant_task(applicant_id, repo=repo, storage=storage, settings=settings)
        scored = score_applicant_task(
            applicant_id,
            evaluated["ai_result"],
            evaluated["metadata"],
            evaluated["coverage"],
            repo=repo,
        )
        return {"applicant_id": applicant_id, "status": "COMPLETED", **scored}
    except Exception as exc:  # noqa: BLE001
        logger.error("Inline processing failed for %s: %s", applicant_id, type(exc).__name__)
        mark_failed(applicant_id, f"{type(exc).__name__}: {str(exc)[:300]}", repo=repo)
        return {"applicant_id": applicant_id, "status": "FAILED", "error": type(exc).__name__}
