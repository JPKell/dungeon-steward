from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

BASE = Path(__file__).parents[1] / "content"
CONTENT_PATH = BASE / "potion_items.json"
REPORT_PATH = BASE / "validation_report.json"


def effect_strength(item: dict[str, Any]) -> tuple[float, float]:
    effect = item["effect"]
    kind = effect["kind"]
    if kind == "heal_between_battles":
        return float(effect["max_hp_percent"]), float(effect["flat_cap"])
    if kind == "maximum_enemy_reward_chance":
        return float(effect["chance"]), 0.0
    return float(effect["bonus"]), 0.0


def eligible(items: list[dict[str, Any]], level: int) -> list[dict[str, Any]]:
    return [
        item
        for item in items
        if item["enabled"] and item["min_explore_level"] <= level <= item["max_explore_level"]
    ]


def drop_chance(document: dict[str, Any], *, dungeon_level: int, rarity: str, success: bool) -> float:
    rules = document["drop_rules"]
    chance = (
        rules["base_drop_chance"]
        + rules["successful_choice_bonus"]
        + max(0, dungeon_level - 1) * rules["dungeon_level_bonus_per_level_after_one"]
        + rules["encounter_rarity_bonus"][rarity]
    )
    if not success:
        chance *= rules["failed_choice_multiplier"]
    return min(rules["maximum_drop_chance"], chance)


def main() -> None:
    document = json.loads(CONTENT_PATH.read_text(encoding="utf-8"))
    items = document["items"]
    errors: list[str] = []
    warnings: list[str] = []

    if len(items) != 90:
        errors.append(f"Expected 90 potion items, found {len(items)}")

    keys = [item["key"] for item in items]
    names = [item["name"] for item in items]
    if len(keys) != len(set(keys)):
        errors.append("Potion keys are not unique")
    if len(names) != len(set(names)):
        errors.append("Potion names are not unique")

    type_counts = Counter(item["potion_type"] for item in items)
    expected_types = {"xp", "max_hp", "healing", "attack", "defense", "luck"}
    if set(type_counts) != expected_types:
        errors.append(f"Potion types differ from expected set: {sorted(type_counts)}")
    for potion_type in expected_types:
        if type_counts[potion_type] != 15:
            errors.append(f"Potion type {potion_type} has {type_counts[potion_type]} entries instead of 15")

    by_type: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for item in items:
        by_type[item["potion_type"]].append(item)
        for field in (
            "key", "name", "category", "potion_type", "effect_group", "tier", "rarity",
            "description", "duration_seconds", "min_explore_level", "max_explore_level",
            "exploration_drop_weight", "inventory_stack_limit", "effect",
        ):
            if field not in item:
                errors.append(f"{item.get('key', '<unknown>')} missing field {field}")
        if item["duration_seconds"] <= 0:
            errors.append(f"{item['key']} has non-positive duration")
        if item["min_explore_level"] < 1 or item["max_explore_level"] < item["min_explore_level"]:
            errors.append(f"{item['key']} has invalid explore level range")
        if item["exploration_drop_weight"] <= 0:
            errors.append(f"{item['key']} has non-positive drop weight")

    progression: dict[str, list[dict[str, Any]]] = {}
    for potion_type, type_items in by_type.items():
        type_items.sort(key=lambda item: item["tier"])
        tiers = [item["tier"] for item in type_items]
        if tiers != list(range(1, 16)):
            errors.append(f"{potion_type} tiers are not exactly 1 through 15")
        strengths = [effect_strength(item) for item in type_items]
        durations = [item["duration_seconds"] for item in type_items]
        for index in range(1, len(strengths)):
            if strengths[index] < strengths[index - 1]:
                errors.append(f"{potion_type} effect decreases between tiers {index} and {index + 1}")
            if durations[index] < durations[index - 1]:
                errors.append(f"{potion_type} duration decreases between tiers {index} and {index + 1}")
        progression[potion_type] = [
            {
                "tier": item["tier"],
                "name": item["name"],
                "duration_minutes": item["duration_seconds"] // 60,
                "effect_strength": effect_strength(item),
            }
            for item in type_items
        ]

    coverage: dict[str, Any] = {}
    for level in range(1, 151):
        pool = eligible(items, level)
        pool_types = Counter(item["potion_type"] for item in pool)
        missing_types = sorted(expected_types - set(pool_types))
        if missing_types:
            errors.append(f"Explore level {level} lacks eligible types: {missing_types}")
        coverage[str(level)] = {
            "eligible_items": len(pool),
            "tiers": sorted({item["tier"] for item in pool}),
            "items_per_type": dict(sorted(pool_types.items())),
        }

    rules = document["drop_rules"]
    if rules["maximum_drop_chance"] > 0.05:
        warnings.append("Maximum aggregate exploration potion drop chance exceeds 5%")
    if document["activation_rules"]["max_simultaneous_effect_groups"] > 3:
        warnings.append("More than three simultaneous effect groups may create excessive burst power")

    reference_drop_rates = {
        "early_success_common_d1": drop_chance(document, dungeon_level=1, rarity="common", success=True),
        "mid_success_uncommon_d10": drop_chance(document, dungeon_level=10, rarity="uncommon", success=True),
        "late_success_rare_d18": drop_chance(document, dungeon_level=18, rarity="rare", success=True),
        "late_success_legendary_d20": drop_chance(document, dungeon_level=20, rarity="legendary", success=True),
        "late_failed_common_d18": drop_chance(document, dungeon_level=18, rarity="common", success=False),
    }

    report = {
        "valid": not errors,
        "item_count": len(items),
        "type_counts": dict(sorted(type_counts.items())),
        "unique_key_count": len(set(keys)),
        "unique_name_count": len(set(names)),
        "explore_level_coverage_1_to_150": coverage,
        "reference_aggregate_drop_rates": reference_drop_rates,
        "errors": errors,
        "warnings": warnings,
    }
    REPORT_PATH.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")

    print(json.dumps({
        "valid": report["valid"],
        "item_count": report["item_count"],
        "type_counts": report["type_counts"],
        "reference_aggregate_drop_rates": report["reference_aggregate_drop_rates"],
        "errors": errors,
        "warnings": warnings,
    }, indent=2))

    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
