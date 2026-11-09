"""Typed application errors and API Gateway response helpers."""

from __future__ import annotations

import json
import traceback
from typing import Any


class AppError(Exception):
    status_code = 500
    code = "INTERNAL_ERROR"

    def __init__(self, message: str, *, details: Any = None, status_code: int | None = None):
        super().__init__(message)
        self.message = message
        self.details = details
        if status_code is not None:
            self.status_code = status_code

    def to_payload(self, request_id: str = "") -> dict[str, Any]:
        return {
            "error": {
                "code": self.code,
                "message": self.message,
                "details": self.details,
                "requestId": request_id,
            }
        }


class ValidationError(AppError):
    status_code = 400
    code = "VALIDATION_ERROR"


class UnauthorizedError(AppError):
    status_code = 401
    code = "UNAUTHORIZED"


class ForbiddenError(AppError):
    status_code = 403
    code = "FORBIDDEN"


class NotFoundError(AppError):
    status_code = 404
    code = "NOT_FOUND"


class ConflictError(AppError):
    status_code = 409
    code = "CONFLICT"


class RateLimitError(AppError):
    status_code = 429
    code = "RATE_LIMITED"


class PayloadTooLargeError(AppError):
    status_code = 413
    code = "PAYLOAD_TOO_LARGE"


class UpstreamError(AppError):
    status_code = 502
    code = "UPSTREAM_ERROR"


def cors_headers(origin: str = "*") -> dict[str, str]:
    return {
        "Access-Control-Allow-Origin": origin,
        "Access-Control-Allow-Headers": "Content-Type,Authorization,X-Requested-With,X-Intake-Key,X-Signature,X-Timestamp",
        "Access-Control-Allow-Methods": "GET,POST,PUT,PATCH,DELETE,OPTIONS",
        "Access-Control-Max-Age": "600",
        "Content-Type": "application/json",
        "X-Content-Type-Options": "nosniff",
        "Referrer-Policy": "no-referrer",
    }


def json_response(status_code: int, body: Any, origin: str = "*") -> dict[str, Any]:
    return {
        "statusCode": status_code,
        "headers": cors_headers(origin),
        "body": json.dumps(body, default=str, separators=(",", ":")),
        "isBase64Encoded": False,
    }


def error_response(error: Exception, request_id: str = "", origin: str = "*") -> dict[str, Any]:
    if isinstance(error, AppError):
        return json_response(error.status_code, error.to_payload(request_id), origin)
    return json_response(
        500,
        {"error": {"code": "INTERNAL_ERROR", "message": "An unexpected error occurred.", "requestId": request_id}},
        origin,
    )
