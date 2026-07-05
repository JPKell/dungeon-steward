#!/usr/bin/env python3
from __future__ import annotations

import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from bot.config import load_settings
from bot.services.discord_asset_service import (
    load_catalog,
    load_registry,
    validate_gameplay_asset_references,
    validate_registry_integrity,
)
from bot.services.location_service import LocationService
from bot.services.potion_service import EXPECTED_POTION_GROUPS, load_potion_content

BASE = Path(__file__).parents[1] / "content"
RARITIES = ("common", "uncommon", "rare", "epic", "legendary")
SLOTS = ("weapon", "shield", "helm", "gloves", "armor", "boots", "trinket")
POWER_WEIGHTS = {"hp": 0.12, "attack": 2.0, "defense": 2.25, "speed": 1.25}


class ValidationFailure(AssertionError):
    pass


def require(condition: bool, message: str, errors: list[str]) -> None:
    if not condition:
        errors.append(message)


def unique(items: list[dict[str, Any]], field: str, label: str, errors: list[str]) -> None:
    values = [item.get(field) for item in items]
    duplicates = [value for value, count in Counter(values).items() if count > 1]
    require(not duplicates, f"{label} duplicate {field}: {duplicates[:10]}", errors)


def item_power(item: dict[str, Any]) -> float:
    return sum(max(0, int(item.get(stat, 0))) * POWER_WEIGHTS[stat] for stat in POWER_WEIGHTS)


def validate() -> dict[str, Any]:
    errors: list[str] = []
    parsed: dict[str, Any] = {}
    for filename in (
        "progression.json",
        "dungeon_levels.json",
        "enemies.json",
        "equipment.json",
        "equipment_descriptions.json",
        "encounters.json",
        "discoveries.json",
        "potion_items.json",
        "locations.json",
        "image_assets.json",
        "image_asset_registry.json",
    ):
        try:
            parsed[filename] = json.loads((BASE / filename).read_text(encoding="utf-8"))
        except Exception as exc:
            errors.append(f"{filename} failed to parse: {exc}")

    if errors:
        return {"passed": False, "errors": errors}

    progression = parsed["progression.json"]
    dungeons = parsed["dungeon_levels.json"]
    enemies = parsed["enemies.json"]
    equipment = parsed["equipment.json"]
    equipment_descriptions = parsed["equipment_descriptions.json"]
    encounters = parsed["encounters.json"]
    discoveries = parsed["discoveries.json"]
    potion_document = parsed["potion_items.json"]

    # Progression configuration.
    require(progression.get("schema_version") == 2, "progression schema_version must be 2", errors)
    exploration = progression["exploration"]
    expected_cap = 1 + (
        (exploration["base_cooldown_minutes"] - exploration["min_cooldown_minutes"]) // exploration["cooldown_reduction_per_level"]
    )
    require(exploration["base_cooldown_minutes"] == 120, "energy must begin at 120 minutes", errors)
    require(exploration["min_cooldown_minutes"] == 30, "energy minimum must be 30 minutes", errors)
    require(exploration["cooldown_cap_level"] == expected_cap == 91, "cooldown cap must occur at explore level 91", errors)
    defense = progression["defense"]
    require(defense["base_minutes"] == 60, "defense must begin at 60 minutes", errors)
    require(defense["max_minutes"] == 480, "defense must cap at 480 minutes", errors)
    require(defense["duration_cap_level"] == 421, "literal one-minute rule must cap at combat level 421", errors)
    require(defense["minimum_damage"] >= 1, "minimum damage must be at least one", errors)
    require(defense["max_battle_rounds"] > 0, "battle round cap must be positive", errors)

    # Dungeon definitions and unlocks.
    require(isinstance(dungeons, list) and len(dungeons) == 20, "exactly 20 dungeon levels are required", errors)
    require([d["level"] for d in dungeons] == list(range(1, 21)), "dungeon levels must be contiguous 1-20", errors)
    for field in (
        "target_day",
        "required_explore_level",
        "required_combat_level",
        "required_equipment_power",
        "required_discoveries",
        "required_defense_wins",
    ):
        values = [d[field] for d in dungeons]
        require(values == sorted(values), f"{field} must be non-decreasing", errors)
    require(dungeons[17]["target_day"] == 365, "dungeon 18 target day must be 365", errors)
    require(dungeons[19]["target_day"] == 548, "dungeon 20 target day must be 548", errors)
    require(
        all(d["requires_previous_completion"] == (d["level"] > 1) for d in dungeons),
        "preceding dungeon completion chain is invalid",
        errors,
    )
    require(
        all(dungeons[i]["reward_modifier"] >= dungeons[i - 1]["reward_modifier"] for i in range(1, 20)),
        "dungeon combat rewards must be monotonic",
        errors,
    )
    require(
        all(dungeons[i]["exploration_gold_modifier"] >= dungeons[i - 1]["exploration_gold_modifier"] for i in range(1, 20)),
        "dungeon exploration rewards must be monotonic",
        errors,
    )

    # Enemy schemas and coverage.
    unique(enemies, "key", "enemy", errors)
    unique(enemies, "name", "enemy", errors)
    valid_ranks = {"common", "standard", "dangerous", "elite", "boss"}
    required_enemy = {
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
    for enemy in enemies:
        missing = required_enemy - set(enemy)
        require(not missing, f"enemy {enemy.get('key')} missing {sorted(missing)}", errors)
        require(enemy.get("rank") in valid_ranks, f"enemy {enemy.get('key')} has invalid rank", errors)
        require(
            1 <= enemy.get("min_dungeon_level", 0) <= enemy.get("max_dungeon_level", 0) <= 20,
            f"enemy {enemy.get('key')} has invalid dungeon range",
            errors,
        )
        for prefix in ("base_hp", "base_attack", "base_defense", "base_speed", "gold", "xp"):
            low, high = enemy.get(f"{prefix}_min"), enemy.get(f"{prefix}_max")
            require(
                isinstance(low, int) and isinstance(high, int) and 0 <= low <= high,
                f"enemy {enemy.get('key')} has invalid {prefix}",
                errors,
            )
    enemy_coverage = {}
    for level in range(1, 21):
        eligible = [e for e in enemies if e["enabled"] and e["min_dungeon_level"] <= level <= e["max_dungeon_level"]]
        enemy_coverage[level] = len(eligible)
        require(bool(eligible), f"dungeon {level} has no enemies", errors)
        if level >= 5:
            require(any(e["rank"] in {"dangerous", "elite", "boss"} for e in eligible), f"dungeon {level} has no dangerous enemy", errors)

    # Equipment schemas and continuous coverage.
    unique(equipment, "key", "equipment", errors)
    unique(equipment, "name", "equipment", errors)
    generated = [item for item in equipment if str(item.get("key", "")).startswith("generated_")]
    require(len(generated) >= 400, "at least 400 generated equipment items are required", errors)
    for item in equipment:
        require(item.get("slot") in SLOTS, f"item {item.get('key')} has invalid slot", errors)
        require(item.get("rarity") in RARITIES, f"item {item.get('key')} has invalid rarity", errors)
        require(
            isinstance(item.get("min_level"), int)
            and isinstance(item.get("max_level"), int)
            and 1 <= item["min_level"] <= item["max_level"],
            f"item {item.get('key')} has invalid level range",
            errors,
        )
        require(isinstance(item.get("cost"), int) and item["cost"] > 0, f"item {item.get('key')} has invalid cost", errors)
        require(
            all(isinstance(item.get(stat), int) and item[stat] >= 0 for stat in POWER_WEIGHTS),
            f"item {item.get('key')} has invalid stats",
            errors,
        )
        require(item_power(item) > 0, f"item {item.get('key')} has no power", errors)
        if str(item.get("key", "")).startswith("generated_") and item["min_level"] < 300:
            require(
                10 <= item["max_level"] - item["min_level"] + 1 <= 20,
                f"generated item {item['key']} has invalid sub-300 availability span",
                errors,
            )
        if str(item.get("key", "")).startswith("generated_") and item["min_level"] >= 300:
            require(item["max_level"] - item["min_level"] + 1 >= 25, f"endgame item {item['key']} should have a wider range", errors)
    equipment_coverage: dict[int, int] = {}
    for level in range(1, 401):
        valid = [item for item in equipment if item["min_level"] <= level <= item["max_level"]]
        equipment_coverage[level] = len(valid)
        require(bool(valid), f"equipment coverage gap at level {level}", errors)
        for slot in SLOTS:
            require(any(item["slot"] == slot for item in valid), f"slot {slot} has no item at level {level}", errors)
        for rarity in RARITIES:
            require(any(item["rarity"] == rarity for item in valid), f"rarity {rarity} has no item at level {level}", errors)

    equipment_keys = {item["key"] for item in equipment}
    require(isinstance(equipment_descriptions, dict), "equipment descriptions must be an object", errors)
    require(set(equipment_descriptions) == equipment_keys, "equipment descriptions must cover every item exactly once", errors)
    require(
        all(isinstance(text, str) and len(text) >= 40 for text in equipment_descriptions.values()),
        "equipment descriptions must be meaningful strings",
        errors,
    )

    # Verify median generated power trends upward by progression band and rarity.
    power_by_band: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    for item in generated:
        band = str((item["min_level"] // 50) * 50)
        power_by_band[band][item["rarity"]].append(item_power(item))
    for rarity in RARITIES:
        medians = []
        for band in sorted(power_by_band, key=int):
            values = power_by_band[band].get(rarity, [])
            if values:
                medians.append(statistics.median(values))
        require(
            all(medians[i] >= medians[i - 1] * 0.90 for i in range(1, len(medians))),
            f"{rarity} equipment power has a severe backward discontinuity",
            errors,
        )

    # Encounter and discovery schemas, references, and coverage.
    unique(encounters, "key", "encounter", errors)
    unique(discoveries, "key", "discovery", errors)
    unique(discoveries, "name", "discovery", errors)
    discovery_keys = {d["key"] for d in discoveries}
    for discovery in discoveries:
        require(discovery.get("rarity") in RARITIES, f"discovery {discovery.get('key')} has unsupported rarity", errors)
        require(isinstance(discovery.get("enabled"), bool), f"discovery {discovery.get('key')} has invalid enabled flag", errors)
    referenced: set[str] = set()
    for encounter in encounters:
        require(encounter.get("rarity") in RARITIES, f"encounter {encounter.get('key')} has invalid rarity", errors)
        require(
            isinstance(encounter.get("min_level"), int) and 1 <= encounter["min_level"] <= 20,
            f"encounter {encounter.get('key')} has invalid min_level",
            errors,
        )
        choices = encounter.get("choices")
        require(isinstance(choices, list) and len(choices) >= 2, f"encounter {encounter.get('key')} needs at least two choices", errors)
        for choice in choices or []:
            for prefix in ("gold", "xp"):
                low, high = choice.get(f"{prefix}_min"), choice.get(f"{prefix}_max")
                require(
                    isinstance(low, int) and isinstance(high, int) and 0 <= low <= high,
                    f"encounter {encounter.get('key')} choice {choice.get('key')} has invalid {prefix}",
                    errors,
                )
            ref = choice.get("discovery_key")
            if ref:
                referenced.add(ref)
                require(ref in discovery_keys, f"encounter {encounter.get('key')} references missing discovery {ref}", errors)
    require(not (discovery_keys - referenced), f"orphan discoveries found: {sorted(discovery_keys - referenced)[:10]}", errors)

    # Timed potion consumables.
    try:
        potion_content = load_potion_content(BASE / "potion_items.json")
    except Exception as exc:
        errors.append(f"potion_items.json failed validation: {exc}")
        potion_content = None
    if potion_content is not None:
        potion_counts = Counter(item.effect_group for item in potion_content.items if item.enabled)
        require(sum(potion_counts.values()) == 90, "exactly 90 enabled potion definitions are required", errors)
        require(
            set(potion_counts) == set(EXPECTED_POTION_GROUPS),
            "potion effect groups must match the expected six groups",
            errors,
        )
        require(
            all(count == 15 for count in potion_counts.values()),
            "each potion effect group must contain 15 enabled tiers",
            errors,
        )
        require(
            potion_document.get("drop_rules", {}).get("max_drops_per_exploration") == 1,
            "potion drops must be capped at one per exploration",
            errors,
        )
    else:
        potion_counts = {}

    try:
        location_content = LocationService(BASE / "locations.json").locations
    except Exception as exc:
        errors.append(f"locations.json failed validation: {exc}")
        location_content = ()

    # Discord image assets.
    try:
        image_catalog = load_catalog(BASE / "image_assets.json", validate_files=True)
        image_registry = load_registry(BASE / "image_asset_registry.json")
        validate_gameplay_asset_references(image_catalog, BASE)
        settings = load_settings(require_token=False)
        require_registry = not settings.is_development
        if require_registry and settings.discord_asset_channel_id is None:
            errors.append("DISCORD_ASSET_CHANNEL_ID is required outside development")
        validate_registry_integrity(
            image_catalog,
            image_registry,
            require_required_assets=require_registry,
        )
    except Exception as exc:
        errors.append(f"image assets failed validation: {exc}")
        image_catalog = None
        image_registry = None

    content_coverage = {}
    for level in range(1, 21):
        eligible_encounters = [e for e in encounters if e.get("enabled", True) and e["min_level"] <= level]
        eligible_refs = {choice["discovery_key"] for e in eligible_encounters for choice in e["choices"] if choice.get("discovery_key")}
        content_coverage[level] = {
            "enemies": enemy_coverage[level],
            "encounters": len(eligible_encounters),
            "discoveries": len(eligible_refs),
            "equipment": equipment_coverage[min(400, dungeons[level - 1]["required_combat_level"])],
        }
        require(len(eligible_encounters) >= 10, f"dungeon {level} has insufficient encounters", errors)
        require(len(eligible_refs) >= 5, f"dungeon {level} has insufficient discovery content", errors)

    # Shop rarity bands total to 100 after normalization and improve over time.
    rarity_tables = {}
    previous_rare_plus = 0.0
    for representative in (1, 25, 50, 100, 200, 300, 400):
        band = progression["shop"]["rarity_bands"][0]
        for candidate in progression["shop"]["rarity_bands"]:
            if representative >= candidate["min_level"]:
                band = candidate
        total = sum(band["weights"].values())
        percentages = {rarity: band["weights"][rarity] / total * 100 for rarity in RARITIES}
        require(abs(sum(percentages.values()) - 100) < 1e-9, f"shop rarity percentages do not total 100 at level {representative}", errors)
        rare_plus = percentages["rare"] + percentages["epic"] + percentages["legendary"]
        require(rare_plus >= previous_rare_plus, f"high rarity chance regresses at level {representative}", errors)
        previous_rare_plus = rare_plus
        rarity_tables[representative] = {k: round(v, 2) for k, v in percentages.items()}

    report = {
        "passed": not errors,
        "errors": errors,
        "counts": {
            "dungeons": len(dungeons),
            "enemies": len(enemies),
            "equipment_total": len(equipment),
            "equipment_generated": len(generated),
            "equipment_descriptions": len(equipment_descriptions),
            "encounters": len(encounters),
            "discoveries": len(discoveries),
            "potions": sum(potion_counts.values()),
            "locations": len(location_content),
            "image_assets": len(image_catalog.assets) if image_catalog else 0,
            "registered_image_assets": len(image_registry.assets) if image_registry else 0,
        },
        "potions_by_group": dict(sorted(potion_counts.items())),
        "equipment_by_slot": dict(Counter(item["slot"] for item in equipment)),
        "equipment_by_rarity": dict(Counter(item["rarity"] for item in equipment)),
        "equipment_valid_options": {
            "minimum": min(equipment_coverage.values()),
            "maximum": max(equipment_coverage.values()),
            "level_1": equipment_coverage[1],
            "level_100": equipment_coverage[100],
            "level_200": equipment_coverage[200],
            "level_300": equipment_coverage[300],
            "level_400": equipment_coverage[400],
        },
        "shop_rarity_percentages": rarity_tables,
        "content_coverage": content_coverage,
    }
    return report


def main() -> None:
    report = validate()
    output = BASE / "content_validation.json"
    output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    if not report["passed"]:
        print(json.dumps(report, indent=2))
        raise SystemExit(1)
    print(json.dumps({"passed": True, **report["counts"]}, indent=2))


if __name__ == "__main__":
    main()
