from __future__ import annotations

import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from bot.services.progression_content import PROGRESSION_CONTENT
from bot.services.progression_service import (
    calculate_combat_power,
    calculate_enemy_reward_scale,
    calculate_enemy_stat_scale,
)


class EnemyContentError(ValueError):
    pass


@dataclass(frozen=True)
class GeneratedEnemy:
    key: str
    name: str
    rank: str
    dungeon_level: int
    level: int
    max_hp: int
    current_hp: int
    attack: int
    defense: int
    speed: int
    gold: int
    combat_xp: int
    power: float
    max_gold: int = 0
    max_combat_xp: int = 0


DUNGEON_OPTIONAL_FIELDS = {
    "target_day": 1,
    "exploration_gold_modifier": 1.0,
    "exploration_xp_modifier": 1.0,
    "expected_player_power": 1.0,
    "required_explore_level": 1,
    "required_combat_level": 1,
    "required_equipment_power": 0.0,
    "required_discoveries": 0,
    "required_defense_wins": 0,
    "requires_previous_completion": False,
    "thumbnail_asset": None,
}

VALID_RANKS = {"common", "standard", "dangerous", "elite", "boss"}


def load_dungeon_levels(
    path: Path | None = None,
    *,
    document: list[Any] | None = None,
) -> dict[int, dict[str, float | int | bool]]:
    if document is None:
        content_path = path or _default_content_path("dungeon_levels.json")
        raw = json.loads(content_path.read_text(encoding="utf-8"))
    else:
        raw = document
    if not isinstance(raw, list):
        raise EnemyContentError("Dungeon level content must be a list")
    levels: dict[int, dict[str, float | int | bool]] = {}
    for entry in raw:
        if not isinstance(entry, dict):
            raise EnemyContentError("Dungeon level entries must be objects")
        level = _positive_int(entry, "level")
        if level in levels:
            raise EnemyContentError(f"Duplicate dungeon level: {level}")
        config: dict[str, float | int | bool] = {
            "enemy_level_min": _positive_int(entry, "enemy_level_min"),
            "enemy_level_max": _positive_int(entry, "enemy_level_max"),
            "stat_modifier": _positive_number(entry, "stat_modifier"),
            "reward_modifier": _positive_number(entry, "reward_modifier"),
        }
        for field, default in DUNGEON_OPTIONAL_FIELDS.items():
            config[field] = entry.get(field, default)
        levels[level] = config
    validate_dungeon_levels(levels)
    return levels


def load_enemy_types(
    path: Path | None = None,
    *,
    document: list[Any] | None = None,
) -> dict[str, dict[str, Any]]:
    if document is None:
        content_path = path or _default_content_path("enemies.json")
        raw = json.loads(content_path.read_text(encoding="utf-8"))
    else:
        raw = document
    if not isinstance(raw, list):
        raise EnemyContentError("Enemy content must be a list")
    enemies: dict[str, dict[str, Any]] = {}
    names: set[str] = set()
    for entry in raw:
        if not isinstance(entry, dict):
            raise EnemyContentError("Enemy entries must be objects")
        key = _required_str(entry, "key")
        name = _required_str(entry, "name")
        if key in enemies:
            raise EnemyContentError(f"Duplicate enemy key: {key}")
        if name in names:
            raise EnemyContentError(f"Duplicate enemy name: {name}")
        names.add(name)
        copied = dict(entry)
        copied.setdefault("rank", "standard")
        enemies[key] = copied
    return enemies


def _default_content_path(filename: str) -> Path:
    project_path = Path(__file__).parents[1] / "content" / filename
    if project_path.exists():
        return project_path
    return Path(__file__).with_name(filename)


def lerp(start: float, end: float, amount: float) -> float:
    return start + ((end - start) * amount)


def validate_dungeon_levels(
    levels: dict[int, dict[str, float | int | bool]] | None = None,
) -> None:
    levels = levels or DUNGEON_LEVELS
    if not levels:
        raise EnemyContentError("Dungeon level configuration cannot be empty")
    expected = set(range(min(levels), max(levels) + 1))
    if set(levels) != expected:
        raise EnemyContentError("Dungeon level configuration must be contiguous")
    previous_target_day = 0
    previous_explore = 0
    previous_combat = 0
    for level, config in sorted(levels.items()):
        enemy_min = int(config["enemy_level_min"])
        enemy_max = int(config["enemy_level_max"])
        if enemy_min <= 0 or enemy_max < enemy_min:
            raise EnemyContentError(f"Dungeon level {level} has invalid enemy level range")
        for field in (
            "stat_modifier",
            "reward_modifier",
            "exploration_gold_modifier",
            "exploration_xp_modifier",
            "expected_player_power",
        ):
            if not isinstance(config[field], int | float) or isinstance(config[field], bool) or float(config[field]) <= 0:
                raise EnemyContentError(f"Dungeon level {level} has invalid {field}")
        for field in (
            "target_day",
            "required_explore_level",
            "required_combat_level",
            "required_discoveries",
            "required_defense_wins",
        ):
            if not isinstance(config[field], int) or isinstance(config[field], bool) or int(config[field]) < 0:
                raise EnemyContentError(f"Dungeon level {level} has invalid {field}")
        if not isinstance(config["required_equipment_power"], int | float) or float(config["required_equipment_power"]) < 0:
            raise EnemyContentError(f"Dungeon level {level} has invalid required_equipment_power")
        if not isinstance(config["requires_previous_completion"], bool):
            raise EnemyContentError(f"Dungeon level {level} has invalid requires_previous_completion")
        if int(config["target_day"]) < previous_target_day:
            raise EnemyContentError("Dungeon target days must be non-decreasing")
        if int(config["required_explore_level"]) < previous_explore:
            raise EnemyContentError("Explore unlock requirements must be non-decreasing")
        if int(config["required_combat_level"]) < previous_combat:
            raise EnemyContentError("Combat unlock requirements must be non-decreasing")
        previous_target_day = int(config["target_day"])
        previous_explore = int(config["required_explore_level"])
        previous_combat = int(config["required_combat_level"])


def validate_enemy_definitions(
    enemies: dict[str, dict[str, Any]] | None = None,
    levels: dict[int, dict[str, float | int | bool]] | None = None,
) -> None:
    enemies = enemies or ENEMY_TYPES
    levels = levels or DUNGEON_LEVELS
    validate_dungeon_levels(levels)
    dungeon_min = min(levels)
    dungeon_max = max(levels)
    required = {
        "key",
        "name",
        "rank",
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
        if enemy["rank"] not in VALID_RANKS:
            raise EnemyContentError(f"Enemy {key} has unsupported rank {enemy['rank']}")
        if not isinstance(enemy["enabled"], bool):
            raise EnemyContentError(f"Enemy {key} has invalid enabled flag")
        if not dungeon_min <= enemy["min_dungeon_level"] <= enemy["max_dungeon_level"] <= dungeon_max:
            raise EnemyContentError(f"Enemy {key} has invalid dungeon level range")
        for prefix in ("base_hp", "base_attack", "base_defense", "base_speed", "gold", "xp"):
            minimum = enemy[f"{prefix}_min"]
            maximum = enemy[f"{prefix}_max"]
            if not isinstance(minimum, int) or isinstance(minimum, bool):
                raise EnemyContentError(f"Enemy {key} has non-integer {prefix} range")
            if not isinstance(maximum, int) or isinstance(maximum, bool):
                raise EnemyContentError(f"Enemy {key} has non-integer {prefix} range")
            if minimum < 0 or maximum < minimum:
                raise EnemyContentError(f"Enemy {key} has invalid {prefix} range")
        if enemy["base_hp_min"] <= 0 or enemy["xp_min"] <= 0:
            raise EnemyContentError(f"Enemy {key} must have positive HP and XP")
        for field in ("stage_modifier_min", "stage_modifier_max"):
            if not isinstance(enemy[field], int | float) or isinstance(enemy[field], bool) or float(enemy[field]) <= 0:
                raise EnemyContentError(f"Enemy {key} has invalid {field}")
        if enemy["stage_modifier_min"] > enemy["stage_modifier_max"]:
            raise EnemyContentError(f"Enemy {key} has invalid stage modifier range")
        if not isinstance(enemy["weight"], int) or isinstance(enemy["weight"], bool) or enemy["weight"] <= 0:
            raise EnemyContentError(f"Enemy {key} must have positive weight")

    for dungeon_level in levels:
        eligible = [
            enemy for enemy in enemies.values()
            if enemy["enabled"]
            and enemy["min_dungeon_level"] <= dungeon_level <= enemy["max_dungeon_level"]
        ]
        if not eligible:
            raise EnemyContentError(f"Dungeon level {dungeon_level} has no enabled enemies")
        ranks = {enemy["rank"] for enemy in eligible}
        if dungeon_level >= 5 and not ranks.intersection({"dangerous", "elite", "boss"}):
            raise EnemyContentError(f"Dungeon level {dungeon_level} has no dangerous enemy tier")


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
    level_span = max(1, DUNGEON_LEVEL_MAX - DUNGEON_LEVEL_MIN)
    stage_position = (dungeon_level - DUNGEON_LEVEL_MIN) / level_span
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
    defense = _scaled_roll(rng, selected, "base_defense", stat_scale, minimum=0)
    speed = _scaled_roll(rng, selected, "base_speed", stat_scale, minimum=1)
    gold = _scaled_roll(
        rng,
        selected,
        "gold",
        reward_scale * PROGRESSION_CONTENT.enemy_generation.combat_gold_multiplier,
        minimum=1,
    )
    combat_xp = _scaled_roll(rng, selected, "xp", reward_scale)
    max_gold = max(
        gold,
        _scaled_value(
            int(selected["gold_max"]),
            reward_scale * PROGRESSION_CONTENT.enemy_generation.combat_gold_multiplier,
            minimum=1,
        ),
    )
    max_combat_xp = max(combat_xp, _scaled_value(int(selected["xp_max"]), reward_scale, minimum=1))
    power = calculate_combat_power(max_hp=hp, attack=attack, defense=defense, speed=speed)

    return GeneratedEnemy(
        key=selected["key"],
        name=selected["name"],
        rank=selected["rank"],
        dungeon_level=dungeon_level,
        level=enemy_level,
        max_hp=hp,
        current_hp=hp,
        attack=attack,
        defense=defense,
        speed=speed,
        gold=gold,
        combat_xp=combat_xp,
        power=power,
        max_gold=max_gold,
        max_combat_xp=max_combat_xp,
    )


def validate_dungeon_level(dungeon_level: int) -> None:
    if dungeon_level not in DUNGEON_LEVELS:
        raise EnemyContentError(
            f"Dungeon level must be between {DUNGEON_LEVEL_MIN} and {DUNGEON_LEVEL_MAX}"
        )


def _eligible_enemies(dungeon_level: int) -> list[dict[str, Any]]:
    return [
        enemy
        for enemy in ENEMY_TYPES.values()
        if enemy["enabled"]
        and enemy["min_dungeon_level"] <= dungeon_level <= enemy["max_dungeon_level"]
    ]


def refresh_enemy_content(
    *,
    dungeon_levels_document: list[Any],
    enemies_document: list[Any],
) -> None:
    global DUNGEON_LEVEL_MAX
    global DUNGEON_LEVEL_MIN
    global DUNGEON_LEVELS
    global ENEMY_TYPES

    DUNGEON_LEVELS = load_dungeon_levels(document=dungeon_levels_document)
    DUNGEON_LEVEL_MIN = min(DUNGEON_LEVELS)
    DUNGEON_LEVEL_MAX = max(DUNGEON_LEVELS)
    ENEMY_TYPES = load_enemy_types(document=enemies_document)
    validate_enemy_definitions()


def _scaled_roll(
    rng: random.Random,
    enemy: dict[str, Any],
    prefix: str,
    scale: float,
    *,
    minimum: int = 1,
) -> int:
    value = rng.randint(int(enemy[f"{prefix}_min"]), int(enemy[f"{prefix}_max"]))
    return _scaled_value(value, scale, minimum=minimum)


def _scaled_value(value: int, scale: float, *, minimum: int = 1) -> int:
    return max(minimum, int(round(value * scale)))


def _required_str(entry: dict[str, Any], field: str) -> str:
    value = entry.get(field)
    if not isinstance(value, str) or not value.strip():
        raise EnemyContentError(f"Missing string field: {field}")
    return value.strip()


def _positive_int(entry: dict[str, Any], field: str) -> int:
    value = entry.get(field)
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise EnemyContentError(f"Missing positive integer field: {field}")
    return value


def _positive_number(entry: dict[str, Any], field: str) -> float:
    value = entry.get(field)
    if not isinstance(value, int | float) or isinstance(value, bool) or float(value) <= 0:
        raise EnemyContentError(f"Missing positive number field: {field}")
    return float(value)


DUNGEON_LEVELS = load_dungeon_levels()
DUNGEON_LEVEL_MIN = min(DUNGEON_LEVELS)
DUNGEON_LEVEL_MAX = max(DUNGEON_LEVELS)
ENEMY_TYPES = load_enemy_types()

validate_enemy_definitions()
