from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ProgressionContentError(ValueError):
    """Raised when progression.json is missing required or valid values."""


@dataclass(frozen=True)
class ExploreLevelingProgression:
    curve: str
    base_xp: float
    linear_growth: float
    quadratic_growth: float
    exponential_growth: float
    max_level: int


@dataclass(frozen=True)
class ScalingProgression:
    curve: str
    base: float
    linear_growth: float
    quadratic_growth: float
    exponential_growth: float
    minimum: float
    maximum: float | None = None


@dataclass(frozen=True)
class ExplorationRewardScaling:
    gold_multiplier: ScalingProgression
    xp_multiplier: ScalingProgression
    dungeon_gold_growth: float
    dungeon_xp_growth: float
    post_cap_gold_growth: float
    underpowered_reward_floor: float
    risk_gold_bonus: float
    failure_xp_multiplier: float
    rarity_gold_multipliers: dict[str, float]
    rarity_xp_multipliers: dict[str, float]


@dataclass(frozen=True)
class ExplorationProgression:
    base_cooldown_minutes: int
    min_cooldown_minutes: int
    cooldown_reduction_per_level: int
    cooldown_cap_level: int
    leveling: ExploreLevelingProgression
    reward_scaling: ExplorationRewardScaling


@dataclass(frozen=True)
class NewPlayerProgression:
    base_hp: int
    attack: int
    defense: int
    speed: int


@dataclass(frozen=True)
class CombatLevelingProgression:
    xp_to_next_level: ScalingProgression
    hp_per_level: ScalingProgression
    stat_points_per_level: ScalingProgression
    hp_milestone_interval: int
    hp_milestone_bonus: int
    stat_milestone_interval: int
    stat_milestone_bonus: int


@dataclass(frozen=True)
class DefenseProgression:
    base_minutes: int
    max_minutes: int
    minutes_per_level: ScalingProgression
    duration_cap_level: int
    restore_full_hp_on_start: bool
    post_defeat_hp_percent: float
    minimum_damage: int
    max_battle_rounds: int
    maximum_elapsed_days: int


@dataclass(frozen=True)
class EnemyGenerationProgression:
    level_stat_scale: float
    level_reward_scale: float
    combat_gold_multiplier: float
    power_xp_floor: float
    power_xp_ceiling: float
    trivial_enemy_ratio: float
    trivial_enemy_xp_multiplier: float
    trivial_enemy_gold_multiplier: float


@dataclass(frozen=True)
class ShopRarityBand:
    min_level: int
    weights: dict[str, int]


@dataclass(frozen=True)
class ShopProgression:
    stock_size: int
    cost_multiplier: ScalingProgression
    stat_multiplier: ScalingProgression
    rarity_weights: dict[str, int]
    rarity_bands: tuple[ShopRarityBand, ...]


@dataclass(frozen=True)
class ProgressionContent:
    schema_version: int
    exploration: ExplorationProgression
    new_player: NewPlayerProgression
    combat_leveling: CombatLevelingProgression
    defense: DefenseProgression
    enemy_generation: EnemyGenerationProgression
    shop: ShopProgression


RARITIES = ("common", "uncommon", "rare", "epic", "legendary")


def load_progression_content(
    path: Path | None = None,
    *,
    document: dict[str, Any] | None = None,
) -> ProgressionContent:
    if document is None:
        content_path = path or _default_content_path("progression.json")
        raw = json.loads(content_path.read_text(encoding="utf-8"))
    else:
        raw = document
    if not isinstance(raw, dict):
        raise ProgressionContentError("Progression content must be an object")

    exploration = _required_dict(raw, "exploration")
    new_player = _required_dict(raw, "new_player")
    combat = _required_dict(raw, "combat_leveling")
    defense = _required_dict(raw, "defense")
    enemy = _required_dict(raw, "enemy_generation")
    shop = _required_dict(raw, "shop")

    base_cooldown = _positive_int(exploration, "base_cooldown_minutes")
    min_cooldown = _positive_int(exploration, "min_cooldown_minutes")
    reduction = _positive_int_default(exploration, "cooldown_reduction_per_level", 1)
    cap_level = _positive_int_default(
        exploration,
        "cooldown_cap_level",
        1 + ((base_cooldown - min_cooldown + reduction - 1) // reduction),
    )

    reward_raw = _required_dict(exploration, "reward_scaling")
    content = ProgressionContent(
        schema_version=_positive_int_default(raw, "schema_version", 1),
        exploration=ExplorationProgression(
            base_cooldown_minutes=base_cooldown,
            min_cooldown_minutes=min_cooldown,
            cooldown_reduction_per_level=reduction,
            cooldown_cap_level=cap_level,
            leveling=_explore_leveling(_required_dict(exploration, "leveling")),
            reward_scaling=ExplorationRewardScaling(
                gold_multiplier=_scaling(_required_dict(reward_raw, "gold_multiplier"), minimum_can_be_zero=True),
                xp_multiplier=_scaling(_required_dict(reward_raw, "xp_multiplier"), minimum_can_be_zero=True),
                dungeon_gold_growth=_non_negative_float_default(reward_raw, "dungeon_gold_growth", 0.04),
                dungeon_xp_growth=_non_negative_float_default(reward_raw, "dungeon_xp_growth", 0.025),
                post_cap_gold_growth=_non_negative_float_default(reward_raw, "post_cap_gold_growth", 0.004),
                underpowered_reward_floor=_ratio_inclusive_default(
                    reward_raw, "underpowered_reward_floor", 0.55
                ),
                risk_gold_bonus=_non_negative_float_default(reward_raw, "risk_gold_bonus", 0.15),
                failure_xp_multiplier=_ratio_inclusive_default(
                    reward_raw, "failure_xp_multiplier", 0.8
                ),
                rarity_gold_multipliers=_rarity_multipliers(
                    reward_raw, "rarity_gold_multipliers"
                ),
                rarity_xp_multipliers=_rarity_multipliers(
                    reward_raw, "rarity_xp_multipliers"
                ),
            ),
        ),
        new_player=NewPlayerProgression(
            base_hp=_positive_int(new_player, "base_hp"),
            attack=_positive_int(new_player, "attack"),
            defense=_positive_int(new_player, "defense"),
            speed=_positive_int(new_player, "speed"),
        ),
        combat_leveling=CombatLevelingProgression(
            xp_to_next_level=_scaling(_required_dict(combat, "xp_to_next_level"), minimum_can_be_zero=False),
            hp_per_level=_scaling(_required_dict(combat, "hp_per_level"), minimum_can_be_zero=False),
            stat_points_per_level=_scaling(
                _required_dict(combat, "stat_points_per_level"), minimum_can_be_zero=False
            ),
            hp_milestone_interval=_positive_int_default(combat, "hp_milestone_interval", 25),
            hp_milestone_bonus=_non_negative_int_default(combat, "hp_milestone_bonus", 5),
            stat_milestone_interval=_positive_int_default(combat, "stat_milestone_interval", 20),
            stat_milestone_bonus=_non_negative_int_default(combat, "stat_milestone_bonus", 1),
        ),
        defense=DefenseProgression(
            base_minutes=_positive_int(defense, "base_minutes"),
            max_minutes=_positive_int(defense, "max_minutes"),
            minutes_per_level=_scaling(
                _required_dict(defense, "minutes_per_level"), minimum_can_be_zero=True
            ),
            duration_cap_level=_positive_int_default(defense, "duration_cap_level", 421),
            restore_full_hp_on_start=_bool_default(defense, "restore_full_hp_on_start", True),
            post_defeat_hp_percent=_ratio(defense, "post_defeat_hp_percent"),
            minimum_damage=_positive_int(defense, "minimum_damage"),
            max_battle_rounds=_positive_int(defense, "max_battle_rounds"),
            maximum_elapsed_days=_positive_int_default(defense, "maximum_elapsed_days", 30),
        ),
        enemy_generation=EnemyGenerationProgression(
            level_stat_scale=_non_negative_float(enemy, "level_stat_scale"),
            level_reward_scale=_non_negative_float(enemy, "level_reward_scale"),
            combat_gold_multiplier=_positive_float_default(enemy, "combat_gold_multiplier", 1.0),
            power_xp_floor=_positive_float_default(enemy, "power_xp_floor", 0.2),
            power_xp_ceiling=_positive_float_default(enemy, "power_xp_ceiling", 1.35),
            trivial_enemy_ratio=_positive_float_default(enemy, "trivial_enemy_ratio", 0.55),
            trivial_enemy_xp_multiplier=_ratio_inclusive_default(
                enemy, "trivial_enemy_xp_multiplier", 0.25
            ),
            trivial_enemy_gold_multiplier=_ratio_inclusive_default(
                enemy, "trivial_enemy_gold_multiplier", 0.35
            ),
        ),
        shop=ShopProgression(
            stock_size=_positive_int(shop, "stock_size"),
            cost_multiplier=_scaling(_required_dict(shop, "cost_multiplier"), minimum_can_be_zero=False),
            stat_multiplier=_scaling(_required_dict(shop, "stat_multiplier"), minimum_can_be_zero=True),
            rarity_weights=_rarity_weights(shop),
            rarity_bands=_rarity_bands(shop),
        ),
    )

    if content.exploration.min_cooldown_minutes > content.exploration.base_cooldown_minutes:
        raise ProgressionContentError("Minimum exploration cooldown cannot exceed base cooldown")
    expected_cap = 1 + (
        (content.exploration.base_cooldown_minutes - content.exploration.min_cooldown_minutes)
        // content.exploration.cooldown_reduction_per_level
    )
    if content.exploration.cooldown_cap_level < expected_cap:
        raise ProgressionContentError("Configured cooldown cap level is earlier than the cooldown formula permits")
    if content.defense.base_minutes > content.defense.max_minutes:
        raise ProgressionContentError("Base defense duration cannot exceed max defense duration")
    literal_cap_level = 1 + (content.defense.max_minutes - content.defense.base_minutes)
    if content.defense.duration_cap_level != literal_cap_level:
        raise ProgressionContentError(
            "duration_cap_level must preserve the literal one-minute-per-level rule"
        )
    return content


def refresh_progression_content(document: dict[str, Any]) -> ProgressionContent:
    global PROGRESSION_CONTENT
    PROGRESSION_CONTENT = load_progression_content(document=document)
    return PROGRESSION_CONTENT


def _default_content_path(filename: str) -> Path:
    project_path = Path(__file__).parents[1] / "content" / filename
    if project_path.exists():
        return project_path
    return Path(__file__).with_name(filename)


def _required_dict(raw: dict[str, Any], field: str) -> dict[str, Any]:
    value = raw.get(field)
    if not isinstance(value, dict):
        raise ProgressionContentError(f"Progression content missing object: {field}")
    return value


def _positive_int(raw: dict[str, Any], field: str) -> int:
    value = raw.get(field)
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ProgressionContentError(f"Progression field must be a positive integer: {field}")
    return value


def _positive_int_default(raw: dict[str, Any], field: str, default: int) -> int:
    if field not in raw:
        return default
    return _positive_int(raw, field)


def _non_negative_int_default(raw: dict[str, Any], field: str, default: int) -> int:
    value = raw.get(field, default)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ProgressionContentError(f"Progression field must be a non-negative integer: {field}")
    return value


def _positive_float(raw: dict[str, Any], field: str) -> float:
    value = raw.get(field)
    if not isinstance(value, int | float) or isinstance(value, bool) or float(value) <= 0:
        raise ProgressionContentError(f"Progression field must be a positive number: {field}")
    return float(value)


def _positive_float_default(raw: dict[str, Any], field: str, default: float) -> float:
    if field not in raw:
        return default
    return _positive_float(raw, field)


def _non_negative_float(raw: dict[str, Any], field: str) -> float:
    value = raw.get(field)
    if not isinstance(value, int | float) or isinstance(value, bool) or float(value) < 0:
        raise ProgressionContentError(f"Progression field must be a non-negative number: {field}")
    return float(value)


def _non_negative_float_default(raw: dict[str, Any], field: str, default: float) -> float:
    if field not in raw:
        return default
    return _non_negative_float(raw, field)


def _ratio(raw: dict[str, Any], field: str) -> float:
    value = raw.get(field)
    if not isinstance(value, int | float) or isinstance(value, bool) or not 0 < float(value) <= 1:
        raise ProgressionContentError(f"Progression field must be a ratio above 0 and at most 1: {field}")
    return float(value)


def _ratio_inclusive_default(raw: dict[str, Any], field: str, default: float) -> float:
    value = raw.get(field, default)
    if not isinstance(value, int | float) or isinstance(value, bool) or not 0 <= float(value) <= 1.5:
        raise ProgressionContentError(f"Progression field must be between 0 and 1.5: {field}")
    return float(value)


def _bool_default(raw: dict[str, Any], field: str, default: bool) -> bool:
    value = raw.get(field, default)
    if not isinstance(value, bool):
        raise ProgressionContentError(f"Progression field must be boolean: {field}")
    return value


def _explore_leveling(raw: dict[str, Any]) -> ExploreLevelingProgression:
    curve = raw.get("curve")
    if curve not in {"linear", "quadratic", "exponential"}:
        raise ProgressionContentError("Explore leveling curve must be linear, quadratic, or exponential")
    exponential_growth = _positive_float(raw, "exponential_growth")
    if curve == "exponential" and exponential_growth <= 1:
        raise ProgressionContentError("Exponential explore leveling requires exponential_growth above 1")
    return ExploreLevelingProgression(
        curve=curve,
        base_xp=_positive_float(raw, "base_xp"),
        linear_growth=_non_negative_float(raw, "linear_growth"),
        quadratic_growth=_non_negative_float(raw, "quadratic_growth"),
        exponential_growth=exponential_growth,
        max_level=_non_negative_int_default(raw, "max_level", 0),
    )


def _scaling(raw: dict[str, Any], *, minimum_can_be_zero: bool) -> ScalingProgression:
    curve = raw.get("curve")
    if curve not in {"linear", "quadratic", "exponential"}:
        raise ProgressionContentError("Scaling curve must be linear, quadratic, or exponential")
    exponential_growth = _positive_float(raw, "exponential_growth")
    minimum = (
        _non_negative_float(raw, "minimum")
        if minimum_can_be_zero
        else _positive_float(raw, "minimum")
    )
    maximum_raw = raw.get("maximum")
    maximum = None
    if maximum_raw is not None:
        if not isinstance(maximum_raw, int | float) or isinstance(maximum_raw, bool):
            raise ProgressionContentError("Scaling maximum must be numeric")
        maximum = float(maximum_raw)
        if maximum < minimum:
            raise ProgressionContentError("Scaling maximum cannot be below minimum")
    return ScalingProgression(
        curve=curve,
        base=_positive_float(raw, "base"),
        linear_growth=_non_negative_float(raw, "linear_growth"),
        quadratic_growth=_non_negative_float(raw, "quadratic_growth"),
        exponential_growth=exponential_growth,
        minimum=minimum,
        maximum=maximum,
    )


def _rarity_weights(raw: dict[str, Any]) -> dict[str, int]:
    value = raw.get("rarity_weights")
    if not isinstance(value, dict):
        raise ProgressionContentError("Shop rarity_weights must be an object")
    weights: dict[str, int] = {}
    for rarity in RARITIES:
        weight = value.get(rarity)
        if not isinstance(weight, int) or isinstance(weight, bool) or weight <= 0:
            raise ProgressionContentError(f"Missing positive shop rarity weight: {rarity}")
        weights[rarity] = weight
    return weights


def _rarity_multipliers(raw: dict[str, Any], field: str) -> dict[str, float]:
    defaults = {
        "common": 1.0,
        "uncommon": 1.08,
        "rare": 1.18,
        "epic": 1.32,
        "legendary": 1.5,
    }
    value = raw.get(field, defaults)
    if not isinstance(value, dict):
        raise ProgressionContentError(f"{field} must be an object")
    result: dict[str, float] = {}
    for rarity in RARITIES:
        multiplier = value.get(rarity)
        if not isinstance(multiplier, int | float) or isinstance(multiplier, bool) or multiplier <= 0:
            raise ProgressionContentError(f"Missing positive multiplier for {rarity} in {field}")
        result[rarity] = float(multiplier)
    return result


def _rarity_bands(raw: dict[str, Any]) -> tuple[ShopRarityBand, ...]:
    value = raw.get("rarity_bands")
    if value is None:
        return (ShopRarityBand(min_level=1, weights=_rarity_weights(raw)),)
    if not isinstance(value, list) or not value:
        raise ProgressionContentError("Shop rarity_bands must be a non-empty list")
    bands: list[ShopRarityBand] = []
    seen_levels: set[int] = set()
    for entry in value:
        if not isinstance(entry, dict):
            raise ProgressionContentError("Shop rarity band entries must be objects")
        min_level = _positive_int(entry, "min_level")
        if min_level in seen_levels:
            raise ProgressionContentError(f"Duplicate rarity band level: {min_level}")
        seen_levels.add(min_level)
        weights_raw = entry.get("weights")
        if not isinstance(weights_raw, dict):
            raise ProgressionContentError("Shop rarity band weights must be objects")
        weights: dict[str, int] = {}
        for rarity in RARITIES:
            weight = weights_raw.get(rarity)
            if not isinstance(weight, int) or isinstance(weight, bool) or weight <= 0:
                raise ProgressionContentError(
                    f"Missing positive rarity weight for {rarity} at level {min_level}"
                )
            weights[rarity] = weight
        bands.append(ShopRarityBand(min_level=min_level, weights=weights))
    bands.sort(key=lambda band: band.min_level)
    if bands[0].min_level != 1:
        raise ProgressionContentError("The first shop rarity band must begin at level 1")
    return tuple(bands)


PROGRESSION_CONTENT = load_progression_content()
