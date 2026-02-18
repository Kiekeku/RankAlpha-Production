from __future__ import annotations

from collections.abc import Sequence
from typing import Dict, Iterable, List

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from apps.common.src.models import AuthRole, AuthUser, AuthUserRole


class AuthRepository:
    """Lightweight data access helpers for RBAC entities."""

    def __init__(self, session: Session):
        self.session = session

    # ---- User lookups -------------------------------------------------
    def get_user_by_id(self, user_id: int) -> AuthUser | None:
        stmt = (
            select(AuthUser)
            .options(selectinload(AuthUser.roles).selectinload(AuthUserRole.role))
            .where(AuthUser.user_id == user_id)
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def get_user_by_email(self, email: str) -> AuthUser | None:
        stmt = (
            select(AuthUser)
            .options(selectinload(AuthUser.roles).selectinload(AuthUserRole.role))
            .where(func.lower(AuthUser.email) == email.lower())
        )
        return self.session.execute(stmt).scalar_one_or_none()

    def list_users(self, search: str | None = None) -> List[AuthUser]:
        stmt = select(AuthUser).options(
            selectinload(AuthUser.roles).selectinload(AuthUserRole.role)
        )
        if search:
            ilike = f"%{search.lower()}%"
            stmt = stmt.where(
                func.lower(AuthUser.email).like(ilike)
                | func.coalesce(func.lower(AuthUser.full_name), "").like(ilike)
            )
        stmt = stmt.order_by(AuthUser.email.asc())
        return list(self.session.execute(stmt).scalars().all())

    # ---- Roles --------------------------------------------------------
    def get_roles_for_user(self, user: AuthUser) -> List[str]:
        return [link.role.role_name for link in user.roles if link.role is not None]

    def get_role_by_name(self, role_name: str) -> AuthRole | None:
        stmt = select(AuthRole).where(func.lower(AuthRole.role_name) == role_name.lower())
        return self.session.execute(stmt).scalar_one_or_none()

    def get_roles_by_names(self, role_names: Iterable[str]) -> Dict[str, AuthRole]:
        normalized = {name.lower(): name for name in role_names if name}
        if not normalized:
            return {}
        stmt = select(AuthRole).where(func.lower(AuthRole.role_name).in_(tuple(normalized.keys())))
        records = self.session.execute(stmt).scalars().all()
        return {rec.role_name.lower(): rec for rec in records}

    # ---- Mutations ----------------------------------------------------
    def ensure_role(self, role_name: str, description: str | None = None) -> AuthRole:
        existing = self.get_role_by_name(role_name)
        if existing:
            return existing
        role = AuthRole(role_name=role_name, description=description)
        self.session.add(role)
        self.session.flush()
        return role

    def add_user(self, email: str, **kwargs) -> AuthUser:
        user = AuthUser(email=email, **kwargs)
        self.session.add(user)
        self.session.flush()
        return user

    def set_user_roles(
        self,
        user: AuthUser,
        target_roles: Sequence[str],
        *,
        assigned_by: int | None = None,
    ) -> List[str]:
        desired = {r.lower() for r in target_roles if r}
        existing_map = {link.role.role_name.lower(): link for link in user.roles if link.role}
        if not desired:
            # Retain at least viewer if nothing specified
            desired = set()

        if desired == set(existing_map.keys()):
            return [link.role.role_name for link in user.roles if link.role]

        role_map = self.get_roles_by_names(desired)
        missing = desired - set(role_map.keys())
        if missing:
            raise ValueError(f"Unknown roles requested: {', '.join(sorted(missing))}")

        # Remove revoked roles
        for role_name, link in list(existing_map.items()):
            if role_name not in desired:
                self.session.delete(link)

        # Add new roles
        for role_name in desired:
            if role_name in existing_map:
                continue
            role = role_map[role_name]
            user.roles.append(
                AuthUserRole(
                    user_id=user.user_id,
                    role_id=role.role_id,
                    assigned_by=assigned_by,
                )
            )

        self.session.flush()
        return [link.role.role_name for link in user.roles if link.role]
