from __future__ import annotations

from bot.services.discovery_service import DiscoveryService
from bot.services.encounter_service import EncounterService
from bot.services.enemy_service import DUNGEON_LEVELS, ENEMY_TYPES, validate_enemy_definitions
from bot.services.equipment_service import EQUIPMENT_SLOTS, EquipmentService
from bot.services.progression_content import PROGRESSION_CONTENT, load_progression_content


def test_encounter_content_is_valid():
    encounters = EncounterService().encounters
    assert len(encounters) >= 20
    assert all(2 <= len(encounter.choices) <= 4 for encounter in encounters)


def test_discovery_content_is_valid():
    discoveries = DiscoveryService().load_content()
    assert len(discoveries) >= 15


def test_equipment_content_is_valid():
    items = EquipmentService().items
    assert len(items) >= 30
    assert set(EQUIPMENT_SLOTS).issubset({item.slot for item in items})


def test_enemy_and_dungeon_level_content_is_valid():
    validate_enemy_definitions()
    assert len(DUNGEON_LEVELS) == 20
    assert len(ENEMY_TYPES) >= 20


def test_progression_content_is_valid():
    loaded = load_progression_content()
    assert loaded == PROGRESSION_CONTENT
    assert loaded.exploration.base_cooldown_minutes == 120
    assert loaded.exploration.leveling.curve in {"linear", "quadratic", "exponential"}
    assert loaded.exploration.leveling.base_xp > 0
    assert loaded.schema_version == 2
    assert loaded.exploration.cooldown_cap_level == 91
    assert loaded.exploration.reward_scaling.gold_multiplier.base > 1
    assert loaded.exploration.reward_scaling.xp_multiplier.base == 1
    assert loaded.combat_leveling.hp_per_level.base > 0
    assert loaded.combat_leveling.stat_points_per_level.base > 0
    assert loaded.combat_leveling.xp_to_next_level.base > 0
    assert loaded.defense.minutes_per_level.base >= 0
    assert loaded.defense.duration_cap_level == 421
    assert loaded.shop.stock_size == 10
    assert loaded.shop.cost_multiplier.base == 1
    assert loaded.shop.stat_multiplier.base == 1
    assert loaded.shop.rarity_bands[-1].min_level == 400
