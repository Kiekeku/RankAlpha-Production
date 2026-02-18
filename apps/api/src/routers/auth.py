from __future__ import annotations

from hmac import compare_digest
from typing import Annotated, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Path, status
from pydantic import BaseModel, EmailStr, Field

from apps.api.src.security import (
    AuthUserPrincipal,
    get_auth_service,
    get_current_user,
    get_optional_user,
    require_admin_access,
)
from apps.api.src.security.service import (
    AuthService,
    AuthUserDTO,
    InvalidRoleError,
    UserNotFoundError,
)
from apps.api.src.settings import Settings
from apps.api.src.utils.settings_cache import make_cached_getter

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class AuthSyncRequest(BaseModel):
    email: EmailStr
    full_name: Optional[str] = None
    avatar_url: Optional[str] = None
    provider: Optional[str] = None
    provider_account_id: Optional[str] = Field(default=None, alias="providerAccountId")
    metadata: Optional[dict] = None


class AuthUserResponse(BaseModel):
    user_id: int
    email: EmailStr
    full_name: Optional[str]
    avatar_url: Optional[str]
    provider: Optional[str]
    provider_account_id: Optional[str]
    roles: List[str]
    is_active: bool
    last_login_at: Optional[str] = None
    created_at: str
    updated_at: str

    @staticmethod
    def from_dto(dto: AuthUserDTO) -> "AuthUserResponse":
        return AuthUserResponse(
            user_id=dto.user_id,
            email=dto.email,
            full_name=dto.full_name,
            avatar_url=dto.avatar_url,
            provider=dto.provider,
            provider_account_id=dto.provider_account_id,
            roles=sorted(dto.roles),
            is_active=dto.is_active,
            last_login_at=dto.last_login_at.isoformat() if dto.last_login_at else None,
            created_at=dto.created_at.isoformat(),
            updated_at=dto.updated_at.isoformat(),
        )


_get_settings = make_cached_getter(lambda: Settings())


def _require_service_token(
    settings: Settings = Depends(_get_settings),
    service_token: str | None = Header(default=None, alias="X-RA-Service-Token"),
    authorization: str | None = Header(default=None),
) -> None:
    configured = (settings.auth_service_token or "").strip()
    if not configured:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Auth service token not configured",
        )
    candidate = (service_token or "").strip()
    if not candidate and authorization and authorization.startswith("Bearer "):
        candidate = authorization.removeprefix("Bearer ").strip()
    if not compare_digest(candidate.encode("utf-8"), configured.encode("utf-8")):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid service token",
        )


@router.post(
    "/sync",
    response_model=AuthUserResponse,
    status_code=status.HTTP_200_OK,
    summary="Upsert a user profile based on OAuth identity (internal use).",
    dependencies=[Depends(_require_service_token)],
)
def sync_user_profile(
    payload: AuthSyncRequest,
    service: AuthService = Depends(get_auth_service),
):
    dto = service.sync_oauth_user(
        email=payload.email,
        full_name=payload.full_name,
        avatar_url=payload.avatar_url,
        provider=payload.provider,
        provider_account_id=payload.provider_account_id,
        metadata=payload.metadata,
    )
    return AuthUserResponse.from_dto(dto)


@router.get(
    "/me",
    response_model=AuthUserResponse,
    summary="Return the authenticated profile.",
)
def get_me(
    principal: AuthUserPrincipal = Depends(get_current_user),
    service: AuthService = Depends(get_auth_service),
):
    dto = service.get_user(principal.user_id)
    return AuthUserResponse.from_dto(dto)


@router.get(
    "/users",
    response_model=list[AuthUserResponse],
    summary="List users and their roles (admin only).",
    dependencies=[Depends(require_admin_access)],
)
def list_users(
    search: str | None = None,
    service: AuthService = Depends(get_auth_service),
):
    records = service.list_users(search)
    return [AuthUserResponse.from_dto(dto) for dto in records]


@router.get(
    "/users/{user_id}",
    response_model=AuthUserResponse,
    summary="Retrieve a single user (admin only).",
    dependencies=[Depends(require_admin_access)],
)
def fetch_user(
    user_id: Annotated[int, Path(gt=0)],
    service: AuthService = Depends(get_auth_service),
):
    try:
        dto = service.get_user(user_id)
    except UserNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    return AuthUserResponse.from_dto(dto)


class RoleUpdateRequest(BaseModel):
    roles: List[str] = Field(default_factory=list, description="Complete set of roles to assign")


@router.put(
    "/users/{user_id}/roles",
    response_model=AuthUserResponse,
    summary="Replace the role assignments for a user (admin only).",
    dependencies=[Depends(require_admin_access)],
)
def replace_user_roles(
    user_id: Annotated[int, Path(gt=0)],
    payload: RoleUpdateRequest,
    service: AuthService = Depends(get_auth_service),
    principal: AuthUserPrincipal | None = Depends(get_optional_user),
):
    assigned_by = principal.user_id if principal else None
    try:
        dto = service.ensure_user_roles(user_id, payload.roles, assigned_by=assigned_by)
    except UserNotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except InvalidRoleError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    return AuthUserResponse.from_dto(dto)
