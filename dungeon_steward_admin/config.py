from __future__ import annotations

import os
from dataclasses import dataclass

from sqlalchemy.engine import make_url

from bot.config import Settings, load_settings
from dungeon_steward_admin.permissions import AdminPrincipal, load_admins_from_env, resolve_admin


class ProductionConfirmationError(RuntimeError):
    pass


@dataclass(frozen=True)
class AdminRuntimeConfig:
    environment: str
    database_url: str
    read_only: bool
    admin: AdminPrincipal
    page_size: int
    statement_timeout_ms: int | None
    production_confirmed: bool

    @property
    def is_production(self) -> bool:
        return self.environment.lower() == "production"

    @property
    def masked_database_url(self) -> str:
        try:
            return str(make_url(self.database_url).render_as_string(hide_password=True))
        except Exception:
            return "<configured database>"


def load_runtime_config(
    *,
    environment: str | None = None,
    read_only: bool = False,
    admin_identity: str | None = None,
    production_confirmed: bool = False,
    settings: Settings | None = None,
) -> AdminRuntimeConfig:
    settings = settings or load_settings(require_token=False)
    admins = load_admins_from_env()
    admin = resolve_admin(admin_identity or os.getenv("DUNGEON_ADMIN_IDENTITY"), admins)
    selected_environment = (environment or settings.environment or "development").lower()
    page_size = _bounded_int(os.getenv("DUNGEON_ADMIN_PAGE_SIZE"), default=50, minimum=5, maximum=200)
    timeout_ms = _optional_positive_int(os.getenv("DUNGEON_ADMIN_STATEMENT_TIMEOUT_MS"))
    config = AdminRuntimeConfig(
        environment=selected_environment,
        database_url=settings.database_url,
        read_only=read_only,
        admin=admin,
        page_size=page_size,
        statement_timeout_ms=timeout_ms,
        production_confirmed=production_confirmed,
    )
    validate_production_safety(config)
    return config


def validate_production_safety(config: AdminRuntimeConfig) -> None:
    if config.is_production and not config.read_only and not config.production_confirmed:
        raise ProductionConfirmationError("Production writes require typing PRODUCTION at startup.")


def _bounded_int(value: str | None, *, default: int, minimum: int, maximum: int) -> int:
    if value is None or not value.strip():
        return default
    parsed = int(value)
    return max(minimum, min(maximum, parsed))


def _optional_positive_int(value: str | None) -> int | None:
    if value is None or not value.strip():
        return None
    parsed = int(value)
    return parsed if parsed > 0 else None
