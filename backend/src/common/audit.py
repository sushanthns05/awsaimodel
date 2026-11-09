"""Audit trail service. Every material action is attributable and immutable."""

from __future__ import annotations

from typing import Any, Optional

from .logging_utils import get_logger
from .models import AuditEntry, new_id, utcnow
from .repository import Repository, get_repository

logger = get_logger("sbg.audit")


def record(
    action: str,
    *,
    applicant_id: str = "",
    reviewer: str = "system",
    previous_value: Any = None,
    updated_value: Any = None,
    reason: str = "",
    metadata: Optional[dict[str, Any]] = None,
    repo: Optional[Repository] = None,
) -> AuditEntry:
    entry = AuditEntry(
        audit_id=new_id("audit"),
        applicant_id=applicant_id,
        reviewer=reviewer[:200],
        action=action[:100],
        timestamp=utcnow(),
        previous_value=previous_value,
        updated_value=updated_value,
        reason=reason[:1000],
        metadata=metadata or {},
    )
    try:
        (repo or get_repository()).add_audit(entry)
    except Exception as exc:  # noqa: BLE001 - never break the business action
        logger.error("Audit write failed for action %s: %s", action, type(exc).__name__)
    return entry
