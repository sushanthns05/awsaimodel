"""FastAPI dependencies for dependency injection across routers."""

from __future__ import annotations

from typing import Callable, Optional
from fastapi import Depends, Header, HTTPException, Request, status

from ..src.common.auth import Principal, authenticate
from ..src.common.config import Settings, get_settings
from ..src.common.errors import ForbiddenError, UnauthorizedError
from ..src.common.repository import Repository, get_repository
from ..src.documents.storage import Storage, get_storage


def get_current_settings() -> Settings:
    """Return application settings singleton."""
    return get_settings()


def get_current_repo() -> Repository:
    """Return repository instance (DynamoDB or Local File-backed)."""
    return get_repository()


def get_current_storage() -> Storage:
    """Return document and report storage instance (S3 or Local File-backed)."""
    return get_storage()


def get_current_principal(
    request: Request,
    authorization: Optional[str] = Header(None),
    x_dev_user: Optional[str] = Header(None),
    settings: Settings = Depends(get_current_settings),
) -> Principal:
    """Extract and authenticate the calling administrator principal.

    Supports:
    1. Cognito JWT token via standard Bearer authorization header.
    2. Local development mock auth when settings.auth_disabled is True.
    """
    event = {
        "headers": {k.lower(): v for k, v in request.headers.items()},
        "requestContext": {
            "http": {
                "method": request.method,
                "path": request.url.path,
                "sourceIp": request.client.host if request.client else "127.0.0.1",
            }
        },
    }

    try:
        return authenticate(event, settings=settings)
    except UnauthorizedError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "UNAUTHORIZED", "message": str(exc)},
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except ForbiddenError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={"code": "FORBIDDEN", "message": str(exc)},
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "AUTH_ERROR", "message": f"Authentication failed: {type(exc).__name__}"},
        ) from exc


def require_permission(permission: str) -> Callable[[Principal], Principal]:
    """Dependency factory enforcing specific RBAC permission."""

    def _dependency(principal: Principal = Depends(get_current_principal)) -> Principal:
        if not principal.can(permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"code": "FORBIDDEN", "message": f"Missing required permission: '{permission}'"},
            )
        return principal

    return _dependency

