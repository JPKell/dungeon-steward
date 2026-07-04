from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

from bot.models import Player
from bot.services.progression_service import scale_shop_item_cost, scale_shop_item_stat

EQUIPMENT_SLOTS = ("weapon", "shield", "helm", "armor", "gloves", "trinket", "boots")
RARITIES = ("common", "uncommon", "rare", "epic", "legendary")


@dataclass(frozen=True)
class CombatStats:
    max_hp: int
    attack: int
    defense: int
    speed: int


@dataclass(frozen=True)
class EquipmentItem:
    key: str
    name: str
    slot: str
    rarity: str
    min_level: int
    max_level: int
    cost: int
    hp: int
    attack: int
    defense: int
    speed: int
    description: str | None = None


class EquipmentContentError(ValueError):
    pass


class EquipmentService:
    def __init__(self, content_path: Path | None = None) -> None:
        self.content_path = content_path or Path(__file__).parents[1] / "content" / "equipment.json"
        self.description_path = self.content_path.with_name("equipment_descriptions.json")
        self._descriptions = self._load_descriptions()
        self._items = self._load()
        self._by_key = {item.key: item for item in self._items}

    @property
    def items(self) -> list[EquipmentItem]:
        return self._items

    def get(self, key: str, *, combat_level: int | None = None) -> EquipmentItem:
        try:
            item = self._by_key[key]
        except KeyError as error:
            raise EquipmentContentError(f"Unknown equipment item: {key}") from error
        if combat_level is None:
            return item
        return self.scaled_for_combat_level(item, combat_level)

    def get_or_none(self, key: str | None, *, combat_level: int | None = None) -> EquipmentItem | None:
        if key is None:
            return None
        item = self._by_key.get(key)
        if item is None or combat_level is None:
            return item
        return self.scaled_for_combat_level(item, combat_level)

    def eligible_for_level(self, combat_level: int) -> list[EquipmentItem]:
        level = max(1, combat_level)
        return [item for item in self._items if item.min_level <= level <= item.max_level]

    def get_player_equipment(self, player: Player) -> dict[str, EquipmentItem | None]:
        return {slot: self.get_or_none(getattr(player, slot), combat_level=player.combat_level) for slot in EQUIPMENT_SLOTS}

    def get_equipment_stat_bonuses(self, player: Player) -> dict[str, int]:
        bonuses = _empty_bonuses()
        for item in self.get_player_equipment(player).values():
            if item is None:
                continue
            bonuses["attack"] += item.attack
            bonuses["defense"] += item.defense
            bonuses["speed"] += item.speed
            bonuses["max_hp"] += item.hp
        return bonuses

    def _load(self) -> list[EquipmentItem]:
        raw = json.loads(self.content_path.read_text(encoding="utf-8"))
        if not isinstance(raw, list):
            raise EquipmentContentError("Equipment content must be a list")
        seen: set[str] = set()
        items: list[EquipmentItem] = []
        for entry in raw:
            if not isinstance(entry, dict):
                raise EquipmentContentError("Equipment entries must be objects")
            item = _item(entry, description=self._descriptions.get(_entry_key(entry)))
            if item.key in seen:
                raise EquipmentContentError(f"Duplicate equipment key: {item.key}")
            seen.add(item.key)
            items.append(item)
        if len(items) < 30:
            raise EquipmentContentError("At least 30 equipment items are required")
        return items

    def _load_descriptions(self) -> dict[str, str]:
        if not self.description_path.exists():
            return {}
        raw = json.loads(self.description_path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise EquipmentContentError("Equipment descriptions content must be an object")
        descriptions: dict[str, str] = {}
        for key, value in raw.items():
            if not isinstance(key, str) or not isinstance(value, str):
                raise EquipmentContentError("Equipment descriptions must map item keys to text")
            descriptions[key] = value.strip()
        return descriptions

    def scaled_for_combat_level(self, item: EquipmentItem, combat_level: int) -> EquipmentItem:
        level = max(1, combat_level)
        return replace(
            item,
            cost=scale_shop_item_cost(item.cost, level),
            hp=scale_shop_item_stat(item.hp, level),
            attack=scale_shop_item_stat(item.attack, level),
            defense=scale_shop_item_stat(item.defense, level),
            speed=scale_shop_item_stat(item.speed, level),
        )


def get_equipment_stat_bonuses(player: Player) -> dict[str, int]:
    return EquipmentService().get_equipment_stat_bonuses(player)


def get_effective_combat_stats(player: Player) -> CombatStats:
    bonuses = get_equipment_stat_bonuses(player)
    return CombatStats(
        max_hp=max(1, player.max_hp + bonuses["max_hp"]),
        attack=max(1, player.attack + bonuses["attack"]),
        defense=max(0, player.defense + bonuses["defense"]),
        speed=max(1, player.speed + bonuses["speed"]),
    )


def _empty_bonuses() -> dict[str, int]:
    return {
        "attack": 0,
        "defense": 0,
        "speed": 0,
        "max_hp": 0,
    }


def _entry_key(entry: dict[str, Any]) -> str:
    value = entry.get("key")
    return value.strip() if isinstance(value, str) else ""


def _item(entry: dict[str, Any], *, description: str | None = None) -> EquipmentItem:
    item = EquipmentItem(
        key=_required_str(entry, "key"),
        name=_required_str(entry, "name"),
        slot=_required_str(entry, "slot"),
        rarity=_required_str(entry, "rarity"),
        min_level=_required_int(entry, "min_level"),
        max_level=_required_int(entry, "max_level"),
        cost=_required_int(entry, "cost"),
        hp=_required_int(entry, "hp"),
        attack=_required_int(entry, "attack"),
        defense=_required_int(entry, "defense"),
        speed=_required_int(entry, "speed"),
        description=description,
    )
    if item.slot not in EQUIPMENT_SLOTS:
        raise EquipmentContentError(f"{item.key} has invalid slot: {item.slot}")
    if item.rarity not in RARITIES:
        raise EquipmentContentError(f"{item.key} has invalid rarity: {item.rarity}")
    if item.min_level < 1 or item.max_level < item.min_level:
        raise EquipmentContentError(f"{item.key} has invalid level range")
    if item.cost <= 0:
        raise EquipmentContentError(f"{item.key} must have a positive cost")
    if min(item.hp, item.attack, item.defense, item.speed) < 0:
        raise EquipmentContentError(f"{item.key} cannot have negative stats")
    return item


def _required_str(entry: dict[str, Any], field: str) -> str:
    value = entry.get(field)
    if not isinstance(value, str) or not value.strip():
        raise EquipmentContentError(f"Equipment item missing string field: {field}")
    return value.strip()


def _required_int(entry: dict[str, Any], field: str) -> int:
    value = entry.get(field)
    if not isinstance(value, int):
        raise EquipmentContentError(f"Equipment item missing integer field: {field}")
    return value
