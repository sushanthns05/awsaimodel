"""Ingestion, validation and duplicate-handling tests."""

from __future__ import annotations

import base64

import pytest

from backend.src.common.errors import PayloadTooLargeError, ValidationError
from backend.src.documents.ingestion import (
    build_applicant,
    decode_documents,
    ingest_submission,
)
from backend.src.documents.validator import (
    DocumentValidationError,
    EICAR,
    MalwareDetectedError,
    ScanUnavailableError,
    safe_filename,
    scan_for_malware,
    validate_file,
)
from backend.tests.helpers import (
    COMPLETE_ANSWERS,
    encode_document,
    make_docx,
    make_pdf,
    make_submission,
)


def _ingest(runtime, payload):
    from backend.src.common.config_store import field_mapping, roles_config

    return ingest_submission(
        payload,
        repo=runtime.repo,
        storage=runtime.storage,
        mapping=field_mapping(runtime.repo),
        roles_config=roles_config(runtime.repo),
        settings=runtime.settings,
    )


def test_ingest_complete_submission(runtime):
    result = _ingest(runtime, make_submission())
    assert result["status"] == "ACCEPTED"
    assert result["documents_received"] == 1
    assert result["missing_required_fields"] == []

    applicant = runtime.repo.get_applicant(result["applicant_id"])
    assert applicant.full_name == "Asha Rao"
    assert applicant.email == "asha.rao@example.com"
    assert applicant.usn == "1AB23CS001"
    assert applicant.roles == ["technical_team", "social_media"]
    assert applicant.responses["extra_fields"] == {"Favourite colour": "Blue"}
    assert applicant.responses["availability_hours"] == "8"
    assert applicant.documents[0].sha256
    assert runtime.storage.get_document(applicant.documents[0].s3_key).startswith(b"%PDF-")


def test_ingest_is_idempotent(runtime):
    payload = make_submission(response_id="response-duplicate")
    first = _ingest(runtime, payload)
    second = _ingest(runtime, payload)
    assert first["status"] == "ACCEPTED"
    assert second["status"] == "DUPLICATE"
    assert second["applicant_id"] == first["applicant_id"]
    assert runtime.repo.count_by_status().get("RECEIVED") == 1


def test_ingest_does_not_duplicate_documents_when_replayed(runtime):
    payload = make_submission(response_id="response-replay")
    result = _ingest(runtime, payload)
    applicant = runtime.repo.get_applicant(result["applicant_id"])
    stored_key = applicant.documents[0].s3_key

    _ingest(runtime, payload)
    after = runtime.repo.get_applicant(result["applicant_id"])
    assert [d.s3_key for d in after.documents] == [stored_key]


def test_ingest_requires_source_response_id(runtime):
    payload = make_submission()
    payload.pop("source_response_id")
    with pytest.raises(ValidationError):
        _ingest(runtime, payload)


def test_ingest_requires_answers(runtime):
    payload = make_submission()
    payload["answers"] = {}
    with pytest.raises(ValidationError):
        _ingest(runtime, payload)


def test_ingest_flags_missing_required_fields(runtime):
    answers = {"Full Name": "Incomplete Applicant"}
    payload = make_submission(answers=answers, with_document=False)
    result = _ingest(runtime, payload)
    assert result["status"] == "ACCEPTED"
    applicant = runtime.repo.get_applicant(result["applicant_id"])
    assert applicant.application_complete is False
    assert "email" in applicant.missing_required_fields
    assert "Resume document" in applicant.missing_required_fields
    # No role was selected, so the configured default role is kept for processing.
    assert applicant.roles == ["technical_team"]
    assert applicant.responses["unmapped_role_preferences"] == []


def test_ingest_rejects_eicar(runtime):
    payload = make_submission(document=EICAR, extra_documents=[])
    payload["documents"][0]["name"] = "resume.pdf"
    result = _ingest(runtime, payload)
    applicant = runtime.repo.get_applicant(result["applicant_id"])
    assert applicant.documents == []
    assert any("failed the malware scan" in error for error in applicant.responses.get("document_errors", []))


def test_ingest_records_invalid_base64(runtime):
    payload = make_submission(with_document=False)
    payload["documents"] = [{"name": "resume.pdf", "base64": "not-valid-base64!!"}]
    result = _ingest(runtime, payload)
    applicant = runtime.repo.get_applicant(result["applicant_id"])
    assert applicant.documents == []
    assert any("not valid base64" in error for error in result["document_errors"])


def test_ingest_rejects_executables(runtime):
    payload = make_submission(
        with_document=False,
        extra_documents=[encode_document(b"MZ\x90\x00payload", "resume.pdf", "application/pdf")],
    )
    result = _ingest(runtime, payload)
    applicant = runtime.repo.get_applicant(result["applicant_id"])
    assert applicant.documents == []
    assert any("not accepted" in error for error in result["document_errors"])


def test_ingest_enforces_document_count(runtime):
    runtime.settings.max_documents = 2
    payload = make_submission(with_document=False)
    payload["documents"] = [
        {"name": f"resume{index}.pdf", "base64": base64.b64encode(make_pdf("text " * 30)).decode()}
        for index in range(3)
    ]
    with pytest.raises(PayloadTooLargeError):
        _ingest(runtime, payload)


def test_decode_documents_rejects_non_list(runtime):
    documents, errors = decode_documents({}, runtime.settings)
    assert documents == []
    assert errors == ["documents must be a list"]


def test_build_applicant_derives_availability_hours(runtime):
    from backend.src.common.config_store import field_mapping, roles_config

    answers = dict(COMPLETE_ANSWERS)
    answers.pop("Hours available per week")
    answers["Weekly availability and commitment"] = "I can commit about 6 hours per week"
    applicant, _, _ = build_applicant(
        {
            "source_response_id": "response-hours",
            "answers": answers,
            "documents": [{"name": "resume.pdf", "base64": "x"}],
        },
        mapping=field_mapping(runtime.repo),
        roles_config=roles_config(runtime.repo),
        settings=runtime.settings,
    )
    assert applicant.responses["availability_hours"] == "6"


def test_build_applicant_keeps_unmapped_roles(runtime):
    from backend.src.common.config_store import field_mapping, roles_config

    answers = dict(COMPLETE_ANSWERS)
    answers["Which team(s) are you applying for?"] = ["Technical Team", "Podcast Host"]
    applicant, _, meta = build_applicant(
        {
            "source_response_id": "response-unmapped-role",
            "answers": answers,
            "documents": [{"name": "resume.pdf", "base64": "x"}],
        },
        mapping=field_mapping(runtime.repo),
        roles_config=roles_config(runtime.repo),
        settings=runtime.settings,
    )
    assert applicant.roles == ["technical_team"]
    assert meta["unmapped_roles"] == ["Podcast Host"]
    assert applicant.responses["unmapped_role_preferences"] == ["Podcast Host"]


def test_validate_file_accepts_pdf_docx_and_rejects_mismatch(runtime):
    pdf = validate_file(make_pdf("valid pdf content " * 20), "resume.pdf", settings=runtime.settings)
    assert pdf.kind == "pdf"
    assert pdf.extension == "pdf"

    docx = validate_file(make_docx(["Hello world"]), "resume.docx", settings=runtime.settings)
    assert docx.kind == "docx"

    with pytest.raises(DocumentValidationError):
        validate_file(make_pdf("text"), "resume.docx", settings=runtime.settings)

    with pytest.raises(DocumentValidationError):
        validate_file(b"%PDF-1.4 tiny", "resume.exe", settings=runtime.settings)

    with pytest.raises(DocumentValidationError):
        validate_file(b"", "resume.pdf", settings=runtime.settings)


def test_validate_file_enforces_size(runtime):
    with pytest.raises(DocumentValidationError):
        validate_file(b"%PDF-" + b"0" * 2048, "resume.pdf", max_bytes=1024, settings=runtime.settings)


def test_safe_filename_strips_paths_and_control_characters():
    assert safe_filename("../../etc/passwd") == "passwd"
    assert safe_filename('bad<>:"/\\|?*name.pdf') == "name.pdf"
    assert safe_filename(" . hidden . ") == "hidden"
    assert safe_filename("") == "document"


def test_malware_scan_fails_closed_when_enabled_without_scanner(runtime):
    runtime.settings.malware_scan_enabled = True
    runtime.settings.malware_scan_lambda = ""
    with pytest.raises(ScanUnavailableError):
        scan_for_malware(b"clean bytes", "resume.pdf", runtime.settings)


def test_malware_scan_detects_eicar(runtime):
    with pytest.raises(MalwareDetectedError):
        scan_for_malware(EICAR, "resume.pdf", runtime.settings)
