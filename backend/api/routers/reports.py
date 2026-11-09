"""Export and reporting router: 12-sheet Excel workbooks and consolidated/individual PDFs."""

from __future__ import annotations

from typing import Any, Dict
from fastapi import APIRouter, Depends, HTTPException, Response, status

from ...src.common.auth import Principal
from ...src.common.config import Settings
from ...src.common.errors import NotFoundError, ValidationError
from ...src.common.repository import Repository
from ...src.documents.storage import Storage
from ...src.services import reports_service
from ...schemas import GenerateReportRequest
from ..deps import get_current_repo, get_current_settings, get_current_storage, require_permission

router = APIRouter(prefix="/reports", tags=["Reports"])


@router.get("")
async def list_reports(
    principal: Principal = Depends(require_permission("read")),
    repo: Repository = Depends(get_current_repo),
    storage: Storage = Depends(get_current_storage),
) -> Dict[str, Any]:
    """Retrieve catalog of generated recruitment reports and download links."""
    return reports_service.list_reports(repo=repo, storage=storage)


@router.post("/generate")
async def generate_report_endpoint(
    payload: GenerateReportRequest,
    response: Response,
    principal: Principal = Depends(require_permission("reports")),
    settings: Settings = Depends(get_current_settings),
    repo: Repository = Depends(get_current_repo),
    storage: Storage = Depends(get_current_storage),
) -> Dict[str, Any]:
    """Trigger recruitment report generation (Excel workbook or ReportLab PDF)."""
    kind = str(payload.type or payload.kind or "").strip().lower()
    scope = payload.scope or {
        "role": payload.role or "",
        "applicant_id": payload.applicantId or "",
    }
    actor = principal.email or principal.username

    try:
        record = reports_service.create_report(
            kind,
            scope,
            actor=actor,
            repo=repo,
            storage=storage,
            settings=settings,
        )

        download_url = ""
        if record.status == "COMPLETED" and record.s3_key:
            try:
                download_url = storage.report_url(record.s3_key, record.filename)
            except Exception:  # noqa: BLE001
                pass

        if record.status == "PENDING":
            response.status_code = status.HTTP_202_ACCEPTED
        else:
            response.status_code = status.HTTP_200_OK

        return record.to_dict() | {"downloadUrl": download_url}
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.get("/{report_id}")
async def get_report_detail(
    report_id: str,
    principal: Principal = Depends(require_permission("read")),
    repo: Repository = Depends(get_current_repo),
    storage: Storage = Depends(get_current_storage),
) -> Dict[str, Any]:
    """Retrieve generation status, metadata, and secure download URL for a report."""
    try:
        return reports_service.get_report(report_id, repo=repo, storage=storage)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.get("/{report_id}/download")
async def download_report(
    report_id: str,
    principal: Principal = Depends(require_permission("reports")),
    repo: Repository = Depends(get_current_repo),
    storage: Storage = Depends(get_current_storage),
) -> Dict[str, Any]:
    """Obtain authenticated signed download URL for an archived report."""
    try:
        data = reports_service.get_report(report_id, repo=repo, storage=storage)
        if data.get("status") != "COMPLETED":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={"code": "NOT_READY", "message": "Report is not yet completed"},
            )
        return {"url": data.get("downloadUrl", ""), "filename": data.get("filename", "")}
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc

