from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass

from bot.config import PROGRESSION_SCHEMA_VERSION
from bot.models import Player
from bot.services.enemy_service import DUNGEON_LEVEL_MAX, DUNGEON_LEVEL_MIN, DUNGEON_LEVELS
from bot.services.equipment_service import EquipmentService
from bot.services.progression_service import (
    DungeonUnlockState,
    calculate_equipment_power,
    evaluate_dungeon_unlock,
    migrate_explore_progression,
    sync_combat_progression,
)


@dataclass(frozen=True)
class DungeonProgressionSnapshot:
    highest_unlocked: int
    next_level: int | None
    next_unlock: DungeonUnlockState | None


def get_dungeon_unlock_state(
    dungeon_level: int,
    *,
    explore_level: int,
    combat_level: int,
    equipment_power: float,
    discoveries: int,
    defense_wins: int,
    completed_dungeons: Collection[int],
) -> DungeonUnlockState:
    if not DUNGEON_LEVEL_MIN <= dungeon_level <= DUNGEON_LEVEL_MAX:
        raise ValueError(f"Dungeon level must be between {DUNGEON_LEVEL_MIN} and {DUNGEON_LEVEL_MAX}")
    if dungeon_level == DUNGEON_LEVEL_MIN:
        return DungeonUnlockState(unlocked=True, missing=())
    config = DUNGEON_LEVELS[dungeon_level]
    return evaluate_dungeon_unlock(
        config,
        explore_level=explore_level,
        combat_level=combat_level,
        equipment_power=equipment_power,
        discoveries=discoveries,
        defense_wins=defense_wins,
        previous_dungeon_completed=(dungeon_level - 1) in completed_dungeons,
    )


def get_progression_snapshot(
    *,
    explore_level: int,
    combat_level: int,
    equipment_power: float,
    discoveries: int,
    defense_wins: int,
    completed_dungeons: Collection[int],
) -> DungeonProgressionSnapshot:
    highest = DUNGEON_LEVEL_MIN
    for level in range(DUNGEON_LEVEL_MIN + 1, DUNGEON_LEVEL_MAX + 1):
        state = get_dungeon_unlock_state(
            level,
            explore_level=explore_level,
            combat_level=combat_level,
            equipment_power=equipment_power,
            discoveries=discoveries,
            defense_wins=defense_wins,
            completed_dungeons=completed_dungeons,
        )
        if not state.unlocked:
            return DungeonProgressionSnapshot(
                highest_unlocked=highest,
                next_level=level,
                next_unlock=state,
            )
        highest = level
    return DungeonProgressionSnapshot(
        highest_unlocked=DUNGEON_LEVEL_MAX,
        next_level=None,
        next_unlock=None,
    )


def can_enter_dungeon(dungeon_level: int, highest_unlocked: int) -> bool:
    """Players may always return to any previously unlocked dungeon."""
    return DUNGEON_LEVEL_MIN <= dungeon_level <= min(DUNGEON_LEVEL_MAX, highest_unlocked)


def get_player_equipment_power(
    player: Player,
    *,
    equipment: EquipmentService | None = None,
) -> float:
    equipment = equipment or EquipmentService()
    return sum(calculate_equipment_power(item) for item in equipment.get_player_equipment(player).values() if item is not None)


def get_player_completed_dungeons(player: Player) -> set[int]:
    highest_completed = min(
        DUNGEON_LEVEL_MAX,
        max(DUNGEON_LEVEL_MIN, int(player.highest_completed_dungeon_level or DUNGEON_LEVEL_MIN)),
    )
    return set(range(DUNGEON_LEVEL_MIN, highest_completed + 1))


def get_player_progression_snapshot(
    player: Player,
    *,
    equipment: EquipmentService | None = None,
) -> DungeonProgressionSnapshot:
    migrate_explore_progression(player)
    sync_combat_progression(player)
    return get_progression_snapshot(
        explore_level=max(1, int(player.explore_level or 1)),
        combat_level=max(1, int(player.combat_level or 1)),
        equipment_power=get_player_equipment_power(player, equipment=equipment),
        discoveries=max(0, int(player.discoveries_found or 0)),
        defense_wins=max(0, int(player.defense_wins or 0)),
        completed_dungeons=get_player_completed_dungeons(player),
    )


def sync_player_dungeon_progression(
    player: Player,
    *,
    equipment: EquipmentService | None = None,
) -> DungeonProgressionSnapshot:
    snapshot = get_player_progression_snapshot(player, equipment=equipment)
    stored_unlocked = int(player.highest_unlocked_dungeon_level or DUNGEON_LEVEL_MIN)
    stored_completed = int(player.highest_completed_dungeon_level or DUNGEON_LEVEL_MIN)
    player.highest_unlocked_dungeon_level = max(
        stored_unlocked,
        stored_completed,
        snapshot.highest_unlocked,
    )
    player.highest_completed_dungeon_level = min(
        stored_completed,
        player.highest_unlocked_dungeon_level,
    )
    player.progression_schema_version = max(
        int(player.progression_schema_version or 0),
        PROGRESSION_SCHEMA_VERSION,
    )
    return snapshot


def get_player_dungeon_unlock_state(
    player: Player,
    dungeon_level: int,
    *,
    equipment: EquipmentService | None = None,
) -> DungeonUnlockState:
    return get_dungeon_unlock_state(
        dungeon_level,
        explore_level=max(1, int(player.explore_level or 1)),
        combat_level=max(1, int(player.combat_level or 1)),
        equipment_power=get_player_equipment_power(player, equipment=equipment),
        discoveries=max(0, int(player.discoveries_found or 0)),
        defense_wins=max(0, int(player.defense_wins or 0)),
        completed_dungeons=get_player_completed_dungeons(player),
    )
