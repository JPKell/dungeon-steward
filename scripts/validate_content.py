from __future__ import annotations

from bot.services.discord_asset_service import (
    load_catalog,
    load_registry,
    validate_gameplay_asset_references,
    validate_registry_integrity,
)
from bot.services.discovery_service import DiscoveryService
from bot.services.encounter_service import EncounterService
from bot.services.enemy_service import DUNGEON_LEVELS, ENEMY_TYPES, validate_enemy_definitions
from bot.services.equipment_service import EquipmentService
from bot.services.location_service import LocationService
from bot.services.potion_service import PotionService
from bot.services.progression_content import PROGRESSION_CONTENT


def main() -> None:
    encounters = EncounterService().encounters
    discoveries = DiscoveryService().load_content()
    equipment = EquipmentService().items
    potions = [item for item in PotionService().content.items if item.enabled]
    locations = LocationService().locations
    image_catalog = load_catalog(validate_files=True)
    image_registry = load_registry()
    validate_gameplay_asset_references(image_catalog)
    validate_registry_integrity(image_catalog, image_registry, require_required_assets=False)
    validate_enemy_definitions()
    discovery_keys = {item["key"] for item in discoveries}
    missing = sorted(
        {
            choice.discovery_key
            for encounter in encounters
            for choice in encounter.choices
            if choice.discovery_key and choice.discovery_key not in discovery_keys
        }
    )
    if missing:
        raise SystemExit(f"Unknown discovery keys in encounters: {', '.join(missing)}")
    print(
        f"Validated {len(encounters)} encounters, {len(discoveries)} discoveries, "
        f"{len(equipment)} equipment items, {len(ENEMY_TYPES)} enemies, "
        f"{len(DUNGEON_LEVELS)} dungeon levels, {len(potions)} potions, {len(locations)} locations, "
        f"{len(image_catalog.assets)} image assets, {len(image_registry.assets)} registered image assets, and progression content "
        f"with base {PROGRESSION_CONTENT.combat_leveling.stat_points_per_level.base:g} stat points per level."
    )


if __name__ == "__main__":
    main()
