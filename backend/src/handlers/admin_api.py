"""Admin API Lambda router.

API Gateway handles Cognito authentication at the edge; this module also
verifies claims and enforces permission-level RBAC in code. Every response is
JSON. Personal data is never written to logs.
"""

from __future__ import annotations

import json
import re
import traceback
from typing import Any, Callable, Optional

from ..common.auth import Principal, authenticate
from ..common.config import get_settings
from ..common.config_store import field_mapping, organization_config, roles_config, rubric
from ..common.errors import AppError, ForbiddenError, NotFoundError, ValidationError, error_response, json_response
from ..common.http import Request, normalize_event, preflight, query_bool, query_float, query_int, ok
from ..common.logging_utils import get_logger
from ..common.repository import ApplicantFilters, get_repository
from ..pipeline.queue import enqueue_processing
from ..services import applicants as applicant_service
from ..services import reports_service, settings_service
from ..services.dashboard import overview
from ..services.shortlist import build_shortlist
from ..common.config_store import ai_config, processing_config

logger = get_logger("sbg.api")

ROUTES: list[tuple[str, re.Pattern[str], str]] = []


def route(method: str, pattern: str) -> Callable:
    def decorator(func: Callable) -> Callable:
        ROUTES.append((method.upper(), re.compile(f"^{pattern}$"), func.__name__))
        return func

    return decorator


def _origin(request: Request) -> str:
    settings = get_settings()
    origin = settings.cors_origin
    if origin and origin != "*":
        return origin
    return "*"


def lambda_handler(event: dict[str, Any], context: Any = None) -> dict[str, Any]:
    settings = get_settings()
    origin = settings.cors_origin
    try:
        request = normalize_event(event, max_body_bytes=2 * 1024 * 1024)
        if request.method == "OPTIONS":
            return preflight(origin)

        if request.path == "/health":
            return ok(
                {
                    "status": "ok",
                    "service": "sbg-recruitment-admin-api",
                    "stage": settings.stage,
                    "time": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(),
                },
                request,
                origin=origin,
            )

        principal = authenticate(request.event, settings)
        request.event["_principal"] = principal  # type: ignore[assignment]

        for method, pattern, handler_name in ROUTES:
            match = pattern.match(request.path)
            if not match:
                continue
            if method != request.method:
                continue
            request.path_params.update({k: v for k, v in match.groupdict().items() if v is not None})
            handler = globals()[handler_name]
            return handler(request, principal, origin)
        raise NotFoundError(f"No route for {request.method} {request.path}")
    except AppError as exc:
        return error_response(exc, _request_id(event), origin)
    except Exception as exc:  # noqa: BLE001
        logger.error("Unhandled API error: %s", type(exc).__name__, exc_info=True)
        return error_response(exc, _request_id(event), origin)


def _request_id(event: dict[str, Any]) -> str:
    return str((event.get("requestContext") or {}).get("requestId") or "")


# ---------------------------------------------------------------------------
# Identity and dashboard
# ---------------------------------------------------------------------------


def _me(request: Request, principal: Principal, origin: str) -> dict[str, Any]:
    principal.require("read")
    return ok({"user": principal.to_dict(), "organization": organization_config(get_repository())}, request, origin=origin)


def _dashboard_overview(request: Request, principal: Principal, origin: str) -> dict[str, Any]:
    principal.require("read")
    repo = get_repository()
    payload = overview(
        repo=repo,
        rubric=rubric(repo),
        roles_config=roles_config(repo),
        organization=organization_config(repo),
    )
    return ok(payload, request, origin=origin)


# ---------------------------------------------------------------------------
# Applicants
# ---------------------------------------------------------------------------


def _applicants_list(request: Request, principal: Principal, origin: str) -> dict[str, Any]:
    principal.require("read")
    filters = ApplicantFilters(
        q=request.query.get("q", ""),
        role=request.query.get("role", ""),
        status=request.query.get("status", ""),
        eligibility=request.query.get("eligibility", ""),
        recommendation=request.query.get("recommendation", ""),
        review_status=request.query.get("reviewStatus", ""),
        department=request.query.get("department", ""),
        min_score=query_float(request, "minScore"),
        max_score=query_float(request, "maxScore"),
        urgent=query_bool(request, "urgent"),
        sort=request.query.get("sort", "submitted_at"),
        page_size=query_int(request, "pageSize", 25, minimum=1, maximum=100),
        cursor=request.query.get("cursor", ""),
    )
    if filters.sort not in ("submitted_at", "score", "name"):
        raise ValidationError("sort must be submitted_at, score or name")
    return ok(applicant_service.list_applicants(filters), request, origin=origin)


def _applicant_detail(request: Request, principal: Principal, origin: str) -> dict[str, Any]:
    principal.require("read")
    payload = applicant_service.get_applicant_detail(
        request.path_params["applicant_id"], repo=get_repository()
    )
    return ok(payload, request, origin=origin)


def _applicant_document_url(request: Request, principal: Principal, origin: str) -> dict[str, Any]:
    principal.require("read")
    payload = applicant_service.get_document_url(
        request.path_params["applicant_id"], request.path_params["document_id"], repo=get_repository()
    )
    return ok(payload, request, origin=origin)


def _applicant_review(request: Request, principal: Principal, origin: str) -> dict[str, Any]:
    principal.require("review")
    payload = applicant_service.review_applicant(
        request.path_params["applicant_id"],
        request.body,
        reviewer=principal.email or principal.username,
        repo=get_repository(),
    )
    return ok(payload, request, origin=origin)


def _applicant_manual_scores(request: Request, principal: Principal, origin: str) -> dict[str, Any]:
    principal.require("review")
    if not principal.can("review"):
        raise ForbiddenError("Manual score changes require reviewer access")
    payload = applicant_service.manual_score_override(
        request.path_params["applicant_id"],
        request.body,
        reviewer=principal.email or principal.username,
        repo=get_repository(),
    )
    return ok(payload, request, origin=origin)


def _applicant_reprocess(request: Request, principal: Principal, origin: str) -> dict[str, Any]:
    principal.require("reprocess")
    settings = get_settings()
    repo = get_repository()
    applicant_id = request.path_params["applicant_id"]
    applicant_service.reset_for_reprocess(applicant_id, reviewer=principal.email, repo=repo)
    queued = enqueue_processing(applicant_id, force=True, repo=repo, settings=settings)
    result: dict[str, Any] = {"applicantId": applicant_id, "queue": queued}
    if queued.get("mode") == "local" and settings.local_inline_processing:
        from ..pipeline.tasks import process_applicant_now

        result["processing"] = process_applicant_now(applicant_id, repo=repo, settings=settings)
    return ok(result, request, status=202, origin=origin)


def _applicant_audit(request: Request, principal: Principal, origin: str) -> dict[str, Any]:
    principal.require("read")
    entries = get_repository().list_audit(request.path_params["applicant_id"], limit=200)
    return ok({"items": [e.to_dict() for e in entries]}, request, origin=origin)


def _applicant_erase(request: Request, principal: Principal, origin: str) -> dict[str, Any]:
    principal.require("admin")
    reason = str(request.body.get("reason") or "")
    payload = applicant_service.erase_applicant(
        request.path_params["applicant_id"],
        reviewer=principal.email or principal.username,
        reason=reason,
        repo=get_repository(),
    )
    return ok(payload, request, origin=origin)


# ---------------------------------------------------------------------------
# Shortlisting
# ---------------------------------------------------------------------------


def _shortlist(request: Request, principal: Principal, origin: str) -> dict[str, Any]:
    principal.require("read")
    payload = build_shortlist(
        request.query.get("role", ""),
        min_score=query_float(request, "minScore"),
        max_score=query_float(request, "maxScore"),
        include_failed=query_bool(request, "includeFailed"),
        limit=query_int(request, "limit", 200, minimum=1, maximum=500),
        repo=get_repository(),
    )
    return ok(payload, request, origin=origin)


def _shortlist_bulk(request: Request, principal: Principal, origin: str) -> dict[str, Any]:
    principal.require("shortlist")
    body = request.body
    payload = applicant_service.bulk_review(
        body.get("applicantIds") or [],
        str(body.get("decision") or "").upper(),
        str(body.get("notes") or ""),
        str(body.get("reason") or ""),
        reviewer=principal.email or principal.username,
        repo=get_repository(),
    )
    return ok(payload, request, origin=origin)


# ---------------------------------------------------------------------------
# Reports
# ---------------------------------------------------------------------------


def _reports_list(request: Request, principal: Principal, origin: str) -> dict[str, Any]:
    principal.require("read")
    return ok(reports_service.list_reports(repo=get_repository()), request, origin=origin)


def _reports_generate(request: Request, principal: Principal, origin: str) -> dict[str, Any]:
    principal.require("reports")
    body = request.body
    kind = str(body.get("type") or body.get("kind") or "").strip()
    scope = body.get("scope") or {
        "role": body.get("role", ""),
        "applicant_id": body.get("applicantId", ""),
    }
    record = reports_service.create_report(
        kind,
        scope,
        actor=principal.email or principal.username,
        repo=get_repository(),
    )
    return ok(record.to_dict() | {"downloadUrl": _report_url(record)}, request, status=202 if record.status == "PENDING" else 200, origin=origin)


def _report_detail(request: Request, principal: Principal, origin: str) -> dict[str, Any]:
    principal.require("read")
    return ok(reports_service.get_report(request.path_params["report_id"], repo=get_repository()), request, origin=origin)


def _report_download(request: Request, principal: Principal, origin: str) -> dict[str, Any]:
    principal.require("reports")
    payload = reports_service.get_report(request.path_params["report_id"], repo=get_repository())
    if payload.get("status") != "COMPLETED":
        raise ValidationError("Report is not ready for download")
    return ok({"url": payload.get("downloadUrl", ""), "filename": payload.get("filename", "")}, request, origin=origin)


def _report_url(record: Any) -> str:
    if getattr(record, "status", "") != "COMPLETED" or not getattr(record, "s3_key", ""):
        return ""
    try:
        from ..documents.storage import get_storage

        return get_storage().report_url(record.s3_key, record.filename)
    except Exception:  # noqa: BLE001
        return ""


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


def _settings_get(request: Request, principal: Principal, origin: str) -> dict[str, Any]:
    principal.require("settings")
    return ok(settings_service.read_settings(repo=get_repository()), request, origin=origin)


def _settings_update(request: Request, principal: Principal, origin: str) -> dict[str, Any]:
    principal.require("settings")
    key = request.path_params["key"]
    result = settings_service.update_settings(
        key, request.body, actor=principal.email or principal.username, repo=get_repository()
    )
    return ok(result, request, origin=origin)


def _settings_ai_test(request: Request, principal: Principal, origin: str) -> dict[str, Any]:
    principal.require("settings")
    return ok(settings_service.test_ai_connection(repo=get_repository()), request, origin=origin)


def _settings_health(request: Request, principal: Principal, origin: str) -> dict[str, Any]:
    principal.require("read")
    return ok(
        {
            "storage": settings_service.storage_health(),
            "ai": settings_service.test_ai_connection(repo=get_repository()) if query_bool(request, "testAi") else None,
        },
        request,
        origin=origin,
    )


def _admins_list(request: Request, principal: Principal, origin: str) -> dict[str, Any]:
    principal.require("settings")
    return ok(settings_service.list_admins(), request, origin=origin)


def _admins_change(request: Request, principal: Principal, origin: str) -> dict[str, Any]:
    principal.require("admin")
    action = "add" if request.method == "POST" else "remove"
    payload = settings_service.change_admin(
        str(request.body.get("email") or ""),
        str(request.body.get("group") or ""),
        action,
        actor=principal.email or principal.username,
        repo=get_repository(),
    )
    return ok(payload, request, origin=origin)


def _form_mapping_preview(request: Request, principal: Principal, origin: str) -> dict[str, Any]:
    principal.require("read")
    repo = get_repository()
    return ok(
        {
            "fieldMapping": field_mapping(repo),
            "roles": roles_config(repo),
            "rubric": rubric(repo),
            "ai": {k: v for k, v in ai_config(repo).items() if k != "api_key"},
            "processing": processing_config(repo),
        },
        request,
        origin=origin,
    )


# ---------------------------------------------------------------------------
# Route table
# ---------------------------------------------------------------------------

route("GET", r"/me")(_me)
route("GET", r"/dashboard/overview")(_dashboard_overview)

route("GET", r"/applicants")(_applicants_list)
route("GET", r"/applicants/(?P<applicant_id>[^/]+)")(_applicant_detail)
route("DELETE", r"/applicants/(?P<applicant_id>[^/]+)")(_applicant_erase)
route("GET", r"/applicants/(?P<applicant_id>[^/]+)/documents/(?P<document_id>[^/]+)/url")(_applicant_document_url)
route("POST", r"/applicants/(?P<applicant_id>[^/]+)/review")(_applicant_review)
route("PATCH", r"/applicants/(?P<applicant_id>[^/]+)/evaluation")(_applicant_manual_scores)
route("POST", r"/applicants/(?P<applicant_id>[^/]+)/reprocess")(_applicant_reprocess)
route("GET", r"/applicants/(?P<applicant_id>[^/]+)/audit")(_applicant_audit)

route("GET", r"/shortlist")(_shortlist)
route("POST", r"/shortlist/bulk")(_shortlist_bulk)

route("GET", r"/reports")(_reports_list)
route("POST", r"/reports/generate")(_reports_generate)
route("GET", r"/reports/(?P<report_id>[^/]+)/download")(_report_download)
route("GET", r"/reports/(?P<report_id>[^/]+)")(_report_detail)

route("GET", r"/settings")(_settings_get)
route("PUT", r"/settings/(?P<key>[a-z_]+)")(_settings_update)
route("POST", r"/settings/ai/test")(_settings_ai_test)
route("GET", r"/settings/health")(_settings_health)
route("GET", r"/form/mapping")(_form_mapping_preview)
route("GET", r"/admins")(_admins_list)
route("POST", r"/admins")(_admins_change)
route("DELETE", r"/admins")(_admins_change)
