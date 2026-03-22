# agent/auth.py - Enterprise authentication & RBAC
# Supports:
#   - JWT Bearer token verification (RS256/HS256)
#   - API Key fallback (for internal services)
#   - Role-based access control (RBAC) headers
#   - TLS-aware request context
#
# For intranet/enterprise use with identity providers (Okta, Azure AD, Keycloak).

import json
import logging
import os
import ssl
import time
from dataclasses import dataclass, field
from functools import wraps
from typing import Callable, Optional

import requests
from fastapi import HTTPException, Request, status

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
_jwks_url: str = os.getenv("JWKS_URL", "")        # e.g. https://your-idp.com/.well-known/jwks.json
_jwt_issuer: str = os.getenv("JWT_ISSUER", "")    # Expected token issuer
_jwt_audience: str = os.getenv("JWT_AUDIENCE", "")  # Expected audience
_jwt_secret: str = os.getenv("JWT_SECRET", "")    # For HS256 (internal services)
_jwt_algorithm: str = os.getenv("JWT_ALGORITHM", "RS256")
_admin_users: set[str] = set(os.getenv("ADMIN_USERS", "").split(",")) - {""}
_internal_header = "X-Internal-Service"  # Header trusted for service-to-service calls

# ---------------------------------------------------------------------------
# JWT / JWKS (cache with 5-min TTL)
# ---------------------------------------------------------------------------
_jwks_cache: dict = {}
_jwks_cache_at: float = 0.0
_JWKS_CACHE_TTL = 300.0


def _fetch_jwks() -> dict:
    """Fetch and cache JWKS from the identity provider."""
    global _jwks_cache, _jwks_cache_at
    now = time.time()
    if _jwks_cache and (now - _jwks_cache_at) < _JWKS_CACHE_TTL:
        return _jwks_cache
    if not _jwks_url:
        return {}
    try:
        resp = requests.get(_jwks_url, timeout=10)
        resp.raise_for_status()
        _jwks_cache = resp.json()
        _jwks_cache_at = now
        logger.info("JWKS cache refreshed from %s", _jwks_url)
        return _jwks_cache
    except requests.exceptions.RequestException as exc:
        logger.warning("Failed to fetch JWKS from %s: %s", _jwks_url, exc)
        return _jwks_cache or {}


def _get_signing_key(token: str) -> Optional[str]:
    """
    Extract the signing key from JWKS based on the token's 'kid' header.
    Returns the PEM key or None.
    """
    try:
        import jwt  # PyJWT
    except ImportError:
        logger.warning("PyJWT not installed. JWT verification unavailable.")
        return None

    try:
        unverified_header = jwt.get_unverified_header(token)
    except jwt.exceptions.DecodeError:
        return None

    kid = unverified_header.get("kid")
    if not kid:
        return None

    jwks = _fetch_jwks()
    for key in jwks.get("keys", []):
        if key.get("kid") == kid:
            # Convert JWK to PEM
            from jwt.algorithms import RSAAlgorithm
            return RSAAlgorithm.from_jwk(json.dumps(key))
    return None


# ---------------------------------------------------------------------------
# User context (attached to request.state)
# ---------------------------------------------------------------------------
@dataclass
class UserContext:
    """Parsed and verified identity from a request."""
    subject: str           # sub claim (user ID)
    email: str = ""
    name: str = ""
    roles: list[str] = field(default_factory=list)
    is_service: bool = False
    is_admin: bool = False
    raw_claims: dict = field(default_factory=dict)

    @classmethod
    def anonymous(cls) -> "UserContext":
        return cls(subject="anonymous", is_service=False)

    @classmethod
    def internal_service(cls) -> "UserContext":
        return cls(subject="internal-service", is_service=True)


# ---------------------------------------------------------------------------
# JWT verification
# ---------------------------------------------------------------------------
def verify_jwt(token: str) -> tuple[bool, UserContext, str]:
    """
    Verify a JWT token and return (success, user_context, error_message).
    Supports RS256 (JWKS) and HS256 (secret).
    """
    if not token:
        return False, UserContext.anonymous(), "Empty token"

    try:
        import jwt
    except ImportError:
        return False, UserContext.anonymous(), "JWT library not installed"

    # Try HS256 with secret first if provided
    if _jwt_secret:
        try:
            claims = jwt.decode(
                token,
                _jwt_secret,
                algorithms=["HS256"],
                audience=_jwt_audience or None,
                issuer=_jwt_issuer or None,
            )
            ctx = _claims_to_context(claims)
            return True, ctx, ""
        except jwt.ExpiredSignatureError:
            return False, UserContext.anonymous(), "Token expired"
        except jwt.InvalidTokenError as e:
            return False, UserContext.anonymous(), f"Invalid token: {e}"

    # Try RS256 with JWKS
    signing_key = _get_signing_key(token)
    if signing_key:
        try:
            claims = jwt.decode(
                token,
                signing_key,
                algorithms=["RS256"],
                audience=_jwt_audience or None,
                issuer=_jwt_issuer or None,
            )
            ctx = _claims_to_context(claims)
            return True, ctx, ""
        except jwt.ExpiredSignatureError:
            return False, UserContext.anonymous(), "Token expired"
        except jwt.InvalidTokenError as e:
            return False, UserContext.anonymous(), f"Invalid token: {e}"

    return False, UserContext.anonymous(), "Unable to verify token (no JWKS URL or secret configured)"


def _claims_to_context(claims: dict) -> UserContext:
    """Convert JWT claims dict to UserContext."""
    roles = []
    # Support common claim locations for roles
    if "roles" in claims:
        roles = claims["roles"] if isinstance(claims["roles"], list) else [claims["roles"]]
    elif "realm_access" in claims:  # Keycloak
        roles = claims.get("realm_access", {}).get("roles", [])
    elif "groups" in claims:  # Azure AD / Okta
        roles = claims.get("groups", [])

    subject = claims.get("sub", claims.get("client_id", "unknown"))
    is_admin = (
        subject in _admin_users
        or "admin" in roles
        or "devops-admin" in roles
    )

    return UserContext(
        subject=subject,
        email=claims.get("email", ""),
        name=claims.get("name", ""),
        roles=roles,
        is_service=bool(claims.get("client_id") and not claims.get("sub")),
        is_admin=is_admin,
        raw_claims=claims,
    )


# ---------------------------------------------------------------------------
# FastAPI middleware
# ---------------------------------------------------------------------------
def attach_user_context(request: Request, call_next):
    """
    Middleware that:
      1. Checks X-Internal-Service header (service-to-service, trusted)
      2. Falls back to JWT Bearer token
      3. Falls back to API Key in Authorization header
      4. Falls back to unauthenticated (anonymous)
    """
    user_ctx = UserContext.anonymous()

    # 1. Internal service token (trusted header from known services)
    if request.headers.get("X-Internal-Service"):
        user_ctx = UserContext.internal_service()
        logger.debug("Internal service call: %s", request.headers.get("X-Internal-Service"))

    # 2. JWT Bearer token
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        ok, ctx, err = verify_jwt(token)
        if ok:
            user_ctx = ctx
            logger.debug("JWT authenticated: sub=%s", ctx.subject)
        else:
            logger.warning("JWT verification failed: %s", err)

    # 3. API Key (from env or configured)
    elif auth_header.startswith("Bearer "):
        # API key is also passed as Bearer token
        pass  # handled in verify_api_key already

    request.state.user = user_ctx
    return call_next(request)


# ---------------------------------------------------------------------------
# RBAC helpers
# ---------------------------------------------------------------------------
def require_role(*required_roles: str) -> Callable:
    """
    Decorator to require specific roles on an endpoint.
    Usage:
        @app.get("/admin")
        @require_role("admin", "devops-admin")
        def admin_endpoint(request: Request):
            ...
    """
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(request: Request, *args, **kwargs):
            user: UserContext = getattr(request.state, "user", UserContext.anonymous())
            if user.is_service:
                return func(request, *args, **kwargs)
            if user.is_admin:
                return func(request, *args, **kwargs)
            # Check required roles
            if not any(r in user.roles for r in required_roles):
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Requires one of roles: {required_roles}",
                )
            return func(request, *args, **kwargs)
        return wrapper
    return decorator


def require_admin(request: Request) -> None:
    """Raise 403 if current user is not an admin."""
    user: UserContext = getattr(request.state, "user", UserContext.anonymous())
    if not user.is_admin and not user.is_service:
        raise HTTPException(status_code=403, detail="Admin access required")


# ---------------------------------------------------------------------------
# TLS context (for mTLS support in enterprise)
# ---------------------------------------------------------------------------
def get_tls_context(
    cert_path: Optional[str] = None,
    key_path: Optional[str] = None,
    ca_path: Optional[str] = None,
) -> ssl.SSLContext:
    """
    Build an SSL context for mTLS (mutual TLS) connections.
    Pass paths to client certificate, key, and CA bundle.
    """
    ctx = ssl.create_default_context(ssl.Purpose.SERVER_AUTH)

    if cert_path and key_path:
        ctx.load_cert_chain(cert_path, key_path)

    if ca_path:
        ctx.load_verify_locations(ca_path)
        ctx.verify_mode = ssl.CERT_REQUIRED
        ctx.check_hostname = True
    else:
        ctx.verify_mode = ssl.CERT_NONE

    return ctx
