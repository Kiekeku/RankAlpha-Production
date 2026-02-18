from __future__ import annotations

from hmac import compare_digest

import jwt
from fastapi import Depends, Header, HTTPException, status
from jwt import InvalidTokenError
from sqlalchemy.orm import Session

from apps.api.src.database import get_db
from apps.api.src.settings import Settings
from apps.api.src.utils.settings_cache import make_cached_getter

from .principals import AuthUserPrincipal
from .repository import AuthRepository
from .service import AuthService

_get_settings = make_cached_getter(lambda: Settings())


def get_auth_repository(db: Session = Depends(get_db)) -> AuthRepository:
    return AuthRepository(db)


def get_auth_service(
    repo: AuthRepository = Depends(get_auth_repository),
) -> AuthService:
    return AuthService(repo, _get_settings())


def extract_bearer_token(authorization: str | None) -> str | None:
    if not authorization:
        return None
    if not authorization.startswith("Bearer "):
        return None
    return authorization.removeprefix("Bearer ").strip() or None


def internal_bearer_tokens(settings: Settings) -> set[str]:
    admin_token = (settings.admin_bearer_token or "").strip()
    service_token = (settings.auth_service_token or "").strip()
    return {token for token in {admin_token, service_token} if token}


def _matches_internal_token(candidate: str, configured: set[str]) -> bool:
    if not candidate or not configured:
        return False
    candidate_bytes = candidate.encode("utf-8")
    for configured_token in configured:
        if compare_digest(candidate_bytes, configured_token.encode("utf-8")):
            return True
    return False


def is_internal_bearer_token(token: str | None, settings: Settings) -> bool:
    if not token:
        return False
    return _matches_internal_token(token, internal_bearer_tokens(settings))


def _decode_token(raw: str, settings: Settings) -> dict:
    secret = (settings.nextauth_secret or "").strip()
    if not secret:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Authentication provider not configured",
        )
    # Accept both HS256 (legacy) and HS512 (NextAuth default) so tokens signed
    # by either hashing scheme can be decoded without extra configuration.
    decode_kwargs: dict[str, object] = {
        "algorithms": ["HS256", "HS512"],
        "options": {"verify_aud": False},
    }
    if settings.nextauth_issuer:
        decode_kwargs["issuer"] = settings.nextauth_issuer
    try:
        return jwt.decode(raw, secret, **decode_kwargs)  # type: ignore[arg-type]
    except InvalidTokenError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
        ) from exc


def _user_from_payload(payload: dict, repo: AuthRepository) -> AuthUserPrincipal:
    user_id_raw = payload.get("userId") or payload.get("sub")
    if user_id_raw is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token missing subject",
        )
    try:
        user_id = int(user_id_raw)
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token subject invalid",
        ) from exc

    user = repo.get_user_by_id(user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User inactive",
        )
    roles = repo.get_roles_for_user(user)
    return AuthUserPrincipal(
        user_id=user.user_id,
        email=user.email,
        roles=tuple(roles),
        full_name=user.full_name,
        provider=user.provider,
    )


def get_optional_user(
    authorization: str | None = Header(default=None),
) -> AuthUserPrincipal | None:
    """Return the authenticated user if present; otherwise None.

    Avoids creating a DB session when the request is already authorized via
    admin/service tokens (useful for local tests without a DB).
    """
    settings = _get_settings()
    token = extract_bearer_token(authorization)
    if not token:
        return None
    if is_internal_bearer_token(token, settings):
        return None
    payload = _decode_token(token, settings)
    # Lazy session to avoid DB connection unless we need user resolution.
    from apps.api.src.database import SessionLocal

    db = SessionLocal()
    try:
        repo = AuthRepository(db)
        return _user_from_payload(payload, repo)
    finally:
        db.close()


def get_optional_user_with_db(
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
) -> AuthUserPrincipal | None:
    """Return the authenticated user if present; otherwise None.

    Uses the request-scoped DB session (avoids opening a second DB connection).
    """
    settings = _get_settings()
    token = extract_bearer_token(authorization)
    if not token:
        return None
    if is_internal_bearer_token(token, settings):
        return None
    try:
        payload = _decode_token(token, settings)
        repo = AuthRepository(db)
        return _user_from_payload(payload, repo)
    except HTTPException:
        return None
    except Exception:
        return None


def get_current_user(
    principal: AuthUserPrincipal | None = Depends(get_optional_user),
) -> AuthUserPrincipal:
    if principal is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )
    return principal


def require_roles(*role_names: str):
    expected = tuple({r.strip() for r in role_names if r and r.strip()})

    def dependency(user: AuthUserPrincipal = Depends(get_current_user)) -> AuthUserPrincipal:
        if not expected:
            return user
        if any(user.has_role(role) for role in expected):
            return user
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Requires one of: {', '.join(expected)}",
        )

    return dependency


def require_admin_access(
    principal: AuthUserPrincipal | None = Depends(get_optional_user),
    authorization: str | None = Header(default=None),
    service_token_header: str | None = Header(default=None, alias="X-RA-Service-Token"),
) -> AuthUserPrincipal | None:
    """Allow access for admin users or when bearing the legacy admin token."""
    settings = _get_settings()
    if principal and principal.has_role("admin"):
        return principal

    supplied = extract_bearer_token(authorization)
    candidate_tokens = [supplied, (service_token_header or "").strip() or None]
    configured = internal_bearer_tokens(settings)
    if any(_matches_internal_token(token, configured) for token in candidate_tokens if token):
        return principal

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Admin privileges required",
    )


def require_operator_access(
    principal: AuthUserPrincipal | None = Depends(get_optional_user),
    authorization: str | None = Header(default=None),
    service_token_header: str | None = Header(default=None, alias="X-RA-Service-Token"),
) -> AuthUserPrincipal | None:
    """Allow access for operator/admin users or when bearing the service/admin token.

    Intended for operational endpoints that mutate caches/materialized views.
    """
    settings = _get_settings()
    if principal and (principal.has_role("admin") or principal.has_role("operator")):
        return principal

    supplied = extract_bearer_token(authorization)
    candidate_tokens = [supplied, (service_token_header or "").strip() or None]
    configured = internal_bearer_tokens(settings)
    if any(_matches_internal_token(token, configured) for token in candidate_tokens if token):
        return principal

    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Operator privileges required",
    )
