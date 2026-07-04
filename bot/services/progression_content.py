from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ProgressionContentError(ValueError):
    pass


@dataclass(frozen=True)
class ExploreLevelingProgression:
    curve: str
    base_xp: int
    linear_growth: int
    quadratic_growth: int
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


@dataclass(frozen=True)
class ExplorationRewardScaling:
    gold_multiplier: ScalingProgression
    xp_multiplier: ScalingProgression


@dataclass(frozen=True)
class ExplorationProgression:
    base_cooldown_minutes: int
    min_cooldown_minutes: int
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


@dataclass(frozen=True)
class DefenseProgression:
    base_minutes: int
    max_minutes: int
    minutes_per_level: ScalingProgression
    post_defeat_hp_percent: float
    minimum_damage: int
    max_battle_rounds: int


@dataclass(frozen=True)
class EnemyGenerationProgression:
    level_stat_scale: float
    level_reward_scale: float


@dataclass(frozen=True)
class ShopProgression:
    stock_size: int
    cost_multiplier: ScalingProgression
    stat_multiplier: ScalingProgression
    rarity_weights: dict[str, int]


@dataclass(frozen=True)
class ProgressionContent:
    exploration: ExplorationProgression
    new_player: NewPlayerProgression
    combat_leveling: CombatLevelingProgression
    defense: DefenseProgression
    enemy_generation: EnemyGenerationProgression
    shop: ShopProgression


def load_progression_content(path: Path | None = None) -> ProgressionContent:
    content_path = path or Path(__file__).parents[1] / "content" / "progression.json"
    raw = json.loads(content_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ProgressionContentError("Progression content must be an object")

    exploration = _required_dict(raw, "exploration")
    new_player = _required_dict(raw, "new_player")
    combat = _required_dict(raw, "combat_leveling")
    defense = _required_dict(raw, "defense")
    enemy = _required_dict(raw, "enemy_generation")
    shop = _required_dict(raw, "shop")

    content = ProgressionContent(
        exploration=ExplorationProgression(
            base_cooldown_minutes=_positive_int(exploration, "base_cooldown_minutes"),
            min_cooldown_minutes=_positive_int(exploration, "min_cooldown_minutes"),
            leveling=_explore_leveling(_required_dict(exploration, "leveling")),
            reward_scaling=_exploration_reward_scaling(_required_dict(exploration, "reward_scaling")),
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
                _required_dict(combat, "stat_points_per_level"),
                minimum_can_be_zero=False,
            ),
        ),
        defense=DefenseProgression(
            base_minutes=_positive_int(defense, "base_minutes"),
            max_minutes=_positive_int(defense, "max_minutes"),
            minutes_per_level=_scaling(_required_dict(defense, "minutes_per_level"), minimum_can_be_zero=True),
            post_defeat_hp_percent=_ratio(defense, "post_defeat_hp_percent"),
            minimum_damage=_positive_int(defense, "minimum_damage"),
            max_battle_rounds=_positive_int(defense, "max_battle_rounds"),
        ),
        enemy_generation=EnemyGenerationProgression(
            level_stat_scale=_non_negative_float(enemy, "level_stat_scale"),
            level_reward_scale=_non_negative_float(enemy, "level_reward_scale"),
        ),
        shop=ShopProgression(
            stock_size=_positive_int(shop, "stock_size"),
            cost_multiplier=_scaling(_required_dict(shop, "cost_multiplier"), minimum_can_be_zero=False),
            stat_multiplier=_scaling(_required_dict(shop, "stat_multiplier"), minimum_can_be_zero=True),
            rarity_weights=_rarity_weights(shop),
        ),
    )
    if content.exploration.min_cooldown_minutes > content.exploration.base_cooldown_minutes:
        raise ProgressionContentError("Minimum exploration cooldown cannot exceed base cooldown")
    if content.defense.base_minutes > content.defense.max_minutes:
        raise ProgressionContentError("Base defense duration cannot exceed max defense duration")
    return content


def _required_dict(raw: dict[str, Any], field: str) -> dict[str, Any]:
    value = raw.get(field)
    if not isinstance(value, dict):
        raise ProgressionContentError(f"Progression content missing object: {field}")
    return value


def _positive_int(raw: dict[str, Any], field: str) -> int:
    value = raw.get(field)
    if not isinstance(value, int) or value <= 0:
        raise ProgressionContentError(f"Progression field must be a positive integer: {field}")
    return value


def _non_negative_int(raw: dict[str, Any], field: str) -> int:
    value = raw.get(field)
    if not isinstance(value, int) or value < 0:
        raise ProgressionContentError(f"Progression field must be a non-negative integer: {field}")
    return value


def _ratio(raw: dict[str, Any], field: str) -> float:
    value = raw.get(field)
    if not isinstance(value, int | float) or not 0 < float(value) <= 1:
        raise ProgressionContentError(f"Progression field must be a ratio between 0 and 1: {field}")
    return float(value)


def _non_negative_float(raw: dict[str, Any], field: str) -> float:
    value = raw.get(field)
    if not isinstance(value, int | float) or float(value) < 0:
        raise ProgressionContentError(f"Progression field must be a non-negative number: {field}")
    return float(value)


def _explore_leveling(raw: dict[str, Any]) -> ExploreLevelingProgression:
    curve = raw.get("curve")
    if curve not in {"linear", "quadratic", "exponential"}:
        raise ProgressionContentError("Explore leveling curve must be linear, quadratic, or exponential")
    exponential_growth = _positive_float(raw, "exponential_growth")
    if curve == "exponential" and exponential_growth <= 1:
        raise ProgressionContentError("Exponential explore leveling requires exponential_growth above 1")
    return ExploreLevelingProgression(
        curve=curve,
        base_xp=_positive_int(raw, "base_xp"),
        linear_growth=_non_negative_int(raw, "linear_growth"),
        quadratic_growth=_non_negative_int(raw, "quadratic_growth"),
        exponential_growth=exponential_growth,
        max_level=_non_negative_int(raw, "max_level"),
    )


def _exploration_reward_scaling(raw: dict[str, Any]) -> ExplorationRewardScaling:
    return ExplorationRewardScaling(
        gold_multiplier=_scaling(_required_dict(raw, "gold_multiplier"), minimum_can_be_zero=True),
        xp_multiplier=_scaling(_required_dict(raw, "xp_multiplier"), minimum_can_be_zero=True),
    )


def _scaling(raw: dict[str, Any], *, minimum_can_be_zero: bool) -> ScalingProgression:
    curve = raw.get("curve")
    if curve not in {"linear", "quadratic", "exponential"}:
        raise ProgressionContentError("Scaling curve must be linear, quadratic, or exponential")
    exponential_growth = _positive_float(raw, "exponential_growth")
    if curve == "exponential" and exponential_growth <= 0:
        raise ProgressionContentError("Exponential scaling requires positive exponential_growth")
    minimum = _non_negative_float(raw, "minimum") if minimum_can_be_zero else _positive_float(raw, "minimum")
    return ScalingProgression(
        curve=curve,
        base=_positive_float(raw, "base"),
        linear_growth=_non_negative_float(raw, "linear_growth"),
        quadratic_growth=_non_negative_float(raw, "quadratic_growth"),
        exponential_growth=exponential_growth,
        minimum=minimum,
    )


def _positive_float(raw: dict[str, Any], field: str) -> float:
    value = raw.get(field)
    if not isinstance(value, int | float) or float(value) <= 0:
        raise ProgressionContentError(f"Progression field must be a positive number: {field}")
    return float(value)


def _rarity_weights(raw: dict[str, Any]) -> dict[str, int]:
    value = raw.get("rarity_weights")
    if not isinstance(value, dict):
        raise ProgressionContentError("Shop rarity_weights must be an object")
    weights: dict[str, int] = {}
    for rarity in ("common", "uncommon", "rare", "epic", "legendary"):
        weight = value.get(rarity)
        if not isinstance(weight, int) or weight <= 0:
            raise ProgressionContentError(f"Missing positive shop rarity weight: {rarity}")
        weights[rarity] = weight
    return weights


PROGRESSION_CONTENT = load_progression_content()
