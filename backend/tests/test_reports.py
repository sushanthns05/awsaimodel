"""Excel and PDF report generation tests."""

from __future__ import annotations

import io
import zipfile

import pytest

from backend.src.common.errors import NotFoundError, ValidationError
from backend.src.common.config_store import eligibility_config, roles_config, rubric
from backend.src.common.models import ReportRecord, new_id, utcnow
from backend.src.reports.data import collect_report_data, summary_stats
from backend.src.reports.service import REPORT_KINDS, generate_report, validate_scope
from backend.src.services.reports_service import create_report, get_report, list_reports
from backend.src.scoring.engine import build_evaluation
from backend.tests.helpers import add_applicant, make_ai_result, make_applicant


def _seed_evaluated_application(runtime, index: int = 0):
    applicant = add_applicant(
        runtime.repo,
        applicant_id=f"APP-REPORT{index:04d}",
        source_response_id=f"report-{index}",
        full_name=f"Report Applicant {index}",
        email=f"report{index}@example.com",
        roles=["technical_team"],
    )
    ai_result = make_ai_result(rubric(), ["technical_team"], fraction=0.72)
    evaluation = build_evaluation(
        applicant,
        ai_result,
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


def test_report_scope_validation():
    assert validate_scope("excel", {}) == {
        "role": "",
        "applicant_id": "",
        "min_score": None,
        "max_score": None,
    }
    with pytest.raises(ValidationError):
        validate_scope("pdf_role", {})
    with pytest.raises(ValidationError):
        validate_scope("pdf_applicant", {})
    with pytest.raises(ValidationError):
        validate_scope("pdf_unknown", {})


def test_excel_report_is_a_valid_workbook(runtime):
    _seed_evaluated_application(runtime, 0)
    _seed_evaluated_application(runtime, 1)

    record = create_report("excel", {}, actor="admin@sjbit.edu.in", repo=runtime.repo, storage=runtime.storage)
    assert record.status == "COMPLETED"
    assert record.filename.endswith(".xlsx")
    data = runtime.storage.get_bytes(runtime.settings.report_bucket, record.s3_key)
    assert data[:2] == b"PK"
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        names = archive.namelist()
        assert any("xl/workbook.xml" in name for name in names)

    # Reports are auditable.
    assert any(entry.action == "REPORT_GENERATED" for entry in runtime.repo.list_audit())


@pytest.mark.parametrize(
    "kind,scope",
    [
        ("pdf_consolidated", {}),
        ("pdf_executive", {}),
        ("pdf_manual_review", {}),
        ("pdf_role", {"role": "technical_team"}),
        ("pdf_applicant", {"applicant_id": "APP-REPORT0000"}),
    ],
)
def test_pdf_reports_render(runtime, kind, scope):
    _seed_evaluated_application(runtime, 0)
    record = create_report(kind, scope, actor="admin@sjbit.edu.in", repo=runtime.repo, storage=runtime.storage)
    assert record.status == "COMPLETED"
    data = runtime.storage.get_bytes(runtime.settings.report_bucket, record.s3_key)
    assert data.startswith(b"%PDF")
    assert record.size_bytes == len(data)


def test_applicant_pdf_requires_existing_applicant(runtime):
    with pytest.raises(NotFoundError):
        create_report(
            "pdf_applicant",
            {"applicant_id": "APP-MISSING"},
            actor="admin@sjbit.edu.in",
            repo=runtime.repo,
            storage=runtime.storage,
        )


def test_report_records_can_be_listed_and_downloaded(runtime):
    _seed_evaluated_application(runtime)
    record = create_report("excel", {}, actor="admin@sjbit.edu.in", repo=runtime.repo, storage=runtime.storage)
    listing = list_reports(repo=runtime.repo, storage=runtime.storage)
    assert listing["count"] == 1
    assert listing["items"][0]["downloadUrl"]
    detail = get_report(record.report_id, repo=runtime.repo, storage=runtime.storage)
    assert detail["status"] == "COMPLETED"
    assert detail["downloadUrl"].startswith("http")


def test_failed_report_is_recorded(runtime, monkeypatch):
    import backend.src.reports.service as reports_service

    def boom(*args, **kwargs):
        raise RuntimeError("renderer exploded")

    monkeypatch.setattr(reports_service, "build_excel", boom)
    with pytest.raises(RuntimeError):
        generate_report(
            "rep_failed",
            "excel",
            {},
            "admin@sjbit.edu.in",
            repo=runtime.repo,
            storage=runtime.storage,
        )
    stored = runtime.repo.get_report("rep_failed")
    assert stored.status == "FAILED"
    assert "renderer exploded" in stored.error


def test_report_data_summary_and_filters(runtime):
    first, _ = _seed_evaluated_application(runtime, 0)
    second, _ = _seed_evaluated_application(runtime, 1)
    second.review_status = "APPROVED"
    runtime.repo.save_applicant(second)

    data = collect_report_data(
        runtime.repo,
        organization={"name": "AWS SBG", "institution": "SJBIT"},
        rubric_version="1.0.0",
        rubric=rubric(),
        roles_config=roles_config(),
    )
    assert data.total == 2
    assert data.organization["name"] == "AWS SBG"
    stats = summary_stats(data.rows)
    assert stats["total"] == 2
    assert stats["processed"] == 2
    assert stats["shortlisted"] == 1
    assert stats["average_score"] > 0


def test_every_report_kind_has_an_extension():
    assert set(REPORT_KINDS) == {
        "excel",
        "pdf_consolidated",
        "pdf_executive",
        "pdf_manual_review",
        "pdf_role",
        "pdf_applicant",
    }
    for extension, content_type in REPORT_KINDS.values():
        assert extension in ("xlsx", "pdf")
        assert "/" in content_type
