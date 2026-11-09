"""File validation and malware scanning integration.

Magic-byte validation is authoritative; client supplied MIME types and file
extensions are advisory only. Executables are rejected outright. A pluggable
malware scan Lambda can be configured; when scanning is enabled but
unavailable the processing fails closed and the applicant is flagged for
manual review rather than silently accepting the file.
"""

from __future__ import annotations

import io
import json
import os
import zipfile
from dataclasses import dataclass
from typing import Any, Optional

from ..common.config import Settings, get_settings
from ..common.logging_utils import get_logger

logger = get_logger("sbg.documents")

ALLOWED_EXTENSIONS = {"pdf", "docx", "doc", "png", "jpg", "jpeg"}
MAX_FILENAME_LENGTH = 180

SIGNATURES = {
    "pdf": [b"%PDF-"],
    "png": [b"\x89PNG\r\n\x1a\n"],
    "jpg": [b"\xff\xd8\xff"],
    "jpeg": [b"\xff\xd8\xff"],
    "doc": [b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"],
}

# Files that must never be accepted even if renamed to .pdf
DANGEROUS_SIGNATURES = [
    b"MZ",  # Windows PE
    b"\x7fELF",  # ELF
    b"\xca\xfe\xba\xbe",  # Mach-O fat
    b"\xcf\xfa\xed\xfe",  # Mach-O 64
    b"#!",  # shell script
]

EICAR = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"


class DocumentValidationError(ValueError):
    pass


class MalwareDetectedError(ValueError):
    pass


class ScanUnavailableError(RuntimeError):
    pass


@dataclass
class ValidatedFile:
    filename: str
    extension: str
    content_type: str
    size_bytes: int
    sha256: str
    kind: str


def safe_filename(name: str) -> str:
    base = os.path.basename(str(name or "document"))
    base = "".join(ch for ch in base if ch.isprintable() and ch not in '\\/:*?"<>|').strip(". ")
    base = base.replace(" ", "_")[:MAX_FILENAME_LENGTH]
    return base or "document"


def _extension(filename: str) -> str:
    return os.path.splitext(filename.lower())[1].lstrip(".")


def sniff_type(data: bytes, filename: str) -> str:
    if data.startswith(b"%PDF-"):
        return "pdf"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if data.startswith(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"):
        return "doc"
    if data.startswith(b"PK\x03\x04"):
        try:
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                names = archive.namelist()
            if any(name.startswith("word/") for name in names):
                return "docx"
        except zipfile.BadZipFile:
            pass
    return _extension(filename)


MIME_BY_KIND = {
    "pdf": "application/pdf",
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "doc": "application/msword",
    "png": "image/png",
    "jpg": "image/jpeg",
    "jpeg": "image/jpeg",
}


def validate_file(
    data: bytes,
    filename: str,
    declared_content_type: str = "",
    *,
    max_bytes: Optional[int] = None,
    settings: Optional[Settings] = None,
) -> ValidatedFile:
    import hashlib

    settings = settings or get_settings()
    max_bytes = max_bytes or settings.max_document_bytes
    if not data:
        raise DocumentValidationError("Uploaded file is empty")
    if len(data) > max_bytes:
        raise DocumentValidationError(f"File exceeds the {max_bytes // (1024 * 1024)} MB limit")
    for signature in DANGEROUS_SIGNATURES:
        if data.startswith(signature):
            raise DocumentValidationError("Executable or script files are not accepted")

    filename = safe_filename(filename)
    ext = _extension(filename)
    if ext not in ALLOWED_EXTENSIONS:
        raise DocumentValidationError(f"Unsupported file type '.{ext}'")

    kind = sniff_type(data, filename)
    if kind not in ALLOWED_EXTENSIONS:
        raise DocumentValidationError("File content does not match an accepted document type")
    if ext in ("jpg", "jpeg") and kind in ("jpg", "jpeg"):
        kind = "jpg"
    if kind in ("docx", "doc", "pdf", "png", "jpg") and ext != kind:
        # Extension/content mismatch: allow only harmless alias jpg/jpeg.
        if not ({ext, kind} <= {"jpg", "jpeg"}):
            raise DocumentValidationError(
                f"File content ({kind}) does not match the filename extension (.{ext})"
            )

    if kind == "png":
        try:
            from PIL import Image

            with Image.open(io.BytesIO(data)) as image:
                image.verify()
        except ImportError:
            pass
        except Exception as exc:  # noqa: BLE001
            raise DocumentValidationError("PNG image is corrupt") from exc
    if kind == "jpg":
        try:
            from PIL import Image

            with Image.open(io.BytesIO(data)) as image:
                image.verify()
        except ImportError:
            pass
        except Exception as exc:  # noqa: BLE001
            raise DocumentValidationError("JPEG image is corrupt") from exc

    return ValidatedFile(
        filename=filename,
        extension=ext,
        content_type=MIME_BY_KIND.get(kind, declared_content_type or "application/octet-stream"),
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        kind=kind,
    )


def scan_for_malware(data: bytes, filename: str, settings: Optional[Settings] = None) -> str:
    """Return a verdict string. Raises on detection or unavailable scanning."""
    settings = settings or get_settings()
    if EICAR in data:
        raise MalwareDetectedError("Malware signature detected (EICAR test file)")

    if not settings.malware_scan_enabled:
        return "SKIPPED"

    if not settings.malware_scan_lambda:
        raise ScanUnavailableError(
            "Malware scanning is enabled but MALWARE_SCAN_LAMBDA is not configured; failing closed"
        )

    try:
        import boto3

        client = boto3.client("lambda", region_name=settings.region)
        response = client.invoke(
            FunctionName=settings.malware_scan_lambda,
            InvocationType="RequestResponse",
            Payload=json.dumps(
                {
                    "filename": safe_filename(filename),
                    "content_base64": __import__("base64").b64encode(data).decode("ascii"),
                }
            ).encode("utf-8"),
        )
        payload = json.loads(response["Payload"].read().decode("utf-8") or "{}")
        verdict = str(payload.get("verdict") or payload.get("status") or "").upper()
        if verdict in ("INFECTED", "MALICIOUS", "THREAT"):
            raise MalwareDetectedError("Malware scanner flagged the uploaded document")
        if verdict not in ("CLEAN", "OK", "PASSED"):
            raise ScanUnavailableError("Malware scanner returned an unrecognised verdict")
        return "CLEAN"
    except (MalwareDetectedError, ScanUnavailableError):
        raise
    except Exception as exc:  # noqa: BLE001
        logger.error("Malware scanner invocation failed: %s", type(exc).__name__)
        raise ScanUnavailableError("Malware scanner is unavailable; document quarantined for review") from exc
