"""Application ingestion: field mapping, document storage and idempotency.

This module is shared by the intake Lambda, the local development server and
the tests. Google Form field names are never assumed: they are resolved from
the editable field mapping configuration with normalised aliases.
"""

from __future__ import annotations

import base64
import binascii
import re
from dataclasses import dataclass
from typing import Any, Optional

from ..common.config import Settings, get_settings
from ..common.errors import PayloadTooLargeError, ValidationError
from ..common.logging_utils import get_logger
from ..common.models import (
    Applicant,
    DocumentRef,
    applicant_id_for,
    iso,
    new_id,
    parse_dt,
    slugify,
    utcnow,
)
from .storage import Storage
from .validator import (
    DocumentValidationError,
    MalwareDetectedError,
    ScanUnavailableError,
    safe_filename,
    scan_for_malware,
    validate_file,
)

logger = get_logger("sbg.ingest")

_NORMALISE = re.compile(r"[^a-z0-9]+")


def normalise_question(text: str) -> str:
    return _NORMALISE.sub("", str(text or "").lower())


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (list, tuple)):
        return "; ".join(str(v) for v in value if v is not None)
    if isinstance(value, bool):
        return "Yes" if value else "No"
    return str(value).strip()


def _as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return [str(v).strip() for v in value if str(v).strip()]
    if isinstance(value, str):
        return [part.strip() for part in re.split(r"[,;|\n]", value) if part.strip()]
    return [str(value).strip()]


def build_field_index(mapping: dict[str, Any]) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    """Return canonical -> field spec and normalised question -> spec."""
    canonical: dict[str, dict[str, Any]] = {}
    questions: dict[str, dict[str, Any]] = {}
    for field in mapping.get("fields", []):
        canonical[field["canonical"]] = field
        for candidate in [field.get("form_question", "")] + list(field.get("aliases", [])):
            key = normalise_question(candidate)
            if key:
                questions.setdefault(key, field)
    return canonical, questions


def map_answers(
    answers: dict[str, Any], mapping: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any], list[str]]:
    canonical_fields, question_index = build_field_index(mapping)
    mapped: dict[str, Any] = {}
    consumed: set[str] = set()
    for question, value in (answers or {}).items():
        field = question_index.get(normalise_question(question))
        if field:
            mapped[field["canonical"]] = value
            consumed.add(question)
    extra = {q: v for q, v in (answers or {}).items() if q not in consumed}
    missing_required = [
        field["canonical"]
        for field in canonical_fields.values()
        if field.get("required") and not _as_text(mapped.get(field["canonical"]))
    ]
    return mapped, extra, missing_required


def match_role(value: str, roles_config: dict[str, Any]) -> Optional[str]:
    key = normalise_question(value)
    if not key:
        return None
    for role in roles_config.get("roles", []):
        for candidate in [role.get("id", ""), role.get("name", "")] + list(role.get("aliases", [])):
            if normalise_question(candidate) == key:
                return str(role["id"])
    for role in roles_config.get("roles", []):
        name_key = normalise_question(role.get("name", ""))
        if name_key and (key in name_key or name_key in key):
            return str(role["id"])
    return None


def normalise_roles(values: list[str], roles_config: dict[str, Any]) -> tuple[list[str], list[str]]:
    resolved: list[str] = []
    unmapped: list[str] = []
    for value in values:
        role_id = match_role(value, roles_config)
        if role_id and role_id not in resolved:
            resolved.append(role_id)
        elif not role_id:
            unmapped.append(value)
    if not resolved:
        default = roles_config.get("default_role")
        if default:
            resolved = [str(default)]
    return resolved, unmapped


def parse_extra(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip().startswith("{"):
        import json

        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


@dataclass
class DecodedDocument:
    filename: str
    content_type: str
    data: bytes
    source_url: str = ""


def decode_documents(raw_documents: list[Any], settings: Settings) -> tuple[list[DecodedDocument], list[str]]:
    documents: list[DecodedDocument] = []
    errors: list[str] = []
    if not isinstance(raw_documents, list):
        return documents, ["documents must be a list"]
    if len(raw_documents) > settings.max_documents:
        raise PayloadTooLargeError(f"At most {settings.max_documents} documents may be submitted")

    for index, item in enumerate(raw_documents):
        if not isinstance(item, dict):
            errors.append(f"Document {index + 1} is not an object")
            continue
        name = safe_filename(item.get("name") or item.get("filename") or f"document_{index + 1}")
        content_type = str(item.get("mime_type") or item.get("content_type") or "")
        encoded = item.get("base64") or item.get("content") or ""
        if not encoded:
            errors.append(f"Document '{name}' has no content")
            continue
        try:
            data = base64.b64decode(encoded, validate=True)
        except (binascii.Error, ValueError):
            errors.append(f"Document '{name}' is not valid base64")
            continue
        if len(data) > settings.max_document_bytes:
            errors.append(f"Document '{name}' exceeds the size limit")
            continue
        try:
            scan_for_malware(data, name, settings)
        except MalwareDetectedError:
            errors.append(f"Document '{name}' failed the malware scan and was rejected")
            continue
        except ScanUnavailableError:
            raise ValidationError("Document security scanning is temporarily unavailable; please retry")
        documents.append(
            DecodedDocument(
                filename=name,
                content_type=content_type,
                data=data,
                source_url=str(item.get("source_url") or "")[:1000],
            )
        )
    return documents, errors


def build_applicant(
    payload: dict[str, Any],
    *,
    mapping: dict[str, Any],
    roles_config: dict[str, Any],
    settings: Settings,
) -> tuple[Applicant, list[str], dict[str, Any]]:
    source_id = str(payload.get("source_response_id") or "").strip()
    if not source_id:
        raise ValidationError("source_response_id is required for idempotency")
    if len(source_id) > 200:
        raise ValidationError("source_response_id is too long")

    answers = payload.get("answers")
    if isinstance(answers, str):
        answers = parse_extra(answers)
    if not isinstance(answers, dict) or not answers:
        raise ValidationError("answers must be a non-empty object")

    mapped, extra, missing_required = map_answers(answers, mapping)
    raw_roles = _as_list(mapped.get("roles")) or _as_list(payload.get("roles"))
    roles, unmapped_roles = normalise_roles(raw_roles, roles_config)

    responses: dict[str, Any] = {}
    for field in mapping.get("fields", []):
        canonical = field["canonical"]
        if canonical in ("resume",):
            continue
        if canonical in mapped:
            responses[canonical] = mapped[canonical]
    for canonical, value in mapped.items():
        if canonical not in responses and canonical != "resume":
            responses[canonical] = value
    responses["raw_answers"] = answers
    responses["extra_fields"] = extra
    responses["unmapped_role_preferences"] = unmapped_roles

    availability_hours = responses.get("availability_hours")
    if not _as_text(availability_hours):
        availability_text = _as_text(responses.get("availability"))
        match = re.search(r"(\d+(?:\.\d+)?)\s*(?:hours?|hrs?)", availability_text, re.I)
        if match:
            responses["availability_hours"] = match.group(1)

    document_errors = [str(e)[:300] for e in (payload.get("document_errors") or [])][:10]
    submitted_at = parse_dt(payload.get("submitted_at")) or utcnow()
    applicant = Applicant(
        applicant_id=applicant_id_for(source_id),
        source_response_id=source_id,
        submitted_at=submitted_at,
        full_name=_as_text(mapped.get("full_name"))[:200],
        email=_as_text(mapped.get("email")).lower()[:254],
        usn=_as_text(mapped.get("usn")).upper()[:40],
        phone=_as_text(mapped.get("phone"))[:30],
        department=_as_text(mapped.get("department"))[:120],
        year_of_study=_as_text(mapped.get("year_of_study"))[:40],
        roles=roles,
        responses=responses,
        processing_status="RECEIVED",
        form_id=str(payload.get("form_id") or "")[:200],
        form_title=str(payload.get("form_title") or "")[:300],
        source=str(payload.get("source") or "google_form")[:40],
    )
    applicant.missing_required_fields = missing_required + [
        label for label in (["Resume document"] if not payload.get("documents") and not document_errors else [])
    ]
    if document_errors:
        applicant.responses["document_errors"] = document_errors
    if missing_required:
        applicant.application_complete = False
    return applicant, missing_required, {"unmapped_roles": unmapped_roles, "extra_fields": extra}


def store_documents(
    applicant: Applicant,
    documents: list[DecodedDocument],
    storage: Storage,
    settings: Settings,
) -> tuple[list[DocumentRef], list[str]]:
    refs: list[DocumentRef] = []
    errors: list[str] = []
    seen_hashes: dict[str, str] = {}
    for document in documents:
        try:
            validated = validate_file(
                document.data,
                document.filename,
                document.content_type,
                max_bytes=settings.max_document_bytes,
                settings=settings,
            )
        except DocumentValidationError as exc:
            errors.append(f"{document.filename}: {exc}")
            continue

        duplicate_of = seen_hashes.get(validated.sha256, "")
        document_id = new_id("doc")
        try:
            key = storage.put_document(
                applicant.applicant_id, document_id, validated.filename, document.data, validated.content_type
            )
        except Exception as exc:  # noqa: BLE001
            logger.error("Failed to store document for %s: %s", applicant.applicant_id, type(exc).__name__)
            errors.append(f"{document.filename}: document storage failed")
            continue

        refs.append(
            DocumentRef(
                document_id=document_id,
                filename=validated.filename,
                content_type=validated.content_type,
                s3_key=key,
                size_bytes=validated.size_bytes,
                sha256=validated.sha256,
                source_url=document.source_url,
                extraction_status="DUPLICATE" if duplicate_of else "PENDING",
                duplicate_of=duplicate_of,
            )
        )
        seen_hashes.setdefault(validated.sha256, document_id)
    return refs, errors


def ingest_submission(
    payload: dict[str, Any],
    *,
    repo: Any,
    storage: Storage,
    mapping: dict[str, Any],
    roles_config: dict[str, Any],
    settings: Optional[Settings] = None,
) -> dict[str, Any]:
    settings = settings or get_settings()
    if not isinstance(payload, dict):
        raise ValidationError("Request body must be a JSON object")

    applicant, missing_required, meta = build_applicant(
        payload, mapping=mapping, roles_config=roles_config, settings=settings
    )
    raw_documents = payload.get("documents") or []
    documents, decode_errors = decode_documents(raw_documents, settings)
    refs, store_errors = store_documents(applicant, documents, storage, settings)
    applicant.documents = refs
    errors = decode_errors + store_errors + [str(e)[:300] for e in (payload.get("document_errors") or [])]
    if errors:
        applicant.responses["document_errors"] = errors[:15]
    if not refs:
        applicant.missing_required_fields = sorted(set(applicant.missing_required_fields + ["Resume document"]))
        applicant.application_complete = False
    if missing_required:
        applicant.application_complete = False
        applicant.missing_required_fields = sorted(set(applicant.missing_required_fields + missing_required))

    inserted = repo.put_applicant_if_absent(applicant)
    if not inserted:
        existing = repo.get_applicant(applicant.applicant_id)
        logger.info("Duplicate submission ignored for %s", applicant.applicant_id)
        return {
            "status": "DUPLICATE",
            "applicant_id": existing.applicant_id,
            "message": "This form response has already been received.",
            "submitted_at": iso(existing.submitted_at),
        }

    return {
        "status": "ACCEPTED",
        "applicant_id": applicant.applicant_id,
        "missing_required_fields": applicant.missing_required_fields,
        "documents_received": len(refs),
        "document_errors": errors,
        "submitted_at": iso(applicant.submitted_at),
    }
