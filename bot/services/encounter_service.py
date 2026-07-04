from __future__ import annotations

import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Choice:
    key: str
    label: str
    result_text: str
    gold_min: int = 0
    gold_max: int = 0
    xp_min: int = 0
    xp_max: int = 0
    hero_effect: int = 0
    villain_effect: int = 0
    stability_effect: int = 0
    success: bool = True
    discovery_key: str | None = None
    weekly_progress: int = 1


@dataclass(frozen=True)
class Encounter:
    key: str
    title: str
    description: str
    category: str
    weight: int
    enabled: bool
    min_level: int
    rarity: str
    choices: list[Choice]


class ContentValidationError(ValueError):
    pass


class EncounterService:
    def __init__(self, content_path: Path | None = None) -> None:
        self.content_path = content_path or Path(__file__).parents[1] / "content" / "encounters.json"
        self._encounters = self._load()

    @property
    def encounters(self) -> list[Encounter]:
        return self._encounters

    def select(self, *, explore_level: int = 1, rng: random.Random | None = None) -> Encounter:
        rng = rng or random
        choices = [
            encounter
            for encounter in self._encounters
            if encounter.enabled and encounter.min_level <= explore_level
        ]
        if not choices:
            raise ContentValidationError("No enabled encounters are available")
        return rng.choices(choices, weights=[encounter.weight for encounter in choices], k=1)[0]

    def get(self, key: str) -> Encounter:
        for encounter in self._encounters:
            if encounter.key == key:
                return encounter
        raise KeyError(key)

    def _load(self) -> list[Encounter]:
        raw = json.loads(self.content_path.read_text(encoding="utf-8"))
        seen: set[str] = set()
        encounters: list[Encounter] = []
        for item in raw:
            key = _required_str(item, "key")
            if key in seen:
                raise ContentValidationError(f"Duplicate encounter key: {key}")
            seen.add(key)
            choices = [_choice(choice) for choice in item.get("choices", [])]
            if not 2 <= len(choices) <= 4:
                raise ContentValidationError(f"{key} must have two to four choices")
            encounters.append(
                Encounter(
                    key=key,
                    title=_required_str(item, "title"),
                    description=_required_str(item, "description"),
                    category=_required_str(item, "category"),
                    weight=int(item.get("weight", 1)),
                    enabled=bool(item.get("enabled", True)),
                    min_level=int(item.get("min_level", 1)),
                    rarity=str(item.get("rarity", "common")),
                    choices=choices,
                )
            )
        if len(encounters) < 20:
            raise ContentValidationError("At least 20 encounters are required")
        return encounters


def _choice(item: dict[str, Any]) -> Choice:
    return Choice(
        key=_required_str(item, "key"),
        label=_required_str(item, "label"),
        result_text=_required_str(item, "result_text"),
        gold_min=int(item.get("gold_min", 0)),
        gold_max=int(item.get("gold_max", item.get("gold_min", 0))),
        xp_min=int(item.get("xp_min", 0)),
        xp_max=int(item.get("xp_max", item.get("xp_min", 0))),
        hero_effect=int(item.get("hero_effect", 0)),
        villain_effect=int(item.get("villain_effect", 0)),
        stability_effect=int(item.get("stability_effect", 0)),
        success=bool(item.get("success", True)),
        discovery_key=item.get("discovery_key"),
        weekly_progress=int(item.get("weekly_progress", 1)),
    )


def _required_str(item: dict[str, Any], key: str) -> str:
    value = item.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ContentValidationError(f"Missing required string field: {key}")
    return value
