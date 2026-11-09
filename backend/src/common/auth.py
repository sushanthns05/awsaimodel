"""Authentication and authorisation helpers.

Supports three modes:
  * API Gateway Cognito authorizer claims already present on the event.
  * Direct Cognito JWT verification (defence in depth, and local server).
  * Explicit local development identity when AUTH_DISABLED=true.

The frontend never receives AWS credentials or API keys.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from .config import Settings, get_settings
from .errors import ForbiddenError, UnauthorizedError
from .logging_utils import get_logger

logger = get_logger("sbg.auth")

GROUP_PERMISSIONS: dict[str, set[str]] = {
    "sbg-admins": {"read", "review", "shortlist", "reports", "settings", "reprocess", "admin"},
    "sbg-reviewers": {"read", "review", "shortlist", "reports"},
    "sbg-viewers": {"read"},
}


@dataclass
class Principal:
    subject: str
    email: str = ""
    username: str = ""
    groups: list[str] = field(default_factory=list)
    permissions: set[str] = field(default_factory=set)
    token_use: str = ""

    @property
    def is_admin(self) -> bool:
        return "admin" in self.permissions

    def can(self, permission: str) -> bool:
        return permission in self.permissions

    def require(self, permission: str) -> None:
        if not self.can(permission):
            raise ForbiddenError(f"Missing required permission: {permission}")

    def to_dict(self) -> dict[str, Any]:
        return {
            "subject": self.subject,
            "email": self.email,
            "username": self.username,
            "groups": self.groups,
            "permissions": sorted(self.permissions),
            "isAdmin": self.is_admin,
        }


def _permissions_for_groups(groups: list[str]) -> set[str]:
    permissions: set[str] = set()
    for group in groups:
        permissions |= GROUP_PERMISSIONS.get(group, set())
    return permissions


def principal_from_claims(claims: dict[str, Any]) -> Principal:
    groups = claims.get("cognito:groups") or []
    if isinstance(groups, str):
        groups = [g for g in groups.replace("[", "").replace("]", "").split(",") if g]
    subject = str(claims.get("sub") or claims.get("username") or "")
    if not subject:
        raise UnauthorizedError("Token has no subject")
    permissions = _permissions_for_groups(list(groups))
    if not permissions:
        # Cognito users without a group get read-only access to avoid lockouts
        # only when explicitly allowed; default is deny.
        permissions = set()
    return Principal(
        subject=subject,
        email=str(claims.get("email") or ""),
        username=str(claims.get("cognito:username") or claims.get("username") or ""),
        groups=list(groups),
        permissions=permissions,
        token_use=str(claims.get("token_use") or ""),
    )


def _claims_from_api_gateway(event: dict[str, Any]) -> Optional[dict[str, Any]]:
    request_context = event.get("requestContext") or {}
    authorizer = request_context.get("authorizer") or {}
    claims = authorizer.get("claims")
    if claims:
        return dict(claims)
    jwt = authorizer.get("jwt") or {}
    if jwt.get("claims"):
        return dict(jwt["claims"])
    return None


_jwks_cache: dict[str, tuple[float, Any]] = {}


def _fetch_jwks(url: str) -> Any:
    import urllib.request

    cached = _jwks_cache.get(url)
    now = time.time()
    if cached and now - cached[0] < 3600:
        return cached[1]
    with urllib.request.urlopen(url, timeout=5) as response:  # nosec - fixed Cognito URL
        data = json.loads(response.read().decode("utf-8"))
    _jwks_cache[url] = (now, data)
    return data


def verify_cognito_jwt(token: str, settings: Settings) -> dict[str, Any]:
    if not settings.cognito_user_pool_id:
        raise UnauthorizedError("Cognito is not configured on the server")
    try:
        import jwt  # PyJWT
        from jwt import PyJWKClient
    except ImportError as exc:  # pragma: no cover - dependency missing
        raise UnauthorizedError("JWT verification unavailable") from exc

    region = settings.cognito_region
    issuer = f"https://cognito-idp.{region}.amazonaws.com/{settings.cognito_user_pool_id}"
    jwks_url = f"{issuer}/.well-known/jwks.json"

    try:
        client = PyJWKClient(jwks_url, cache_keys=True, lifespan=3600)
        signing_key = client.get_signing_key_from_jwt(token).key
        claims = jwt.decode(
            token,
            signing_key,
            algorithms=["RS256"],
            issuer=issuer,
            options={"verify_aud": False},
        )
    except Exception as exc:  # noqa: BLE001 - normalise all JWT errors
        logger.warning("JWT verification failed: %s", exc)
        raise UnauthorizedError("Invalid or expired authentication token") from exc

    token_use = claims.get("token_use")
    if token_use == "id" and settings.cognito_client_id and claims.get("aud") != settings.cognito_client_id:
        raise UnauthorizedError("Token audience mismatch")
    if token_use == "access" and settings.cognito_client_id and claims.get("client_id") != settings.cognito_client_id:
        raise UnauthorizedError("Token client mismatch")
    if token_use not in ("id", "access"):
        raise UnauthorizedError("Unsupported token type")
    return claims


def extract_bearer(event: dict[str, Any]) -> str:
    headers = {str(k).lower(): v for k, v in (event.get("headers") or {}).items()}
    raw = headers.get("authorization") or ""
    if not raw.lower().startswith("bearer "):
        raise UnauthorizedError("Missing bearer token")
    return raw[7:].strip()


def authenticate(event: dict[str, Any], settings: Optional[Settings] = None) -> Principal:
    settings = settings or get_settings()

    claims = _claims_from_api_gateway(event)
    if claims:
        return principal_from_claims(claims)

    if settings.auth_disabled:
        dev_user = (event.get("headers") or {}).get("x-dev-user") or "local.admin@sbg.example"
        return Principal(
            subject="local-dev",
            email=str(dev_user),
            username=str(dev_user),
            groups=["sbg-admins"],
            permissions=set(GROUP_PERMISSIONS["sbg-admins"]),
            token_use="dev",
        )

    token = extract_bearer(event)
    claims = verify_cognito_jwt(token, settings)
    principal = principal_from_claims(claims)
    if not principal.permissions:
        raise ForbiddenError("Your account has no recruitment role assigned")
    return principal


_INTAKE_SECRET_CACHE: dict[str, tuple[float, str]] = {}


def _load_intake_key(settings: Settings) -> str:
    """Load the shared intake key from Secrets Manager when not in the environment."""
    if settings.intake_key:
        return settings.intake_key
    if not settings.intake_secret_arn:
        return ""
    cached = _INTAKE_SECRET_CACHE.get(settings.intake_secret_arn)
    now = time.time()
    if cached and now - cached[0] < 900:
        return cached[1]
    try:
        import boto3

        client = boto3.client("secretsmanager", region_name=settings.region)
        response = client.get_secret_value(SecretId=settings.intake_secret_arn)
        raw = response.get("SecretString") or ""
        try:
            payload = json.loads(raw)
            value = str(payload.get("intake_key") or payload.get("key") or "") if isinstance(payload, dict) else str(payload)
        except json.JSONDecodeError:
            value = raw
        value = value.strip()
        if not value:
            raise UnauthorizedError("Intake endpoint is not configured")
        _INTAKE_SECRET_CACHE[settings.intake_secret_arn] = (now, value)
        return value
    except UnauthorizedError:
        raise
    except Exception as exc:  # noqa: BLE001 - never leak secret details
        logger.error("Unable to load intake secret: %s", type(exc).__name__)
        raise UnauthorizedError("Intake endpoint is not configured") from exc


def verify_intake_request(event: dict[str, Any], settings: Optional[Settings] = None) -> None:
    """Verify the shared secret and optional HMAC signature from Apps Script."""
    settings = settings or get_settings()
    headers = {str(k).lower(): v for k, v in (event.get("headers") or {}).items()}
    provided_key = headers.get("x-intake-key", "")
    expected_key = _load_intake_key(settings)
    if not expected_key:
        raise UnauthorizedError("Intake endpoint is not configured")
    if not provided_key or not hmac.compare_digest(provided_key, expected_key):
        raise UnauthorizedError("Invalid intake key")

    if settings.intake_signature_required:
        signature = headers.get("x-signature", "")
        timestamp = headers.get("x-timestamp", "")
        if not signature or not timestamp:
            raise UnauthorizedError("Missing request signature")
        try:
            ts = int(timestamp)
        except ValueError as exc:
            raise UnauthorizedError("Invalid request timestamp") from exc
        skew = abs(int(time.time()) - ts)
        if skew > settings.intake_signature_tolerance_seconds:
            raise UnauthorizedError("Request timestamp outside allowed window")
        body = event.get("body") or ""
        expected = hmac.new(
            expected_key.encode("utf-8"),
            f"{timestamp}.{body}".encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        if not hmac.compare_digest(signature, expected):
            raise UnauthorizedError("Invalid request signature")
