"""Deterministic scoring, eligibility and ranking tests."""

from __future__ import annotations

import copy

import pytest

from backend.src.common.config_store import eligibility_config, roles_config, rubric
from backend.src.common.models import ELIGIBILITY_FAIL, ELIGIBILITY_PASS
from backend.src.scoring.engine import (
    ScoringError,
    apply_manual_scores,
    build_evaluation,
    normalise_role_ids,
    recommendation_for,
    resolve_criteria,
    role_map,
    score_distribution,
)
from backend.src.scoring.eligibility import (
    evaluate_eligibility,
    evaluate_rule,
    find_missing_required_fields,
    summarise_eligibility,
)
from backend.src.services.shortlist import build_shortlist
from backend.tests.helpers import add_applicant, make_ai_result, make_applicant


def _evaluate(applicant=None, ai_result=None, **kwargs):
    applicant = applicant or make_applicant()
    rubric_cfg = rubric()
    ai_result = ai_result or make_ai_result(rubric_cfg, normalise_role_ids(applicant.roles, roles_config()))
    return build_evaluation(
        applicant,
        ai_result,
        rubric_cfg,
        roles_config(),
        eligibility_config(),
        model_metadata={"model": "test"},
        prompt_version="test-1",
        document_coverage={"resume_available": True},
        **kwargs,
    )


def test_role_map_and_normalisation():
    assert "technical_team" in role_map(roles_config())
    assert normalise_role_ids(["technical_team", "social_media"], roles_config()) == [
        "technical_team",
        "social_media",
    ]
    assert normalise_role_ids([], roles_config()) == ["technical_team"]
    assert normalise_role_ids(["not_real"], roles_config()) == ["technical_team"]


def test_resolve_criteria_uses_role_weights():
    criteria = {c["id"]: c["max_score"] for c in resolve_criteria(rubric(), "technical_team", roles_config())}
    assert criteria["relevant_skills"] == 25
    assert criteria["role_knowledge"] == 20
    assert criteria["communication"] == 5


def test_complete_evaluation_computes_points_in_python():
    applicant = make_applicant()
    ai_result = make_ai_result(rubric(), ["technical_team"], fraction=0.8)
    evaluation = _evaluate(applicant, ai_result)
    # 0.8 * 100 weighted points across the technical team profile.
    assert evaluation.total_score == pytest.approx(80.0)
    assert evaluation.score_complete is True
    assert evaluation.recommendation == "STRONG_INTERVIEW"
    assert all(c.validated for c in evaluation.criteria)
    assert evaluation.criteria[0].final_score == pytest.approx(20.0)
    assert evaluation.eligibility_status == ELIGIBILITY_PASS


def test_role_knowledge_uses_role_specific_fraction():
    applicant = make_applicant(roles=["social_media"])
    ai_result = make_ai_result(rubric(), ["social_media"], fraction=0.7, roles_fraction=0.9)
    evaluation = _evaluate(applicant, ai_result)
    role_knowledge = next(c for c in evaluation.criteria if c.criterion_id == "role_knowledge")
    assert role_knowledge.max_score == 20
    assert role_knowledge.final_score == pytest.approx(18.0)
    # 0.7 across other criteria (80 points) + 18 role knowledge.
    assert evaluation.total_score == pytest.approx(74.0)
    assert evaluation.role_evaluations[0]["score"] == pytest.approx(74.0)


def test_missing_criterion_assigns_zero_and_flags_review():
    rubric_cfg = rubric()
    ai_result = make_ai_result(rubric_cfg, ["technical_team"])
    ai_result["criteria"] = [c for c in ai_result["criteria"] if c["id"] != "projects_experience"]
    evaluation = _evaluate(make_applicant(), ai_result)
    missing = next(c for c in evaluation.criteria if c.criterion_id == "projects_experience")
    assert missing.validated is False
    assert missing.final_score == 0
    assert evaluation.score_complete is False
    assert evaluation.validation_errors
    assert evaluation.recommendation == "NEEDS_REVIEW"


def test_marks_without_evidence_are_rejected():
    ai_result = make_ai_result(rubric(), ["technical_team"], evidence=False)
    evaluation = _evaluate(make_applicant(), ai_result)
    assert evaluation.score_complete is False
    assert evaluation.total_score == 0.0
    assert evaluation.recommendation == "NEEDS_REVIEW"


def test_invalid_fraction_is_flagged_not_accepted():
    ai_result = make_ai_result(rubric(), ["technical_team"])
    ai_result["criteria"][0]["score_fraction"] = 2.5
    evaluation = _evaluate(make_applicant(), ai_result)
    criterion = evaluation.criteria[0]
    assert criterion.validated is False
    assert criterion.final_score == 0
    assert evaluation.recommendation == "NEEDS_REVIEW"


def test_reject_policy_raises():
    rubric_cfg = copy.deepcopy(rubric())
    rubric_cfg["invalid_response_policy"] = "reject"
    ai_result = make_ai_result(rubric_cfg, ["technical_team"])
    ai_result["criteria"] = ai_result["criteria"][:-1]
    with pytest.raises(ScoringError):
        build_evaluation(
            make_applicant(),
            ai_result,
            rubric_cfg,
            roles_config(),
            eligibility_config(),
        )


def test_recommendation_thresholds():
    rubric_cfg = rubric()
    assert recommendation_for(95, rubric_cfg) == "STRONG_INTERVIEW"
    assert recommendation_for(80, rubric_cfg) == "STRONG_INTERVIEW"
    assert recommendation_for(70, rubric_cfg) == "INTERVIEW_CONSIDERATION"
    assert recommendation_for(55, rubric_cfg) == "MANUAL_REVIEW"
    assert recommendation_for(10, rubric_cfg) == "ELIGIBILITY_REVIEW"


def test_eligibility_failure_sets_review_recommendation():
    applicant = make_applicant(responses={"availability": "2 hours per week", "availability_hours": "2"})
    evaluation = _evaluate(applicant)
    assert evaluation.eligibility_status == ELIGIBILITY_FAIL
    assert evaluation.recommendation == "ELIGIBILITY_REVIEW"
    assert evaluation.eligibility_failures


def test_eligibility_failure_with_missing_fields_still_needs_review():
    applicant = make_applicant(usn="")
    evaluation = _evaluate(applicant)
    assert evaluation.eligibility_status == ELIGIBILITY_FAIL
    assert evaluation.recommendation == "NEEDS_REVIEW"


def test_missing_application_fields_force_review():
    applicant = make_applicant(responses={"availability": ""})
    applicant.responses.pop("availability_hours", None)
    evaluation = _evaluate(applicant)
    assert evaluation.recommendation == "NEEDS_REVIEW"
    assert any("Availability" in item for item in evaluation.missing_information)


def test_eligibility_rule_types():
    applicant = make_applicant()
    assert evaluate_rule(applicant, {"id": "n", "label": "N", "field": "full_name", "type": "required"}).status == "PASS"
    assert evaluate_rule(applicant, {"id": "e", "label": "E", "field": "email", "type": "pattern", "pattern": r"^[^@]+@[^@]+\.[a-z]{2,}$"}).status == "PASS"
    assert evaluate_rule(applicant, {"id": "h", "label": "H", "field": "responses.availability_hours", "type": "min_number", "value": 4}).status == "PASS"
    assert evaluate_rule(applicant, {"id": "h2", "label": "H2", "field": "responses.availability_hours", "type": "max_number", "value": 4}).status == "FAIL"
    assert evaluate_rule(applicant, {"id": "o", "label": "O", "field": "department", "type": "one_of", "values": ["Computer Science"]}).status == "PASS"
    assert evaluate_rule(applicant, {"id": "c", "label": "C", "field": "responses.technical_skills", "type": "contains", "value": "python"}).status == "PASS"
    assert evaluate_rule(applicant, {"id": "b", "label": "B", "field": "responses.consent", "type": "boolean_true"}).status == "UNKNOWN"


def test_eligibility_summary_distinguishes_unknown_and_fail():
    applicant = make_applicant()
    unknown = evaluate_rule(applicant, {"id": "b", "label": "Consent", "field": "responses.consent", "type": "boolean_true"})
    status, notes = summarise_eligibility([unknown])
    assert status == "UNKNOWN"
    assert notes

    failure = evaluate_rule(applicant, {"id": "x", "label": "USN", "field": "usn", "type": "required"})
    applicant.usn = ""
    failure = evaluate_rule(applicant, {"id": "x", "label": "USN", "field": "usn", "type": "required"})
    status, notes = summarise_eligibility([failure])
    assert status == "FAIL"
    assert notes == ["USN"]


def test_find_missing_required_fields_complete_application():
    assert find_missing_required_fields(make_applicant()) == []


def test_find_missing_required_fields_detects_gaps():
    applicant = make_applicant(full_name="", email="", roles=[], with_document=False, availability="")
    missing = find_missing_required_fields(applicant)
    assert "Full name" in missing
    assert "Email" in missing
    assert "Role preference" in missing
    assert "Resume document" in missing
    assert "Availability" in missing


def test_manual_score_override_recomputes_total_and_requires_reason():
    evaluation = _evaluate()
    version_before = evaluation.version
    updated = apply_manual_scores(
        evaluation,
        {"communication": 4, "leadership_collaboration": 4},
        reviewer="panel@sjbit.edu.in",
        reason="Panel reviewed workshop evidence in more depth.",
        rubric=rubric(),
    )
    by_id = {criterion.criterion_id: criterion for criterion in updated.criteria}
    assert by_id["communication"].final_score == 4
    assert by_id["leadership_collaboration"].final_score == 4
    assert updated.review_status == "MANUAL_REVIEW"
    assert updated.human_override["reviewer"] == "panel@sjbit.edu.in"
    assert updated.version == version_before + 1
    assert updated.total_score == round(sum(c.final_score for c in updated.criteria), 2)


def test_manual_score_override_rejects_unknown_or_out_of_range():
    evaluation = _evaluate()
    with pytest.raises(ScoringError):
        apply_manual_scores(evaluation, {"nope": 5}, reviewer="r", reason="valid reason", rubric=rubric())
    with pytest.raises(ScoringError):
        apply_manual_scores(evaluation, {"communication": 999}, reviewer="r", reason="valid reason", rubric=rubric())


def test_score_distribution_counts_bands():
    distribution = score_distribution([95, 70, 55, 10], rubric())
    counts = {band["label"]: band["count"] for band in distribution}
    assert counts["80-100"] == 1
    assert counts["65-79"] == 1
    assert counts["50-64"] == 1
    assert counts["0-49"] == 1


def test_shortlist_ranking_and_filters(runtime):
    low = add_applicant(
        runtime.repo,
        applicant_id="APP-LOW",
        source_response_id="r-low",
        full_name="Low Score",
        roles=["technical_team"],
    )
    low.total_score = 40
    low.processing_status = "COMPLETED"
    low.role_scores = {"technical_team": 40}
    runtime.repo.save_applicant(low)

    high = add_applicant(
        runtime.repo,
        applicant_id="APP-HIGH",
        source_response_id="r-high",
        full_name="High Score",
        roles=["technical_team"],
    )
    high.total_score = 88
    high.processing_status = "COMPLETED"
    high.role_scores = {"technical_team": 88}
    runtime.repo.save_applicant(high)

    pending = add_applicant(
        runtime.repo,
        applicant_id="APP-PENDING",
        source_response_id="r-pending",
        full_name="Still Processing",
        roles=["technical_team"],
    )
    pending.processing_status = "QUEUED"
    runtime.repo.save_applicant(pending)

    result = build_shortlist(role="technical_team", repo=runtime.repo)
    assert [item["applicantId"] for item in result["items"]] == ["APP-HIGH", "APP-LOW"]
    assert result["items"][0]["rank"] == 1
    assert result["items"][0]["roleScore"] == 88

    filtered = build_shortlist(min_score=50, repo=runtime.repo)
    assert [item["applicantId"] for item in filtered["items"]] == ["APP-HIGH"]
