"""Reports API service."""

from __future__ import annotations

import json
from typing import Any, Optional

from ..common.config import Settings, get_settings
from ..common.errors import NotFoundError
from ..common.logging_utils import get_logger
from ..common.models import ReportRecord, new_id, utcnow
from ..common.repository import Repository, get_repository
from ..documents.storage import Storage, get_storage
from ..reports.service import generate_report, validate_scope

logger = get_logger("sbg.reports.api")


def list_reports(
    *,
    repo: Optional[Repository] = None,
    storage: Optional[Storage] = None,
    limit: int = 50,
) -> dict[str, Any]:
    repo = repo or get_repository()
    storage = storage or get_storage()
    items = []
    for record in repo.list_reports(limit=limit):
        entry = record.to_dict()
        entry["downloadUrl"] = ""
        if record.status == "COMPLETED" and record.s3_key:
            try:
                entry["downloadUrl"] = storage.report_url(record.s3_key, record.filename)
            except Exception:  # noqa: BLE001
                pass
        items.append(entry)
    return {"items": items, "count": len(items)}


def create_report(
    kind: str,
    scope: dict[str, Any],
    *,
    actor: str,
    repo: Optional[Repository] = None,
    storage: Optional[Storage] = None,
    settings: Optional[Settings] = None,
    synchronous: Optional[bool] = None,
) -> ReportRecord:
    repo = repo or get_repository()
    storage = storage or get_storage()
    settings = settings or get_settings()
    scope = validate_scope(kind, scope)

    record = ReportRecord(
        report_id=new_id("rep"),
        kind=kind,
        status="PENDING",
        created_at=utcnow(),
        created_by=actor,
        scope=scope,
    )
    repo.save_report(record)

    run_sync = settings.is_local if synchronous is None else synchronous
    if run_sync:
        return generate_report(record.report_id, kind, scope, actor, repo=repo, storage=storage)

    if not settings.reports_worker_function:
        # No worker configured: generate inline rather than silently stalling.
        return generate_report(record.report_id, kind, scope, actor, repo=repo, storage=storage)

    try:
        import boto3

        client = boto3.client("lambda", region_name=settings.region)
        client.invoke(
            FunctionName=settings.reports_worker_function,
            InvocationType="Event",
            Payload=json.dumps(
                {"report_id": record.report_id, "kind": kind, "scope": scope, "actor": actor}
            ).encode("utf-8"),
        )
    except Exception as exc:  # noqa: BLE001
        logger.error("Unable to invoke reports worker: %s", type(exc).__name__)
        record.status = "FAILED"
        record.error = "Report worker could not be started"
        repo.save_report(record)
    return record


def get_report(
    report_id: str,
    *,
    repo: Optional[Repository] = None,
    storage: Optional[Storage] = None,
) -> dict[str, Any]:
    repo = repo or get_repository()
    storage = storage or get_storage()
    try:
        record = repo.get_report(report_id)
    except NotFoundError:
        raise
    entry = record.to_dict()
    entry["downloadUrl"] = ""
    if record.status == "COMPLETED" and record.s3_key:
        entry["downloadUrl"] = storage.report_url(record.s3_key, record.filename)
    return entry
