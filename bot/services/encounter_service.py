from __future__ import annotations

import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from bot.models import ContentEncounter, ContentEncounterChoice


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
    def __init__(
        self,
        content_path: Path | None = None,
        *,
        document: list[Any] | None = None,
    ) -> None:
        self.content_path = content_path or Path(__file__).parents[1] / "content" / "encounters.json"
        self._document = document
        self._encounters = self._load()

    @property
    def encounters(self) -> list[Encounter]:
        return self._encounters

    def select(
        self,
        *,
        session: Session | None = None,
        explore_level: int = 1,
        dungeon_level: int | None = None,
        rng: random.Random | None = None,
    ) -> Encounter:
        rng = rng or random
        content_level = max(1, int(dungeon_level if dungeon_level is not None else min(explore_level, 20)))
        if session is not None:
            encounter = self._select_from_database(session, content_level=content_level, rng=rng)
            if encounter is not None:
                return encounter
        choices = [
            encounter
            for encounter in self._encounters
            if encounter.enabled and encounter.min_level <= content_level
        ]
        if not choices:
            raise ContentValidationError("No enabled encounters are available")
        return rng.choices(choices, weights=[encounter.weight for encounter in choices], k=1)[0]

    def get(self, key: str, *, session: Session | None = None) -> Encounter:
        if session is not None:
            encounter = self._get_from_database(session, key)
            if encounter is not None:
                return encounter
        for encounter in self._encounters:
            if encounter.key == key:
                return encounter
        raise KeyError(key)

    def get_resolution(
        self,
        session: Session,
        *,
        encounter_key: str,
        choice_key: str,
    ) -> tuple[Encounter, Choice]:
        row = session.execute(
            select(ContentEncounter, ContentEncounterChoice)
            .join(ContentEncounterChoice, ContentEncounterChoice.encounter_id == ContentEncounter.id)
            .where(
                ContentEncounter.key == encounter_key,
                ContentEncounterChoice.key == choice_key,
            )
        ).one_or_none()
        if row is not None:
            encounter_row, choice_row = row
            choice = _choice_from_database_row(choice_row)
            return _encounter_from_database_row(encounter_row, [choice]), choice

        if _database_has_encounters(session):
            raise KeyError(choice_key)

        encounter = self.get(encounter_key)
        choice = next((candidate for candidate in encounter.choices if candidate.key == choice_key), None)
        if choice is None:
            raise KeyError(choice_key)
        return encounter, choice

    def _select_from_database(
        self,
        session: Session,
        *,
        content_level: int,
        rng: random.Random | Any,
    ) -> Encounter | None:
        rows = session.scalars(
            select(ContentEncounter)
            .where(ContentEncounter.enabled.is_(True), ContentEncounter.min_level <= content_level)
            .order_by(ContentEncounter.sort_order, ContentEncounter.id)
        ).all()
        if not rows:
            return None
        selected = rng.choices(rows, weights=[row.weight for row in rows], k=1)[0]
        choices = session.scalars(
            select(ContentEncounterChoice)
            .where(ContentEncounterChoice.encounter_id == selected.id)
            .order_by(ContentEncounterChoice.sort_order, ContentEncounterChoice.id)
        ).all()
        if not choices:
            raise ContentValidationError(f"{selected.key} has no normalized choices")
        return _encounter_from_database_row(
            selected,
            [_choice_from_database_row(choice) for choice in choices],
        )

    def _get_from_database(self, session: Session, key: str) -> Encounter | None:
        row = session.scalar(
            select(ContentEncounter)
            .options(selectinload(ContentEncounter.choices))
            .where(ContentEncounter.key == key)
        )
        if row is None:
            return None
        return _encounter_from_database_row(
            row,
            [_choice_from_database_row(choice) for choice in row.choices],
        )

    def _load(self) -> list[Encounter]:
        raw = self._document
        if raw is None:
            raw = _ENCOUNTER_DOCUMENT
        if raw is None:
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


def _encounter_from_database_row(row: ContentEncounter, choices: list[Choice]) -> Encounter:
    return Encounter(
        key=row.key,
        title=row.title,
        description=row.description,
        category=row.category,
        weight=row.weight,
        enabled=row.enabled,
        min_level=row.min_level,
        rarity=row.rarity,
        choices=choices,
    )


def _choice_from_database_row(row: ContentEncounterChoice) -> Choice:
    return Choice(
        key=row.key,
        label=row.label,
        result_text=row.result_text,
        gold_min=row.gold_min,
        gold_max=row.gold_max,
        xp_min=row.xp_min,
        xp_max=row.xp_max,
        hero_effect=row.hero_effect,
        villain_effect=row.villain_effect,
        stability_effect=row.stability_effect,
        success=row.success,
        discovery_key=row.discovery_key,
        weekly_progress=row.weekly_progress,
    )


def _database_has_encounters(session: Session) -> bool:
    count = session.scalar(select(func.count()).select_from(ContentEncounter))
    return bool(count)


def _required_str(item: dict[str, Any], key: str) -> str:
    value = item.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ContentValidationError(f"Missing required string field: {key}")
    return value


_ENCOUNTER_DOCUMENT: list[Any] | None = None


def refresh_encounter_content(document: list[Any]) -> None:
    global _ENCOUNTER_DOCUMENT
    _ENCOUNTER_DOCUMENT = document
