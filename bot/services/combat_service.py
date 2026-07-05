from __future__ import annotations

import random
from dataclasses import dataclass

from bot.services.enemy_service import GeneratedEnemy
from bot.services.equipment_service import CombatStats
from bot.services.progression_content import PROGRESSION_CONTENT
from bot.services.progression_service import (
    calculate_combat_power,
    scale_combat_gold_for_power,
    scale_combat_xp_for_power,
)


class CombatValidationError(ValueError):
    pass


@dataclass(frozen=True)
class BattleResult:
    enemy: GeneratedEnemy
    outcome: str
    player_hp: int
    enemy_hp: int
    combat_xp: int
    gold: int
    rounds: int
    potion_bonus_xp: int = 0
    luck_proc: bool = False


def resolve_battle(
    *,
    player_stats: CombatStats,
    player_hp: int,
    enemy: GeneratedEnemy,
    rng: random.Random | None = None,
    reward_combat_xp: int | None = None,
    reward_gold: int | None = None,
    combat_xp_multiplier: float = 1.0,
    luck_proc: bool = False,
) -> BattleResult:
    rng = rng or random
    _validate_combatant(
        name="player",
        max_hp=player_stats.max_hp,
        attack=player_stats.attack,
        defense=player_stats.defense,
        speed=player_stats.speed,
    )
    _validate_combatant(
        name=enemy.name,
        max_hp=enemy.max_hp,
        attack=enemy.attack,
        defense=enemy.defense,
        speed=enemy.speed,
    )

    player_hp = min(max(0, int(player_hp)), int(player_stats.max_hp))
    enemy_hp = min(max(0, int(enemy.current_hp)), int(enemy.max_hp))
    if player_hp <= 0:
        return BattleResult(
            enemy=enemy,
            outcome="defeat",
            player_hp=0,
            enemy_hp=enemy_hp,
            combat_xp=0,
            gold=0,
            rounds=0,
        )

    player_first = _player_has_initiative(player_stats.speed, enemy.speed, rng=rng)
    minimum_damage = PROGRESSION_CONTENT.defense.minimum_damage
    max_rounds = PROGRESSION_CONTENT.defense.max_battle_rounds

    rounds = 0
    while player_hp > 0 and enemy_hp > 0 and rounds < max_rounds:
        rounds += 1
        if player_first:
            enemy_hp -= _damage(player_stats.attack, enemy.defense, minimum_damage)
            if enemy_hp <= 0:
                break
            player_hp -= _damage(enemy.attack, player_stats.defense, minimum_damage)
        else:
            player_hp -= _damage(enemy.attack, player_stats.defense, minimum_damage)
            if player_hp <= 0:
                break
            enemy_hp -= _damage(player_stats.attack, enemy.defense, minimum_damage)

    if enemy_hp <= 0 and player_hp > 0:
        outcome = "victory"
        player_power = calculate_combat_power(
            max_hp=player_stats.max_hp,
            attack=player_stats.attack,
            defense=player_stats.defense,
            speed=player_stats.speed,
        )
        base_combat_xp = enemy.combat_xp if reward_combat_xp is None else max(0, int(reward_combat_xp))
        base_gold = enemy.gold if reward_gold is None else max(0, int(reward_gold))
        scaled_combat_xp = scale_combat_xp_for_power(
            base_combat_xp,
            player_power=player_power,
            enemy_power=max(1.0, enemy.power),
        )
        if combat_xp_multiplier > 1 and scaled_combat_xp > 0:
            combat_xp = max(0, int(round(scaled_combat_xp * combat_xp_multiplier)))
            potion_bonus_xp = max(0, combat_xp - scaled_combat_xp)
        else:
            combat_xp = scaled_combat_xp
            potion_bonus_xp = 0
        gold = scale_combat_gold_for_power(
            base_gold,
            player_power=player_power,
            enemy_power=max(1.0, enemy.power),
        )
    elif player_hp <= 0:
        outcome = "defeat"
        combat_xp = 0
        gold = 0
        potion_bonus_xp = 0
    else:
        outcome = "draw"
        combat_xp = 0
        gold = 0
        potion_bonus_xp = 0

    return BattleResult(
        enemy=enemy,
        outcome=outcome,
        player_hp=max(0, player_hp),
        enemy_hp=max(0, enemy_hp),
        combat_xp=combat_xp,
        gold=gold,
        rounds=rounds,
        potion_bonus_xp=potion_bonus_xp,
        luck_proc=luck_proc and outcome == "victory",
    )


def _validate_combatant(
    *,
    name: str,
    max_hp: int,
    attack: int,
    defense: int,
    speed: int,
) -> None:
    values = {
        "max_hp": max_hp,
        "attack": attack,
        "defense": defense,
        "speed": speed,
    }
    for field, value in values.items():
        if not isinstance(value, int) or isinstance(value, bool):
            raise CombatValidationError(f"{name} {field} must be an integer")
        if value < 0:
            raise CombatValidationError(f"{name} {field} cannot be negative")
    if max_hp <= 0:
        raise CombatValidationError(f"{name} max_hp must be positive")


def _damage(attack: int, defense: int, minimum_damage: int | None = None) -> int:
    minimum = minimum_damage or PROGRESSION_CONTENT.defense.minimum_damage
    return max(minimum, max(0, attack) - max(0, defense))


def _player_has_initiative(player_speed: int, enemy_speed: int, *, rng: random.Random) -> bool:
    player_weight = max(1, player_speed)
    enemy_weight = max(1, enemy_speed)
    # Weighted opposed roll. The tiny tie-breaker makes seeded tests deterministic.
    player_roll = rng.uniform(0, player_weight) + rng.random() * 0.0001
    enemy_roll = rng.uniform(0, enemy_weight)
    return player_roll >= enemy_roll
