"""Admin API routing, authentication, RBAC and contract tests."""

from __future__ import annotations

import json

import pytest

from backend.src.common.auth import authenticate, principal_from_claims, verify_intake_request
from backend.src.common.config_store import eligibility_config, roles_config, rubric
from backend.src.common.errors import ForbiddenError, UnauthorizedError
from backend.src.handlers import admin_api, intake
from backend.src.scoring.engine import build_evaluation
from backend.tests.helpers import (
    add_applicant,
    api_event,
    make_ai_result,
    make_submission,
    response_json,
)

ADMIN = ["sbg-admins"]
REVIEWER = ["sbg-reviewers"]
VIEWER = ["sbg-viewers"]


def _call(event):
    return admin_api.lambda_handler(event, None)


def _seed_evaluated(runtime, index=0, **overrides):
    applicant = add_applicant(
        runtime.repo,
        applicant_id=f"APP-API{index:06d}",
        source_response_id=f"api-{index}",
        full_name=overrides.pop("full_name", f"API Applicant {index}"),
        email=overrides.pop("email", f"api{index}@example.com"),
        roles=overrides.pop("roles", ["technical_team"]),
        **overrides,
    )
    evaluation = build_evaluation(
        applicant,
        make_ai_result(rubric(), ["technical_team"], fraction=0.76),
        rubric(),
        roles_config(),
        eligibility_config(),
        model_metadata={"model": "test-model"},
        prompt_version="test",
    )
    runtime.repo.save_evaluation(evaluation)
    applicant.latest_evaluation_id = evaluation.evaluation_id
    applicant.total_score = evaluation.total_score
    applicant.recommendation = evaluation.recommendation
    applicant.eligibility_status = evaluation.eligibility_status
    applicant.role_scores = {"technical_team": evaluation.total_score}
    applicant.processing_status = "COMPLETED"
    runtime.repo.save_applicant(applicant)
    return applicant, evaluation


def test_health_is_public(runtime, app_settings, monkeypatch):
    monkeypatch.setattr(app_settings, "auth_disabled", False)
    response = _call(api_event("GET", "/health"))
    assert response["statusCode"] == 200
    assert response_json(response)["status"] == "ok"


def test_missing_token_returns_401(runtime, app_settings, monkeypatch):
    monkeypatch.setattr(app_settings, "auth_disabled", False)
    response = _call(api_event("GET", "/applicants"))
    assert response["statusCode"] == 401
    assert response_json(response)["error"]["code"] == "UNAUTHORIZED"


def test_local_dev_auth_bypass_still_uses_rbac(runtime, app_settings, monkeypatch):
    monkeypatch.setattr(app_settings, "auth_disabled", True)
    event = api_event("GET", "/applicants")
    event["headers"]["x-dev-user"] = "dev@sjbit.edu.in"
    principal = authenticate(event, app_settings)
    assert principal.email == "dev@sjbit.edu.in"
    assert principal.can("settings")
    assert principal.is_admin


def test_principal_permissions_from_cognito_groups():
    admin = principal_from_claims({"sub": "1", "cognito:groups": ["sbg-admins"]})
    reviewer = principal_from_claims({"sub": "2", "cognito:groups": ["sbg-reviewers"]})
    viewer = principal_from_claims({"sub": "3", "cognito:groups": ["sbg-viewers"]})
    assert admin.can("admin") and admin.can("settings")
    assert reviewer.can("shortlist") and not reviewer.can("settings")
    assert viewer.can("read") and not viewer.can("review")
    with pytest.raises(ForbiddenError):
        viewer.require("review")
    with pytest.raises(UnauthorizedError):
        principal_from_claims({})


def test_viewer_can_read_but_not_review(runtime):
    applicant, _ = _seed_evaluated(runtime)

    listing = _call(api_event("GET", "/applicants", groups=VIEWER))
    assert listing["statusCode"] == 200

    detail = _call(api_event("GET", f"/applicants/{applicant.applicant_id}", groups=VIEWER))
    assert detail["statusCode"] == 200

    review = _call(
        api_event("POST", f"/applicants/{applicant.applicant_id}/review", groups=VIEWER, body={"decision": "PENDING"})
    )
    assert review["statusCode"] == 403


def test_reviewer_cannot_read_settings(runtime):
    response = _call(api_event("GET", "/settings", groups=REVIEWER))
    assert response["statusCode"] == 403


def test_admin_can_read_settings_without_secrets(runtime):
    response = _call(api_event("GET", "/settings", groups=ADMIN))
    assert response["statusCode"] == 200
    payload = response_json(response)
    serialised = json.dumps(payload)
    assert "api_key" not in serialised
    assert '"apiKey"' not in serialised
    assert '"apiKeyValue"' not in serialised
    assert payload["aiPublic"]["apiKeyConfigured"] is False
    assert payload["environment"]["localMode"] is True


def test_settings_update_is_validated(runtime):
    bad = _call(
        api_event("PUT", "/settings/rubric", groups=ADMIN, body={"criteria": []}),
    )
    assert bad["statusCode"] == 400

    good = _call(
        api_event(
            "PUT",
            "/settings/organization",
            groups=ADMIN,
            body={"name": "AWS Student Builder Group", "institution": "SJBIT", "cycle": "2026-27"},
        )
    )
    assert good["statusCode"] == 200
    assert response_json(good)["version"] == 1

    rejected_secret = _call(
        api_event("PUT", "/settings/ai", groups=ADMIN, body={"provider": "deepseek", "api_key": "sk-secret"})
    )
    assert rejected_secret["statusCode"] == 400


def test_unknown_section_and_route_return_errors(runtime):
    assert _call(api_event("PUT", "/settings/nope", groups=ADMIN, body={}))["statusCode"] == 400
    assert _call(api_event("GET", "/does/not/exist", groups=ADMIN))["statusCode"] == 404


def test_me_returns_permissions_and_organization(runtime):
    response = _call(api_event("GET", "/me", groups=REVIEWER))
    payload = response_json(response)
    assert response["statusCode"] == 200
    assert payload["user"]["groups"] == REVIEWER
    assert "organization" in payload


def test_applicant_list_filters_and_pagination(runtime):
    _seed_evaluated(runtime, 0, full_name="Alpha Applicant")
    _seed_evaluated(runtime, 1, full_name="Beta Applicant")
    _seed_evaluated(runtime, 2, full_name="Gamma Applicant")

    all_items = response_json(_call(api_event("GET", "/applicants", groups=VIEWER, query={"pageSize": "2"})))
    assert all_items["count"] == 2
    assert all_items["nextCursor"]

    page_two = response_json(
        _call(api_event("GET", "/applicants", groups=VIEWER, query={"pageSize": "2", "cursor": all_items["nextCursor"]}))
    )
    assert page_two["count"] == 1

    filtered = response_json(_call(api_event("GET", "/applicants", groups=VIEWER, query={"q": "beta"})))
    assert filtered["count"] == 1
    assert filtered["items"][0]["fullName"] == "Beta Applicant"

    by_score = response_json(_call(api_event("GET", "/applicants", groups=VIEWER, query={"minScore": "70"})))
    assert by_score["count"] == 3

    invalid_sort = _call(api_event("GET", "/applicants", groups=VIEWER, query={"sort": "hacker"}))
    assert invalid_sort["statusCode"] == 400

    invalid_number = _call(api_event("GET", "/applicants", groups=VIEWER, query={"minScore": "abc"}))
    assert invalid_number["statusCode"] == 400


def test_applicant_detail_contains_evaluation_and_audit(runtime):
    applicant, evaluation = _seed_evaluated(runtime)
    response = _call(api_event("GET", f"/applicants/{applicant.applicant_id}", groups=VIEWER))
    payload = response_json(response)
    assert response["statusCode"] == 200
    assert payload["applicant"]["applicant_id"] == applicant.applicant_id
    assert payload["evaluation"]["evaluation_id"] == evaluation.evaluation_id
    assert payload["evaluationHistory"][0]["evaluationId"] == evaluation.evaluation_id


def test_missing_applicant_returns_404(runtime):
    assert _call(api_event("GET", "/applicants/APP-NOT-FOUND", groups=VIEWER))["statusCode"] == 404


def test_review_decision_requires_reason_for_flagged_applicant(runtime):
    applicant, _ = _seed_evaluated(runtime)
    applicant.recommendation = "NEEDS_REVIEW"
    applicant.urgent_review = True
    runtime.repo.save_applicant(applicant)

    rejected = _call(
        api_event(
            "POST",
            f"/applicants/{applicant.applicant_id}/review",
            groups=REVIEWER,
            body={"decision": "SHORTLISTED", "notes": "Strong panel impression."},
        )
    )
    assert rejected["statusCode"] == 400

    accepted = _call(
        api_event(
            "POST",
            f"/applicants/{applicant.applicant_id}/review",
            groups=REVIEWER,
            body={"decision": "SHORTLISTED", "notes": "Strong panel impression.", "reason": "Panel verified the evidence."},
        )
    )
    assert accepted["statusCode"] == 200
    assert response_json(accepted)["reviewStatus"] == "APPROVED"
    assert runtime.repo.get_applicant(applicant.applicant_id).review_decision == "SHORTLISTED"
    assert any(entry.action == "REVIEW_DECISION" for entry in runtime.repo.list_audit(applicant.applicant_id))


def test_bulk_review_requires_reason_for_flagged_items(runtime):
    applicant, _ = _seed_evaluated(runtime)
    applicant.recommendation = "NEEDS_REVIEW"
    runtime.repo.save_applicant(applicant)
    response = _call(
        api_event(
            "POST",
            "/shortlist/bulk",
            groups=REVIEWER,
            body={"applicantIds": [applicant.applicant_id, "APP-MISSING"], "decision": "SHORTLISTED"},
        )
    )
    payload = response_json(response)
    assert response["statusCode"] == 200
    assert payload["updated"] == []
    assert len(payload["skipped"]) == 2


def test_shortlist_ranking_endpoint(runtime):
    first, _ = _seed_evaluated(runtime, 0)
    second, _ = _seed_evaluated(runtime, 1)
    first.total_score = 90
    first.role_scores = {"technical_team": 90}
    runtime.repo.save_applicant(first)
    second.total_score = 55
    second.role_scores = {"technical_team": 55}
    runtime.repo.save_applicant(second)

    response = _call(api_event("GET", "/shortlist", groups=VIEWER, query={"role": "technical_team"}))
    payload = response_json(response)
    assert response["statusCode"] == 200
    assert [item["applicantId"] for item in payload["items"]] == [first.applicant_id, second.applicant_id]


def test_manual_score_override_endpoint(runtime):
    applicant, evaluation = _seed_evaluated(runtime)
    response = _call(
        api_event(
            "PATCH",
            f"/applicants/{applicant.applicant_id}/evaluation",
            groups=REVIEWER,
            body={"scores": {"communication": 5}, "reason": "Panel reviewed additional evidence."},
        )
    )
    assert response["statusCode"] == 200
    payload = response_json(response)
    assert payload["totalScore"] > evaluation.total_score
    latest = runtime.repo.get_latest_evaluation(applicant.applicant_id)
    assert latest.human_override["reviewer"] == "reviewer@sjbit.edu.in"


def test_manual_score_override_requires_reason(runtime):
    applicant, _ = _seed_evaluated(runtime)
    response = _call(
        api_event(
            "PATCH",
            f"/applicants/{applicant.applicant_id}/evaluation",
            groups=REVIEWER,
            body={"scores": {"communication": 5}, "reason": ""},
        )
    )
    assert response["statusCode"] == 400


def test_report_generation_and_download_endpoints(runtime):
    _seed_evaluated(runtime)
    generated = _call(api_event("POST", "/reports/generate", groups=REVIEWER, body={"type": "excel"}))
    payload = response_json(generated)
    assert generated["statusCode"] == 200
    assert payload["status"] == "COMPLETED"
    assert payload["downloadUrl"]

    listing = response_json(_call(api_event("GET", "/reports", groups=VIEWER)))
    assert listing["count"] == 1

    download = _call(api_event("GET", f"/reports/{payload['report_id']}/download", groups=REVIEWER))
    assert download["statusCode"] == 200
    assert response_json(download)["url"].startswith("http")

    forbidden = _call(api_event("POST", "/reports/generate", groups=VIEWER, body={"type": "excel"}))
    assert forbidden["statusCode"] == 403


def test_report_generation_rejects_unknown_kind(runtime):
    response = _call(api_event("POST", "/reports/generate", groups=REVIEWER, body={"type": "xml"}))
    assert response["statusCode"] == 400


def test_audit_endpoint_lists_actions(runtime):
    applicant, _ = _seed_evaluated(runtime)
    _call(
        api_event(
            "POST",
            f"/applicants/{applicant.applicant_id}/review",
            groups=REVIEWER,
            body={"decision": "REJECTED", "reason": "Not a fit for this cycle."},
        )
    )
    response = _call(api_event("GET", f"/applicants/{applicant.applicant_id}/audit", groups=VIEWER))
    assert response["statusCode"] == 200
    assert any(item["action"] == "REVIEW_DECISION" for item in response_json(response)["items"])


def test_admin_group_management(runtime):
    listing = _call(api_event("GET", "/admins", groups=ADMIN))
    assert listing["statusCode"] == 200
    assert response_json(listing)["items"][0]["username"] == "local.admin"

    added = _call(
        api_event("POST", "/admins", groups=ADMIN, body={"email": "new.admin@sjbit.edu.in", "group": "sbg-reviewers"})
    )
    assert added["statusCode"] == 200
    assert response_json(added)["status"] == "SIMULATED"

    invalid = _call(api_event("POST", "/admins", groups=ADMIN, body={"email": "bad", "group": "sbg-reviewers"}))
    assert invalid["statusCode"] == 400

    forbidden = _call(
        api_event("POST", "/admins", groups=REVIEWER, body={"email": "new@sjbit.edu.in", "group": "sbg-reviewers"})
    )
    assert forbidden["statusCode"] == 403


def test_form_mapping_preview(runtime):
    response = _call(api_event("GET", "/form/mapping", groups=VIEWER))
    payload = response_json(response)
    assert response["statusCode"] == 200
    assert payload["fieldMapping"]["fields"]
    assert "api_key" not in json.dumps(payload["ai"])


def test_intake_endpoint_accepts_and_queues_locally(runtime):
    event = api_event("POST", "/intake", body=make_submission(response_id="api-intake-1"))
    response = intake.lambda_handler(event, None)
    payload = response_json(response)
    assert response["statusCode"] == 202
    assert payload["status"] == "ACCEPTED"
    assert payload["queue"]["mode"] == "local"
    assert runtime.repo.get_applicant(payload["applicant_id"]).processing_status in ("RECEIVED", "COMPLETED", "NEEDS_REVIEW")


def test_intake_endpoint_rejects_unsigned_requests_when_auth_enabled(runtime, app_settings, monkeypatch):
    monkeypatch.setattr(app_settings, "auth_disabled", False)
    monkeypatch.setattr(app_settings, "intake_key", "expected-key")
    event = api_event("POST", "/intake", body=make_submission(response_id="api-intake-2"))
    response = intake.lambda_handler(event, None)
    assert response["statusCode"] == 401


def test_intake_signature_verification(runtime, app_settings):
    import hashlib
    import hmac
    import time

    key = "shared-intake-key"
    app_settings.intake_key = key
    app_settings.intake_signature_required = True
    body = json.dumps({"hello": "world"})
    timestamp = str(int(time.time()))
    signature = hmac.new(key.encode(), f"{timestamp}.{body}".encode(), hashlib.sha256).hexdigest()
    event = {
        "headers": {"x-intake-key": key, "x-signature": signature, "x-timestamp": timestamp},
        "body": body,
    }
    verify_intake_request(event, app_settings)

    bad = dict(event)
    bad["headers"] = dict(event["headers"])
    bad["headers"]["x-signature"] = "0" * 64
    with pytest.raises(UnauthorizedError):
        verify_intake_request(bad, app_settings)

    stale = dict(event)
    stale["headers"] = dict(event["headers"])
    stale["headers"]["x-timestamp"] = str(int(time.time()) - 5000)
    stale["headers"]["x-signature"] = hmac.new(
        key.encode(), f"{stale['headers']['x-timestamp']}.{body}".encode(), hashlib.sha256
    ).hexdigest()
    with pytest.raises(UnauthorizedError):
        verify_intake_request(stale, app_settings)


def test_options_preflight(runtime):
    response = _call(api_event("OPTIONS", "/applicants", groups=VIEWER))
    assert response["statusCode"] == 204
    assert response["headers"]["Access-Control-Allow-Methods"]
