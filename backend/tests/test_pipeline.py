"""End-to-end pipeline tests: ingest -> extract -> evaluate -> score."""

from __future__ import annotations

import pytest

from backend.src.common.config_store import field_mapping, roles_config
from backend.src.documents.ingestion import ingest_submission
from backend.src.pipeline import tasks
from backend.src.pipeline.queue import dispatch_message, enqueue_processing
from backend.tests.helpers import make_pdf, make_submission


def _ingest(runtime, payload):
    return ingest_submission(
        payload,
        repo=runtime.repo,
        storage=runtime.storage,
        mapping=field_mapping(runtime.repo),
        roles_config=roles_config(runtime.repo),
        settings=runtime.settings,
    )


def test_full_pipeline_produces_auditable_evaluation(runtime):
    result = _ingest(runtime, make_submission(response_id="pipeline-happy"))
    applicant_id = result["applicant_id"]

    processed = tasks.process_applicant_now(
        applicant_id, repo=runtime.repo, storage=runtime.storage, settings=runtime.settings
    )
    assert processed["status"] == "COMPLETED"

    applicant = runtime.repo.get_applicant(applicant_id)
    assert applicant.processing_status == "COMPLETED"
    assert applicant.extracted_text_key
    assert applicant.extracted_text_chars > 0
    assert applicant.documents[0].extraction_status == "EXTRACTED"
    assert applicant.documents[0].page_count == 1
    assert 0 < applicant.total_score <= 100
    assert applicant.latest_evaluation_id
    assert applicant.eligibility_status == "PASS"
    assert set(applicant.role_scores) == {"technical_team", "social_media"}

    evaluation = runtime.repo.get_latest_evaluation(applicant_id)
    assert evaluation is not None
    assert evaluation.evaluation_id == applicant.latest_evaluation_id
    assert evaluation.score_complete is True
    assert len(evaluation.criteria) == 7
    assert all(c.validated for c in evaluation.criteria)
    assert all(c.evidence for c in evaluation.criteria)
    assert evaluation.model_metadata.get("mock") is True
    assert evaluation.document_coverage["resume_available"] is True

    actions = [entry.action for entry in runtime.repo.list_audit(applicant_id)]
    assert "DOCUMENTS_EXTRACTED" in actions
    assert "AI_EVALUATION_COMPLETED" in actions
    assert "EVALUATION_SCORED" in actions


def test_processed_applicant_is_not_reprocessed(runtime):
    result = _ingest(runtime, make_submission(response_id="pipeline-idempotent"))
    applicant_id = result["applicant_id"]
    tasks.process_applicant_now(applicant_id, repo=runtime.repo, storage=runtime.storage, settings=runtime.settings)

    second = tasks.process_applicant_now(
        applicant_id, repo=runtime.repo, storage=runtime.storage, settings=runtime.settings
    )
    assert second["skipped"] is True

    dispatch = dispatch_message({"applicant_id": applicant_id}, settings=runtime.settings)
    assert dispatch["status"] == "SKIPPED"

    forced = dispatch_message({"applicant_id": applicant_id, "force": True}, settings=runtime.settings)
    assert forced["status"] == "QUEUED"


def test_corrupt_document_does_not_block_evaluation(runtime):
    payload = make_submission(
        response_id="pipeline-corrupt",
        document=b"%PDF-1.4 this is not really a pdf",
    )
    result = _ingest(runtime, payload)
    applicant_id = result["applicant_id"]

    extraction = tasks.extract_applicant_documents(
        applicant_id, repo=runtime.repo, storage=runtime.storage, settings=runtime.settings
    )
    applicant = runtime.repo.get_applicant(applicant_id)
    assert extraction["characters"] == 0
    assert applicant.extraction_summary["failed"] == 1
    assert applicant.urgent_review is True
    assert "extraction_warning" in applicant.responses

    processed = tasks.process_applicant_now(
        applicant_id, repo=runtime.repo, storage=runtime.storage, settings=runtime.settings
    )
    assert processed["status"] == "COMPLETED"
    evaluation = runtime.repo.get_latest_evaluation(applicant_id)
    assert evaluation.document_coverage["used_application_answers_only"] is True


def test_ai_failure_marks_applicant_failed(runtime, monkeypatch):
    result = _ingest(runtime, make_submission(response_id="pipeline-ai-failure"))
    applicant_id = result["applicant_id"]

    class BrokenClient:
        def evaluate(self, *args, **kwargs):
            raise RuntimeError("upstream unavailable")

    monkeypatch.setattr(tasks, "get_ai_client", lambda *args, **kwargs: BrokenClient())

    processed = tasks.process_applicant_now(
        applicant_id, repo=runtime.repo, storage=runtime.storage, settings=runtime.settings
    )
    assert processed["status"] == "FAILED"
    applicant = runtime.repo.get_applicant(applicant_id)
    assert applicant.processing_status == "FAILED"
    assert applicant.urgent_review is True
    assert "upstream unavailable" in applicant.processing_error
    assert any(entry.action == "PROCESSING_FAILED" for entry in runtime.repo.list_audit(applicant_id))


def test_mark_failed_handles_unknown_applicant(runtime):
    assert tasks.mark_failed("APP-UNKNOWN", "boom", repo=runtime.repo)["status"] == "NOT_FOUND"


def test_enqueue_processing_local_mode(runtime):
    queued = enqueue_processing("APP-X", repo=runtime.repo, settings=runtime.settings)
    assert queued["mode"] == "local"


def test_dispatch_message_missing_id_raises(runtime):
    from backend.src.common.errors import AppError

    with pytest.raises(AppError):
        dispatch_message({}, settings=runtime.settings)


def test_dispatch_message_unknown_applicant(runtime):
    assert dispatch_message({"applicant_id": "APP-MISSING"}, settings=runtime.settings)["status"] == "NOT_FOUND"


def test_docx_resume_is_extracted(runtime):
    from backend.tests.helpers import encode_document, make_docx

    document = encode_document(
        make_docx(["Asha Rao", "Python and AWS experience.", "Led a team of three students."]),
        filename="resume.docx",
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    payload = make_submission(response_id="pipeline-docx", with_document=False, extra_documents=[document])
    result = _ingest(runtime, payload)
    applicant_id = result["applicant_id"]

    extraction = tasks.extract_applicant_documents(
        applicant_id, repo=runtime.repo, storage=runtime.storage, settings=runtime.settings
    )
    assert extraction["characters"] > 0
    applicant = runtime.repo.get_applicant(applicant_id)
    assert applicant.documents[0].extraction_status == "EXTRACTED"


def test_duplicate_documents_within_submission_are_marked(runtime):
    pdf = make_pdf("A resume paragraph with sufficient detail about Python and AWS projects.")
    payload = make_submission(response_id="pipeline-duplicate-docs", document=pdf)
    payload["documents"].append(
        {"name": "resume-copy.pdf", "mime_type": "application/pdf", "base64": payload["documents"][0]["base64"]}
    )
    result = _ingest(runtime, payload)
    applicant = runtime.repo.get_applicant(result["applicant_id"])
    assert len(applicant.documents) == 2
    assert applicant.documents[1].extraction_status == "DUPLICATE"
    assert applicant.documents[1].duplicate_of == applicant.documents[0].document_id
