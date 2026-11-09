"""Domain model, configuration and field-mapping tests."""

from __future__ import annotations

import copy

import pytest

from backend.src.common.config_store import (
    ai_config,
    eligibility_config,
    field_mapping,
    get_config,
    get_config_meta,
    roles_config,
    rubric,
    validate_config,
)
from backend.src.common.errors import ValidationError
from backend.src.common.models import Applicant, applicant_id_for, parse_dt
from backend.src.documents.ingestion import (
    build_field_index,
    map_answers,
    match_role,
    normalise_question,
    normalise_roles,
    parse_extra,
)


def test_config_defaults_load_and_are_valid():
    for key, loader in (
        ("rubric", rubric),
        ("eligibility", eligibility_config),
        ("roles", roles_config),
        ("field_mapping", field_mapping),
    ):
        value = loader()
        validate_config(key, {k: v for k, v in value.items() if not k.startswith("_")})


def test_rubric_criteria_sum_to_total():
    config = rubric()
    assert sum(float(c["max_score"]) for c in config["criteria"]) == config["total_points"]


def test_role_weights_sum_to_one_hundred():
    for role in roles_config()["roles"]:
        assert abs(sum(float(v) for v in role["weights"].values()) - 100.0) < 0.01


def test_config_meta_reports_packaged_default(repo):
    meta = get_config_meta("rubric", repo)
    assert meta["version"] == 0
    assert meta["source"] == "packaged_default"


def test_config_override_round_trip(repo):
    value = copy.deepcopy(rubric(repo))
    value["version"] = "1.0.1"
    repo.put_config("rubric", {k: v for k, v in value.items() if not k.startswith("_")}, actor="tester")
    loaded = rubric(repo)
    assert loaded["version"] == "1.0.1"
    meta = get_config_meta("rubric", repo)
    assert meta["version"] == 1
    assert meta["source"] == "dynamodb"
    assert meta["updated_by"] == "tester"


def test_rubric_validation_rejects_bad_total():
    broken = copy.deepcopy(rubric())
    broken["criteria"][0]["max_score"] = 99
    with pytest.raises(ValidationError):
        validate_config("rubric", {k: v for k, v in broken.items() if not k.startswith("_")})


def test_rubric_validation_rejects_duplicate_ids():
    broken = copy.deepcopy(rubric())
    broken["criteria"][1]["id"] = broken["criteria"][0]["id"]
    with pytest.raises(ValidationError):
        validate_config("rubric", {k: v for k, v in broken.items() if not k.startswith("_")})


def test_role_validation_rejects_bad_weights():
    broken = copy.deepcopy(roles_config())
    broken["roles"][0]["weights"]["relevant_skills"] = 99
    with pytest.raises(ValidationError):
        validate_config("roles", broken)


def test_eligibility_validation_rejects_unknown_rule_type():
    broken = copy.deepcopy(eligibility_config())
    broken["rules"][0]["type"] = "psychic"
    with pytest.raises(ValidationError):
        validate_config("eligibility", broken)


def test_field_mapping_validation_rejects_duplicate_canonical():
    broken = copy.deepcopy(field_mapping())
    broken["fields"][1]["canonical"] = broken["fields"][0]["canonical"]
    with pytest.raises(ValidationError):
        validate_config("field_mapping", broken)


def test_unknown_config_key_raises(repo):
    with pytest.raises(ValidationError):
        get_config("not_a_section", repo)


def test_ai_config_never_exposes_secret(repo):
    config = ai_config(repo)
    assert "api_key" not in config
    assert config["enabled"] is True


def test_applicant_id_is_deterministic():
    first = applicant_id_for("response-123")
    second = applicant_id_for("response-123")
    assert first == second
    assert first.startswith("APP-")
    assert len(first) == 20
    assert applicant_id_for("response-124") != first


def test_parse_dt_supports_multiple_formats():
    assert parse_dt("2026-03-01T10:00:00Z").year == 2026
    assert parse_dt("2026-03-01 10:00:00").month == 3
    assert parse_dt("01/03/2026 10:00:00").day == 1
    assert parse_dt("") is None
    assert parse_dt("not a date") is None


def test_applicant_serialisation_round_trip():
    from backend.tests.helpers import make_applicant

    applicant = make_applicant()
    restored = Applicant.from_dict(applicant.to_dict())
    assert restored == applicant


def test_question_normalisation_and_field_index():
    mapping = field_mapping()
    assert normalise_question("  Full-Name!! ") == "fullname"
    canonical, questions = build_field_index(mapping)
    assert "full_name" in canonical
    assert "fullname" in questions


def test_map_answers_uses_aliases_and_preserves_extra():
    mapping = field_mapping()
    answers = {
        "your name": "Asha",
        "e-mail": "asha@example.com",
        "USN": "1AB23CS001",
        "Department": "CSE",
        "Year": "3",
        "team preference": "Technical Team",
        "Availability": "8 hours",
        "Unmapped question": "keep me",
    }
    mapped, extra, missing = map_answers(answers, mapping)
    assert mapped["full_name"] == "Asha"
    assert mapped["email"] == "asha@example.com"
    assert mapped["roles"] == "Technical Team"
    assert extra == {"Unmapped question": "keep me"}
    assert missing == []


def test_map_answers_reports_missing_required():
    mapped, extra, missing = map_answers({"Full Name": "Only a name"}, field_mapping())
    assert mapped == {"full_name": "Only a name"}
    assert extra == {}
    assert "email" in missing
    assert "availability" in missing


def test_role_matching_accepts_id_name_and_alias():
    config = roles_config()
    assert match_role("technical_team", config) == "technical_team"
    assert match_role("Technical Team", config) == "technical_team"
    assert match_role("technical team", config) == "technical_team"
    assert match_role("Unknown role", config) is None


def test_normalise_roles_falls_back_to_default():
    config = roles_config()
    roles, unmapped = normalise_roles(["Not a real team"], config)
    assert roles == [config["default_role"]]
    assert unmapped == ["Not a real team"]
    roles, unmapped = normalise_roles(["Social Media", "social_media"], config)
    assert roles == ["social_media"]
    assert unmapped == []


def test_parse_extra_handles_dict_json_and_garbage():
    assert parse_extra({"a": 1}) == {"a": 1}
    assert parse_extra('{"a": 2}') == {"a": 2}
    assert parse_extra("not json") == {}
    assert parse_extra(None) == {}
