from __future__ import annotations

import random
from collections import Counter
from collections.abc import Iterable, Mapping
from typing import Any

from bot.services.progression_content import PROGRESSION_CONTENT
from bot.services.progression_service import get_shop_rarity_weights


class ShopSelectionError(ValueError):
    pass


def select_shop_items(
    items: Iterable[Mapping[str, Any]],
    *,
    shop_level: int,
    rng: random.Random | None = None,
    stock_size: int | None = None,
) -> list[Mapping[str, Any]]:
    """Select a full shop from the valid item pool without empty rarity rolls.

    Rarity is weighted only among rarities that currently have valid, unselected
    items. Slot weighting favors underrepresented slots during the same refresh.
    """
    rng = rng or random.Random()
    size = stock_size or PROGRESSION_CONTENT.shop.stock_size
    if shop_level <= 0 or size <= 0:
        raise ShopSelectionError("shop_level and stock_size must be positive")

    valid = [
        item
        for item in items
        if bool(item)
        and int(item.get("min_level", 0)) <= shop_level <= int(item.get("max_level", -1))
        and isinstance(item.get("key"), str)
        and isinstance(item.get("rarity"), str)
        and isinstance(item.get("slot"), str)
    ]
    if not valid:
        # Graceful nearest-level fallback for corrupted or incomplete content.
        all_items = [item for item in items if isinstance(item.get("key"), str)]
        if not all_items:
            raise ShopSelectionError("No equipment definitions are available")
        nearest_distance = min(
            min(abs(shop_level - int(item.get("min_level", shop_level))), abs(shop_level - int(item.get("max_level", shop_level))))
            for item in all_items
        )
        valid = [
            item
            for item in all_items
            if min(abs(shop_level - int(item.get("min_level", shop_level))), abs(shop_level - int(item.get("max_level", shop_level))))
            == nearest_distance
        ]

    selected: list[Mapping[str, Any]] = []
    selected_keys: set[str] = set()
    slot_counts: Counter[str] = Counter()
    base_rarity_weights = get_shop_rarity_weights(shop_level)

    while len(selected) < min(size, len(valid)):
        remaining = [item for item in valid if str(item["key"]) not in selected_keys]
        by_rarity: dict[str, list[Mapping[str, Any]]] = {}
        for item in remaining:
            by_rarity.setdefault(str(item["rarity"]), []).append(item)
        available_rarities = list(by_rarity)
        if not available_rarities:
            break
        rarity = rng.choices(
            available_rarities,
            weights=[base_rarity_weights.get(value, 1) for value in available_rarities],
            k=1,
        )[0]
        candidates = by_rarity[rarity]
        slot_weights = [1.0 / (1 + slot_counts[str(item["slot"])]) for item in candidates]
        chosen = rng.choices(candidates, weights=slot_weights, k=1)[0]
        selected.append(chosen)
        selected_keys.add(str(chosen["key"]))
        slot_counts[str(chosen["slot"])] += 1

    return selected
