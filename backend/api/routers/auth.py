"""Authentication and identity router."""

from __future__ import annotations

from typing import Any, Dict
from fastapi import APIRouter, Depends, HTTPException, status

from ...src.common.auth import Principal, verify_cognito_jwt
from ...src.common.config import Settings, get_settings
from ...src.common.config_store import organization_config
from ...src.common.repository import Repository, get_repository
from ...schemas import LoginRequest
from ..deps import get_current_principal, get_current_repo, get_current_settings, require_permission

router = APIRouter(tags=["Auth"])


@router.get("/me")
async def get_me(
    principal: Principal = Depends(require_permission("read")),
    repo: Repository = Depends(get_current_repo),
) -> Dict[str, Any]:
    """Retrieve the currently authenticated administrator's profile and RBAC permissions."""
    return {
        "user": principal.to_dict(),
        "organization": organization_config(repo),
    }


@router.post("/auth/login")
async def login(
    payload: LoginRequest,
    settings: Settings = Depends(get_current_settings),
) -> Dict[str, Any]:
    """Authenticate an administrator and receive JWT tokens.

    Supports AWS Cognito User Pool in production and local development bypass.
    """
    if settings.auth_disabled:
        # Development bypass session
        return {
            "accessToken": "local-dev-token",
            "idToken": "local-dev-token",
            "refreshToken": "",
            "expiresIn": 86400,
            "user": {
                "subject": "local-admin",
                "email": payload.email or "local.admin@sbg.example",
                "groups": ["sbg-admins"],
                "permissions": ["read", "review", "shortlist", "reports", "settings", "reprocess", "admin"],
                "isAdmin": True,
            },
        }

    # In production, login happens through AWS Cognito SDK or Cognito User Pool AuthFlow
    try:
        import boto3

        client = boto3.client("cognito-idp", region_name=settings.cognito_region)
        resp = client.initiate_auth(
            ClientId=settings.cognito_client_id,
            AuthFlow="USER_PASSWORD_AUTH",
            AuthParameters={
                "USERNAME": payload.email,
                "PASSWORD": payload.password,
            },
        )
        auth_result = resp.get("AuthenticationResult") or {}
        id_token = auth_result.get("IdToken", "")
        access_token = auth_result.get("AccessToken", "")
        refresh_token = auth_result.get("RefreshToken", "")

        # Decode token to verify groups
        claims = verify_cognito_jwt(id_token, settings)
        groups = claims.get("cognito:groups") or []

        return {
            "accessToken": access_token,
            "idToken": id_token,
            "refreshToken": refresh_token,
            "expiresIn": auth_result.get("ExpiresIn", 3600),
            "user": {
                "subject": claims.get("sub", ""),
                "email": claims.get("email", payload.email),
                "groups": groups,
                "isAdmin": "sbg-admins" in groups,
            },
        }
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "INVALID_CREDENTIALS", "message": f"Authentication failed: {str(exc)}"},
        ) from exc


@router.post("/auth/logout")
async def logout(
    principal: Principal = Depends(get_current_principal),
) -> Dict[str, Any]:
    """Log out and terminate administrative session."""
    return {"status": "LOGGED_OUT", "email": principal.email}
