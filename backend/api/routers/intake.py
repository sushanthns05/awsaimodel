"""Google Apps Script intake endpoint router.

Receives form responses, verifies HMAC signature / intake key, parses uploaded
documents, persists the applicant record, and enqueues asynchronous processing.
"""

from __future__ import annotations

import csv
import io
import json
import re
import urllib.request
from typing import Any, Dict
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel

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


class SyncSheetRequest(BaseModel):
    sheet_url: str
    evaluate_immediately: bool = True


class CsvImportRequest(BaseModel):
    csv_text: str
    evaluate_immediately: bool = True


async def _ingest_csv_content(
    csv_text: str,
    evaluate: bool,
    settings: Settings,
    repo: Repository,
    storage: Storage,
) -> Dict[str, Any]:
    reader = csv.DictReader(io.StringIO(csv_text))
    rows = list(reader)
    if not rows:
        return {"total_rows": 0, "imported": 0, "skipped_duplicates": 0, "errors": []}

    imported = 0
    duplicates = 0
    errors: list[str] = []

    for index, row in enumerate(rows):
        try:
            timestamp = row.get("Timestamp") or row.get("timestamp") or ""
            ident = row.get("Email Address") or row.get("Email") or row.get("USN") or f"row-{index}"
            resp_id = f"GF-{index+1}-{abs(hash(ident)) % 100000}"

            payload: dict[str, Any] = {
                "source_response_id": resp_id,
                "submitted_at": timestamp,
                "form_title": "AWS Student Builder Group SJBIT Recruitment 2026-27",
                "responses": row,
                "documents": [],
            }

            for col_name, val in row.items():
                if any(w in str(col_name).lower() for w in ("resume", "cv", "portfolio", "upload", "drive")):
                    drive_url = str(val).strip()
                    if drive_url and ("drive.google.com" in drive_url or "http" in drive_url):
                        payload["documents"].append({
                            "filename": f"resume_{index+1}.pdf",
                            "source_url": drive_url,
                            "type": "resume",
                        })

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
                imported += 1
                if evaluate:
                    from ...src.pipeline.tasks import process_applicant_now
                    try:
                        process_applicant_now(applicant_id, repo=repo, storage=storage, settings=settings)
                    except Exception as p_exc:
                        logger.warning("Inline processing warning for %s: %s", applicant_id, p_exc)
            elif result.get("status") == "DUPLICATE":
                duplicates += 1
        except Exception as r_exc:
            errors.append(f"Row {index+1}: {str(r_exc)}")

    return {
        "total_rows": len(rows),
        "imported": imported,
        "skipped_duplicates": duplicates,
        "errors": errors[:10],
    }


@router.post("/intake/sync-sheet")
async def sync_google_sheet(
    body: SyncSheetRequest,
    settings: Settings = Depends(get_current_settings),
    repo: Repository = Depends(get_current_repo),
    storage: Storage = Depends(get_current_storage),
) -> Dict[str, Any]:
    """Sync real candidate submissions directly from the linked Google Sheet."""
    match = re.search(r"/spreadsheets/d/([a-zA-Z0-9-_]+)", body.sheet_url)
    if not match:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_SHEET_URL", "message": "Could not find Google Spreadsheet ID in the provided URL."},
        )
    sheet_id = match.group(1)
    csv_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv"

    try:
        req = urllib.request.Request(csv_url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            content = resp.read().decode("utf-8", errors="replace")
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "SHEET_FETCH_FAILED",
                "message": (
                    f"Could not read Google Sheet ({exc}). Please ensure the Sheet sharing is set to "
                    "'Anyone with the link can view' (or export as CSV and upload directly)."
                ),
            },
        ) from exc

    return await _ingest_csv_content(content, body.evaluate_immediately, settings, repo, storage)


@router.post("/intake/upload-csv")
async def import_csv_responses(
    body: CsvImportRequest,
    settings: Settings = Depends(get_current_settings),
    repo: Repository = Depends(get_current_repo),
    storage: Storage = Depends(get_current_storage),
) -> Dict[str, Any]:
    """Import Google Form responses from an exported CSV file directly."""
    return await _ingest_csv_content(body.csv_text, body.evaluate_immediately, settings, repo, storage)

