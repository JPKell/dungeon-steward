from __future__ import annotations

import random
from dataclasses import dataclass

from bot.config import MAX_BATTLE_ROUNDS, MINIMUM_DAMAGE
from bot.services.enemy_service import GeneratedEnemy
from bot.services.equipment_service import CombatStats


@dataclass(frozen=True)
class BattleResult:
    enemy: GeneratedEnemy
    outcome: str
    player_hp: int
    enemy_hp: int
    combat_xp: int
    gold: int
    rounds: int


def resolve_battle(
    *,
    player_stats: CombatStats,
    player_hp: int,
    enemy: GeneratedEnemy,
    rng: random.Random | None = None,
) -> BattleResult:
    rng = rng or random
    player_hp = min(max(0, player_hp), player_stats.max_hp)
    enemy_hp = enemy.current_hp
    player_first = _player_has_initiative(player_stats.speed, enemy.speed, rng=rng)

    rounds = 0
    while player_hp > 0 and enemy_hp > 0 and rounds < MAX_BATTLE_ROUNDS:
        rounds += 1
        if player_first:
            enemy_hp -= _damage(player_stats.attack, enemy.defense)
            if enemy_hp <= 0:
                break
            player_hp -= _damage(enemy.attack, player_stats.defense)
        else:
            player_hp -= _damage(enemy.attack, player_stats.defense)
            if player_hp <= 0:
                break
            enemy_hp -= _damage(player_stats.attack, enemy.defense)

    if enemy_hp <= 0 and player_hp > 0:
        outcome = "victory"
        combat_xp = enemy.combat_xp
        gold = enemy.gold
    elif player_hp <= 0:
        outcome = "defeat"
        combat_xp = 0
        gold = 0
    else:
        outcome = "draw"
        combat_xp = 0
        gold = 0

    return BattleResult(
        enemy=enemy,
        outcome=outcome,
        player_hp=max(0, player_hp),
        enemy_hp=max(0, enemy_hp),
        combat_xp=combat_xp,
        gold=gold,
        rounds=rounds,
    )


def _damage(attack: int, defense: int) -> int:
    return max(MINIMUM_DAMAGE, attack - defense)


def _player_has_initiative(player_speed: int, enemy_speed: int, *, rng: random.Random) -> bool:
    player_roll = rng.uniform(0, max(1, player_speed)) + rng.random() * 0.0001
    enemy_roll = rng.uniform(0, max(1, enemy_speed))
    return player_roll >= enemy_roll
