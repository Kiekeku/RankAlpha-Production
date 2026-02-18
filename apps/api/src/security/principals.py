from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Tuple


def _normalize_roles(roles: Iterable[str]) -> Tuple[str, ...]:
    return tuple(sorted({r.strip() for r in roles if r and r.strip()}))


@dataclass(frozen=True)
class AuthUserPrincipal:
    """Represents the authenticated user/actor resolved from a bearer token."""

    user_id: int
    email: str
    roles: Tuple[str, ...]
    full_name: str | None = None
    provider: str | None = None

    def __post_init__(self):
        object.__setattr__(self, "roles", _normalize_roles(self.roles))

    def has_role(self, role: str) -> bool:
        return role in self.roles

    def require_any(self, required: Iterable[str]) -> None:
        if not any(self.has_role(r) for r in required):
            raise PermissionError(f"Missing any required roles: {', '.join(required)}")
