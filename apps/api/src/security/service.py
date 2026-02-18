from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any, Dict, Iterable, List

from apps.api.src.settings import Settings
from apps.common.src.models import AuthUser

from .repository import AuthRepository


class UserNotFoundError(Exception):
    """Raised when the requested user does not exist."""


class InvalidRoleError(Exception):
    """Raised when one or more role names are invalid."""


@dataclass(slots=True)
class AuthUserDTO:
    user_id: int
    email: str
    full_name: str | None
    avatar_url: str | None
    provider: str | None
    provider_account_id: str | None
    roles: List[str]
    is_active: bool
    last_login_at: datetime | None
    created_at: datetime
    updated_at: datetime

    def to_dict(self) -> Dict[str, Any]:
        payload = asdict(self)
        payload["roles"] = sorted(self.roles)
        return payload


class AuthService:
    """Business logic for user synchronization and role assignment."""

    def __init__(self, repo: AuthRepository, settings: Settings):
        self.repo = repo
        self.settings = settings

    @property
    def _default_role(self) -> str:
        return (self.settings.auth_default_role or "viewer").strip()

    def _serialize(self, user: AuthUser, roles: Iterable[str]) -> AuthUserDTO:
        return AuthUserDTO(
            user_id=user.user_id,
            email=user.email,
            full_name=user.full_name,
            avatar_url=user.avatar_url,
            provider=user.provider,
            provider_account_id=user.provider_account_id,
            roles=sorted({r for r in roles if r}),
            is_active=user.is_active,
            last_login_at=user.last_login_at,
            created_at=user.created_at,
            updated_at=user.updated_at,
        )

    def sync_oauth_user(
        self,
        *,
        email: str,
        full_name: str | None = None,
        avatar_url: str | None = None,
        provider: str | None = None,
        provider_account_id: str | None = None,
        metadata: Dict[str, Any] | None = None,
    ) -> AuthUserDTO:
        now = datetime.now(tz=UTC)
        user = self.repo.get_user_by_email(email)
        if user is None:
            user = self.repo.add_user(
                email=email,
                full_name=full_name,
                avatar_url=avatar_url,
                provider=provider,
                provider_account_id=provider_account_id,
                profile_metadata=metadata or {},
                last_login_at=now,
                created_at=now,
                updated_at=now,
            )
            try:
                roles = self.repo.set_user_roles(
                    user, [self._default_role] if self._default_role else []
                )
            except ValueError as exc:
                raise InvalidRoleError(str(exc)) from exc
            return self._serialize(user, roles)

        # Existing user – update profile details if changed
        updated = False
        if full_name and user.full_name != full_name:
            user.full_name = full_name
            updated = True
        if avatar_url and user.avatar_url != avatar_url:
            user.avatar_url = avatar_url
            updated = True
        if provider and user.provider != provider:
            user.provider = provider
            updated = True
        if provider_account_id and user.provider_account_id != provider_account_id:
            user.provider_account_id = provider_account_id
            updated = True
        if metadata:
            # Merge metadata – prefer latest keys
            merged = dict(user.profile_metadata or {})
            merged.update(metadata)
            user.profile_metadata = merged
            updated = True

        user.last_login_at = now
        if updated:
            user.updated_at = now

        roles = self.repo.get_roles_for_user(user)
        if not roles and self._default_role:
            try:
                roles = self.repo.set_user_roles(user, [self._default_role])
            except ValueError as exc:
                raise InvalidRoleError(str(exc)) from exc
        return self._serialize(user, roles)

    def ensure_user_roles(
        self,
        user_id: int,
        role_names: Iterable[str],
        *,
        assigned_by: int | None = None,
    ) -> AuthUserDTO:
        user = self.repo.get_user_by_id(user_id)
        if user is None:
            raise UserNotFoundError(f"User id {user_id} not found")
        try:
            roles = self.repo.set_user_roles(user, list(role_names), assigned_by=assigned_by)
        except ValueError as exc:
            raise InvalidRoleError(str(exc)) from exc
        user.updated_at = datetime.now(tz=UTC)
        return self._serialize(user, roles)

    def list_users(self, search: str | None = None) -> List[AuthUserDTO]:
        records = self.repo.list_users(search)
        return [self._serialize(user, self.repo.get_roles_for_user(user)) for user in records]

    def get_user(self, user_id: int) -> AuthUserDTO:
        user = self.repo.get_user_by_id(user_id)
        if user is None:
            raise UserNotFoundError(f"User id {user_id} not found")
        return self._serialize(user, self.repo.get_roles_for_user(user))
