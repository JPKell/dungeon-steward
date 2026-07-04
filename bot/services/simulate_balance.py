#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import random
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

BASE = Path(__file__).parents[1] / "content"
RARITIES = ("common", "uncommon", "rare", "epic", "legendary")
POWER_WEIGHTS = {"hp": 0.12, "attack": 2.0, "defense": 2.25, "speed": 1.25}
ENCOUNTER_POOL_CACHE: dict[int, tuple[list[dict[str, Any]], list[int]]] = {}
ENEMY_EXPECTATION_CACHE: dict[int, tuple[float, float, float]] = {}
EQUIPMENT_POOL_CACHE: dict[int, list[dict[str, Any]]] = {}
MAX_CACHED_EQUIPMENT_LEVEL = 1


@dataclass(frozen=True)
class Profile:
    name: str
    exploration_use: float
    defense_sessions: float
    shop_refreshes: float
    allocation_quality: float


PROFILES = (
    Profile("casual", 0.45, 0.85, 0.55, 0.90),
    Profile("typical", 0.80, 1.80, 1.00, 1.00),
    Profile("dedicated", 0.98, 2.60, 1.75, 1.06),
)


@dataclass
class State:
    explore_level: int = 1
    explore_xp: int = 0
    combat_level: int = 1
    combat_xp: int = 0
    gold: int = 0
    gold_earned_explore: int = 0
    gold_earned_defense: int = 0
    gold_spent: int = 0
    purchase_count: int = 0
    purchase_days: list[int] = field(default_factory=list)
    purchase_costs: list[int] = field(default_factory=list)
    discoveries: set[str] = field(default_factory=set)
    defense_wins: int = 0
    highest_dungeon: int = 1
    unlock_days: dict[int, int] = field(default_factory=lambda: {1: 1})
    equipped: dict[str, dict[str, Any]] = field(default_factory=dict)
    total_stat_points: int = 0
    cooldown_cap_day: int | None = None
    combat_milestone_days: dict[int, int] = field(default_factory=dict)
    death_by_dungeon: Counter[int] = field(default_factory=Counter)
    battles_by_dungeon: Counter[int] = field(default_factory=Counter)
    equipment_power_history: dict[int, float] = field(default_factory=dict)
    gold_band: dict[str, dict[str, int]] = field(default_factory=lambda: defaultdict(lambda: defaultdict(int)))


def load() -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    progression = json.loads((BASE / "progression.json").read_text())
    dungeons = json.loads((BASE / "dungeon_levels.json").read_text())
    enemies = json.loads((BASE / "enemies.json").read_text())
    equipment = json.loads((BASE / "equipment.json").read_text())
    encounters = json.loads((BASE / "encounters.json").read_text())
    return progression, dungeons, enemies, equipment, encounters


def scaling(step: int, cfg: dict[str, Any]) -> float:
    n = max(0, step - 1)
    curve = cfg["curve"]
    if curve == "linear":
        value = cfg["base"] + cfg["linear_growth"] * n
    elif curve == "quadratic":
        value = cfg["base"] + cfg["linear_growth"] * n + cfg["quadratic_growth"] * n * n
    else:
        value = cfg["base"] * cfg["exponential_growth"] ** n
    value = max(cfg.get("minimum", value), value)
    if cfg.get("maximum") is not None:
        value = min(cfg["maximum"], value)
    return value


def explore_xp_next(level: int, progression: dict[str, Any]) -> int:
    cfg = progression["exploration"]["leveling"]
    n = max(0, level - 1)
    if cfg["curve"] == "quadratic":
        value = cfg["base_xp"] + cfg["linear_growth"] * n + cfg["quadratic_growth"] * n * n
    elif cfg["curve"] == "linear":
        value = cfg["base_xp"] + cfg["linear_growth"] * n
    else:
        value = cfg["base_xp"] * cfg["exponential_growth"] ** n
    return max(1, round(value))


def combat_xp_next(level: int, progression: dict[str, Any]) -> int:
    return max(1, round(scaling(level, progression["combat_leveling"]["xp_to_next_level"])))


def hp_gain(level: int, progression: dict[str, Any]) -> int:
    if level <= 1:
        return 0
    cfg = progression["combat_leveling"]
    gain = max(1, round(scaling(level - 1, cfg["hp_per_level"])))
    if level % cfg["hp_milestone_interval"] == 0:
        gain += cfg["hp_milestone_bonus"]
    return gain


def stat_gain(level: int, progression: dict[str, Any]) -> int:
    if level <= 1:
        return 0
    cfg = progression["combat_leveling"]
    gain = max(1, round(scaling(level - 1, cfg["stat_points_per_level"])))
    if level % cfg["stat_milestone_interval"] == 0:
        gain += cfg["stat_milestone_bonus"]
    return gain


def cooldown(level: int, progression: dict[str, Any]) -> int:
    cfg = progression["exploration"]
    return max(cfg["min_cooldown_minutes"], cfg["base_cooldown_minutes"] - (level - 1) * cfg["cooldown_reduction_per_level"])


def defense_minutes(level: int, progression: dict[str, Any]) -> int:
    cfg = progression["defense"]
    return min(cfg["max_minutes"], cfg["base_minutes"] + max(0, level - 1))


def equipment_power(item: dict[str, Any]) -> float:
    return sum(max(0, item[stat]) * POWER_WEIGHTS[stat] for stat in POWER_WEIGHTS)


def total_equipment_power(state: State) -> float:
    return sum(equipment_power(item) for item in state.equipped.values())


def player_power(state: State, progression: dict[str, Any], profile: Profile) -> float:
    max_hp = progression["new_player"]["base_hp"] + sum(hp_gain(level, progression) for level in range(2, state.combat_level + 1))
    points = state.total_stat_points
    attack = progression["new_player"]["attack"] + round(points * 0.40 * profile.allocation_quality)
    defense = progression["new_player"]["defense"] + round(points * 0.36 * profile.allocation_quality)
    speed = progression["new_player"]["speed"] + round(points * 0.24 * profile.allocation_quality)
    return max_hp * 0.12 + attack * 2.0 + defense * 2.25 + speed * 1.25 + total_equipment_power(state)


def rarity_weights(level: int, progression: dict[str, Any]) -> dict[str, int]:
    selected = progression["shop"]["rarity_bands"][0]
    for band in progression["shop"]["rarity_bands"]:
        if level >= band["min_level"]:
            selected = band
    return selected["weights"]


def select_shop(equipment: list[dict[str, Any]], level: int, progression: dict[str, Any], rng: random.Random) -> list[dict[str, Any]]:
    cached_level = min(max(1, level), MAX_CACHED_EQUIPMENT_LEVEL)
    valid = EQUIPMENT_POOL_CACHE.get(cached_level)
    if valid is None:
        valid = [item for item in equipment if item["min_level"] <= level <= item["max_level"]]
    if not valid:
        return []
    result: list[dict[str, Any]] = []
    used: set[str] = set()
    weights = rarity_weights(level, progression)
    for _ in range(progression["shop"]["stock_size"]):
        remaining = [item for item in valid if item["key"] not in used]
        if not remaining:
            break
        available = sorted({item["rarity"] for item in remaining})
        rarity = rng.choices(available, weights=[weights[r] for r in available], k=1)[0]
        candidates = [item for item in remaining if item["rarity"] == rarity]
        item = rng.choice(candidates)
        result.append(item)
        used.add(item["key"])
    return result


def buy_upgrades(state: State, stock: list[dict[str, Any]], day: int) -> None:
    candidates = []
    for item in stock:
        current = state.equipped.get(item["slot"])
        gain = equipment_power(item) - (equipment_power(current) if current else 0.0)
        if gain > 0 and item["cost"] <= state.gold:
            candidates.append((gain / max(1, item["cost"]), gain, item))
    candidates.sort(reverse=True, key=lambda row: (row[0], row[1]))
    for _, _gain, item in candidates:
        current = state.equipped.get(item["slot"])
        current_power = equipment_power(current) if current else 0.0
        if equipment_power(item) <= current_power * 1.035:
            continue
        if item["cost"] > state.gold:
            continue
        state.gold -= item["cost"]
        state.gold_spent += item["cost"]
        state.purchase_count += 1
        state.purchase_days.append(day)
        state.purchase_costs.append(item["cost"])
        state.gold_band[band_for_day(day)]["spent"] += item["cost"]
        state.equipped[item["slot"]] = item


def encounter_reward(
    encounter: dict[str, Any],
    choice: dict[str, Any],
    state: State,
    dungeon: dict[str, Any],
    progression: dict[str, Any],
    rng: random.Random,
) -> tuple[int, int]:
    reward_cfg = progression["exploration"]["reward_scaling"]
    rarity = encounter.get("rarity", "common")
    base_gold = rng.randint(choice["gold_min"], choice["gold_max"])
    base_xp = rng.randint(choice["xp_min"], choice["xp_max"])
    cap_level = progression["exploration"]["cooldown_cap_level"]
    gold_level = scaling(min(state.explore_level, cap_level), reward_cfg["gold_multiplier"])
    gold_level *= 1 + max(0, state.explore_level - cap_level) * reward_cfg["post_cap_gold_growth"]
    xp_level = scaling(min(state.explore_level, cap_level), reward_cfg["xp_multiplier"])
    gold_mult = gold_level * dungeon["exploration_gold_modifier"] * reward_cfg["rarity_gold_multipliers"][rarity]
    xp_mult = xp_level * dungeon["exploration_xp_modifier"] * reward_cfg["rarity_xp_multipliers"][rarity]
    if choice.get("success", True) is False:
        gold_mult *= 1 + reward_cfg["risk_gold_bonus"]
        xp_mult *= reward_cfg["failure_xp_multiplier"]
    return round(base_gold * gold_mult), round(base_xp * xp_mult)


def weighted_encounter(encounters: list[dict[str, Any]], explore_level: int, rng: random.Random) -> dict[str, Any]:
    cache_level = min(max(1, explore_level), max(ENCOUNTER_POOL_CACHE))
    eligible, weights = ENCOUNTER_POOL_CACHE[cache_level]
    return rng.choices(eligible, weights=weights, k=1)[0]


def choose_choice(encounter: dict[str, Any], rng: random.Random) -> dict[str, Any]:
    choices = encounter["choices"]
    # Typical players prefer reliable progress but occasionally choose high-risk gold.
    weights = []
    for choice in choices:
        value = 1.0
        if choice.get("success", True):
            value += 1.4
        if choice.get("discovery_key"):
            value += 0.8
        average_gold = (choice["gold_min"] + choice["gold_max"]) / 2
        average_xp = (choice["xp_min"] + choice["xp_max"]) / 2
        value += average_xp / max(1, average_gold + average_xp)
        weights.append(value)
    return rng.choices(choices, weights=weights, k=1)[0]


def enemy_expectations(
    dungeon_level: int, dungeons: list[dict[str, Any]], enemies: list[dict[str, Any]], progression: dict[str, Any]
) -> tuple[float, float, float]:
    cached = ENEMY_EXPECTATION_CACHE.get(dungeon_level)
    if cached is not None:
        return cached
    dungeon = dungeons[dungeon_level - 1]
    eligible = [e for e in enemies if e["enabled"] and e["min_dungeon_level"] <= dungeon_level <= e["max_dungeon_level"]]
    total_weight = sum(e["weight"] for e in eligible)
    avg_level = (dungeon["enemy_level_min"] + dungeon["enemy_level_max"]) / 2
    level_reward = 1 + (avg_level - 1) * progression["enemy_generation"]["level_reward_scale"]
    xp = sum(((e["xp_min"] + e["xp_max"]) / 2) * e["weight"] for e in eligible) / total_weight
    gold = sum(((e["gold_min"] + e["gold_max"]) / 2) * e["weight"] for e in eligible) / total_weight
    rank_hazard = {"common": 0.8, "standard": 1.0, "dangerous": 1.35, "elite": 1.8, "boss": 2.5}
    hazard = sum(rank_hazard[e["rank"]] * e["weight"] for e in eligible) / total_weight
    return (
        xp * dungeon["reward_modifier"] * level_reward,
        gold * dungeon["reward_modifier"] * level_reward * progression["enemy_generation"].get("combat_gold_multiplier", 1.0),
        hazard,
    )


def add_explore_xp(state: State, amount: int, progression: dict[str, Any]) -> None:
    state.explore_xp += amount
    while state.explore_xp >= explore_xp_next(state.explore_level, progression):
        state.explore_xp -= explore_xp_next(state.explore_level, progression)
        state.explore_level += 1


def add_combat_xp(state: State, amount: int, progression: dict[str, Any], day: int) -> None:
    state.combat_xp += amount
    while state.combat_xp >= combat_xp_next(state.combat_level, progression):
        state.combat_xp -= combat_xp_next(state.combat_level, progression)
        state.combat_level += 1
        state.total_stat_points += stat_gain(state.combat_level, progression)
        for milestone in (100, 200, 300, 400, 421):
            if state.combat_level >= milestone and milestone not in state.combat_milestone_days:
                state.combat_milestone_days[milestone] = day


def geometric_wins(hazard: float, cap: int, rng: random.Random) -> tuple[int, bool]:
    wins = 0
    for _ in range(cap):
        if rng.random() < hazard:
            return wins, True
        wins += 1
    return wins, False


def try_unlock(
    state: State, dungeons: list[dict[str, Any]], progression: dict[str, Any], profile: Profile, day: int, rng: random.Random
) -> None:
    while state.highest_dungeon < 20:
        next_level = state.highest_dungeon + 1
        req = dungeons[next_level - 1]
        eq_power = total_equipment_power(state)
        checks = (
            state.explore_level >= req["required_explore_level"],
            state.combat_level >= req["required_combat_level"],
            eq_power >= req["required_equipment_power"],
            len(state.discoveries) >= req["required_discoveries"],
            state.defense_wins >= req["required_defense_wins"],
        )
        if not all(checks):
            return
        ratio = player_power(state, progression, profile) / max(1.0, req["expected_player_power"])
        success_chance = min(0.95, max(0.28, 0.48 + (ratio - 1.0) * 0.28))
        if rng.random() > success_chance:
            return
        state.highest_dungeon = next_level
        state.unlock_days[next_level] = day


def band_for_day(day: int) -> str:
    if day <= 30:
        return "days_1_30"
    if day <= 120:
        return "days_31_120"
    if day <= 365:
        return "days_121_365"
    return "days_366_600"


def simulate_one(profile: Profile, seed: int, max_days: int, data: tuple[Any, ...]) -> State:
    progression, dungeons, enemies, equipment, encounters = data
    rng = random.Random(seed)
    state = State()
    for day in range(1, max_days + 1):
        current_dungeon = dungeons[state.highest_dungeon - 1]
        cd = cooldown(state.explore_level, progression)
        generated_actions = 1440 / cd
        action_mean = generated_actions * profile.exploration_use
        actions = max(0, round(rng.gauss(action_mean, max(0.7, action_mean * 0.08))))
        for _ in range(actions):
            encounter = weighted_encounter(encounters, state.explore_level, rng)
            choice = choose_choice(encounter, rng)
            gold, xp = encounter_reward(encounter, choice, state, current_dungeon, progression, rng)
            state.gold += gold
            state.gold_earned_explore += gold
            state.gold_band[band_for_day(day)]["exploration"] += gold
            add_explore_xp(state, xp, progression)
            discovery = choice.get("discovery_key")
            if discovery and rng.random() < 0.72:
                state.discoveries.add(discovery)

        if cd == progression["exploration"]["min_cooldown_minutes"] and state.cooldown_cap_day is None:
            state.cooldown_cap_day = day

        sessions_floor = math.floor(profile.defense_sessions)
        sessions = sessions_floor + (1 if rng.random() < profile.defense_sessions - sessions_floor else 0)
        for _ in range(sessions):
            dungeon_level = state.highest_dungeon
            expected_xp, expected_gold, rank_hazard = enemy_expectations(dungeon_level, dungeons, enemies, progression)
            power_ratio = player_power(state, progression, profile) / max(1.0, dungeons[dungeon_level - 1]["expected_player_power"])
            loss_hazard = 0.0032 * rank_hazard / max(0.45, power_ratio**0.72)
            loss_hazard = min(0.12, max(0.0018, loss_hazard))
            cap = defense_minutes(state.combat_level, progression)
            wins, died = geometric_wins(loss_hazard, cap, rng)
            state.defense_wins += wins
            state.battles_by_dungeon[dungeon_level] += wins + int(died)
            if died:
                state.death_by_dungeon[dungeon_level] += 1
            # Reward power adjustment reduces trivial-floor farming.
            enemy_to_player = min(1.35, max(0.2, 1.0 / max(0.4, power_ratio)))
            xp_gain = round(wins * expected_xp * (0.55 + 0.55 * enemy_to_player))
            gold_power_multiplier = (
                progression["enemy_generation"].get("trivial_enemy_gold_multiplier", 0.35)
                if enemy_to_player < progression["enemy_generation"].get("trivial_enemy_ratio", 0.55)
                else min(1.1, max(0.35, 0.55 + enemy_to_player * 0.45))
            )
            gold_gain = round(wins * expected_gold * gold_power_multiplier)
            add_combat_xp(state, xp_gain, progression, day)
            state.gold += gold_gain
            state.gold_earned_defense += gold_gain
            state.gold_band[band_for_day(day)]["defense"] += gold_gain

        refresh_floor = math.floor(profile.shop_refreshes)
        refreshes = refresh_floor + (1 if rng.random() < profile.shop_refreshes - refresh_floor else 0)
        for _ in range(refreshes):
            stock = select_shop(equipment, state.combat_level, progression, rng)
            buy_upgrades(state, stock, day)

        try_unlock(state, dungeons, progression, profile, day, rng)
        if day in (30, 120, 240, 365, 450, 548, 600):
            state.equipment_power_history[day] = total_equipment_power(state)
    return state


def median(values: list[float | int | None]) -> float | None:
    clean = [value for value in values if value is not None]
    return statistics.median(clean) if clean else None


def aggregate(profile: Profile, states: list[State], progression: dict[str, Any]) -> dict[str, Any]:
    unlocks = {str(level): median([state.unlock_days.get(level) for state in states]) for level in range(1, 21)}
    reached = {str(level): sum(level in state.unlock_days for state in states) / len(states) for level in range(1, 21)}
    cooldown_days = [state.cooldown_cap_day for state in states]
    combat_milestones = {
        str(level): median([state.combat_milestone_days.get(level) for state in states]) for level in (100, 200, 300, 400, 421)
    }
    equipment_history = {
        str(day): median([state.equipment_power_history.get(day) for state in states]) for day in (30, 120, 240, 365, 450, 548, 600)
    }
    gold = {
        "exploration": median([state.gold_earned_explore for state in states]),
        "defense": median([state.gold_earned_defense for state in states]),
        "spent": median([state.gold_spent for state in states]),
        "remaining": median([state.gold for state in states]),
    }
    band_lengths = {"days_1_30": 30, "days_31_120": 90, "days_121_365": 245, "days_366_600": 235}
    gold_by_band: dict[str, dict[str, float | None]] = {}
    for band, length in band_lengths.items():
        explore = median([state.gold_band[band].get("exploration", 0) for state in states]) or 0
        defense_gold = median([state.gold_band[band].get("defense", 0) for state in states]) or 0
        spent = median([state.gold_band[band].get("spent", 0) for state in states]) or 0
        gold_by_band[band] = {
            "exploration_per_day": round(explore / length, 2),
            "defense_per_day": round(defense_gold / length, 2),
            "total_per_day": round((explore + defense_gold) / length, 2),
            "spent_per_day": round(spent / length, 2),
        }
    purchase_intervals = []
    for state in states:
        if len(state.purchase_days) >= 2:
            purchase_intervals.append(
                sum(b - a for a, b in zip(state.purchase_days, state.purchase_days[1:], strict=False))
                / (len(state.purchase_days) - 1)
            )
    purchase_stats = {
        "median_purchase_count": median([state.purchase_count for state in states]),
        "median_days_between_purchases": median(purchase_intervals),
        "median_purchase_cost": median([statistics.median(state.purchase_costs) if state.purchase_costs else None for state in states]),
    }
    deaths: dict[str, float] = {}
    for level in range(1, 21):
        deaths_count = sum(state.death_by_dungeon[level] for state in states)
        battles = sum(state.battles_by_dungeon[level] for state in states)
        deaths[str(level)] = (deaths_count / battles * 100.0) if battles else 0.0
    return {
        "profile": profile.name,
        "runs": len(states),
        "median_unlock_day": unlocks,
        "reach_rate": reached,
        "median_cooldown_cap_day": median(cooldown_days),
        "median_combat_milestone_day": combat_milestones,
        "median_equipment_power": equipment_history,
        "median_gold": gold,
        "median_gold_by_band": gold_by_band,
        "purchase_stats": purchase_stats,
        "death_rate_percent_by_dungeon": deaths,
        "median_final_explore_level": median([state.explore_level for state in states]),
        "median_final_combat_level": median([state.combat_level for state in states]),
        "median_discoveries": median([len(state.discoveries) for state in states]),
        "median_defense_wins": median([state.defense_wins for state in states]),
        "defense_duration_at_final_median_level": defense_minutes(
            round(median([state.combat_level for state in states]) or 1), progression
        ),
    }


def shop_percentages(progression: dict[str, Any]) -> dict[str, dict[str, float]]:
    result = {}
    for level in (1, 25, 50, 100, 200, 300, 400):
        weights = rarity_weights(level, progression)
        total = sum(weights.values())
        result[str(level)] = {rarity: round(weights[rarity] / total * 100, 2) for rarity in RARITIES}
    return result


def build_caches(data: tuple[Any, ...]) -> None:
    global MAX_CACHED_EQUIPMENT_LEVEL
    progression, dungeons, enemies, equipment, encounters = data
    max_explore = max(200, max(int(e.get("min_level", 1)) for e in encounters))
    for level in range(1, max_explore + 1):
        eligible = [e for e in encounters if e.get("enabled", True) and e.get("min_level", 1) <= level]
        ENCOUNTER_POOL_CACHE[level] = (eligible, [max(1, int(e.get("weight", 1))) for e in eligible])
    for level in range(1, 21):
        # Temporarily bypass cache population recursion by calculating directly once.
        dungeon = dungeons[level - 1]
        eligible = [e for e in enemies if e["enabled"] and e["min_dungeon_level"] <= level <= e["max_dungeon_level"]]
        total_weight = sum(e["weight"] for e in eligible)
        avg_level = (dungeon["enemy_level_min"] + dungeon["enemy_level_max"]) / 2
        level_reward = 1 + (avg_level - 1) * progression["enemy_generation"]["level_reward_scale"]
        xp = sum(((e["xp_min"] + e["xp_max"]) / 2) * e["weight"] for e in eligible) / total_weight
        gold = sum(((e["gold_min"] + e["gold_max"]) / 2) * e["weight"] for e in eligible) / total_weight
        rank_hazard = {"common": 0.8, "standard": 1.0, "dangerous": 1.35, "elite": 1.8, "boss": 2.5}
        hazard = sum(rank_hazard[e["rank"]] * e["weight"] for e in eligible) / total_weight
        ENEMY_EXPECTATION_CACHE[level] = (
            xp * dungeon["reward_modifier"] * level_reward,
            gold * dungeon["reward_modifier"] * level_reward * progression["enemy_generation"].get("combat_gold_multiplier", 1.0),
            hazard,
        )
    MAX_CACHED_EQUIPMENT_LEVEL = max(int(item["max_level"]) for item in equipment)
    for level in range(1, MAX_CACHED_EQUIPMENT_LEVEL + 1):
        EQUIPMENT_POOL_CACHE[level] = [item for item in equipment if item["min_level"] <= level <= item["max_level"]]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=40)
    parser.add_argument("--days", type=int, default=600)
    parser.add_argument("--seed", type=int, default=20260703)
    parser.add_argument("--output", type=Path, default=BASE / "simulation_results.json")
    args = parser.parse_args()

    data = load()
    build_caches(data)
    progression = data[0]
    results: dict[str, Any] = {
        "assumptions": {
            profile.name: {
                "exploration_energy_use": profile.exploration_use,
                "defense_sessions_per_day": profile.defense_sessions,
                "shop_refreshes_per_day": profile.shop_refreshes,
                "allocation_quality": profile.allocation_quality,
            }
            for profile in PROFILES
        },
        "shop_rarity_percentages": shop_percentages(progression),
        "profiles": {},
    }
    for profile_index, profile in enumerate(PROFILES):
        states = [simulate_one(profile, args.seed + profile_index * 100000 + run, args.days, data) for run in range(args.runs)]
        results["profiles"][profile.name] = aggregate(profile, states, progression)

    typical = results["profiles"]["typical"]
    d18 = typical["median_unlock_day"]["18"]
    d20 = typical["median_unlock_day"]["20"]
    cap = typical["median_cooldown_cap_day"]
    results["target_evaluation"] = {
        "dungeon_18_in_range": d18 is not None and 330 <= d18 <= 400,
        "dungeon_20_in_range": d20 is not None and 500 <= d20 <= 600,
        "cooldown_cap_in_range": cap is not None and 330 <= cap <= 400,
        "typical_dungeon_18_day": d18,
        "typical_dungeon_20_day": d20,
        "typical_cooldown_cap_day": cap,
    }
    args.output.write_text(json.dumps(results, indent=2) + "\n")
    print(json.dumps(results["target_evaluation"], indent=2))
    for name, result in results["profiles"].items():
        print(
            name,
            "D18",
            result["median_unlock_day"]["18"],
            "D20",
            result["median_unlock_day"]["20"],
            "cap",
            result["median_cooldown_cap_day"],
            "C400",
            result["median_combat_milestone_day"]["400"],
        )


if __name__ == "__main__":
    main()
