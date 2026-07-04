#!/usr/bin/env python3
"""Deterministically expand equipment.json for levels 1-450.

The generator preserves hand-authored items, removes prior generated items, and
rebuilds generated content from a fixed seed and a stat-budget formula.
"""

from __future__ import annotations

import json
import random
import re
from collections import Counter
from pathlib import Path

SEED = 20260703
CONTENT_DIR = Path(__file__).parents[1] / "content"
RARITY_MULTIPLIER = {
    "common": 1.00,
    "uncommon": 1.16,
    "rare": 1.36,
    "epic": 1.64,
    "legendary": 1.98,
}
RARITY_COST = {
    "common": 1.00,
    "uncommon": 1.12,
    "rare": 1.28,
    "epic": 1.50,
    "legendary": 1.78,
}
SLOTS = ("weapon", "shield", "helm", "gloves", "armor", "boots", "trinket")
RARITIES = tuple(RARITY_MULTIPLIER)
POWER_WEIGHTS = {"hp": 0.12, "attack": 2.0, "defense": 2.25, "speed": 1.25}
SLOT_PROFILES = {
    "weapon": {"hp": 0.05, "attack": 0.66, "defense": 0.07, "speed": 0.22},
    "shield": {"hp": 0.34, "attack": 0.03, "defense": 0.51, "speed": 0.12},
    "helm": {"hp": 0.22, "attack": 0.20, "defense": 0.30, "speed": 0.28},
    "gloves": {"hp": 0.04, "attack": 0.42, "defense": 0.14, "speed": 0.40},
    "armor": {"hp": 0.43, "attack": 0.02, "defense": 0.46, "speed": 0.09},
    "boots": {"hp": 0.12, "attack": 0.04, "defense": 0.14, "speed": 0.70},
    "trinket": {"hp": 0.24, "attack": 0.25, "defense": 0.25, "speed": 0.26},
}
SLOT_NOUNS = {
    "weapon": ("Blade", "Saber", "Pike", "Axe", "Glaive", "Dirk", "Hammer", "Spear"),
    "shield": ("Ward", "Bulwark", "Aegis", "Buckler", "Rampart", "Guard", "Barrier"),
    "helm": ("Helm", "Crown", "Visor", "Mask", "Coif", "Greathelm", "Hood"),
    "gloves": ("Grips", "Gauntlets", "Wraps", "Claws", "Knuckles", "Gloves", "Bracers"),
    "armor": ("Mail", "Cuirass", "Harness", "Plate", "Vestment", "Hauberk", "Carapace"),
    "boots": ("Boots", "Greaves", "Treads", "Sandals", "Sabatons", "Striders", "Footguards"),
    "trinket": ("Charm", "Idol", "Token", "Reliquary", "Compass", "Sigil", "Talisman"),
}
MATERIALS = (
    "Ashen",
    "Bronze",
    "Iron",
    "Silver",
    "Runed",
    "Obsidian",
    "Moonstone",
    "Starforged",
    "Emberglass",
    "Gravewood",
    "Stormsteel",
    "Dawnfire",
    "Voidglass",
    "Dragonbone",
    "Kingsilver",
    "Nightwoven",
    "Sunstone",
    "Deepdelve",
    "Oathbound",
    "Cryptiron",
    "Wyrmscale",
    "Frostbound",
    "Thunderforged",
    "Bloodstone",
    "Spiritwoven",
    "Gloomsteel",
    "Auric",
)
EPITHETS = (
    "Steward's",
    "Warden's",
    "Delver's",
    "Sentinel's",
    "Architect's",
    "Keeper's",
    "Vigilant",
    "Unbroken",
    "Cunning",
    "Patient",
    "Relentless",
    "Hidden",
    "Last",
    "First",
    "Silent",
    "Ironbound",
    "Wayward",
    "Resolute",
    "Ancient",
)
VIRTUES = (
    "the Deep Watch",
    "Measured Fury",
    "Quiet Corridors",
    "the Final Bell",
    "Dungeon Law",
    "the Long Vigil",
    "Balanced Scales",
    "the Lost Key",
    "Patient Stone",
    "the Ember Court",
    "Midnight Duty",
    "the Sealed Gate",
    "the Steward's Oath",
    "Unpaid Debts",
    "the Ninth Lock",
    "the Lower Halls",
    "Distant Thunder",
    "the Crownless King",
    "the Sleeping Forge",
    "the Old Compact",
    "the Moonlit Ledger",
    "the Last Patrol",
    "Secret Stairs",
    "the Hollow Throne",
)


def slugify(value: str) -> str:
    value = value.lower().replace("'", "")
    return re.sub(r"[^a-z0-9]+", "_", value).strip("_")


def availability(min_level: int, rarity: str) -> tuple[int, int]:
    if min_level < 300:
        return min_level, min_level + 14
    width = {
        "common": 34,
        "uncommon": 39,
        "rare": 44,
        "epic": 54,
        "legendary": 74,
    }[rarity]
    return min_level, min_level + width


def item_power(level: int, rarity: str, rng: random.Random) -> float:
    base = 5.0 + (0.55 * (max(1, level) ** 0.82))
    variation = rng.uniform(0.96, 1.04)
    return base * RARITY_MULTIPLIER[rarity] * variation


def allocate_stats(slot: str, power: float, rng: random.Random) -> dict[str, int]:
    profile = SLOT_PROFILES[slot]
    jittered = {stat: max(0.001, share * rng.uniform(0.92, 1.08)) for stat, share in profile.items()}
    total = sum(jittered.values())
    stats: dict[str, int] = {}
    for stat, share in jittered.items():
        allocated_power = power * (share / total)
        value = allocated_power / POWER_WEIGHTS[stat]
        stats[stat] = max(0, int(round(value)))
    # Every generated item must contribute meaningfully in its primary role.
    primary = max(profile, key=profile.get)
    stats[primary] = max(1, stats[primary])
    return stats


def make_name(slot: str, rarity: str, anchor: int, ordinal: int) -> str:
    # Index arithmetic provides deterministic variety without numbered duplicates.
    material = MATERIALS[(ordinal * 7 + anchor // 15) % len(MATERIALS)]
    noun = SLOT_NOUNS[slot][(ordinal * 5 + anchor // 10) % len(SLOT_NOUNS[slot])]
    epithet = EPITHETS[(ordinal * 11 + anchor // 20) % len(EPITHETS)]
    virtue = VIRTUES[(ordinal * 13 + anchor // 25) % len(VIRTUES)]
    if rarity in {"common", "uncommon"}:
        return f"{material} {noun} of {virtue}"
    if rarity == "rare":
        return f"{epithet} {material} {noun}"
    return f"{epithet} {material} {noun} of {virtue}"


def generate_items(existing_names: set[str], existing_keys: set[str]) -> list[dict[str, object]]:
    rng = random.Random(SEED)
    generated: list[dict[str, object]] = []
    anchors = list(range(1, 300, 15)) + [301, 326, 351, 376, 401]
    ordinal = 0
    for anchor in anchors:
        for slot in SLOTS:
            for rarity in RARITIES:
                ordinal += 1
                min_level, max_level = availability(anchor, rarity)
                midpoint = min_level + ((max_level - min_level) // 2)
                power = item_power(midpoint, rarity, rng)
                stats = allocate_stats(slot, power, rng)
                name = make_name(slot, rarity, anchor, ordinal)
                # Collisions are resolved with a lore suffix, never a number.
                if name in existing_names:
                    suffix = VIRTUES[(ordinal + 9) % len(VIRTUES)]
                    name = f"{name}, Covenant of {suffix}"
                key = f"generated_{slugify(name)}"
                if key in existing_keys:
                    key = f"{key}_{slugify(VIRTUES[(ordinal + 3) % len(VIRTUES)])}"
                cost_base = 20 + ((max(1, midpoint) ** 1.20) * 3.5) + (power * 12.0)
                cost = max(25, int(round(cost_base * RARITY_COST[rarity] * 1.55 / 5.0) * 5))
                item = {
                    "key": key,
                    "name": name,
                    "slot": slot,
                    "rarity": rarity,
                    "min_level": min_level,
                    "max_level": max_level,
                    "cost": cost,
                    "hp": stats["hp"],
                    "attack": stats["attack"],
                    "defense": stats["defense"],
                    "speed": stats["speed"],
                }
                generated.append(item)
                existing_names.add(name)
                existing_keys.add(key)
    return generated


def normalize_legacy_ranges(items: list[dict[str, object]]) -> None:
    max_by_rarity = {
        "common": 12,
        "uncommon": 18,
        "rare": 24,
        "epic": 32,
        "legendary": 38,
    }
    for item in items:
        if str(item.get("key", "")).startswith("generated_"):
            continue
        min_level = int(item["min_level"])
        item["max_level"] = max(min_level + 9, max_by_rarity[str(item["rarity"])])


def main() -> None:
    path = CONTENT_DIR / "equipment.json"
    current = json.loads(path.read_text(encoding="utf-8"))
    legacy = [item for item in current if not str(item.get("key", "")).startswith("generated_")]
    normalize_legacy_ranges(legacy)
    existing_names = {str(item["name"]) for item in legacy}
    existing_keys = {str(item["key"]) for item in legacy}
    generated = generate_items(existing_names, existing_keys)
    output = legacy + generated
    output.sort(key=lambda item: (int(item["min_level"]), str(item["slot"]), str(item["rarity"]), str(item["name"])))
    path.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    descriptions = {}
    for item in output:
        primary = max(("hp", "attack", "defense", "speed"), key=lambda stat: int(item[stat]) * POWER_WEIGHTS[stat])
        descriptions[item["key"]] = (
            f"{item['name']} is a {item['rarity']} {item['slot']} built for dungeon stewards "
            f"working through shop levels {item['min_level']}–{item['max_level']}. "
            f"Its strongest contribution is {primary}, with supporting attributes balanced to its tier."
        )
    (CONTENT_DIR / "equipment_descriptions.json").write_text(json.dumps(descriptions, indent=2) + "\n", encoding="utf-8")

    print(f"legacy={len(legacy)} generated={len(generated)} total={len(output)}")
    print("slots", dict(Counter(str(item["slot"]) for item in output)))
    print("rarities", dict(Counter(str(item["rarity"]) for item in output)))


if __name__ == "__main__":
    main()
