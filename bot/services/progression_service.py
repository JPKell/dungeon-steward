from __future__ import annotations

import math

from bot.config import (
    BASE_EXPLORE_COOLDOWN_MINUTES,
    BASE_PLAYER_HP,
    MIN_EXPLORE_COOLDOWN_MINUTES,
)
from bot.models import Player
from bot.services.progression_content import (
    PROGRESSION_CONTENT,
    ExploreLevelingProgression,
    ScalingProgression,
)

ALLOCATABLE_STATS = {"attack", "defense", "speed"}


def calculate_scaling_amount(step: int, scaling: ScalingProgression) -> float:
    step_offset = max(0, step - 1)
    if scaling.curve == "linear":
        value = scaling.base + (scaling.linear_growth * step_offset)
    elif scaling.curve == "quadratic":
        value = (
            scaling.base
            + (scaling.linear_growth * step_offset)
            + (scaling.quadratic_growth * step_offset * step_offset)
        )
    elif scaling.curve == "exponential":
        value = scaling.base * (scaling.exponential_growth**step_offset)
    else:
        raise ValueError(f"Unsupported scaling curve: {scaling.curve}")
    return max(scaling.minimum, value)


def calculate_scaled_int(step: int, scaling: ScalingProgression) -> int:
    return max(int(round(scaling.minimum)), int(round(calculate_scaling_amount(step, scaling))))


def get_explore_cooldown_minutes(explore_level: int) -> int:
    return max(
        MIN_EXPLORE_COOLDOWN_MINUTES,
        BASE_EXPLORE_COOLDOWN_MINUTES - max(0, explore_level - 1),
    )


def get_explore_xp_to_next_level(
    explore_level: int,
    leveling: ExploreLevelingProgression | None = None,
) -> int:
    leveling = leveling or PROGRESSION_CONTENT.exploration.leveling
    level_offset = max(0, explore_level - 1)
    if leveling.curve == "linear":
        required = leveling.base_xp + (leveling.linear_growth * level_offset)
    elif leveling.curve == "quadratic":
        required = (
            leveling.base_xp
            + (leveling.linear_growth * level_offset)
            + (leveling.quadratic_growth * level_offset * level_offset)
        )
    elif leveling.curve == "exponential":
        required = round(leveling.base_xp * (leveling.exponential_growth**level_offset))
    else:
        raise ValueError(f"Unsupported explore leveling curve: {leveling.curve}")
    return max(1, int(required))


def calculate_explore_level(
    experience: int,
    leveling: ExploreLevelingProgression | None = None,
) -> int:
    leveling = leveling or PROGRESSION_CONTENT.exploration.leveling
    remaining_xp = max(0, experience)
    level = 1
    while leveling.max_level <= 0 or level < leveling.max_level:
        xp_to_next = get_explore_xp_to_next_level(level, leveling)
        if remaining_xp < xp_to_next:
            break
        remaining_xp -= xp_to_next
        level += 1
    return level


def calculate_max_hp(
    combat_level: int,
    base_hp: int = BASE_PLAYER_HP,
) -> int:
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
    return calculate_scaled_int(
        combat_level - 1,
        PROGRESSION_CONTENT.combat_leveling.hp_per_level,
    )


def get_stat_points_for_combat_level(combat_level: int) -> int:
    if combat_level <= 1:
        return 0
    return calculate_scaled_int(
        combat_level - 1,
        PROGRESSION_CONTENT.combat_leveling.stat_points_per_level,
    )


def sync_combat_progression(player: Player) -> None:
    player.combat_level = max(1, player.combat_level)
    player.max_hp = max(player.max_hp, calculate_max_hp(player.combat_level))
    player.current_hp = min(max(1, player.current_hp), player.max_hp)
    player.combat_xp_to_next_level = get_combat_xp_to_next_level(player.combat_level)


def grant_combat_xp(player: Player, amount: int) -> tuple[int, int]:
    if amount <= 0:
        sync_combat_progression(player)
        return 0, 0

    sync_combat_progression(player)
    player.combat_xp += amount
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
    return min(
        PROGRESSION_CONTENT.defense.max_minutes,
        PROGRESSION_CONTENT.defense.base_minutes
        + sum(
            get_defense_minutes_gain_for_combat_level(next_level)
            for next_level in range(2, max(1, combat_level) + 1)
        ),
    )


def get_defense_minutes_gain_for_combat_level(combat_level: int) -> int:
    if combat_level <= 1:
        return 0
    return calculate_scaled_int(
        combat_level - 1,
        PROGRESSION_CONTENT.defense.minutes_per_level,
    )


def calculate_post_defeat_hp(max_hp: int) -> int:
    return max(1, math.ceil(max_hp * PROGRESSION_CONTENT.defense.post_defeat_hp_percent))


def get_exploration_gold_multiplier(explore_level: int) -> float:
    return calculate_scaling_amount(
        max(1, explore_level),
        PROGRESSION_CONTENT.exploration.reward_scaling.gold_multiplier,
    )


def get_exploration_xp_multiplier(explore_level: int) -> float:
    return calculate_scaling_amount(
        max(1, explore_level),
        PROGRESSION_CONTENT.exploration.reward_scaling.xp_multiplier,
    )


def scale_exploration_gold(amount: int, explore_level: int) -> int:
    if amount <= 0:
        return 0
    return max(0, int(round(amount * get_exploration_gold_multiplier(explore_level))))


def scale_exploration_xp(amount: int, explore_level: int) -> int:
    if amount <= 0:
        return 0
    return max(0, int(round(amount * get_exploration_xp_multiplier(explore_level))))


def get_shop_cost_multiplier(combat_level: int) -> float:
    return calculate_scaling_amount(
        max(1, combat_level),
        PROGRESSION_CONTENT.shop.cost_multiplier,
    )


def get_shop_stat_multiplier(combat_level: int) -> float:
    return calculate_scaling_amount(
        max(1, combat_level),
        PROGRESSION_CONTENT.shop.stat_multiplier,
    )


def scale_shop_item_cost(amount: int, combat_level: int) -> int:
    if amount <= 0:
        return 0
    return max(1, int(round(amount * get_shop_cost_multiplier(combat_level))))


def scale_shop_item_stat(amount: int, combat_level: int) -> int:
    if amount <= 0:
        return 0
    return max(0, int(round(amount * get_shop_stat_multiplier(combat_level))))


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


def allocate_stat_points(player: Player, stat: str, amount: int) -> None:
    if stat not in ALLOCATABLE_STATS:
        raise ValueError("Stat must be attack, defense, or speed")
    if amount <= 0:
        raise ValueError("Amount must be a positive integer")
    if amount > player.unspent_stat_points:
        raise ValueError("Not enough unspent stat points")
    setattr(player, stat, getattr(player, stat) + amount)
    player.unspent_stat_points -= amount
