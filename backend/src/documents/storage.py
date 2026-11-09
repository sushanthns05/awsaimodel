"""S3 storage abstraction with a filesystem fallback for local development."""

from __future__ import annotations

import os
import shutil
import urllib.parse
from pathlib import Path
from typing import Optional

from ..common.config import Settings, get_settings
from ..common.logging_utils import get_logger

logger = get_logger("sbg.storage")


class Storage:
    def __init__(self, settings: Optional[Settings] = None):
        self.settings = settings or get_settings()
        self.local_root = Path(self.settings.local_store_path) / "s3"
        self.local_root.mkdir(parents=True, exist_ok=True)
        self._s3 = None
        if not self.settings.is_local:
            import boto3

            self._s3 = boto3.client("s3", region_name=self.settings.region)

    # -- helpers ------------------------------------------------------------
    def _local_path(self, bucket: str, key: str) -> Path:
        safe_bucket = bucket.replace("/", "_")
        path = self.local_root / safe_bucket / key
        resolved = path.resolve()
        root = (self.local_root / safe_bucket).resolve()
        if not str(resolved).startswith(str(root)):
            raise ValueError("Invalid storage key")
        return path

    def _extra(self, kms_key: str = "") -> dict:
        extra: dict = {"ServerSideEncryption": "AES256"}
        if kms_key:
            extra = {"ServerSideEncryption": "aws:kms", "SSEKMSKeyId": kms_key}
        return extra

    # -- documents ----------------------------------------------------------
    def put_document(self, applicant_id: str, document_id: str, filename: str, data: bytes, content_type: str) -> str:
        key = f"applicants/{applicant_id}/documents/{document_id}/{filename}"
        self.put_bytes(self.settings.resume_bucket, key, data, content_type, self.settings.resume_kms_key)
        return key

    def put_extracted_text(self, applicant_id: str, text: str) -> str:
        key = f"applicants/{applicant_id}/extracted/resume.txt"
        self.put_bytes(
            self.settings.resume_bucket,
            key,
            text.encode("utf-8"),
            "text/plain; charset=utf-8",
            self.settings.resume_kms_key,
        )
        return key

    def get_extracted_text(self, key: str) -> str:
        return self.get_bytes(self.settings.resume_bucket, key).decode("utf-8", errors="replace")

    def get_document(self, key: str) -> bytes:
        return self.get_bytes(self.settings.resume_bucket, key)

    def document_url(self, key: str, filename: str = "") -> str:
        return self.signed_url(self.settings.resume_bucket, key, self.settings.document_signed_url_seconds, filename)

    # -- reports ------------------------------------------------------------
    def put_report(self, report_id: str, filename: str, data: bytes, content_type: str) -> str:
        key = f"reports/{report_id}/{filename}"
        self.put_bytes(self.settings.report_bucket, key, data, content_type, self.settings.report_kms_key)
        return key

    def report_url(self, key: str, filename: str = "") -> str:
        return self.signed_url(self.settings.report_bucket, key, self.settings.report_signed_url_seconds, filename)

    # -- primitives ---------------------------------------------------------
    def put_bytes(self, bucket: str, key: str, data: bytes, content_type: str, kms_key: str = "") -> None:
        if self._s3 is None:
            path = self._local_path(bucket, key)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
            return
        self._s3.put_object(
            Bucket=bucket,
            Key=key,
            Body=data,
            ContentType=content_type,
            Metadata={"scanner": "sbg-recruitment"},
            **self._extra(kms_key),
        )

    def get_bytes(self, bucket: str, key: str) -> bytes:
        if self._s3 is None:
            path = self._local_path(bucket, key)
            if not path.exists():
                raise FileNotFoundError(f"Object not found: {bucket}/{key}")
            return path.read_bytes()
        response = self._s3.get_object(Bucket=bucket, Key=key)
        return response["Body"].read()

    def delete(self, bucket: str, key: str) -> None:
        if self._s3 is None:
            path = self._local_path(bucket, key)
            if path.exists():
                path.unlink()
            return
        self._s3.delete_object(Bucket=bucket, Key=key)

    def signed_url(self, bucket: str, key: str, expires_in: int = 300, filename: str = "") -> str:
        if self._s3 is None:
            base = os.getenv("LOCAL_API_BASE", "http://127.0.0.1:8000")
            quoted = urllib.parse.quote(key, safe="")
            return f"{base}/dev/files/{bucket}/{quoted}"
        params = {"Bucket": bucket, "Key": key}
        if filename:
            params["ResponseContentDisposition"] = f'attachment; filename="{filename}"'
            params["ResponseContentType"] = "application/octet-stream"
        return self._s3.generate_presigned_url(
            "get_object",
            Params=params,
            ExpiresIn=max(60, min(int(expires_in), 3600)),
        )

    def purge_applicant(self, applicant_id: str) -> int:
        """Delete all stored documents for an applicant (retention requests)."""
        removed = 0
        if self._s3 is None:
            folder = self._local_path(self.settings.resume_bucket, f"applicants/{applicant_id}")
            if folder.exists():
                removed = sum(1 for _ in folder.rglob("*") if _.is_file())
                shutil.rmtree(folder)
            return removed
        paginator = self._s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.settings.resume_bucket, Prefix=f"applicants/{applicant_id}/"):
            keys = [{"Key": obj["Key"]} for obj in page.get("Contents", [])]
            if keys:
                self._s3.delete_objects(Bucket=self.settings.resume_bucket, Delete={"Objects": keys})
                removed += len(keys)
        return removed


_storage: Optional[Storage] = None


def get_storage(settings: Optional[Settings] = None) -> Storage:
    global _storage
    if _storage is None:
        _storage = Storage(settings)
    return _storage


def reset_storage(value: Optional[Storage] = None) -> None:
    global _storage
    _storage = value
