from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from bot.models import Player
from bot.services.progression_content import (
    PROGRESSION_CONTENT,
    ExploreLevelingProgression,
    ScalingProgression,
)

ALLOCATABLE_STATS = {"attack", "defense", "speed"}
RARITIES = ("common", "uncommon", "rare", "epic", "legendary")


@dataclass(frozen=True)
class DungeonUnlockState:
    unlocked: bool
    missing: tuple[str, ...]


def calculate_scaling_amount(step: int, scaling: ScalingProgression) -> float:
    step_offset = max(0, step - 1)
    if scaling.curve == "linear":
        value = scaling.base + (scaling.linear_growth * step_offset)
    elif scaling.curve == "quadratic":
        value = scaling.base + (scaling.linear_growth * step_offset) + (scaling.quadratic_growth * step_offset * step_offset)
    elif scaling.curve == "exponential":
        value = scaling.base * (scaling.exponential_growth**step_offset)
    else:
        raise ValueError(f"Unsupported scaling curve: {scaling.curve}")
    value = max(scaling.minimum, value)
    if scaling.maximum is not None:
        value = min(scaling.maximum, value)
    return value


def calculate_scaled_int(step: int, scaling: ScalingProgression) -> int:
    return max(int(round(scaling.minimum)), int(round(calculate_scaling_amount(step, scaling))))


def get_explore_cooldown_minutes(explore_level: int) -> int:
    config = PROGRESSION_CONTENT.exploration
    reductions = max(0, max(1, explore_level) - 1) * config.cooldown_reduction_per_level
    return max(config.min_cooldown_minutes, config.base_cooldown_minutes - reductions)


def get_explore_cooldown_cap_level() -> int:
    return PROGRESSION_CONTENT.exploration.cooldown_cap_level


def get_explore_xp_to_next_level(
    explore_level: int,
    leveling: ExploreLevelingProgression | None = None,
) -> int:
    leveling = leveling or PROGRESSION_CONTENT.exploration.leveling
    level_offset = max(0, explore_level - 1)
    if leveling.curve == "linear":
        required = leveling.base_xp + (leveling.linear_growth * level_offset)
    elif leveling.curve == "quadratic":
        required = leveling.base_xp + (leveling.linear_growth * level_offset) + (leveling.quadratic_growth * level_offset * level_offset)
    elif leveling.curve == "exponential":
        required = leveling.base_xp * (leveling.exponential_growth**level_offset)
    else:
        raise ValueError(f"Unsupported explore leveling curve: {leveling.curve}")
    return max(1, int(round(required)))


def get_total_explore_xp_for_level(
    explore_level: int,
    leveling: ExploreLevelingProgression | None = None,
) -> int:
    """Return total lifetime XP required to begin explore_level."""
    leveling = leveling or PROGRESSION_CONTENT.exploration.leveling
    level = max(1, explore_level)
    return sum(get_explore_xp_to_next_level(current, leveling) for current in range(1, level))


def calculate_explore_level(
    experience: int,
    leveling: ExploreLevelingProgression | None = None,
) -> int:
    leveling = leveling or PROGRESSION_CONTENT.exploration.leveling
    remaining_xp = max(0, int(experience))
    level = 1
    while leveling.max_level <= 0 or level < leveling.max_level:
        xp_to_next = get_explore_xp_to_next_level(level, leveling)
        if remaining_xp < xp_to_next:
            break
        remaining_xp -= xp_to_next
        level += 1
    return level


def migrate_explore_progression(player: Player) -> bool:
    """Preserve a legitimate existing explore level when moving from flat 100-XP levels.

    The old total XP value is retained when already sufficient. If it would cause a
    level regression under the new curve, XP is raised only to the minimum required
    for the saved level. This is idempotent and never removes XP or levels.
    """
    saved_level = max(1, int(getattr(player, "explore_level", 1) or 1))
    saved_xp = max(0, int(getattr(player, "experience", 0) or 0))
    minimum_xp = get_total_explore_xp_for_level(saved_level)
    migrated_xp = max(saved_xp, minimum_xp)
    migrated_level = max(saved_level, calculate_explore_level(migrated_xp))
    changed = migrated_xp != saved_xp or migrated_level != saved_level
    player.experience = migrated_xp
    player.explore_level = migrated_level
    return changed


def calculate_max_hp(
    combat_level: int,
    base_hp: int | None = None,
) -> int:
    if base_hp is None:
        base_hp = PROGRESSION_CONTENT.new_player.base_hp
    level = max(1, combat_level)
    return base_hp + sum(get_hp_gain_for_combat_level(next_level) for next_level in range(2, level + 1))


def get_combat_xp_to_next_level(combat_level: int) -> int:
    return calculate_scaled_int(
        max(1, combat_level),
        PROGRESSION_CONTENT.combat_leveling.xp_to_next_level,
    )


def get_hp_gain_for_combat_level(combat_level: int) -> int:
    if combat_level <= 1:
        return 0
    config = PROGRESSION_CONTENT.combat_leveling
    gain = calculate_scaled_int(combat_level - 1, config.hp_per_level)
    if combat_level % config.hp_milestone_interval == 0:
        gain += config.hp_milestone_bonus
    return gain


def get_stat_points_for_combat_level(combat_level: int) -> int:
    if combat_level <= 1:
        return 0
    config = PROGRESSION_CONTENT.combat_leveling
    points = calculate_scaled_int(combat_level - 1, config.stat_points_per_level)
    if combat_level % config.stat_milestone_interval == 0:
        points += config.stat_milestone_bonus
    return points


def sync_combat_progression(player: Player) -> None:
    player.combat_level = max(1, int(player.combat_level or 1))
    calculated_max_hp = calculate_max_hp(player.combat_level)
    player.max_hp = max(int(player.max_hp or 0), calculated_max_hp)
    player.current_hp = min(max(1, int(player.current_hp or 1)), player.max_hp)
    player.combat_xp = max(0, int(player.combat_xp or 0))
    player.combat_xp_to_next_level = get_combat_xp_to_next_level(player.combat_level)
    player.unspent_stat_points = max(0, int(player.unspent_stat_points or 0))


def grant_combat_xp(player: Player, amount: int) -> tuple[int, int]:
    sync_combat_progression(player)
    if amount <= 0:
        return 0, 0

    player.combat_xp += int(amount)
    levels_gained = 0
    stat_points_gained = 0
    while player.combat_xp >= player.combat_xp_to_next_level:
        player.combat_xp -= player.combat_xp_to_next_level
        player.combat_level += 1
        levels_gained += 1
        earned_points = get_stat_points_for_combat_level(player.combat_level)
        stat_points_gained += earned_points
        player.unspent_stat_points += earned_points
        player.max_hp = calculate_max_hp(player.combat_level)
        player.combat_xp_to_next_level = get_combat_xp_to_next_level(player.combat_level)

    if levels_gained:
        player.current_hp = player.max_hp
    return levels_gained, stat_points_gained


def get_max_defense_minutes(combat_level: int) -> int:
    config = PROGRESSION_CONTENT.defense
    # Literal rule: level 1 = 60 minutes; every level after adds exactly one.
    minutes = config.base_minutes + max(0, int(combat_level) - 1)
    return min(config.max_minutes, minutes)


def get_defense_minutes_gain_for_combat_level(combat_level: int) -> int:
    if combat_level <= 1 or get_max_defense_minutes(combat_level - 1) >= PROGRESSION_CONTENT.defense.max_minutes:
        return 0
    return get_max_defense_minutes(combat_level) - get_max_defense_minutes(combat_level - 1)


def calculate_post_defeat_hp(max_hp: int) -> int:
    return max(1, math.ceil(max(1, max_hp) * PROGRESSION_CONTENT.defense.post_defeat_hp_percent))


def get_exploration_gold_multiplier(explore_level: int) -> float:
    config = PROGRESSION_CONTENT.exploration
    capped_level = min(max(1, explore_level), config.cooldown_cap_level)
    multiplier = calculate_scaling_amount(
        capped_level,
        config.reward_scaling.gold_multiplier,
    )
    post_cap_levels = max(0, explore_level - config.cooldown_cap_level)
    return multiplier * (1.0 + post_cap_levels * config.reward_scaling.post_cap_gold_growth)


def get_exploration_xp_multiplier(explore_level: int) -> float:
    capped_level = min(
        max(1, explore_level),
        PROGRESSION_CONTENT.exploration.cooldown_cap_level,
    )
    return calculate_scaling_amount(
        capped_level,
        PROGRESSION_CONTENT.exploration.reward_scaling.xp_multiplier,
    )


def get_dungeon_exploration_multiplier(dungeon_level: int, *, reward: str) -> float:
    level_offset = max(0, min(20, dungeon_level) - 1)
    reward_config = PROGRESSION_CONTENT.exploration.reward_scaling
    growth = reward_config.dungeon_gold_growth if reward == "gold" else reward_config.dungeon_xp_growth
    return 1.0 + (growth * level_offset)


def get_exploration_reward_multiplier(
    *,
    explore_level: int,
    dungeon_level: int = 1,
    rarity: str = "common",
    successful: bool = True,
    power_ratio: float = 1.0,
    reward: str,
) -> float:
    if reward not in {"gold", "xp"}:
        raise ValueError("reward must be gold or xp")
    rarity = rarity if rarity in RARITIES else "common"
    config = PROGRESSION_CONTENT.exploration.reward_scaling
    level_multiplier = get_exploration_gold_multiplier(explore_level) if reward == "gold" else get_exploration_xp_multiplier(explore_level)
    dungeon_multiplier = get_dungeon_exploration_multiplier(dungeon_level, reward=reward)
    rarity_multiplier = config.rarity_gold_multipliers[rarity] if reward == "gold" else config.rarity_xp_multipliers[rarity]

    # Entering content well above current power still raises rewards, but not at the
    # full nominal rate. This avoids making reckless highest-floor farming optimal.
    safe_ratio = max(0.05, float(power_ratio))
    power_multiplier = min(1.0, max(config.underpowered_reward_floor, safe_ratio))
    if safe_ratio > 1.0:
        power_multiplier = min(1.12, 1.0 + ((safe_ratio - 1.0) * 0.08))

    outcome_multiplier = 1.0
    if not successful:
        if reward == "gold":
            outcome_multiplier += config.risk_gold_bonus
        else:
            outcome_multiplier *= config.failure_xp_multiplier

    return level_multiplier * dungeon_multiplier * rarity_multiplier * power_multiplier * outcome_multiplier


def scale_exploration_gold(
    amount: int,
    explore_level: int,
    *,
    dungeon_level: int = 1,
    rarity: str = "common",
    successful: bool = True,
    power_ratio: float = 1.0,
) -> int:
    if amount <= 0:
        return 0
    multiplier = get_exploration_reward_multiplier(
        explore_level=explore_level,
        dungeon_level=dungeon_level,
        rarity=rarity,
        successful=successful,
        power_ratio=power_ratio,
        reward="gold",
    )
    return max(0, int(round(amount * multiplier)))


def scale_exploration_xp(
    amount: int,
    explore_level: int,
    *,
    dungeon_level: int = 1,
    rarity: str = "common",
    successful: bool = True,
    power_ratio: float = 1.0,
) -> int:
    if amount <= 0:
        return 0
    multiplier = get_exploration_reward_multiplier(
        explore_level=explore_level,
        dungeon_level=dungeon_level,
        rarity=rarity,
        successful=successful,
        power_ratio=power_ratio,
        reward="xp",
    )
    return max(0, int(round(amount * multiplier)))


def calculate_combat_power(*, max_hp: int, attack: int, defense: int, speed: int) -> float:
    return max(1, max_hp) * 0.12 + max(0, attack) * 2.0 + max(0, defense) * 2.25 + max(0, speed) * 1.25


def get_combat_xp_power_multiplier(*, player_power: float, enemy_power: float) -> float:
    config = PROGRESSION_CONTENT.enemy_generation
    player_power = max(1.0, player_power)
    enemy_power = max(1.0, enemy_power)
    ratio = enemy_power / player_power
    if ratio < config.trivial_enemy_ratio:
        return config.trivial_enemy_xp_multiplier
    # Smoothly rewards near-tier and difficult enemies while capping power-level exploits.
    multiplier = 0.55 + (ratio * 0.55)
    return min(config.power_xp_ceiling, max(config.power_xp_floor, multiplier))


def scale_combat_xp_for_power(
    amount: int,
    *,
    player_power: float,
    enemy_power: float,
) -> int:
    if amount <= 0:
        return 0
    return max(
        1,
        int(
            round(
                amount
                * get_combat_xp_power_multiplier(
                    player_power=player_power,
                    enemy_power=enemy_power,
                )
            )
        ),
    )


def get_combat_gold_power_multiplier(*, player_power: float, enemy_power: float) -> float:
    config = PROGRESSION_CONTENT.enemy_generation
    ratio = max(0.01, enemy_power) / max(1.0, player_power)
    if ratio < config.trivial_enemy_ratio:
        return config.trivial_enemy_gold_multiplier
    return min(1.1, max(config.trivial_enemy_gold_multiplier, 0.55 + ratio * 0.45))


def scale_combat_gold_for_power(
    amount: int,
    *,
    player_power: float,
    enemy_power: float,
) -> int:
    if amount <= 0:
        return 0
    return max(
        0,
        int(
            round(
                amount
                * get_combat_gold_power_multiplier(
                    player_power=player_power,
                    enemy_power=enemy_power,
                )
            )
        ),
    )


def get_shop_cost_multiplier(combat_level: int) -> float:
    return calculate_scaling_amount(max(1, combat_level), PROGRESSION_CONTENT.shop.cost_multiplier)


def get_shop_stat_multiplier(combat_level: int) -> float:
    return calculate_scaling_amount(max(1, combat_level), PROGRESSION_CONTENT.shop.stat_multiplier)


def scale_shop_item_cost(amount: int, combat_level: int) -> int:
    if amount <= 0:
        return 0
    return max(1, int(round(amount * get_shop_cost_multiplier(combat_level))))


def scale_shop_item_stat(amount: int, combat_level: int) -> int:
    if amount <= 0:
        return 0
    return max(0, int(round(amount * get_shop_stat_multiplier(combat_level))))


def get_shop_rarity_weights(shop_level: int) -> dict[str, int]:
    selected = PROGRESSION_CONTENT.shop.rarity_bands[0]
    for band in PROGRESSION_CONTENT.shop.rarity_bands:
        if shop_level >= band.min_level:
            selected = band
        else:
            break
    return dict(selected.weights)


def get_shop_rarity_percentages(shop_level: int) -> dict[str, float]:
    weights = get_shop_rarity_weights(shop_level)
    total = sum(weights.values())
    return {rarity: (weights[rarity] / total) * 100.0 for rarity in RARITIES}


def calculate_enemy_level_stat_multiplier(enemy_level: int) -> float:
    return 1 + ((max(1, enemy_level) - 1) * PROGRESSION_CONTENT.enemy_generation.level_stat_scale)


def calculate_enemy_level_reward_multiplier(enemy_level: int) -> float:
    return 1 + ((max(1, enemy_level) - 1) * PROGRESSION_CONTENT.enemy_generation.level_reward_scale)


def calculate_enemy_stat_scale(
    *,
    dungeon_stat_modifier: float,
    enemy_stage_modifier: float,
    enemy_level: int,
) -> float:
    return dungeon_stat_modifier * enemy_stage_modifier * calculate_enemy_level_stat_multiplier(enemy_level)


def calculate_enemy_reward_scale(
    *,
    dungeon_reward_modifier: float,
    enemy_level: int,
) -> float:
    return dungeon_reward_modifier * calculate_enemy_level_reward_multiplier(enemy_level)


def calculate_equipment_power(item: Mapping[str, Any] | Any) -> float:
    def value(stat: str) -> int:
        if isinstance(item, Mapping):
            raw = item.get(stat, 0)
        else:
            raw = getattr(item, stat, 0)
        return max(0, int(raw or 0))

    return value("hp") * 0.12 + value("attack") * 2.0 + value("defense") * 2.25 + value("speed") * 1.25


def evaluate_dungeon_unlock(
    requirements: Mapping[str, Any],
    *,
    explore_level: int,
    combat_level: int,
    equipment_power: float,
    discoveries: int,
    defense_wins: int,
    previous_dungeon_completed: bool,
) -> DungeonUnlockState:
    missing: list[str] = []
    checks = (
        (explore_level, int(requirements.get("required_explore_level", 1)), "explore level"),
        (combat_level, int(requirements.get("required_combat_level", 1)), "combat level"),
        (equipment_power, float(requirements.get("required_equipment_power", 0)), "equipment power"),
        (discoveries, int(requirements.get("required_discoveries", 0)), "discoveries"),
        (defense_wins, int(requirements.get("required_defense_wins", 0)), "defense wins"),
    )
    for actual, required, label in checks:
        if actual < required:
            missing.append(f"{label}: {actual:g}/{required:g}")
    if bool(requirements.get("requires_previous_completion", False)) and not previous_dungeon_completed:
        missing.append("complete the preceding dungeon")
    return DungeonUnlockState(unlocked=not missing, missing=tuple(missing))


def allocate_stat_points(player: Player, stat: str, amount: int) -> None:
    if stat not in ALLOCATABLE_STATS:
        raise ValueError("Stat must be attack, defense, or speed")
    if not isinstance(amount, int) or amount <= 0:
        raise ValueError("Amount must be a positive integer")
    if amount > player.unspent_stat_points:
        raise ValueError("Not enough unspent stat points")
    current_value = max(0, int(getattr(player, stat)))
    setattr(player, stat, current_value + amount)
    player.unspent_stat_points -= amount
