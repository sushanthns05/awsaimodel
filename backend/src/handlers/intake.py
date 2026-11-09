"""Google Apps Script intake endpoint.

Verifies the shared intake key and HMAC signature, validates the payload,
stores documents, writes the applicant idempotently and queues processing.
It never waits for AI evaluation.
"""

from __future__ import annotations

from typing import Any

from ..common.auth import verify_intake_request
from ..common.config import get_settings
from ..common.config_store import field_mapping, roles_config
from ..common.errors import AppError, error_response, json_response
from ..common.http import normalize_event, preflight
from ..common.logging_utils import get_logger
from ..common.repository import get_repository
from ..documents.ingestion import ingest_submission
from ..documents.storage import get_storage
from ..pipeline.queue import enqueue_processing

logger = get_logger("sbg.intake")


def lambda_handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    settings = get_settings()
    origin = settings.cors_origin
    try:
        request = normalize_event(event, max_body_bytes=int(settings.max_submission_bytes * 1.6))
        if request.method == "OPTIONS":
            return preflight(origin)
        if request.method != "POST":
            return json_response(405, {"error": {"code": "METHOD_NOT_ALLOWED", "message": "Use POST"}}, origin)

        if not (settings.is_local and settings.auth_disabled):
            verify_intake_request(request.event, settings)

        repo = get_repository()
        storage = get_storage()
        result = ingest_submission(
            request.body,
            repo=repo,
            storage=storage,
            mapping=field_mapping(repo),
            roles_config=roles_config(repo),
            settings=settings,
        )

        if result.get("status") == "ACCEPTED":
            applicant_id = result["applicant_id"]
            queue_info = enqueue_processing(applicant_id, repo=repo, settings=settings)
            result["queue"] = queue_info
            if queue_info.get("mode") == "local" and settings.local_inline_processing:
                from ..pipeline.tasks import process_applicant_now

                result["processing"] = process_applicant_now(applicant_id, repo=repo, settings=settings)
            return json_response(202, result, origin)

        return json_response(200, result, origin)
    except AppError as exc:
        return error_response(exc, str((event.get("requestContext") or {}).get("requestId") or ""), origin)
    except Exception as exc:  # noqa: BLE001
        logger.error("Unhandled intake error: %s", type(exc).__name__, exc_info=True)
        return error_response(exc, str((event.get("requestContext") or {}).get("requestId") or ""), origin)
