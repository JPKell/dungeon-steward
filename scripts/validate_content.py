from __future__ import annotations

from bot.services.discovery_service import DiscoveryService
from bot.services.encounter_service import EncounterService
from bot.services.enemy_service import DUNGEON_LEVELS, ENEMY_TYPES, validate_enemy_definitions
from bot.services.equipment_service import EquipmentService
from bot.services.progression_content import PROGRESSION_CONTENT


def main() -> None:
    encounters = EncounterService().encounters
    discoveries = DiscoveryService().load_content()
    equipment = EquipmentService().items
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
        f"{len(DUNGEON_LEVELS)} dungeon levels, and progression content "
        f"with base {PROGRESSION_CONTENT.combat_leveling.stat_points_per_level.base:g} stat points per level."
    )


if __name__ == "__main__":
    main()
