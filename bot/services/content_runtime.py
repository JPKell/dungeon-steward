from __future__ import annotations

import logging
from typing import Any

from sqlalchemy.orm import Session, sessionmaker

from bot.services.content_database import (
    load_content_documents_from_database,
    sync_runtime_discoveries_from_content_tables,
)

log = logging.getLogger(__name__)


class RuntimeContentError(RuntimeError):
    pass


def refresh_runtime_content_from_database(
    session_or_factory: Session | sessionmaker[Session],
) -> dict[str, Any]:
    if isinstance(session_or_factory, Session):
        return _refresh(session_or_factory)

    with session_or_factory() as session:
        documents = _refresh(session)
        session.commit()
        return documents


def _refresh(session: Session) -> dict[str, Any]:
    documents = load_content_documents_from_database(session)

    from bot import config
    from bot.commands import admin as admin_commands
    from bot.commands import dungeon as dungeon_commands
    from bot.services import (
        combat_service,
        defense_service,
        discord_asset_service,
        discord_emoji_service,
        discovery_service,
        dungeon_progression_service,
        encounter_service,
        enemy_service,
        equipment_service,
        exploration_service,
        location_service,
        player_service,
        potion_service,
        progression_content,
        progression_service,
        shop_selection,
        shop_service,
    )
    from bot.utils import defense_embeds, shop_embeds
    from bot.views import exploration as exploration_view

    progression = progression_content.refresh_progression_content(_document_object(documents, "progression.json"))
    config.apply_progression_content(progression)

    for module in (
        combat_service,
        defense_service,
        enemy_service,
        progression_service,
        shop_selection,
        shop_service,
    ):
        module.PROGRESSION_CONTENT = progression

    shop_service.SHOP_STOCK_SIZE = progression.shop.stock_size
    dungeon_progression_service.PROGRESSION_SCHEMA_VERSION = progression.schema_version
    player_service.PROGRESSION_SCHEMA_VERSION = progression.schema_version

    enemy_service.refresh_enemy_content(
        dungeon_levels_document=_document_list(documents, "dungeon_levels.json"),
        enemies_document=_document_list(documents, "enemies.json"),
    )
    for module in (dungeon_progression_service, exploration_service, defense_embeds):
        module.DUNGEON_LEVELS = enemy_service.DUNGEON_LEVELS
    for module in (defense_service, dungeon_progression_service, exploration_view):
        module.DUNGEON_LEVEL_MIN = enemy_service.DUNGEON_LEVEL_MIN
        module.DUNGEON_LEVEL_MAX = enemy_service.DUNGEON_LEVEL_MAX

    encounter_service.refresh_encounter_content(_document_list(documents, "encounters.json"))
    equipment_service.refresh_equipment_content(
        equipment_document=_document_list(documents, "equipment.json"),
        descriptions_document=_document_object(documents, "equipment_descriptions.json"),
    )
    discovery_service.refresh_discovery_content(_document_list(documents, "discoveries.json"))
    potion_service.refresh_potion_content(_document_object(documents, "potion_items.json"))
    location = location_service.refresh_location_service(_document_list(documents, "locations.json"))
    assets = discord_asset_service.refresh_default_discord_assets(
        catalog_document=_document_object(documents, "image_assets.json"),
        registry_document=_document_object(documents, "image_asset_registry.json"),
    )
    emojis = discord_emoji_service.DiscordEmojiService()
    if emojis.catalog.emojis and not emojis.registry.emojis:
        log.warning("Loaded %s Discord emoji definitions but no registered emoji IDs.", len(emojis.catalog.emojis))
    else:
        log.info("Loaded %s Discord emoji registry entries.", len(emojis.registry.emojis))

    for module in (dungeon_commands, defense_embeds, exploration_view, shop_embeds):
        module.LOCATION_SERVICE = location
    for module in (dungeon_commands, defense_embeds, exploration_view, shop_embeds):
        module.DEFAULT_DISCORD_ASSETS = assets
    defense_embeds.DEFAULT_DISCORD_EMOJIS = emojis
    exploration_view.DEFAULT_DISCORD_EMOJIS = emojis
    admin_commands.DEFAULT_DISCORD_EMOJIS = emojis
    admin_commands.EquipmentService = equipment_service.EquipmentService
    admin_commands.PotionService = potion_service.PotionService
    exploration_view.PotionService = potion_service.PotionService
    dungeon_commands.PotionService = potion_service.PotionService
    dungeon_commands.EncounterService = encounter_service.EncounterService
    dungeon_commands.DiscoveryService = discovery_service.DiscoveryService

    sync_runtime_discoveries_from_content_tables(session)
    session.flush()
    return documents


def _document_object(documents: dict[str, Any], filename: str) -> dict[str, Any]:
    value = documents.get(filename)
    if not isinstance(value, dict):
        raise RuntimeContentError(f"{filename} was not loaded from content tables")
    return value


def _document_list(documents: dict[str, Any], filename: str) -> list[Any]:
    value = documents.get(filename)
    if not isinstance(value, list):
        raise RuntimeContentError(f"{filename} was not loaded from content tables")
    return value
