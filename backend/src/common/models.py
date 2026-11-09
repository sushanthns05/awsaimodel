"""Domain models for the AWS Student Builder AI Recruitment System.

All models are plain dataclasses so they can be used by Lambda handlers,
the local development server, tests and report generators without any
framework dependency.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any, Literal, Optional

ProcessingStatus = Literal[
    "RECEIVED",
    "QUEUED",
    "EXTRACTING",
    "EXTRACTED",
    "EVALUATING",
    "SCORING",
    "COMPLETED",
    "NEEDS_REVIEW",
    "FAILED",
    "DUPLICATE",
]

ReviewStatus = Literal["PENDING", "APPROVED", "REJECTED", "MANUAL_REVIEW"]

Recommendation = Literal[
    "STRONG_INTERVIEW",
    "INTERVIEW_CONSIDERATION",
    "MANUAL_REVIEW",
    "ELIGIBILITY_REVIEW",
    "NEEDS_REVIEW",
]

ELIGIBILITY_PASS = "PASS"
ELIGIBILITY_FAIL = "FAIL"
ELIGIBILITY_UNKNOWN = "UNKNOWN"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: Optional[datetime]) -> Optional[str]:
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_dt(value: Any) -> Optional[datetime]:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value
    text = str(value).strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    for parser in (
        lambda v: datetime.fromisoformat(v),
        lambda v: datetime.strptime(v, "%Y-%m-%d %H:%M:%S"),
        lambda v: datetime.strptime(v, "%d/%m/%Y %H:%M:%S"),
        lambda v: datetime.strptime(v, "%m/%d/%Y %H:%M:%S"),
    ):
        try:
            parsed = parser(text)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed
        except (ValueError, TypeError):
            continue
    return None


def new_id(prefix: str) -> str:
    from uuid import uuid4

    return f"{prefix}_{uuid4().hex}"


def applicant_id_for(source_response_id: str) -> str:
    """Deterministic applicant id so re-deliveries never create duplicates."""
    digest = hashlib.sha256(f"sbg-applicant::{source_response_id}".encode()).hexdigest()
    return f"APP-{digest[:16].upper()}"


def slugify(value: str) -> str:
    text = re.sub(r"[^a-zA-Z0-9]+", "_", (value or "").strip().lower()).strip("_")
    return text or "unknown"


def normalize_roles(roles: Any, allowed: Optional[list[str]] = None) -> list[str]:
    if roles is None:
        return []
    if isinstance(roles, str):
        raw = [part.strip() for part in re.split(r"[,;|\n]", roles)]
    elif isinstance(roles, (list, tuple, set)):
        raw = [str(part).strip() for part in roles]
    else:
        raw = [str(roles).strip()]
    out: list[str] = []
    for role in raw:
        if not role:
            continue
        rid = role if re.fullmatch(r"[a-z0-9_\-]{2,64}", role) else slugify(role)
        if allowed is not None and rid not in allowed:
            # keep unknown preferences in "other" so nothing is silently lost
            continue
        if rid not in out:
            out.append(rid)
    return out


@dataclass
class DocumentRef:
    document_id: str
    filename: str
    content_type: str
    s3_key: str
    size_bytes: int = 0
    sha256: str = ""
    source_url: str = ""
    extraction_status: str = "PENDING"
    extraction_error: str = ""
    page_count: int = 0
    text_chars: int = 0
    textract_used: bool = False
    scanned: bool = False
    duplicate_of: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DocumentRef":
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class Applicant:
    applicant_id: str
    source_response_id: str
    submitted_at: datetime
    full_name: str
    email: str
    usn: str = ""
    phone: str = ""
    department: str = ""
    year_of_study: str = ""
    roles: list[str] = field(default_factory=list)
    responses: dict[str, Any] = field(default_factory=dict)
    documents: list[DocumentRef] = field(default_factory=list)
    processing_status: ProcessingStatus = "RECEIVED"
    processing_error: str = ""
    extracted_text_key: str = ""
    extracted_text_chars: int = 0
    extraction_summary: dict[str, Any] = field(default_factory=dict)
    application_complete: bool = True
    missing_required_fields: list[str] = field(default_factory=list)
    urgent_review: bool = False
    review_status: ReviewStatus = "PENDING"
    review_decision: str = ""
    review_notes: str = ""
    reviewed_by: str = ""
    reviewed_at: Optional[datetime] = None
    total_score: float = 0.0
    recommendation: str = "NEEDS_REVIEW"
    eligibility_status: str = ELIGIBILITY_UNKNOWN
    eligibility_failures: list[str] = field(default_factory=list)
    role_scores: dict[str, float] = field(default_factory=dict)
    latest_evaluation_id: str = ""
    rubric_version: str = ""
    form_id: str = ""
    form_title: str = ""
    source: str = "google_form"
    schema_version: int = 1
    created_at: datetime = field(default_factory=utcnow)
    updated_at: datetime = field(default_factory=utcnow)
    version: int = 1

    def every_document_extracted(self) -> bool:
        return all(d.extraction_status in ("EXTRACTED", "SKIPPED", "DUPLICATE") for d in self.documents)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["submitted_at"] = iso(self.submitted_at)
        data["reviewed_at"] = iso(self.reviewed_at)
        data["created_at"] = iso(self.created_at)
        data["updated_at"] = iso(self.updated_at)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Applicant":
        payload = dict(data)
        payload["submitted_at"] = parse_dt(payload.get("submitted_at")) or utcnow()
        payload["reviewed_at"] = parse_dt(payload.get("reviewed_at"))
        payload["created_at"] = parse_dt(payload.get("created_at")) or utcnow()
        payload["updated_at"] = parse_dt(payload.get("updated_at")) or utcnow()
        payload["documents"] = [DocumentRef.from_dict(d) for d in payload.get("documents") or []]
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in payload.items() if k in known})

    def search_text(self) -> str:
        parts = [
            self.applicant_id, self.full_name, self.email, self.usn, self.phone,
            self.department, self.year_of_study, " ".join(self.roles),
        ]
        skills = self.responses.get("technical_skills") or ""
        if isinstance(skills, (list, tuple)):
            skills = " ".join(map(str, skills))
        parts.append(str(skills))
        return " | ".join(p.lower() for p in parts if p)


@dataclass
class CriterionScore:
    criterion_id: str
    name: str
    max_score: float
    suggested_score: Optional[float] = None
    final_score: float = 0.0
    evidence: list[str] = field(default_factory=list)
    reasoning: str = ""
    validated: bool = True
    validation_error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CriterionScore":
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class EligibilityResult:
    rule_id: str
    label: str
    status: str
    mandatory: bool = True
    detail: str = ""
    observed: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EligibilityResult":
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in data.items() if k in known})


@dataclass
class Evaluation:
    applicant_id: str
    evaluation_id: str
    rubric_version: str
    created_at: datetime
    criteria: list[CriterionScore] = field(default_factory=list)
    total_score: float = 0.0
    max_score: float = 100.0
    score_complete: bool = True
    ai_suggested_total: Optional[float] = None
    recommendation: str = "NEEDS_REVIEW"
    eligibility: list[EligibilityResult] = field(default_factory=list)
    eligibility_status: str = ELIGIBILITY_UNKNOWN
    eligibility_failures: list[str] = field(default_factory=list)
    summary: str = ""
    strengths: list[str] = field(default_factory=list)
    weaknesses: list[str] = field(default_factory=list)
    missing_information: list[str] = field(default_factory=list)
    inconsistencies: list[str] = field(default_factory=list)
    uncertain_findings: list[str] = field(default_factory=list)
    technical_skills: list[str] = field(default_factory=list)
    nontechnical_skills: list[str] = field(default_factory=list)
    projects: list[dict[str, Any]] = field(default_factory=list)
    certifications: list[str] = field(default_factory=list)
    experience: list[dict[str, Any]] = field(default_factory=list)
    leadership_evidence: list[str] = field(default_factory=list)
    communication_evidence: list[str] = field(default_factory=list)
    interview_questions: list[dict[str, Any]] = field(default_factory=list)
    role_evaluations: list[dict[str, Any]] = field(default_factory=list)
    confidence: str = "medium"
    model_metadata: dict[str, Any] = field(default_factory=dict)
    validation_errors: list[str] = field(default_factory=list)
    prompt_version: str = ""
    document_coverage: dict[str, Any] = field(default_factory=dict)
    review_status: ReviewStatus = "PENDING"
    human_notes: str = ""
    human_override: dict[str, Any] = field(default_factory=dict)
    superseded: bool = False
    version: int = 1

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["created_at"] = iso(self.created_at)
        data["criteria"] = [c.to_dict() if isinstance(c, CriterionScore) else c for c in self.criteria]
        data["eligibility"] = [e.to_dict() if isinstance(e, EligibilityResult) else e for e in self.eligibility]
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Evaluation":
        payload = dict(data)
        payload["created_at"] = parse_dt(payload.get("created_at")) or utcnow()
        payload["criteria"] = [CriterionScore.from_dict(c) for c in payload.get("criteria") or []]
        payload["eligibility"] = [EligibilityResult.from_dict(e) for e in payload.get("eligibility") or []]
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in payload.items() if k in known})


@dataclass
class AuditEntry:
    audit_id: str
    applicant_id: str
    reviewer: str
    action: str
    timestamp: datetime
    previous_value: Any = None
    updated_value: Any = None
    reason: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["timestamp"] = iso(self.timestamp)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AuditEntry":
        payload = dict(data)
        payload["timestamp"] = parse_dt(payload.get("timestamp")) or utcnow()
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in payload.items() if k in known})


@dataclass
class ReportRecord:
    report_id: str
    kind: str
    status: str
    created_at: datetime
    created_by: str
    s3_key: str = ""
    filename: str = ""
    size_bytes: int = 0
    scope: dict[str, Any] = field(default_factory=dict)
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["created_at"] = iso(self.created_at)
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ReportRecord":
        payload = dict(data)
        payload["created_at"] = parse_dt(payload.get("created_at")) or utcnow()
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in payload.items() if k in known})
