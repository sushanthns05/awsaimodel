"""Text extraction for PDF, DOCX, DOC and image resumes.

Digital text is extracted locally with PyMuPDF / python-docx. Pages that
contain no extractable text are rendered and sent to Amazon Textract. All
failures are converted into typed results so one bad document never blocks
the whole applicant record.
"""

from __future__ import annotations

import io
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field
from typing import Any, Optional

from ..common.config import Settings, get_settings
from ..common.logging_utils import get_logger

logger = get_logger("sbg.extract")

MAX_TEXT_CHARS = 400_000
MAX_TEXTRACT_PAGES = 20
CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class ExtractionError(RuntimeError):
    pass


class PasswordProtectedError(ExtractionError):
    pass


class CorruptDocumentError(ExtractionError):
    pass


@dataclass
class ExtractionResult:
    text: str = ""
    page_count: int = 0
    method: str = ""
    scanned: bool = False
    textract_used: bool = False
    warnings: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def chars(self) -> int:
        return len(self.text)


def sanitize_text(text: str) -> str:
    clean = CONTROL.sub(" ", text or "")
    clean = clean.replace("\u00a0", " ").replace("\u200b", "")
    clean = re.sub(r"[ \t]+", " ", clean)
    clean = re.sub(r"\n{3,}", "\n\n", clean)
    return clean.strip()[:MAX_TEXT_CHARS]


def _textract_client() -> Any:
    import boto3

    return boto3.client("textract", region_name=get_settings().region)


def _textract_image(image_bytes: bytes, client: Any) -> str:
    response = client.detect_document_text(Document={"Bytes": image_bytes})
    lines = []
    for block in response.get("Blocks", []):
        if block.get("BlockType") == "LINE" and block.get("Text"):
            lines.append(block["Text"])
    return "\n".join(lines)


def _pdf(data: bytes, settings: Settings, client: Any) -> ExtractionResult:
    try:
        import fitz  # PyMuPDF
    except ImportError as exc:  # pragma: no cover
        raise ExtractionError("PyMuPDF is not installed; PDF extraction unavailable") from exc

    try:
        document = fitz.open(stream=data, filetype="pdf")
    except Exception as exc:  # noqa: BLE001
        raise CorruptDocumentError("PDF could not be opened; it may be corrupt") from exc

    if document.needs_pass:
        document.close()
        raise PasswordProtectedError("PDF is password protected")

    page_count = document.page_count
    if page_count == 0:
        document.close()
        raise CorruptDocumentError("PDF contains no pages")

    warnings: list[str] = []
    parts: list[str] = []
    scanned_pages = 0
    textract_pages = 0
    for index in range(page_count):
        try:
            page = document.load_page(index)
            page_text = sanitize_text(page.get_text("text") or "")
        except Exception:  # noqa: BLE001
            warnings.append(f"Page {index + 1} could not be read")
            continue

        if len(page_text) >= 60:
            parts.append(page_text)
            continue

        scanned_pages += 1
        if not settings.textract_enabled:
            warnings.append(f"Page {index + 1} appears scanned and Textract is disabled")
            if page_text:
                parts.append(page_text)
            continue
        if client is None:
            warnings.append(f"Page {index + 1} appears scanned and Textract is unavailable")
            continue
        if textract_pages >= MAX_TEXTRACT_PAGES:
            warnings.append(f"Textract page limit reached; pages after {index} skipped")
            break
        try:
            pixmap = page.get_pixmap(dpi=170)
            image_bytes = pixmap.tobytes("png")
            ocr_text = sanitize_text(_textract_image(image_bytes, client))
            textract_pages += 1
            if ocr_text:
                parts.append(ocr_text)
            else:
                warnings.append(f"Page {index + 1} produced no OCR text")
        except Exception as exc:  # noqa: BLE001
            logger.warning("Textract failed for page %s: %s", index + 1, type(exc).__name__)
            warnings.append(f"Textract failed on page {index + 1}")

    document.close()
    text = sanitize_text("\n\n".join(parts))
    return ExtractionResult(
        text=text,
        page_count=page_count,
        method="pymupdf+textract" if textract_pages else "pymupdf",
        scanned=scanned_pages > 0,
        textract_used=textract_pages > 0,
        warnings=warnings,
        metadata={"ocr_pages": textract_pages, "scanned_pages": scanned_pages},
    )


def _docx(data: bytes) -> ExtractionResult:
    try:
        import docx  # python-docx
    except ImportError as exc:  # pragma: no cover
        raise ExtractionError("python-docx is not installed; DOCX extraction unavailable") from exc

    try:
        document = docx.Document(io.BytesIO(data))
    except Exception as exc:  # noqa: BLE001
        raise CorruptDocumentError("DOCX could not be opened; it may be corrupt") from exc

    parts = [paragraph.text for paragraph in document.paragraphs if paragraph.text.strip()]
    for table in document.tables:
        for row in table.rows:
            cells = [cell.text.strip() for cell in row.cells if cell.text.strip()]
            if cells:
                parts.append(" | ".join(cells))
    text = sanitize_text("\n".join(parts))
    return ExtractionResult(text=text, page_count=0, method="python-docx")


def _doc(data: bytes) -> ExtractionResult:
    """Legacy .doc requires an external converter. Fail clearly if absent."""
    converter = shutil.which("soffice") or shutil.which("libreoffice")
    if not converter:
        raise ExtractionError(
            "Legacy .doc format requires LibreOffice on the processing host. "
            "Ask the applicant for PDF/DOCX or enable the conversion Lambda container."
        )
    with tempfile.TemporaryDirectory() as tmp:
        source = os.path.join(tmp, "input.doc")
        with open(source, "wb") as handle:
            handle.write(data)
        try:
            subprocess.run(  # nosec - fixed converter with controlled temp path
                [converter, "--headless", "--convert-to", "docx", "--outdir", tmp, source],
                check=True,
                capture_output=True,
                timeout=60,
            )
        except (subprocess.SubprocessError, OSError) as exc:
            raise ExtractionError("Legacy DOC conversion failed") from exc
        converted = os.path.join(tmp, "input.docx")
        if not os.path.exists(converted):
            raise ExtractionError("Legacy DOC conversion produced no output")
        with open(converted, "rb") as handle:
            return _docx(handle.read())


def _image(data: bytes, settings: Settings, client: Any) -> ExtractionResult:
    if not settings.textract_enabled:
        raise ExtractionError("Image resume requires Textract, which is disabled")
    if client is None:
        raise ExtractionError("Image resume requires Textract, which is unavailable")
    try:
        text = sanitize_text(_textract_image(data, client))
    except Exception as exc:  # noqa: BLE001
        raise ExtractionError("Textract could not read the image resume") from exc
    if not text:
        raise ExtractionError("No text found in the image resume")
    return ExtractionResult(
        text=text,
        page_count=1,
        method="textract-image",
        scanned=True,
        textract_used=True,
    )


def extract_document(
    data: bytes,
    kind: str,
    *,
    filename: str = "",
    settings: Optional[Settings] = None,
    textract_client: Any = None,
    use_textract: Optional[bool] = None,
) -> ExtractionResult:
    settings = settings or get_settings()
    if use_textract is False:
        settings = Settings(**{**settings.__dict__, "textract_enabled": False})
    client = textract_client
    if client is None and settings.textract_enabled:
        try:
            client = _textract_client()
        except Exception:  # noqa: BLE001 - credentials may be absent locally
            client = None

    kind = kind.lower()
    if kind == "pdf":
        return _pdf(data, settings, client)
    if kind == "docx":
        return _docx(data)
    if kind == "doc":
        return _doc(data)
    if kind in ("png", "jpg", "jpeg"):
        return _image(data, settings, client)
    raise ExtractionError(f"Unsupported document type: {kind}")
