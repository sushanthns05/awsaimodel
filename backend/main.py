"""FastAPI Application Entry Point for AWS Student Builder AI Recruitment Platform.

Provides high-performance, asynchronous REST APIs for candidate intake, document
processing, evidence-backed AI evaluation, scoring, shortlisting, and reports.
"""

from __future__ import annotations

import time
import urllib.parse
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncGenerator, Dict

from fastapi import FastAPI, HTTPException, Request, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response as RawResponse

from .api.routers import applicants, auth, dashboard, intake, reports, settings as settings_router, shortlist
from .src.common.config import get_settings
from .src.common.errors import (
    AppError,
    ConflictError,
    ForbiddenError,
    NotFoundError,
    UnauthorizedError,
    ValidationError,
)
from .src.common.logging_utils import get_logger
from .src.common.models import iso, utcnow
from .src.documents.storage import get_storage

logger = get_logger("sbg.fastapi.app")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Startup and graceful shutdown lifecycle manager."""
    settings = get_settings()
    logger.info(
        "Starting AWS Student Builder AI Recruitment API [Stage: %s, LocalMode: %s]",
        settings.stage,
        settings.is_local,
    )
    yield
    logger.info("Shutting down AWS Student Builder AI Recruitment API")


app = FastAPI(
    title="AWS Student Builder Group — AI Recruitment Platform",
    description=(
        "Production AI-powered recruitment and candidate shortlisting engine "
        "for AWS Student Builder Group, SJB Institute of Technology (SJBIT), Bengaluru."
    ),
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json",
)

# ---------------------------------------------------------------------------
# Middleware: CORS & Performance Timing
# ---------------------------------------------------------------------------

settings = get_settings()
allowed_origins = [settings.cors_origin] if settings.cors_origin and settings.cors_origin != "*" else ["*"]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)





# ---------------------------------------------------------------------------
# Global Exception Handlers
# ---------------------------------------------------------------------------


@app.exception_handler(NotFoundError)
async def not_found_handler(request: Request, exc: NotFoundError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_404_NOT_FOUND,
        content={"error": {"code": "NOT_FOUND", "message": str(exc)}},
    )


@app.exception_handler(ValidationError)
async def validation_error_handler(request: Request, exc: ValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={"error": {"code": "VALIDATION_ERROR", "message": str(exc)}},
    )


@app.exception_handler(ForbiddenError)
async def forbidden_handler(request: Request, exc: ForbiddenError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_403_FORBIDDEN,
        content={"error": {"code": "FORBIDDEN", "message": str(exc)}},
    )


@app.exception_handler(UnauthorizedError)
async def unauthorized_handler(request: Request, exc: UnauthorizedError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_401_UNAUTHORIZED,
        content={"error": {"code": "UNAUTHORIZED", "message": str(exc)}},
        headers={"WWW-Authenticate": "Bearer"},
    )


@app.exception_handler(ConflictError)
async def conflict_handler(request: Request, exc: ConflictError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_409_CONFLICT,
        content={"error": {"code": "CONFLICT", "message": str(exc)}},
    )


@app.exception_handler(AppError)
async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    return JSONResponse(
        status_code=status.HTTP_400_BAD_REQUEST,
        content={"error": {"code": "APP_ERROR", "message": str(exc)}},
    )


# ---------------------------------------------------------------------------
# Health & Status Probes (Render Web Service health check)
# ---------------------------------------------------------------------------


@app.get("/health", tags=["Health"])
@app.get("/api/health", tags=["Health"])
async def health_check() -> Dict[str, Any]:
    """Health check probe for Render Web Service, ALB, and uptime monitors."""
    settings = get_settings()
    return {
        "status": "ok",
        "service": "sbg-ai-recruitment-backend",
        "stage": settings.stage,
        "region": settings.region,
        "organization": settings.org_name,
        "institution": settings.institution,
        "cycle": settings.cycle,
        "timestamp": iso(utcnow()),
    }


# ---------------------------------------------------------------------------
# Local/Dev File Server for Resumes and Reports
# ---------------------------------------------------------------------------


@app.get("/dev/files/{bucket}/{encoded_key:path}", tags=["Development Files"])
@app.get("/api/dev/files/{bucket}/{encoded_key:path}", tags=["Development Files"])
async def serve_dev_file(bucket: str, encoded_key: str):
    """Serve resume documents and generated reports locally without live S3 credentials."""
    settings = get_settings()
    key = urllib.parse.unquote(encoded_key)

    if bucket not in (settings.resume_bucket, settings.report_bucket):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Access denied for bucket")

    try:
        storage = get_storage()
        data = storage.get_bytes(bucket, key)
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"File not found: {key}") from exc

    content_type = "application/pdf" if key.endswith(".pdf") else "application/octet-stream"
    if key.endswith(".xlsx"):
        content_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    elif key.endswith(".txt"):
        content_type = "text/plain"

    return RawResponse(
        content=data,
        media_type=content_type,
        headers={"Content-Disposition": f'inline; filename="{Path(key).name}"'},
    )


# ---------------------------------------------------------------------------
# Register Routers (Both Root and /api Prefix for total client flexibility)
# ---------------------------------------------------------------------------

ROUTERS = [
    intake.router,
    auth.router,
    dashboard.router,
    applicants.router,
    shortlist.router,
    reports.router,
    settings_router.router,
]

for r in ROUTERS:
    # Mount at root (e.g. /applicants, /intake, /dashboard/overview)
    app.include_router(r)
    # Also mount with /api prefix (e.g. /api/applicants, /api/intake, /api/dashboard/overview)
    app.include_router(r, prefix="/api")
