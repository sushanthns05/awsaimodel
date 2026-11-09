"""Lambda entry points for the processing pipeline and report worker."""

from __future__ import annotations

import json
from typing import Any

from ..common.config import get_settings
from ..common.errors import AppError
from ..common.logging_utils import get_logger
from ..common.repository import get_repository
from ..documents.storage import get_storage
from ..pipeline.queue import dispatch_message
from ..pipeline.tasks import (
    evaluate_applicant_task,
    extract_applicant_documents,
    mark_failed,
    score_applicant_task,
)
from ..reports.service import generate_report

logger = get_logger("sbg.worker")


def _applicant_id(event: dict[str, Any]) -> str:
    applicant_id = str(event.get("applicant_id") or (event.get("detail") or {}).get("applicant_id") or "")
    if not applicant_id:
        raise AppError("Worker event is missing applicant_id")
    return applicant_id


def extract_handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    applicant_id = _applicant_id(event)
    try:
        return extract_applicant_documents(applicant_id)
    except Exception as exc:  # noqa: BLE001
        logger.error("Extraction worker failed for %s: %s", applicant_id, type(exc).__name__)
        mark_failed(applicant_id, f"Extraction failed: {type(exc).__name__}")
        raise


def evaluate_handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    applicant_id = _applicant_id(event)
    try:
        return evaluate_applicant_task(applicant_id)
    except Exception as exc:  # noqa: BLE001
        logger.error("Evaluation worker failed for %s: %s", applicant_id, type(exc).__name__)
        mark_failed(applicant_id, f"Evaluation failed: {type(exc).__name__}")
        raise


def score_handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    applicant_id = _applicant_id(event)
    try:
        return score_applicant_task(
            applicant_id,
            event.get("ai_result") or {},
            event.get("metadata") or {},
            event.get("coverage") or {},
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("Scoring worker failed for %s: %s", applicant_id, type(exc).__name__)
        mark_failed(applicant_id, f"Scoring failed: {type(exc).__name__}")
        raise


def mark_failed_handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    applicant_id = str(event.get("applicant_id") or "")
    error = str(event.get("error") or event.get("cause") or "Workflow failed")
    if not applicant_id:
        return {"status": "IGNORED", "reason": "missing applicant_id"}
    return mark_failed(applicant_id, error)


def queue_consumer_handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    results = []
    failures = []
    for record in event.get("Records", []):
        try:
            body = json.loads(record.get("body") or "{}")
            results.append(dispatch_message(body))
        except Exception as exc:  # noqa: BLE001
            logger.error("Queue message failed: %s", type(exc).__name__)
            failures.append({"messageId": record.get("messageId"), "error": type(exc).__name__})
    if failures:
        # Raising lets SQS retry and eventually route the message to the DLQ.
        raise AppError(f"{len(failures)} queue message(s) failed")
    return {"processed": len(results), "results": results}


def reports_worker_handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    report_id = str(event.get("report_id") or "")
    if not report_id:
        raise AppError("Report worker event is missing report_id")
    record = generate_report(
        report_id,
        str(event.get("kind") or ""),
        event.get("scope") or {},
        str(event.get("actor") or "system"),
        repo=get_repository(),
        storage=get_storage(),
    )
    return record.to_dict()


def reprocess_handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    """Scheduled reconciliation: re-queue applications stuck in processing."""
    from datetime import datetime, timedelta, timezone

    from ..common.repository import ApplicantFilters
    from ..pipeline.queue import enqueue_processing

    settings = get_settings()
    repo = get_repository()
    stale_after = timedelta(minutes=30)
    now = datetime.now(timezone.utc)
    requeued: list[str] = []
    for status in ("QUEUED", "EXTRACTING", "EXTRACTED", "EVALUATING", "SCORING"):
        page = repo.list_applicants(ApplicantFilters(status=status, page_size=50))
        for applicant in page.items:
            if now - applicant.updated_at < stale_after:
                continue
            enqueue_processing(applicant.applicant_id, force=True, repo=repo, settings=settings)
            requeued.append(applicant.applicant_id)
            if len(requeued) >= 50:
                break
        if len(requeued) >= 50:
            break
    return {"requeued": len(requeued), "applicant_ids": requeued}

