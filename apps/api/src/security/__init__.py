"""Security utilities for FastAPI RBAC integration."""

from .dependencies import (
    extract_bearer_token,
    get_auth_service,
    get_current_user,
    get_optional_user,
    get_optional_user_with_db,
    internal_bearer_tokens,
    is_internal_bearer_token,
    require_admin_access,
    require_operator_access,
    require_roles,
)
from .principals import AuthUserPrincipal
from .repository import AuthRepository

__all__ = [
    "AuthUserPrincipal",
    "AuthRepository",
    "extract_bearer_token",
    "get_auth_service",
    "get_current_user",
    "get_optional_user",
    "get_optional_user_with_db",
    "internal_bearer_tokens",
    "is_internal_bearer_token",
    "require_roles",
    "require_admin_access",
    "require_operator_access",
]
