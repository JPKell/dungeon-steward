from __future__ import annotations

import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bot.services.progression_service import calculate_enemy_reward_scale, calculate_enemy_stat_scale


class EnemyContentError(ValueError):
    pass


@dataclass(frozen=True)
class GeneratedEnemy:
    key: str
    name: str
    level: int
    max_hp: int
    current_hp: int
    attack: int
    defense: int
    speed: int
    gold: int
    combat_xp: int


def load_dungeon_levels(path: Path | None = None) -> dict[int, dict[str, float | int]]:
    content_path = path or Path(__file__).parents[1] / "content" / "dungeon_levels.json"
    raw = json.loads(content_path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise EnemyContentError("Dungeon level content must be a list")
    levels: dict[int, dict[str, float | int]] = {}
    for entry in raw:
        if not isinstance(entry, dict):
            raise EnemyContentError("Dungeon level entries must be objects")
        level = _positive_int(entry, "level")
        if level in levels:
            raise EnemyContentError(f"Duplicate dungeon level: {level}")
        levels[level] = {
            "enemy_level_min": _positive_int(entry, "enemy_level_min"),
            "enemy_level_max": _positive_int(entry, "enemy_level_max"),
            "stat_modifier": _positive_number(entry, "stat_modifier"),
            "reward_modifier": _positive_number(entry, "reward_modifier"),
        }
    validate_dungeon_levels(levels)
    return levels


def load_enemy_types(path: Path | None = None) -> dict[str, dict[str, Any]]:
    content_path = path or Path(__file__).parents[1] / "content" / "enemies.json"
    raw = json.loads(content_path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise EnemyContentError("Enemy content must be a list")
    enemies: dict[str, dict[str, Any]] = {}
    for entry in raw:
        if not isinstance(entry, dict):
            raise EnemyContentError("Enemy entries must be objects")
        key = _required_str(entry, "key")
        if key in enemies:
            raise EnemyContentError(f"Duplicate enemy key: {key}")
        enemies[key] = dict(entry)
    return enemies


def lerp(start: float, end: float, amount: float) -> float:
    return start + ((end - start) * amount)


def validate_dungeon_levels(levels: dict[int, dict[str, float | int]] | None = None) -> None:
    levels = levels or DUNGEON_LEVELS
    if not levels:
        raise EnemyContentError("Dungeon level configuration cannot be empty")
    expected = set(range(min(levels), max(levels) + 1))
    if set(levels) != expected:
        raise EnemyContentError("Dungeon level configuration must be contiguous")
    for level, config in levels.items():
        enemy_min = int(config["enemy_level_min"])
        enemy_max = int(config["enemy_level_max"])
        if enemy_min <= 0 or enemy_max < enemy_min:
            raise EnemyContentError(f"Dungeon level {level} has invalid enemy level range")
        if float(config["stat_modifier"]) <= 0 or float(config["reward_modifier"]) <= 0:
            raise EnemyContentError(f"Dungeon level {level} has invalid modifiers")


def validate_enemy_definitions(
    enemies: dict[str, dict[str, Any]] | None = None,
    levels: dict[int, dict[str, float | int]] | None = None,
) -> None:
    enemies = enemies or ENEMY_TYPES
    levels = levels or DUNGEON_LEVELS
    validate_dungeon_levels(levels)
    dungeon_min = min(levels)
    dungeon_max = max(levels)
    required = {
        "key",
        "name",
        "min_dungeon_level",
        "max_dungeon_level",
        "base_hp_min",
        "base_hp_max",
        "base_attack_min",
        "base_attack_max",
        "base_defense_min",
        "base_defense_max",
        "base_speed_min",
        "base_speed_max",
        "stage_modifier_min",
        "stage_modifier_max",
        "gold_min",
        "gold_max",
        "xp_min",
        "xp_max",
        "weight",
        "enabled",
    }
    for key, enemy in enemies.items():
        missing = required - set(enemy)
        if missing:
            raise EnemyContentError(f"Enemy {key} missing fields: {sorted(missing)}")
        if enemy["key"] != key:
            raise EnemyContentError(f"Enemy {key} has mismatched key {enemy['key']}")
        if not isinstance(enemy["enabled"], bool):
            raise EnemyContentError(f"Enemy {key} has invalid enabled flag")
        if not dungeon_min <= enemy["min_dungeon_level"] <= enemy["max_dungeon_level"] <= dungeon_max:
            raise EnemyContentError(f"Enemy {key} has invalid dungeon level range")
        for prefix in ("base_hp", "base_attack", "base_defense", "base_speed", "gold", "xp"):
            if not isinstance(enemy[f"{prefix}_min"], int) or not isinstance(enemy[f"{prefix}_max"], int):
                raise EnemyContentError(f"Enemy {key} has non-integer {prefix} range")
            if enemy[f"{prefix}_min"] > enemy[f"{prefix}_max"]:
                raise EnemyContentError(f"Enemy {key} has invalid {prefix} range")
        for field in ("stage_modifier_min", "stage_modifier_max"):
            if not isinstance(enemy[field], int | float) or float(enemy[field]) <= 0:
                raise EnemyContentError(f"Enemy {key} has invalid {field}")
        if enemy["stage_modifier_min"] > enemy["stage_modifier_max"]:
            raise EnemyContentError(f"Enemy {key} has invalid stage modifier range")
        if not isinstance(enemy["weight"], int) or enemy["weight"] <= 0:
            raise EnemyContentError(f"Enemy {key} must have positive weight")


def generate_enemy(
    dungeon_level: int,
    *,
    rng: random.Random | None = None,
) -> GeneratedEnemy:
    validate_dungeon_level(dungeon_level)
    rng = rng or random
    enemies = _eligible_enemies(dungeon_level)
    if not enemies:
        raise EnemyContentError(f"No enabled enemies for dungeon level {dungeon_level}")

    selected = rng.choices(enemies, weights=[enemy["weight"] for enemy in enemies], k=1)[0]
    dungeon_config = DUNGEON_LEVELS[dungeon_level]
    enemy_level = rng.randint(
        int(dungeon_config["enemy_level_min"]),
        int(dungeon_config["enemy_level_max"]),
    )
    stage_position = (dungeon_level - DUNGEON_LEVEL_MIN) / (DUNGEON_LEVEL_MAX - DUNGEON_LEVEL_MIN)
    stage_modifier = lerp(
        float(selected["stage_modifier_min"]),
        float(selected["stage_modifier_max"]),
        stage_position,
    )
    stat_scale = calculate_enemy_stat_scale(
        dungeon_stat_modifier=float(dungeon_config["stat_modifier"]),
        enemy_stage_modifier=stage_modifier,
        enemy_level=enemy_level,
    )
    reward_scale = calculate_enemy_reward_scale(
        dungeon_reward_modifier=float(dungeon_config["reward_modifier"]),
        enemy_level=enemy_level,
    )

    hp = _scaled_roll(rng, selected, "base_hp", stat_scale)
    attack = _scaled_roll(rng, selected, "base_attack", stat_scale)
    defense = _scaled_roll(rng, selected, "base_defense", stat_scale)
    speed = _scaled_roll(rng, selected, "base_speed", stat_scale)
    gold = _scaled_roll(rng, selected, "gold", reward_scale, minimum=0)
    combat_xp = _scaled_roll(rng, selected, "xp", reward_scale)

    return GeneratedEnemy(
        key=selected["key"],
        name=selected["name"],
        level=enemy_level,
        max_hp=hp,
        current_hp=hp,
        attack=attack,
        defense=defense,
        speed=speed,
        gold=gold,
        combat_xp=combat_xp,
    )


def validate_dungeon_level(dungeon_level: int) -> None:
    if dungeon_level not in DUNGEON_LEVELS:
        raise EnemyContentError(f"Dungeon level must be between {DUNGEON_LEVEL_MIN} and {DUNGEON_LEVEL_MAX}")


def _eligible_enemies(dungeon_level: int) -> list[dict[str, Any]]:
    return [
        enemy
        for enemy in ENEMY_TYPES.values()
        if enemy["enabled"]
        and enemy["min_dungeon_level"] <= dungeon_level <= enemy["max_dungeon_level"]
    ]


def _scaled_roll(
    rng: random.Random,
    enemy: dict[str, Any],
    prefix: str,
    scale: float,
    *,
    minimum: int = 1,
) -> int:
    value = rng.randint(int(enemy[f"{prefix}_min"]), int(enemy[f"{prefix}_max"]))
    return max(minimum, int(round(value * scale)))


def _required_str(entry: dict[str, Any], field: str) -> str:
    value = entry.get(field)
    if not isinstance(value, str) or not value.strip():
        raise EnemyContentError(f"Missing string field: {field}")
    return value.strip()


def _positive_int(entry: dict[str, Any], field: str) -> int:
    value = entry.get(field)
    if not isinstance(value, int) or value <= 0:
        raise EnemyContentError(f"Missing positive integer field: {field}")
    return value


def _positive_number(entry: dict[str, Any], field: str) -> float:
    value = entry.get(field)
    if not isinstance(value, int | float) or float(value) <= 0:
        raise EnemyContentError(f"Missing positive number field: {field}")
    return float(value)


DUNGEON_LEVELS = load_dungeon_levels()
DUNGEON_LEVEL_MIN = min(DUNGEON_LEVELS)
DUNGEON_LEVEL_MAX = max(DUNGEON_LEVELS)
ENEMY_TYPES = load_enemy_types()


validate_enemy_definitions()
