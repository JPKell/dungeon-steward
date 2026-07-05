from __future__ import annotations

import json
from pathlib import Path
from typing import Any

OUTPUT = Path(__file__).with_name("potion_items.json")

LEVEL_RANGES = [
    (1, 12),
    (9, 20),
    (17, 28),
    (25, 36),
    (33, 44),
    (41, 52),
    (49, 60),
    (57, 68),
    (65, 76),
    (73, 84),
    (81, 92),
    (89, 104),
    (101, 116),
    (113, 132),
    (125, 999),
]

TIER_DROP_WEIGHTS = [120, 105, 92, 80, 68, 58, 49, 41, 34, 28, 22, 17, 12, 8, 5]

RARITIES = [
    "common", "common", "common",
    "uncommon", "uncommon", "uncommon",
    "rare", "rare", "rare",
    "epic", "epic", "epic",
    "legendary", "legendary", "legendary",
]

POTION_DEFINITIONS: dict[str, dict[str, Any]] = {
    "xp": {
        "display_name": "Combat XP",
        "icon_key": "potion_xp",
        "weight_multiplier": 0.80,
        "names": [
            "Scholar's Sip",
            "Scribe's Draught",
            "Apprentice's Insight",
            "Archivist's Tonic",
            "Sageleaf Infusion",
            "Runekeeper's Elixir",
            "Loremaster's Distillate",
            "Oracle's Memory",
            "Magister's Cognition",
            "Seer's Revelation",
            "Astral Epiphany",
            "Ancient Mindfire",
            "Chronomancer's Insight",
            "Dragon-Sage's Revelation",
            "Elixir of Endless Study",
        ],
        "values": [0.04, 0.045, 0.05, 0.055, 0.06, 0.0675, 0.075, 0.0825, 0.09, 0.10, 0.11, 0.12, 0.13, 0.14, 0.15],
        "durations": [30, 32, 34, 36, 38, 40, 43, 46, 49, 52, 55, 58, 62, 66, 72],
    },
    "max_hp": {
        "display_name": "Maximum HP",
        "icon_key": "potion_hp",
        "weight_multiplier": 0.95,
        "names": [
            "Stoutroot Tonic",
            "Ironberry Draught",
            "Boarheart Brew",
            "Oakblood Tonic",
            "Trollbone Infusion",
            "Stoneheart Elixir",
            "Giant's Reserve",
            "Wyrmheart Draught",
            "Colossus Blood",
            "Titanroot Elixir",
            "Mountain's Pulse",
            "Leviathan Vitality",
            "Worldtree Sap",
            "Phoenix Heartblood",
            "Elixir of the Undying Steward",
        ],
        "values": [0.05, 0.0575, 0.065, 0.0725, 0.08, 0.09, 0.10, 0.11, 0.12, 0.13, 0.14, 0.15, 0.16, 0.17, 0.18],
        "durations": [35, 37, 39, 41, 43, 45, 48, 51, 54, 57, 60, 64, 68, 74, 80],
    },
    "healing": {
        "display_name": "Battle Recovery",
        "icon_key": "potion_healing",
        "weight_multiplier": 1.20,
        "names": [
            "Mosswater Remedy",
            "Redleaf Restorative",
            "Field Medic's Tonic",
            "Moonwell Draught",
            "Saint's Balm",
            "Trollmender's Brew",
            "Silverthorn Restorative",
            "Dawnwater Elixir",
            "Phoenix-Tear Tonic",
            "High Cleric's Reserve",
            "Celestial Renewal",
            "Lifewarden's Draught",
            "Sacred Spring Elixir",
            "Elixir of Returning Breath",
            "Ambrosia of the First Healer",
        ],
        "values": [0.0015, 0.0017, 0.0019, 0.0021, 0.0023, 0.0025, 0.0028, 0.0031, 0.0034, 0.0037, 0.0040, 0.0043, 0.0046, 0.0049, 0.0052],
        "caps": [1, 1, 2, 2, 3, 3, 4, 5, 6, 7, 8, 10, 12, 15, 18],
        "durations": [25, 27, 29, 31, 33, 35, 38, 41, 44, 47, 50, 54, 58, 64, 70],
    },
    "attack": {
        "display_name": "Attack",
        "icon_key": "potion_attack",
        "weight_multiplier": 1.00,
        "names": [
            "Emberbite Tonic",
            "Wolf-Fang Draught",
            "Raider's Courage",
            "Orcblood Infusion",
            "Berserker's Brew",
            "Redsteel Elixir",
            "Manticore Venom",
            "Warlord's Fury",
            "Dragonclaw Tonic",
            "Infernal Might",
            "Titan's Wrath",
            "Stormlord's Blood",
            "Godslayer's Resolve",
            "Worldbreaker Elixir",
            "Draught of the Final Blow",
        ],
        "values": [0.03, 0.035, 0.04, 0.045, 0.05, 0.055, 0.06, 0.0675, 0.075, 0.0825, 0.09, 0.0975, 0.105, 0.1125, 0.12],
        "durations": [30, 32, 34, 36, 38, 40, 43, 46, 49, 52, 55, 58, 62, 67, 75],
    },
    "defense": {
        "display_name": "Defense",
        "icon_key": "potion_defense",
        "weight_multiplier": 1.00,
        "names": [
            "Barkskin Tonic",
            "Boarhide Brew",
            "Ironbark Draught",
            "Stonewall Infusion",
            "Knight's Bulwark",
            "Graniteblood Elixir",
            "Golemhide Tonic",
            "Fortress Draught",
            "Dragonscale Infusion",
            "Adamant Guard",
            "Mountainfather's Aegis",
            "Titanplate Elixir",
            "Worldshield Tonic",
            "Immortal Bastion",
            "Draught of the Unbroken Gate",
        ],
        "values": [0.03, 0.035, 0.04, 0.045, 0.05, 0.055, 0.06, 0.0675, 0.075, 0.0825, 0.09, 0.0975, 0.105, 0.1125, 0.12],
        "durations": [30, 32, 34, 36, 38, 40, 43, 46, 49, 52, 55, 58, 62, 67, 75],
    },
    "luck": {
        "display_name": "Luck",
        "icon_key": "potion_luck",
        "weight_multiplier": 0.75,
        "names": [
            "Copper-Coin Cordial",
            "Rabbit's Foot Tonic",
            "Lucky Goblin's Brew",
            "Four-Leaf Infusion",
            "Smuggler's Fortune",
            "Mooncoin Elixir",
            "Trickster's Favor",
            "Fey-Touched Cordial",
            "Fortune-Teller's Draught",
            "Golden Serendipity",
            "Djinn's Favor",
            "Fateweaver's Elixir",
            "Dragon's Hoard Luck",
            "Lady Fortune's Reserve",
            "Elixir of the Impossible Prize",
        ],
        "values": [0.02, 0.024, 0.028, 0.032, 0.036, 0.04, 0.045, 0.05, 0.055, 0.06, 0.0675, 0.075, 0.0825, 0.09, 0.10],
        "durations": [30, 32, 34, 36, 38, 40, 42, 45, 48, 51, 54, 57, 60, 64, 70],
    },
}

TYPE_ORDER = ["xp", "max_hp", "healing", "attack", "defense", "luck"]


def percent(value: float) -> str:
    return f"{value * 100:g}%"


def make_effect(potion_type: str, value: float, tier_index: int) -> dict[str, Any]:
    if potion_type == "xp":
        return {
            "kind": "combat_xp_multiplier",
            "operation": "multiply_bonus",
            "bonus": value,
            "final_multiplier": round(1.0 + value, 4),
            "applies_to": ["defense_combat_xp"],
        }
    if potion_type == "max_hp":
        return {
            "kind": "max_hp_multiplier",
            "operation": "multiply_bonus",
            "bonus": value,
            "final_multiplier": round(1.0 + value, 4),
            "heals_on_activation": False,
        }
    if potion_type == "healing":
        cap = POTION_DEFINITIONS[potion_type]["caps"][tier_index]
        return {
            "kind": "heal_between_battles",
            "operation": "max_hp_percent_with_flat_cap",
            "max_hp_percent": value,
            "flat_cap": cap,
            "minimum_heal": 1,
            "trigger": "after_victory_before_next_battle",
        }
    if potion_type == "attack":
        return {
            "kind": "attack_multiplier",
            "operation": "multiply_bonus",
            "bonus": value,
            "final_multiplier": round(1.0 + value, 4),
        }
    if potion_type == "defense":
        return {
            "kind": "defense_multiplier",
            "operation": "multiply_bonus",
            "bonus": value,
            "final_multiplier": round(1.0 + value, 4),
        }
    if potion_type == "luck":
        return {
            "kind": "maximum_enemy_reward_chance",
            "operation": "proc_chance",
            "chance": value,
            "applies_to": ["combat_xp", "gold"],
            "proc_scope": "each_enemy_victory",
        }
    raise ValueError(f"Unknown potion type: {potion_type}")


def make_description(potion_type: str, value: float, tier_index: int, duration: int) -> str:
    if potion_type == "xp":
        return f"Increases combat XP earned from defeated enemies by {percent(value)} for {duration} minutes."
    if potion_type == "max_hp":
        return f"Increases maximum HP by {percent(value)} for {duration} minutes. It does not restore HP when consumed."
    if potion_type == "healing":
        cap = POTION_DEFINITIONS[potion_type]["caps"][tier_index]
        return (
            f"After each defense victory, restores {percent(value)} of current maximum HP, "
            f"up to {cap} HP, for {duration} minutes."
        )
    if potion_type == "attack":
        return f"Increases attack by {percent(value)} for {duration} minutes."
    if potion_type == "defense":
        return f"Increases defense by {percent(value)} for {duration} minutes."
    if potion_type == "luck":
        return (
            f"Each defeated enemy has a {percent(value)} chance to award its maximum possible "
            f"combat XP and gold for {duration} minutes."
        )
    raise ValueError(f"Unknown potion type: {potion_type}")


def build_items() -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for type_index, potion_type in enumerate(TYPE_ORDER, start=1):
        definition = POTION_DEFINITIONS[potion_type]
        for tier_index in range(15):
            tier = tier_index + 1
            minimum_level, maximum_level = LEVEL_RANGES[tier_index]
            value = definition["values"][tier_index]
            duration = definition["durations"][tier_index]
            drop_weight = max(
                1,
                int(round(TIER_DROP_WEIGHTS[tier_index] * definition["weight_multiplier"])),
            )
            items.append(
                {
                    "key": f"potion_{potion_type}_{tier:02d}",
                    "name": definition["names"][tier_index],
                    "category": "potion",
                    "potion_type": potion_type,
                    "effect_group": potion_type,
                    "tier": tier,
                    "rarity": RARITIES[tier_index],
                    "description": make_description(potion_type, value, tier_index, duration),
                    "icon_key": definition["icon_key"],
                    "duration_seconds": duration * 60,
                    "min_explore_level": minimum_level,
                    "max_explore_level": maximum_level,
                    "exploration_drop_weight": drop_weight,
                    "inventory_stack_limit": 99,
                    "consumable": True,
                    "enabled": True,
                    "sort_order": type_index * 100 + tier,
                    "effect": make_effect(potion_type, value, tier_index),
                }
            )
    return items


def build_document() -> dict[str, Any]:
    return {
        "schema_version": 1,
        "content_type": "timed_consumable_potions",
        "balance_intent": (
            "Potions are occasional tactical boosts. Their aggregate exploration drop rate, limited "
            "duration, three-effect active cap, and non-stacking effect groups are intended to make "
            "progression slightly easier without replacing equipment or long-term character growth."
        ),
        "drop_rules": {
            "eligibility_stat": "explore_level",
            "base_drop_chance": 0.0225,
            "successful_choice_bonus": 0.0025,
            "failed_choice_multiplier": 0.35,
            "dungeon_level_bonus_per_level_after_one": 0.0005,
            "encounter_rarity_bonus": {
                "common": 0.0,
                "uncommon": 0.001,
                "rare": 0.002,
                "epic": 0.003,
                "legendary": 0.004,
            },
            "maximum_drop_chance": 0.045,
            "max_drops_per_exploration": 1,
            "selection_method": "weighted_random_from_eligible_items",
            "item_weight_field": "exploration_drop_weight",
            "award_timing": "after_exploration_resolution",
        },
        "activation_rules": {
            "clock": "server_utc",
            "duration_runs_while_offline": True,
            "max_simultaneous_effect_groups": 3,
            "same_effect_group_policy": "replace_existing_effect",
            "replacement_requires_confirmation": True,
            "effects_are_not_retroactive": True,
            "active_at_boundary_rule": "activated_at <= battle_time < effective_ends_at",
            "healing_occurs_after_victory_only": True,
            "xp_potions_affect_defense_combat_xp_only": True,
            "luck_affects_enemy_gold_and_combat_xp": True,
        },
        "items": build_items(),
    }


if __name__ == "__main__":
    document = build_document()
    OUTPUT.write_text(json.dumps(document, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {len(document['items'])} potion items to {OUTPUT}")
