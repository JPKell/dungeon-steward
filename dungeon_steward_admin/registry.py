from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import inspect

from bot.database.base import Base
from bot.models import (
    AdminAuditLog,
    EncounterHistory,
    ExplorationSession,
    Player,
    PotionActivation,
    PotionInventoryStack,
)

Formatter = Callable[[Any], str]
Validator = Callable[[Any], None]

DEFAULT_PROTECTED_FIELDS = frozenset({"id", "created_at", "updated_at"})


@dataclass
class AdminModelConfig:
    model: type[Any]
    friendly_name: str | None = None
    searchable_fields: tuple[str, ...] = ()
    readonly_fields: frozenset[str] = DEFAULT_PROTECTED_FIELDS
    hidden_fields: frozenset[str] = frozenset()
    display_fields: tuple[str, ...] = ()
    default_sort: tuple[str, bool] | None = None
    validators: dict[str, Validator] = field(default_factory=dict)
    formatters: dict[str, Formatter] = field(default_factory=dict)
    read_only: bool = False
    exclude: bool = False
    permission: str = "database_admin"
    delete_permission: str = "delete"

    @property
    def table_name(self) -> str:
        return inspect(self.model).local_table.name


@dataclass(frozen=True)
class AdminTableInfo:
    table_name: str
    model_name: str
    primary_key: tuple[str, ...]
    record_count: int | None
    read_only: bool
    custom_configured: bool


class AdminRegistry:
    def __init__(self) -> None:
        self._configs: dict[type[Any], AdminModelConfig] = {}

    def register(self, config: AdminModelConfig) -> AdminModelConfig:
        self._configs[config.model] = config
        return config

    def config_for_model(self, model: type[Any]) -> AdminModelConfig:
        if model in self._configs:
            return self._configs[model]
        mapper = inspect(model)
        fields = tuple(column.key for column in mapper.columns if column.key not in DEFAULT_PROTECTED_FIELDS)
        searchable = tuple(column.key for column in mapper.columns if _python_type(column.type) is str)
        return AdminModelConfig(
            model=model,
            searchable_fields=searchable,
            display_fields=tuple(column.key for column in mapper.primary_key) + fields[:4],
        )

    def custom_configured(self, model: type[Any]) -> bool:
        return model in self._configs

    def models(self) -> list[type[Any]]:
        models = [mapper.class_ for mapper in Base.registry.mappers]
        return sorted(models, key=lambda model: inspect(model).local_table.name)

    def table_model(self, table_name: str) -> type[Any]:
        for model in self.models():
            if inspect(model).local_table.name == table_name:
                config = self.config_for_model(model)
                if config.exclude:
                    break
                return model
        raise KeyError(f"Unknown admin table: {table_name}")

    def visible_models(self) -> list[type[Any]]:
        return [model for model in self.models() if not self.config_for_model(model).exclude]


DEFAULT_REGISTRY = AdminRegistry()


def register_admin_model(
    model: type[Any],
    *,
    friendly_name: str | None = None,
    searchable_fields: Iterable[str] = (),
    readonly_fields: Iterable[str] = DEFAULT_PROTECTED_FIELDS,
    hidden_fields: Iterable[str] = (),
    display_fields: Iterable[str] = (),
    default_sort: tuple[str, bool] | None = None,
    validators: dict[str, Validator] | None = None,
    formatters: dict[str, Formatter] | None = None,
    read_only: bool = False,
    exclude: bool = False,
    permission: str = "database_admin",
    delete_permission: str = "delete",
) -> AdminModelConfig:
    return DEFAULT_REGISTRY.register(
        AdminModelConfig(
            model=model,
            friendly_name=friendly_name,
            searchable_fields=tuple(searchable_fields),
            readonly_fields=frozenset(readonly_fields),
            hidden_fields=frozenset(hidden_fields),
            display_fields=tuple(display_fields),
            default_sort=default_sort,
            validators=validators or {},
            formatters=formatters or {},
            read_only=read_only,
            exclude=exclude,
            permission=permission,
            delete_permission=delete_permission,
        )
    )


def _python_type(column_type: Any) -> type[Any] | None:
    try:
        return column_type.python_type
    except (AttributeError, NotImplementedError):
        return None


register_admin_model(
    Player,
    friendly_name="Players",
    searchable_fields=("id", "discord_user_id", "display_name"),
    display_fields=("id", "guild_id", "discord_user_id", "display_name", "combat_level", "explore_level", "gold"),
    default_sort=("id", False),
    permission="game_support",
)
register_admin_model(
    PotionInventoryStack,
    friendly_name="Potion Inventory",
    searchable_fields=("item_key",),
    display_fields=("id", "player_id", "item_key", "quantity"),
    permission="game_support",
)
register_admin_model(
    PotionActivation,
    friendly_name="Potion Activations",
    searchable_fields=("item_key", "effect_group"),
    display_fields=("id", "player_id", "item_key", "effect_group", "activated_at", "effective_ends_at"),
    permission="game_support",
)
register_admin_model(
    ExplorationSession,
    friendly_name="Exploration Sessions",
    searchable_fields=("resolution_key", "encounter_key"),
    display_fields=("id", "player_id", "encounter_key", "dungeon_level", "resolved_at", "expires_at"),
    permission="game_support",
)
register_admin_model(
    EncounterHistory,
    friendly_name="Encounter History",
    searchable_fields=("encounter_key", "choice_key", "discovery_key", "potion_item_key"),
    display_fields=("id", "player_id", "encounter_key", "choice_key", "gold_awarded", "experience_awarded"),
    read_only=True,
    permission="game_support",
)
register_admin_model(
    AdminAuditLog,
    friendly_name="Admin Audit Log",
    searchable_fields=("administrator_identity", "action_name", "target_table", "result"),
    display_fields=("id", "created_at", "administrator_identity", "action_name", "target_table", "target_user_id", "result"),
    read_only=True,
    permission="read",
    delete_permission="super_admin",
)
