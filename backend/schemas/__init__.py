"""Pydantic schemas for FastAPI validation and OpenAPI documentation."""

from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Intake Models (from Google Forms / Apps Script)
# ---------------------------------------------------------------------------


class UploadedDocument(BaseModel):
    filename: str
    content_type: Optional[str] = None
    data_base64: str
    drive_id: Optional[str] = None
    url: Optional[str] = None


class SubmissionPayload(BaseModel):
    response_id: str = Field(..., description="Unique Google Form submission ID")
    submitted_at: Optional[str] = Field(None, description="ISO timestamp of submission")
    answers: Dict[str, Any] = Field(default_factory=dict, description="Raw form answers keyed by question title")
    documents: List[UploadedDocument] = Field(default_factory=list, description="Base64 encoded attached resumes/files")
    client_metadata: Optional[Dict[str, Any]] = None


class SubmissionResponse(BaseModel):
    status: Literal["ACCEPTED", "DUPLICATE", "REJECTED"]
    applicant_id: str
    duplicate: bool = False
    documents_received: int = 0
    message: Optional[str] = None
    queue: Optional[Dict[str, Any]] = None


# ---------------------------------------------------------------------------
# Review & Scoring Models
# ---------------------------------------------------------------------------


class ReviewApplicantRequest(BaseModel):
    decision: Literal["APPROVED", "REJECTED", "MANUAL_REVIEW", "PENDING"]
    notes: Optional[str] = Field("", description="Reviewer feedback or notes")
    reason: Optional[str] = Field("", description="Justification for the decision")


class ManualScoreOverrideRequest(BaseModel):
    scores: Dict[str, float] = Field(..., description="Keyed by criterion_id with point values")
    reason: str = Field(..., min_length=3, description="Mandatory audit explanation for manual override")


class BulkReviewRequest(BaseModel):
    applicantIds: List[str] = Field(..., min_items=1, description="List of applicant IDs to update")
    decision: Literal["APPROVED", "REJECTED", "MANUAL_REVIEW"]
    notes: Optional[str] = ""
    reason: Optional[str] = Field("", description="Reason recorded in the audit trail")


class EraseApplicantRequest(BaseModel):
    reason: str = Field(..., min_length=3, description="Justification for deleting applicant and all personal data")


# ---------------------------------------------------------------------------
# Reports Models
# ---------------------------------------------------------------------------


class GenerateReportRequest(BaseModel):
    type: Optional[str] = Field(None, description="Report type: excel, consolidated_pdf, role_pdf, candidate_pdf")
    kind: Optional[str] = None
    scope: Optional[Dict[str, Any]] = Field(default_factory=dict)
    role: Optional[str] = None
    applicantId: Optional[str] = None


# ---------------------------------------------------------------------------
# Admin & Settings Models
# ---------------------------------------------------------------------------


class AdminChangeRequest(BaseModel):
    email: str = Field(..., description="Administrator email address")
    group: Literal["sbg-admins", "sbg-reviewers", "sbg-viewers"] = Field(
        ..., description="Assigned administrative group"
    )


class LoginRequest(BaseModel):
    email: str
    password: str


class LoginResponse(BaseModel):
    accessToken: str
    idToken: str
    refreshToken: Optional[str] = ""
    expiresIn: int = 3600
    user: Dict[str, Any]

