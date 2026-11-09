"""Document extraction tests for digital, scanned and corrupt documents."""

from __future__ import annotations

import pytest

from backend.src.documents.extractor import (
    CorruptDocumentError,
    ExtractionError,
    PasswordProtectedError,
    extract_document,
    sanitize_text,
)
from backend.tests.helpers import make_blank_pdf, make_docx, make_pdf


class FakeTextract:
    def __init__(self, text: str = "Scanned resume text: Python AWS leadership."):
        self.text = text
        self.calls = 0

    def detect_document_text(self, Document):  # noqa: N803 - boto3 shape
        self.calls += 1
        return {"Blocks": [{"BlockType": "LINE", "Text": line} for line in self.text.split("\n")]}


def test_pdf_extraction(runtime):
    data = make_pdf("Asha Rao. Python AWS Lambda. Project Atlas. Led a team of three students.")
    result = extract_document(
        data,
        "pdf",
        filename="resume.pdf",
        settings=runtime.settings,
        use_textract=False,
    )
    assert result.page_count == 1
    assert "Project Atlas" in result.text
    assert result.method == "pymupdf"
    assert result.textract_used is False


def test_pdf_multi_page_extraction(runtime):
    data = make_pdf("A sufficiently long resume paragraph with cloud project experience.", pages=3)
    result = extract_document(data, "pdf", settings=runtime.settings, use_textract=False)
    assert result.page_count == 3


def test_docx_extraction_includes_tables(runtime):
    data = make_docx(["Asha Rao", "Built a serverless pipeline with AWS Lambda."])
    result = extract_document(data, "docx", settings=runtime.settings, use_textract=False)
    assert "Asha Rao" in result.text
    assert "Python" in result.text
    assert result.method == "python-docx"


def test_scanned_pdf_falls_back_to_textract(runtime):
    runtime.settings.textract_enabled = True
    fake = FakeTextract("Scanned resume: Python and AWS project experience.")
    result = extract_document(
        make_blank_pdf(),
        "pdf",
        settings=runtime.settings,
        textract_client=fake,
        use_textract=True,
    )
    assert fake.calls == 1
    assert result.textract_used is True
    assert result.scanned is True
    assert "Scanned resume" in result.text
    assert result.method == "pymupdf+textract"


def test_scanned_pdf_with_textract_disabled_warns(runtime):
    runtime.settings.textract_enabled = False
    result = extract_document(make_blank_pdf(), "pdf", settings=runtime.settings, use_textract=False)
    assert result.text == ""
    assert result.scanned is True
    assert any("Textract is disabled" in warning for warning in result.warnings)


def test_image_requires_textract(runtime):
    runtime.settings.textract_enabled = False
    with pytest.raises(ExtractionError):
        extract_document(b"\x89PNG\r\n\x1a\nnot-a-real-image", "png", settings=runtime.settings, use_textract=False)


def test_image_uses_textract(runtime):
    runtime.settings.textract_enabled = True
    fake = FakeTextract("Image resume text")
    result = extract_document(
        b"\x89PNG\r\n\x1a\nfake",
        "png",
        settings=runtime.settings,
        textract_client=fake,
        use_textract=True,
    )
    assert result.textract_used is True
    assert result.scanned is True
    assert "Image resume" in result.text


def test_corrupt_pdf_raises(runtime):
    with pytest.raises(CorruptDocumentError):
        extract_document(b"%PDF-1.4 definitely not a real pdf", "pdf", settings=runtime.settings, use_textract=False)


def test_password_protected_pdf_raises(runtime):
    import fitz

    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "Protected content " * 10)
    data = document.tobytes(
        encryption=fitz.PDF_ENCRYPT_AES_256,
        owner_pw="owner-secret",
        user_pw="user-secret",
        permissions=fitz.PDF_PERM_PRINT,
    )
    document.close()
    with pytest.raises(PasswordProtectedError):
        extract_document(data, "pdf", settings=runtime.settings, use_textract=False)


def test_unsupported_kind_raises(runtime):
    with pytest.raises(ExtractionError):
        extract_document(b"data", "xlsx", settings=runtime.settings, use_textract=False)


def test_sanitize_text_removes_control_characters_and_limits():
    cleaned = sanitize_text("Hello\x00world\u200b   spaced\n\n\n\nend")
    assert "\x00" not in cleaned
    assert "\u200b" not in cleaned
    assert cleaned == "Hello world spaced\n\nend"
