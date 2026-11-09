"""Integration and unit tests for the FastAPI recruitment API layer."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from typing import Any, Dict

import pytest
from fastapi.testclient import TestClient

from backend.main import app
from backend.src.common.config import get_settings
from backend.src.common.models import Applicant, utcnow
from backend.src.common.repository import get_repository


@pytest.fixture
def client(isolated_environment, monkeypatch) -> TestClient:
    """Create a TestClient with local test store and auth bypass."""
    monkeypatch.setenv("ENVIRONMENT", "test")
    monkeypatch.setenv("USE_LOCAL_STORE", "true")
    monkeypatch.setenv("AUTH_DISABLED", "true")
    monkeypatch.setenv("AI_PROVIDER", "mock")
    monkeypatch.setenv("INTAKE_KEY", "test-secret-key-1234")
    monkeypatch.setenv("INTAKE_SIGNATURE_REQUIRED", "true")

    settings = get_settings()
    settings.auth_disabled = True
    settings.use_local_store = True
    settings.ai_provider = "mock"
    settings.intake_key = "test-secret-key-1234"
    settings.intake_signature_required = True

    return TestClient(app)


def make_signed_headers(body: Dict[str, Any], key: str = "test-secret-key-1234") -> Dict[str, str]:
    """Generate valid HMAC-SHA256 headers matching Google Apps Script."""
    body_str = json.dumps(body)
    ts = str(int(time.time()))
    signature = hmac.new(
        key.encode("utf-8"),
        f"{ts}.{body_str}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()
    return {
        "x-intake-key": key,
        "x-timestamp": ts,
        "x-signature": signature,
        "Content-Type": "application/json",
    }


# ---------------------------------------------------------------------------
# 1. Health & Status Tests
# ---------------------------------------------------------------------------


def test_health_endpoint(client: TestClient):
    resp = client.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["service"] == "sbg-ai-recruitment-backend"
    assert "timestamp" in data

    # Test /api/health alias
    resp_api = client.get("/api/health")
    assert resp_api.status_code == 200
    assert resp_api.json()["status"] == "ok"


# ---------------------------------------------------------------------------
# 2. Intake Endpoint Tests
# ---------------------------------------------------------------------------


def test_intake_rejects_missing_signature(client: TestClient, monkeypatch):
    monkeypatch.setenv("INTAKE_SIGNATURE_REQUIRED", "true")
    monkeypatch.setenv("AUTH_DISABLED", "false")
    settings = get_settings()
    settings.intake_signature_required = True
    settings.auth_disabled = False

    payload = {"response_id": "FORM-TEST-001", "answers": {}}
    resp = client.post("/api/intake", json=payload, headers={"x-intake-key": "test-secret-key-1234"})
    assert resp.status_code == 401


def test_intake_rejects_wrong_key(client: TestClient, monkeypatch):
    monkeypatch.setenv("AUTH_DISABLED", "false")
    get_settings().auth_disabled = False

    payload = {"response_id": "FORM-TEST-002", "answers": {}}
    headers = make_signed_headers(payload, key="wrong-key")
    headers["x-intake-key"] = "wrong-key"
    resp = client.post("/api/intake", json=payload, headers=headers)
    assert resp.status_code == 401


def test_intake_accepts_valid_submission(client: TestClient):
    payload = {
        "response_id": f"FORM-RESP-{int(time.time()*1000)}",
        "submitted_at": utcnow().isoformat(),
        "answers": {
            "Full Name": "Aarav Sharma",
            "Email Address": f"aarav.{int(time.time())}@sjbit.edu.in",
            "University Seat Number (USN)": f"1JB22CS{int(time.time()%1000):03d}",
            "Department": "Computer Science and Engineering",
            "Year of Study": "3rd Year",
            "Which team(s) are you applying for?": "Technical Team",
            "Why do you want to join AWS Student Builder Group?": "I build serverless applications with AWS Lambda and DynamoDB.",
        },
        "documents": [],
    }
    headers = make_signed_headers(payload)
    resp = client.post("/api/intake", json=payload, headers=headers)
    assert resp.status_code in (200, 202)
    data = resp.json()
    assert data["status"] == "ACCEPTED"
    assert "applicant_id" in data


# ---------------------------------------------------------------------------
# 3. Identity and Dashboard Overview Tests
# ---------------------------------------------------------------------------


def test_me_endpoint(client: TestClient):
    resp = client.get("/api/me")
    assert resp.status_code == 200
    data = resp.json()
    assert "user" in data
    assert "organization" in data
    assert data["user"]["isAdmin"] is True


def test_dashboard_overview_endpoint(client: TestClient):
    resp = client.get("/api/dashboard/overview")
    assert resp.status_code == 200
    data = resp.json()
    assert "stats" in data
    assert "roleStats" in data
    assert "scoreDistribution" in data
    assert "processingStatus" in data
    assert data["stats"]["totalApplications"] >= 0


# ---------------------------------------------------------------------------
# 4. Applicants List & Filters Tests
# ---------------------------------------------------------------------------


def test_list_applicants_endpoint(client: TestClient):
    resp = client.get("/api/applicants?pageSize=10")
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert "count" in data
    assert isinstance(data["items"], list)


def test_list_applicants_with_filters(client: TestClient):
    resp = client.get("/api/applicants?role=Technical Team&minScore=50&sort=score")
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data


def test_list_applicants_invalid_sort(client: TestClient):
    resp = client.get("/api/applicants?sort=invalid_column")
    assert resp.status_code == 400


# ---------------------------------------------------------------------------
# 5. Applicant Profile & Review Flow Tests
# ---------------------------------------------------------------------------


def test_applicant_detail_not_found(client: TestClient):
    resp = client.get("/api/applicants/NON-EXISTENT-ID")
    assert resp.status_code == 404


def test_review_and_manual_score_override(client: TestClient):
    repo = get_repository()
    # Seed a test applicant
    app_id = f"APP-TEST-{int(time.time()*1000)}"
    applicant = Applicant(
        applicant_id=app_id,
        source_response_id="TEST-RESP-999",
        submitted_at=utcnow(),
        full_name="Priya Patel",
        email=f"priya.{int(time.time())}@sjbit.edu.in",
        usn=f"1JB23IS{int(time.time()%1000):03d}",
        department="Information Science",
        year_of_study="2nd Year",
        roles=["Technical Team"],
        responses={"Full Name": "Priya Patel"},
        processing_status="COMPLETED",
        total_score=75.0,
    )
    repo.save_applicant(applicant)

    # 1. Get detail
    resp = client.get(f"/api/applicants/{app_id}")
    assert resp.status_code == 200
    assert resp.json()["applicantId"] == app_id

    # 2. Review applicant
    review_resp = client.post(
        f"/api/applicants/{app_id}/review",
        json={"decision": "APPROVED", "notes": "Strong AWS cloud portfolio", "reason": "Passed committee screening"},
    )
    assert review_resp.status_code == 200
    assert review_resp.json()["reviewStatus"] == "APPROVED"

    # 3. Check audit log
    audit_resp = client.get(f"/api/applicants/{app_id}/audit")
    assert audit_resp.status_code == 200
    assert len(audit_resp.json()["items"]) >= 1


# ---------------------------------------------------------------------------
# 6. Shortlisting & Bulk Actions Tests
# ---------------------------------------------------------------------------


def test_shortlist_endpoint(client: TestClient):
    resp = client.get("/api/shortlist")
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert "total" in data


def test_bulk_review_endpoint(client: TestClient):
    repo = get_repository()
    app_id = f"APP-BULK-{int(time.time()*1000)}"
    repo.save_applicant(
        Applicant(
            applicant_id=app_id,
            source_response_id="BULK-001",
            submitted_at=utcnow(),
            full_name="Bulk Candidate",
            email=f"bulk.{int(time.time())}@sjbit.edu.in",
            usn="1JB22CS999",
            department="CSE",
            year_of_study="3rd Year",
            roles=["Technical Team"],
            processing_status="COMPLETED",
            total_score=85.0,
        )
    )

    resp = client.post(
        "/api/shortlist/bulk",
        json={
            "applicantIds": [app_id],
            "decision": "APPROVED",
            "notes": "Bulk shortlist approval",
            "reason": "Top scoring quartile",
        },
    )
    assert resp.status_code == 200
    data = resp.json()
    assert app_id in data["updated"]


# ---------------------------------------------------------------------------
# 7. Reports Endpoints Tests
# ---------------------------------------------------------------------------


def test_reports_list_and_generate(client: TestClient):
    # List existing reports
    resp = client.get("/api/reports")
    assert resp.status_code == 200
    assert "items" in resp.json()

    # Generate an Excel report synchronously in test mode
    gen_resp = client.post(
        "/api/reports/generate",
        json={"type": "excel", "scope": {}},
    )
    assert gen_resp.status_code in (200, 202)
    rep_data = gen_resp.json()
    assert "report_id" in rep_data

    # Check report detail
    detail_resp = client.get(f"/api/reports/{rep_data['report_id']}")
    assert detail_resp.status_code == 200


# ---------------------------------------------------------------------------
# 8. Settings & Admin Endpoints Tests
# ---------------------------------------------------------------------------


def test_settings_read_and_ai_probe(client: TestClient):
    resp = client.get("/api/settings")
    assert resp.status_code == 200
    data = resp.json()
    assert "rubric" in data
    assert "eligibility" in data
    assert "roles" in data
    assert "aiPublic" in data

    # Test AI connection endpoint
    ai_resp = client.post("/api/settings/ai/test", json={})
    assert ai_resp.status_code == 200
    assert "ok" in ai_resp.json()


def test_settings_form_mapping(client: TestClient):
    resp = client.get("/api/form/mapping")
    assert resp.status_code == 200
    data = resp.json()
    assert "fieldMapping" in data
    assert "roles" in data
    assert "rubric" in data


def test_admins_management(client: TestClient):
    list_resp = client.get("/api/admins")
    assert list_resp.status_code == 200
    assert "items" in list_resp.json()
