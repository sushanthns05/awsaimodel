"""Test data builders shared by the backend test modules."""

from __future__ import annotations

import base64
import io
import json
from typing import Any, Optional

from backend.src.common.models import Applicant, DocumentRef, utcnow
from backend.src.common.repository import ApplicantFilters


# ---------------------------------------------------------------------------
# Documents
# ---------------------------------------------------------------------------


def make_pdf(text: str, *, pages: int = 1) -> bytes:
    import fitz

    document = fitz.open()
    for _ in range(pages):
        page = document.new_page()
        page.insert_text((72, 72), text)
    data = document.tobytes()
    document.close()
    return data


def make_blank_pdf() -> bytes:
    import fitz

    document = fitz.open()
    document.new_page()
    data = document.tobytes()
    document.close()
    return data


def make_docx(paragraphs: list[str]) -> bytes:
    import docx

    document = docx.Document()
    for paragraph in paragraphs:
        document.add_paragraph(paragraph)
    table = document.add_table(rows=1, cols=2)
    table.cell(0, 0).text = "Skill"
    table.cell(0, 1).text = "Python"
    buffer = io.BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def encode_document(data: bytes, filename: str = "resume.pdf", content_type: str = "application/pdf") -> dict[str, Any]:
    return {
        "name": filename,
        "mime_type": content_type,
        "base64": base64.b64encode(data).decode("ascii"),
    }


# ---------------------------------------------------------------------------
# Applications
# ---------------------------------------------------------------------------

COMPLETE_ANSWERS: dict[str, Any] = {
    "Full Name": "Asha Rao",
    "Email Address": "Asha.Rao@example.com",
    "University Seat Number (USN)": "1AB23CS001",
    "Phone Number": "+91 9876543210",
    "Department": "Computer Science",
    "Year of Study": "3",
    "Which team(s) are you applying for?": ["Technical Team", "Social Media"],
    "Technical Skills": "Python, AWS Lambda, React and DynamoDB",
    "Experience (internships, freelance, clubs, competitions)": (
        "Built a serverless attendance tool used by 120 students; interned for six weeks on a data pipeline."
    ),
    "Projects you have built": (
        "Project Atlas: serverless file processing on AWS with S3, SQS and Lambda. Led a team of three."
    ),
    "Certifications": "AWS Cloud Practitioner",
    "Leadership or team experience": "Technical lead for the college coding club; ran weekly workshops.",
    "Why do you want to join the AWS Student Builder Group?": (
        "I want to help other students learn cloud engineering through hands-on workshops."
    ),
    "Weekly availability and commitment": "8 hours per week",
    "Hours available per week": "8",
    "I consent to my application being processed for recruitment": "Yes",
    "Favourite colour": "Blue",
}


def make_submission(
    *,
    response_id: str = "response-0001",
    with_document: bool = True,
    answers: Optional[dict[str, Any]] = None,
    document: Optional[bytes] = None,
    extra_documents: Optional[list[dict[str, Any]]] = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "source_response_id": response_id,
        "form_id": "form-test",
        "form_title": "SBG Recruitment 2026-27",
        "submitted_at": "2026-03-01T10:00:00Z",
        "answers": dict(COMPLETE_ANSWERS if answers is None else answers),
    }
    documents: list[dict[str, Any]] = []
    if with_document:
        documents.append(
            encode_document(
                document
                or make_pdf(
                    "Asha Rao resume. Python AWS Lambda DynamoDB React. "
                    "Project Atlas serverless processing. Led a team of three students."
                )
            )
        )
    documents.extend(extra_documents or [])
    payload["documents"] = documents
    return payload


def make_applicant(
    *,
    applicant_id: str = "APP-TEST0000000001",
    source_response_id: str = "response-test-1",
    full_name: str = "Test Applicant",
    email: str = "test.applicant@example.com",
    usn: str = "1AB23CS002",
    department: str = "Computer Science",
    year_of_study: str = "3",
    roles: Optional[list[str]] = None,
    with_document: bool = True,
    availability: str = "8 hours per week",
    responses: Optional[dict[str, Any]] = None,
) -> Applicant:
    documents = []
    if with_document:
        documents.append(
            DocumentRef(
                document_id="doc_test_1",
                filename="resume.pdf",
                content_type="application/pdf",
                s3_key="applicants/test/resume.pdf",
                size_bytes=1234,
                sha256="a" * 64,
                extraction_status="EXTRACTED",
            )
        )
    base_responses: dict[str, Any] = {
        "technical_skills": "Python, AWS",
        "experience": "Built a serverless project and led a team.",
        "projects": "Project Atlas using S3, SQS and Lambda.",
        "leadership": "Coding club technical lead.",
        "motivation": "Help students learn cloud engineering.",
        "availability": availability,
        "availability_hours": "8",
    }
    base_responses.update(responses or {})
    return Applicant(
        applicant_id=applicant_id,
        source_response_id=source_response_id,
        submitted_at=utcnow(),
        full_name=full_name,
        email=email,
        usn=usn,
        department=department,
        year_of_study=year_of_study,
        roles=list(["technical_team"] if roles is None else roles),
        responses=base_responses,
        documents=documents,
    )


def save_applicant(repo, applicant: Applicant) -> Applicant:
    assert repo.put_applicant_if_absent(applicant), "applicant unexpectedly exists"
    return applicant


def add_applicant(repo, **kwargs) -> Applicant:
    applicant = make_applicant(**kwargs)
    return save_applicant(repo, applicant)


# ---------------------------------------------------------------------------
# AI response builders
# ---------------------------------------------------------------------------


def make_ai_result(
    rubric: dict[str, Any],
    roles: list[str],
    *,
    fraction: float = 0.8,
    evidence: bool = True,
    roles_fraction: Optional[float] = None,
) -> dict[str, Any]:
    criteria = []
    for criterion in rubric.get("criteria", []):
        criteria.append(
            {
                "id": criterion["id"],
                "score_fraction": fraction,
                "evidence": (["Demonstrated Python and AWS work on Project Atlas."] if evidence else []),
                "reasoning": "Evidence supports the proposed fraction.",
            }
        )
    role_fraction = fraction if roles_fraction is None else roles_fraction
    return {
        "candidate_summary": "A final year student with applied cloud project experience.",
        "technical_skills": ["Python", "AWS Lambda"],
        "nontechnical_skills": ["Collaboration"],
        "projects": [
            {
                "name": "Project Atlas",
                "description": "Serverless file processing pipeline",
                "evidence": "Built with S3, SQS and Lambda",
                "outcome": "Processed files for a campus tool",
            }
        ],
        "experience": [],
        "certifications": ["AWS Cloud Practitioner"],
        "leadership_evidence": ["Led a team of three students"],
        "communication_evidence": ["Ran weekly workshops"],
        "criteria": criteria,
        "role_knowledge": {
            role: {
                "score_fraction": role_fraction,
                "evidence": (["Hands-on cloud project work."] if evidence else []),
                "reasoning": "Directly relevant to the role.",
            }
            for role in roles
        },
        "role_fit": {role: {"fit": "strong", "rationale": "Relevant project evidence."} for role in roles},
        "strengths": ["Applied AWS project experience"],
        "weaknesses": ["Limited formal internship duration"],
        "missing_information": [],
        "inconsistencies": [],
        "uncertain_findings": [],
        "interview_questions": [
            {"role": roles[0], "question": "How did you design the SQS retry policy?", "why": "Tests depth"}
        ],
        "confidence": "high",
    }


# ---------------------------------------------------------------------------
# API Gateway events
# ---------------------------------------------------------------------------


def api_event(
    method: str,
    path: str,
    *,
    body: Optional[dict[str, Any]] = None,
    query: Optional[dict[str, str]] = None,
    groups: Optional[list[str]] = None,
    claims: Optional[dict[str, Any]] = None,
    raw_body: Optional[str] = None,
    headers: Optional[dict[str, str]] = None,
    request_id: str = "test-request",
) -> dict[str, Any]:
    event_headers = {"content-type": "application/json"}
    event_headers.update(headers or {})
    if body is not None:
        raw_body = json.dumps(body)
    authorizer: dict[str, Any] = {}
    if claims is None and groups is not None:
        claims = {
            "sub": "user-1",
            "email": "reviewer@sjbit.edu.in",
            "cognito:username": "reviewer",
            "cognito:groups": groups,
            "token_use": "id",
        }
    if claims:
        authorizer = {"jwt": {"claims": claims}}
    return {
        "version": "2.0",
        "rawPath": path,
        "rawQueryString": "",
        "headers": event_headers,
        "queryStringParameters": query or {},
        "requestContext": {
            "http": {"method": method, "path": path, "sourceIp": "127.0.0.1"},
            "requestId": request_id,
            "stage": "test",
            "authorizer": authorizer,
        },
        "body": raw_body or "",
        "isBase64Encoded": False,
    }


def response_json(response: dict[str, Any]) -> Any:
    body = response.get("body") or "{}"
    return json.loads(body)


def seed_applicants(repo, count: int = 3):
    applicants = []
    for index in range(count):
        applicants.append(
            add_applicant(
                repo,
                applicant_id=f"APP-TEST{index:012d}",
                source_response_id=f"response-{index}",
                full_name=f"Applicant {index}",
                email=f"applicant{index}@example.com",
                roles=["technical_team"],
            )
        )
    return applicants
