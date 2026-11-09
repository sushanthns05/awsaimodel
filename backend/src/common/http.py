"""API Gateway event normalisation and JSON response helpers."""

from __future__ import annotations

import base64
import json
from dataclasses import dataclass, field
from typing import Any, Optional

from .errors import PayloadTooLargeError, ValidationError, cors_headers, json_response


@dataclass
class Request:
    method: str
    path: str
    query: dict[str, str] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)
    body: dict[str, Any] = field(default_factory=dict)
    raw_body: str = ""
    request_id: str = ""
    source_ip: str = ""
    path_params: dict[str, str] = field(default_factory=dict)
    event: dict[str, Any] = field(default_factory=dict)


def normalize_event(event: dict[str, Any], max_body_bytes: int = 6 * 1024 * 1024) -> Request:
    request_context = event.get("requestContext") or {}
    http = request_context.get("http") or {}
    method = str(http.get("method") or event.get("httpMethod") or "GET").upper()

    raw_path = str(event.get("rawPath") or event.get("path") or "/")
    stage = request_context.get("stage")
    if stage and raw_path.startswith(f"/{stage}/"):
        raw_path = raw_path[len(stage) + 1 :]
    path = raw_path.rstrip("/") or "/"

    query = dict(event.get("queryStringParameters") or {})
    multi = event.get("multiValueQueryStringParameters") or {}
    for key, values in multi.items():
        if isinstance(values, list) and values:
            query[key] = values[0]

    headers = {str(k).lower(): str(v) for k, v in (event.get("headers") or {}).items()}
    body_text = event.get("body") or ""
    if event.get("isBase64Encoded") and body_text:
        try:
            body_text = base64.b64decode(body_text).decode("utf-8")
        except Exception as exc:  # noqa: BLE001
            raise ValidationError("Request body is not valid base64") from exc
    if body_text and len(body_text.encode("utf-8")) > max_body_bytes:
        raise PayloadTooLargeError("Request body exceeds the allowed size")

    body: dict[str, Any] = {}
    if body_text:
        content_type = headers.get("content-type", "")
        if "application/json" in content_type or body_text.strip().startswith(("{", "[")):
            try:
                parsed = json.loads(body_text)
            except json.JSONDecodeError as exc:
                raise ValidationError(f"Request body is not valid JSON: {exc.msg}") from exc
            if not isinstance(parsed, dict):
                raise ValidationError("JSON body must be an object")
            body = parsed
        else:
            raise ValidationError("Content-Type must be application/json")

    return Request(
        method=method,
        path=path,
        query=query,
        headers=headers,
        body=body,
        raw_body=body_text,
        request_id=str(request_context.get("requestId") or event.get("requestId") or ""),
        source_ip=str((request_context.get("http") or {}).get("sourceIp") or request_context.get("identity", {}).get("sourceIp") or ""),
        event=event,
    )


def ok(body: Any, request: Optional[Request] = None, status: int = 200, origin: str = "*") -> dict[str, Any]:
    return json_response(status, body, origin)


def created(body: Any, request: Optional[Request] = None, origin: str = "*") -> dict[str, Any]:
    return json_response(201, body, origin)


def preflight(origin: str = "*") -> dict[str, Any]:
    return {"statusCode": 204, "headers": cors_headers(origin), "body": ""}


def query_int(request: Request, key: str, default: int, *, minimum: int = 0, maximum: int = 1000) -> int:
    raw = request.query.get(key)
    if raw in (None, ""):
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"Query parameter '{key}' must be an integer") from exc
    return max(minimum, min(maximum, value))


def query_float(request: Request, key: str, default: Optional[float] = None) -> Optional[float]:
    raw = request.query.get(key)
    if raw in (None, ""):
        return default
    try:
        return float(raw)
    except (TypeError, ValueError) as exc:
        raise ValidationError(f"Query parameter '{key}' must be a number") from exc


def query_bool(request: Request, key: str, default: bool = False) -> bool:
    raw = request.query.get(key)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")
