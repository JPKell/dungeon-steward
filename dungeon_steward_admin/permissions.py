from __future__ import annotations

import os
from dataclasses import dataclass


class PermissionError(Exception):
    pass


class AdminConfigurationError(RuntimeError):
    pass


ROLE_LEVELS = {
    "read_only": 0,
    "game_support": 10,
    "database_admin": 20,
    "super_admin": 30,
}

PERMISSION_LEVELS = {
    "read": ROLE_LEVELS["read_only"],
    "game_support": ROLE_LEVELS["game_support"],
    "database_admin": ROLE_LEVELS["database_admin"],
    "delete": ROLE_LEVELS["database_admin"],
    "super_admin": ROLE_LEVELS["super_admin"],
}


@dataclass(frozen=True)
class AdminPrincipal:
    identity: str
    role: str

    def has_permission(self, permission: str) -> bool:
        required = PERMISSION_LEVELS.get(permission, ROLE_LEVELS["super_admin"])
        return ROLE_LEVELS[self.role] >= required


def load_admins_from_env(raw: str | None = None) -> dict[str, AdminPrincipal]:
    raw = os.getenv("DUNGEON_ADMIN_IDENTITIES", "") if raw is None else raw
    admins: dict[str, AdminPrincipal] = {}
    for chunk in raw.split(","):
        token = chunk.strip()
        if not token:
            continue
        if ":" in token:
            identity, role = token.split(":", 1)
            role = role.strip() or "read_only"
        else:
            identity, role = token, "read_only"
        identity = identity.strip()
        if not identity:
            continue
        if role not in ROLE_LEVELS:
            raise AdminConfigurationError(f"Unsupported admin role: {role}")
        admins[identity] = AdminPrincipal(identity=identity, role=role)
    return admins


def resolve_admin(identity: str | None, admins: dict[str, AdminPrincipal]) -> AdminPrincipal:
    if not identity or not identity.strip():
        raise AdminConfigurationError("An administrator identity is required. Use --admin or DUNGEON_ADMIN_IDENTITY.")
    identity = identity.strip()
    try:
        return admins[identity]
    except KeyError as error:
        raise PermissionError(f"{identity} is not configured in DUNGEON_ADMIN_IDENTITIES") from error


def require_permission(admin: AdminPrincipal, permission: str, *, read_only: bool = False) -> None:
    if read_only and permission != "read":
        raise PermissionError("The console is running in read-only mode.")
    if not admin.has_permission(permission):
        raise PermissionError(f"{admin.identity} does not have {permission} permission.")
