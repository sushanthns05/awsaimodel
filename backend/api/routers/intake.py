"""Google Apps Script intake endpoint router.

Receives form responses, verifies HMAC signature / intake key, parses uploaded
documents, persists the applicant record, and enqueues asynchronous processing.
"""

from __future__ import annotations

import json
from typing import Any, Dict
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from ...src.common.auth import verify_intake_request
from ...src.common.config import Settings, get_settings
from ...src.common.config_store import field_mapping, roles_config
from ...src.common.errors import AppError, UnauthorizedError
from ...src.common.logging_utils import get_logger
from ...src.common.repository import Repository, get_repository
from ...src.documents.ingestion import ingest_submission
from ...src.documents.storage import Storage, get_storage
from ...src.pipeline.queue import enqueue_processing
from ..deps import get_current_repo, get_current_settings, get_current_storage

logger = get_logger("sbg.fastapi.intake")

router = APIRouter(tags=["Intake"])


@router.post("/intake", status_code=status.HTTP_202_ACCEPTED)
async def submit_application(
    request: Request,
    response: Response,
    settings: Settings = Depends(get_current_settings),
    repo: Repository = Depends(get_current_repo),
    storage: Storage = Depends(get_current_storage),
) -> Dict[str, Any]:
    """Receive Google Form submission with uploaded resumes.

    Authenticates using the shared intake key or HMAC-SHA256 signature from
    Google Apps Script. Fast acknowledgement; never waits for AI analysis.
    """
    raw_body = await request.body()
    body_text = raw_body.decode("utf-8") if raw_body else "{}"

    # Build event dict matching verify_intake_request interface
    headers = {str(k).lower(): v for k, v in request.headers.items()}
    event = {
        "headers": headers,
        "body": body_text,
    }

    # Verify credentials unless running in local test mode with auth disabled
    if not (settings.is_local and settings.auth_disabled):
        try:
            verify_intake_request(event, settings)
        except UnauthorizedError as exc:
            logger.warning("Intake auth failed: %s", exc)
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail={"code": "UNAUTHORIZED", "message": str(exc)},
            ) from exc

    try:
        payload = json.loads(body_text) if body_text else {}
        # Normalise source_response_id from response_id if needed
        if "source_response_id" not in payload and "response_id" in payload:
            payload["source_response_id"] = payload["response_id"]
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_JSON", "message": "Failed to parse JSON body"},
        ) from exc

    try:
        result = ingest_submission(
            payload,
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

            # In local single-process development mode, execute inline pipeline
            if queue_info.get("mode") == "local" and settings.local_inline_processing:
                from ...src.pipeline.tasks import process_applicant_now

                result["processing"] = process_applicant_now(applicant_id, repo=repo, settings=settings)

            response.status_code = status.HTTP_202_ACCEPTED
            return result

        # Handled duplicate or rejected submission
        response.status_code = status.HTTP_200_OK
        return result

    except AppError as exc:
        logger.error("Intake processing error: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INGESTION_ERROR", "message": str(exc)},
        ) from exc
    except Exception as exc:
        logger.error("Unhandled intake exception: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail={"code": "INTERNAL_ERROR", "message": "Failed to ingest submission"},
        ) from exc
