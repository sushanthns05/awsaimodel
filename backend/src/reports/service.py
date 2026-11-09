"""Report orchestration: collect data, render, store and record."""

from __future__ import annotations

import hashlib
from typing import Any, Optional

from ..common import audit
from ..common.config_store import organization_config, roles_config, rubric
from ..common.errors import NotFoundError, ValidationError
from ..common.logging_utils import get_logger
from ..common.models import ReportRecord, iso, utcnow
from ..common.repository import Repository, get_repository
from ..documents.storage import Storage, get_storage
from .data import collect_report_data
from .excel import build_excel
from .pdf import build_pdf

logger = get_logger("sbg.reports")

REPORT_KINDS = {
    "excel": ("xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
    "pdf_consolidated": ("pdf", "application/pdf"),
    "pdf_executive": ("pdf", "application/pdf"),
    "pdf_manual_review": ("pdf", "application/pdf"),
    "pdf_role": ("pdf", "application/pdf"),
    "pdf_applicant": ("pdf", "application/pdf"),
}

KIND_TO_PDF = {
    "pdf_consolidated": "consolidated",
    "pdf_executive": "executive",
    "pdf_manual_review": "manual_review",
    "pdf_role": "role",
    "pdf_applicant": "applicant",
}


def validate_scope(kind: str, scope: dict[str, Any]) -> dict[str, Any]:
    if kind not in REPORT_KINDS:
        raise ValidationError(f"Unsupported report type '{kind}'. Choose one of: {', '.join(REPORT_KINDS)}")
    scope = scope or {}
    if kind == "pdf_role" and not scope.get("role"):
        raise ValidationError("role is required for a role-wise PDF report")
    if kind == "pdf_applicant" and not scope.get("applicant_id"):
        raise ValidationError("applicant_id is required for an applicant PDF report")
    return {
        "role": str(scope.get("role", ""))[:64],
        "applicant_id": str(scope.get("applicant_id", ""))[:64],
        "min_score": scope.get("min_score"),
        "max_score": scope.get("max_score"),
    }


def generate_report(
    report_id: str,
    kind: str,
    scope: dict[str, Any],
    actor: str,
    *,
    repo: Optional[Repository] = None,
    storage: Optional[Storage] = None,
) -> ReportRecord:
    repo = repo or get_repository()
    storage = storage or get_storage()
    scope = validate_scope(kind, scope)

    try:
        record = repo.get_report(report_id)
    except NotFoundError:
        record = ReportRecord(
            report_id=report_id,
            kind=kind,
            status="PENDING",
            created_at=utcnow(),
            created_by=actor,
            scope=scope,
        )

    rubric_cfg = rubric(repo)
    roles_cfg = roles_config(repo)
    org_cfg = organization_config(repo)

    try:
        data = collect_report_data(
            repo,
            role=scope.get("role", ""),
            applicant_ids=[scope["applicant_id"]] if scope.get("applicant_id") else None,
            organization=org_cfg,
            rubric_version=str(rubric_cfg.get("version", "1.0.0")),
            rubric=rubric_cfg,
            roles_config=roles_cfg,
        )
        if kind == "pdf_applicant" and not data.rows:
            raise NotFoundError("Applicant not found for report")

        if kind == "excel":
            content = build_excel(data, roles_cfg, rubric_cfg)
        else:
            content = build_pdf(
                data,
                kind=KIND_TO_PDF[kind],
                applicant_id=scope.get("applicant_id", ""),
                role=scope.get("role", ""),
            )
    except Exception as exc:  # noqa: BLE001
        record.status = "FAILED"
        record.error = f"{type(exc).__name__}: {str(exc)[:500]}"
        repo.save_report(record)
        logger.error("Report %s failed: %s", report_id, type(exc).__name__)
        raise

    extension, content_type = REPORT_KINDS[kind]
    stamp = utcnow().strftime("%Y%m%d-%H%M%S")
    filename = _filename(kind, scope, stamp, extension)
    key = storage.put_report(report_id, filename, content, content_type)

    record.status = "COMPLETED"
    record.s3_key = key
    record.filename = filename
    record.size_bytes = len(content)
    record.error = ""
    repo.save_report(record)

    audit.record(
        "REPORT_GENERATED",
        reviewer=actor,
        updated_value={"report_id": report_id, "kind": kind, "filename": filename, "rows": data.total},
        metadata={"sha256": hashlib.sha256(content).hexdigest()[:16], "generated_at": iso(utcnow())},
        repo=repo,
    )
    return record


def _filename(kind: str, scope: dict[str, Any], stamp: str, extension: str) -> str:
    base = {
        "excel": "SBG-Recruitment-Report",
        "pdf_consolidated": "SBG-Consolidated-Recruitment-Report",
        "pdf_executive": "SBG-Executive-Summary",
        "pdf_manual_review": "SBG-Manual-Review",
        "pdf_role": f"SBG-Role-{scope.get('role', 'role')}",
        "pdf_applicant": f"SBG-Applicant-{scope.get('applicant_id', 'applicant')}",
    }.get(kind, "SBG-Report")
    return f"{base}-{stamp}.{extension}"
