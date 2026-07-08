from __future__ import annotations

import json
import random
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from bot.models import Player, PotionActivation, PotionInventoryStack
from bot.services.equipment_service import CombatStats
from bot.utils.time import ensure_utc, human_duration, utc_now

EXPECTED_POTION_GROUPS = ("xp", "max_hp", "healing", "attack", "defense", "luck")
SUPPORTED_SCHEMA_VERSION = 1
POTION_TYPE_EMOJIS = {
    "xp": "📘",
    "max_hp": "❤️",
    "healing": "💚",
    "attack": "⚔️",
    "defense": "🛡️",
    "luck": "🍀",
}


class PotionContentError(ValueError):
    pass


class PotionInventoryError(Exception):
    pass


class PotionNotFoundError(PotionInventoryError):
    pass


class PotionNotOwnedError(PotionInventoryError):
    pass


class PotionReplacementRequired(PotionInventoryError):
    def __init__(self, *, requested: PotionItem, active: ActivePotion) -> None:
        self.requested = requested
        self.active = active
        super().__init__(f"{active.item.name} is already active for {requested.effect_group}")


class PotionActiveSlotLimitError(PotionInventoryError):
    def __init__(self, active: tuple[ActivePotion, ...]) -> None:
        self.active = active
        super().__init__("Maximum active potion effect groups reached")


@dataclass(frozen=True)
class PotionDropRules:
    base_drop_chance: float
    successful_choice_bonus: float
    failed_choice_multiplier: float
    dungeon_level_bonus_per_level_after_one: float
    encounter_rarity_bonus: Mapping[str, float]
    maximum_drop_chance: float
    max_drops_per_exploration: int


@dataclass(frozen=True)
class PotionActivationRules:
    max_simultaneous_effect_groups: int
    same_effect_group_policy: str
    replacement_requires_confirmation: bool


@dataclass(frozen=True)
class PotionItem:
    key: str
    name: str
    category: str
    potion_type: str
    effect_group: str
    tier: int
    rarity: str
    description: str
    icon_key: str
    duration_seconds: int
    min_explore_level: int
    max_explore_level: int
    exploration_drop_weight: int
    inventory_stack_limit: int
    consumable: bool
    enabled: bool
    sort_order: int
    effect: Mapping[str, Any]
    thumbnail_asset: str | None = None


@dataclass(frozen=True)
class PotionContent:
    schema_version: int
    drop_rules: PotionDropRules
    activation_rules: PotionActivationRules
    items: tuple[PotionItem, ...]
    by_key: Mapping[str, PotionItem]

    def get(self, key: str) -> PotionItem:
        try:
            return self.by_key[key]
        except KeyError as error:
            raise PotionNotFoundError(f"Unknown potion item: {key}") from error

    def eligible_for_explore_level(self, explore_level: int) -> tuple[PotionItem, ...]:
        level = max(1, int(explore_level))
        return tuple(
            item
            for item in self.items
            if item.enabled and item.min_explore_level <= level <= item.max_explore_level
        )


@dataclass(frozen=True)
class ActivePotion:
    activation: PotionActivation
    item: PotionItem

    @property
    def effect_group(self) -> str:
        return self.item.effect_group


@dataclass(frozen=True)
class PotionInventoryEntry:
    stack: PotionInventoryStack
    item: PotionItem


@dataclass(frozen=True)
class PotionUseResult:
    item: PotionItem
    activation: PotionActivation
    idempotent: bool = False


class PotionService:
    def __init__(self, *, content: PotionContent | None = None) -> None:
        self.content = content or POTION_CONTENT

    def get(self, key: str) -> PotionItem:
        return self.content.get(key)

    def drop_chance(self, *, dungeon_level: int, encounter_rarity: str, successful: bool) -> float:
        rules = self.content.drop_rules
        chance = (
            rules.base_drop_chance
            + rules.successful_choice_bonus
            + max(0, int(dungeon_level) - 1) * rules.dungeon_level_bonus_per_level_after_one
            + rules.encounter_rarity_bonus.get(encounter_rarity, 0.0)
        )
        if not successful:
            chance *= rules.failed_choice_multiplier
        return min(rules.maximum_drop_chance, chance)

    def select_drop_item(
        self,
        *,
        explore_level: int,
        rng: random.Random | Any | None = None,
    ) -> PotionItem | None:
        rng = rng or random
        eligible = self.content.eligible_for_explore_level(explore_level)
        if not eligible:
            return None
        return rng.choices(eligible, weights=[item.exploration_drop_weight for item in eligible], k=1)[0]

    def maybe_award_exploration_drop(
        self,
        session: Session,
        player: Player,
        *,
        dungeon_level: int,
        encounter_rarity: str,
        successful: bool,
        rng: random.Random | Any | None = None,
    ) -> PotionItem | None:
        rng = rng or random
        chance = self.drop_chance(
            dungeon_level=dungeon_level,
            encounter_rarity=encounter_rarity,
            successful=successful,
        )
        if rng.random() >= chance:
            return None
        item = self.select_drop_item(explore_level=player.explore_level, rng=rng)
        if item is None:
            return None
        self.add_drop(session, player, item.key)
        return item

    def add_drop(
        self,
        session: Session,
        player: Player,
        item_key: str,
        *,
        amount: int = 1,
    ) -> PotionInventoryStack:
        if amount <= 0:
            raise ValueError("Potion drop amount must be positive")
        item = self.content.get(item_key)
        stack = session.scalar(
            select(PotionInventoryStack)
            .where(
                PotionInventoryStack.player_id == player.id,
                PotionInventoryStack.item_key == item.key,
            )
            .with_for_update()
        )
        if stack is None:
            stack = PotionInventoryStack(player_id=player.id, item_key=item.key, quantity=0)
            session.add(stack)
            session.flush()
        stack.quantity = min(item.inventory_stack_limit, int(stack.quantity or 0) + amount)
        session.flush()
        return stack

    def consume(
        self,
        session: Session,
        player: Player,
        item_key: str,
        *,
        idempotency_token: str,
        now: datetime | None = None,
    ) -> PotionUseResult:
        if not idempotency_token:
            raise ValueError("Potion consumption requires an idempotency token")
        now = ensure_utc(now or utc_now())
        existing = session.scalar(
            select(PotionActivation).where(
                PotionActivation.player_id == player.id,
                PotionActivation.idempotency_token == idempotency_token,
            )
        )
        if existing is not None:
            return PotionUseResult(
                item=self.content.get(existing.item_key),
                activation=existing,
                idempotent=True,
            )

        item = self.content.get(item_key)
        stack = session.scalar(
            select(PotionInventoryStack)
            .where(
                PotionInventoryStack.player_id == player.id,
                PotionInventoryStack.item_key == item.key,
            )
            .with_for_update()
        )
        if stack is None or int(stack.quantity or 0) <= 0:
            raise PotionNotOwnedError(f"You do not have {item.name}.")

        active = self.active_effects_at(session, player, now)
        active_by_group = {effect.effect_group: effect for effect in active}
        replaced = active_by_group.get(item.effect_group)
        if replaced is not None:
            raise PotionReplacementRequired(requested=item, active=replaced)
        if replaced is None and len(active_by_group) >= self.content.activation_rules.max_simultaneous_effect_groups:
            raise PotionActiveSlotLimitError(active)

        stack.quantity -= 1
        expires_at = now + timedelta(seconds=item.duration_seconds)
        activation = PotionActivation(
            player_id=player.id,
            item_key=item.key,
            effect_group=item.effect_group,
            tier=item.tier,
            activated_at=now,
            original_expires_at=expires_at,
            effective_ends_at=expires_at,
            idempotency_token=idempotency_token,
        )
        session.add(activation)
        session.flush()
        return PotionUseResult(item=item, activation=activation)

    def inventory_entries(self, session: Session, player: Player) -> tuple[PotionInventoryEntry, ...]:
        stacks = session.scalars(
            select(PotionInventoryStack)
            .where(PotionInventoryStack.player_id == player.id, PotionInventoryStack.quantity > 0)
            .order_by(PotionInventoryStack.item_key)
        ).all()
        entries: list[PotionInventoryEntry] = []
        for stack in stacks:
            try:
                item = self.content.get(stack.item_key)
            except PotionNotFoundError:
                continue
            entries.append(PotionInventoryEntry(stack=stack, item=item))
        return tuple(sorted(entries, key=lambda entry: (entry.item.sort_order, entry.item.name)))

    def active_effects_at(
        self,
        session: Session,
        player: Player,
        at: datetime | None = None,
    ) -> tuple[ActivePotion, ...]:
        at = ensure_utc(at or utc_now())
        activations = session.scalars(
            select(PotionActivation)
            .where(
                PotionActivation.player_id == player.id,
                PotionActivation.activated_at <= at,
                PotionActivation.effective_ends_at > at,
            )
            .order_by(PotionActivation.activated_at, PotionActivation.id)
        ).all()
        return self.active_from_history(activations, at)

    def activation_history(
        self,
        session: Session,
        player: Player,
        *,
        start: datetime,
        end: datetime,
    ) -> tuple[PotionActivation, ...]:
        start = ensure_utc(start)
        end = ensure_utc(end)
        if end < start:
            start, end = end, start
        return tuple(
            session.scalars(
                select(PotionActivation)
                .where(
                    PotionActivation.player_id == player.id,
                    PotionActivation.activated_at < end,
                    PotionActivation.effective_ends_at > start,
                )
                .order_by(PotionActivation.activated_at, PotionActivation.id)
            ).all()
        )

    def active_from_history(
        self,
        history: Iterable[PotionActivation],
        at: datetime,
    ) -> tuple[ActivePotion, ...]:
        at = ensure_utc(at)
        active_by_group: dict[str, ActivePotion] = {}
        for activation in history:
            if not _activation_applies(activation, at):
                continue
            try:
                item = self.content.get(activation.item_key)
            except PotionNotFoundError:
                continue
            current = active_by_group.get(item.effect_group)
            if current is None or _activation_sort_key(activation) >= _activation_sort_key(current.activation):
                active_by_group[item.effect_group] = ActivePotion(activation=activation, item=item)
        return tuple(active_by_group[group] for group in sorted(active_by_group))

    def apply_effects_to_stats(
        self,
        stats: CombatStats,
        active_effects: Iterable[ActivePotion],
    ) -> CombatStats:
        max_hp = stats.max_hp
        attack = stats.attack
        defense = stats.defense
        for active in active_effects:
            effect = active.item.effect
            kind = effect["kind"]
            if kind == "max_hp_multiplier":
                max_hp = max(1, int(round(max_hp * float(effect["final_multiplier"]))))
            elif kind == "attack_multiplier":
                attack = max(1, int(round(attack * float(effect["final_multiplier"]))))
            elif kind == "defense_multiplier":
                defense = max(0, int(round(defense * float(effect["final_multiplier"]))))
        return CombatStats(max_hp=max_hp, attack=attack, defense=defense, speed=stats.speed)

    def combat_xp_multiplier(self, active_effects: Iterable[ActivePotion]) -> float:
        multiplier = 1.0
        for active in active_effects:
            if active.item.effect["kind"] == "combat_xp_multiplier":
                multiplier *= float(active.item.effect["final_multiplier"])
        return multiplier

    def luck_chance(self, active_effects: Iterable[ActivePotion]) -> float:
        for active in active_effects:
            if active.item.effect["kind"] == "maximum_enemy_reward_chance":
                return float(active.item.effect["chance"])
        return 0.0

    def healing_amount(self, active_effects: Iterable[ActivePotion], *, active_max_hp: int) -> int:
        for active in active_effects:
            effect = active.item.effect
            if effect["kind"] != "heal_between_battles":
                continue
            percent_heal = int(round(max(1, active_max_hp) * float(effect["max_hp_percent"])))
            return min(int(effect["flat_cap"]), max(int(effect["minimum_heal"]), percent_heal))
        return 0

    def effect_summary(self, item: PotionItem) -> str:
        effect = item.effect
        kind = effect["kind"]
        if kind == "combat_xp_multiplier":
            return f"+{_percent(effect['bonus'])} Combat XP"
        if kind == "max_hp_multiplier":
            return f"+{_percent(effect['bonus'])} max HP"
        if kind == "attack_multiplier":
            return f"+{_percent(effect['bonus'])} ATK"
        if kind == "defense_multiplier":
            return f"+{_percent(effect['bonus'])} DEF"
        if kind == "maximum_enemy_reward_chance":
            return f"{_percent(effect['chance'])} max reward chance"
        if kind == "heal_between_battles":
            return f"Heal up to {effect['flat_cap']} HP after victories"
        return item.description

    def active_slot_usage(self, active_effects: Iterable[ActivePotion]) -> str:
        used = len({active.effect_group for active in active_effects})
        maximum = self.content.activation_rules.max_simultaneous_effect_groups
        return f"{used}/{maximum} effect groups active"

    def format_item_line(self, item: PotionItem) -> str:
        emoji = POTION_TYPE_EMOJIS.get(item.effect_group, "🧪")
        return f"{emoji} {item.name} T{item.tier} - {self.effect_summary(item)} for {human_duration(item.duration_seconds)}"


def load_potion_content(
    path: Path | None = None,
    *,
    document: dict[str, Any] | None = None,
) -> PotionContent:
    if document is None:
        content_path = path or _default_content_path("potion_items.json")
        raw = json.loads(content_path.read_text(encoding="utf-8"))
    else:
        raw = document
    if not isinstance(raw, dict):
        raise PotionContentError("Potion content must be an object")

    schema_version = _required_int(raw, "schema_version")
    if schema_version != SUPPORTED_SCHEMA_VERSION:
        raise PotionContentError(f"Unsupported potion schema version: {schema_version}")
    if raw.get("content_type") != "timed_consumable_potions":
        raise PotionContentError("Potion content_type must be timed_consumable_potions")

    drop_rules = _drop_rules(raw.get("drop_rules"))
    activation_rules = _activation_rules(raw.get("activation_rules"))
    item_entries = raw.get("items")
    if not isinstance(item_entries, list):
        raise PotionContentError("Potion items must be a list")

    items = tuple(_potion_item(entry) for entry in item_entries)
    _validate_items(items)
    by_key = {item.key: item for item in items}
    return PotionContent(
        schema_version=schema_version,
        drop_rules=drop_rules,
        activation_rules=activation_rules,
        items=items,
        by_key=by_key,
    )


def _default_content_path(filename: str) -> Path:
    return Path(__file__).parents[1] / "content" / filename


def _drop_rules(value: Any) -> PotionDropRules:
    if not isinstance(value, dict):
        raise PotionContentError("Potion drop_rules must be an object")
    rarity_bonus = value.get("encounter_rarity_bonus")
    if not isinstance(rarity_bonus, dict) or not rarity_bonus:
        raise PotionContentError("Potion drop rules require encounter_rarity_bonus")
    rules = PotionDropRules(
        base_drop_chance=_required_number(value, "base_drop_chance"),
        successful_choice_bonus=_required_number(value, "successful_choice_bonus"),
        failed_choice_multiplier=_required_number(value, "failed_choice_multiplier"),
        dungeon_level_bonus_per_level_after_one=_required_number(value, "dungeon_level_bonus_per_level_after_one"),
        encounter_rarity_bonus={str(key): float(amount) for key, amount in rarity_bonus.items()},
        maximum_drop_chance=_required_number(value, "maximum_drop_chance"),
        max_drops_per_exploration=_required_int(value, "max_drops_per_exploration"),
    )
    if rules.base_drop_chance < 0 or rules.maximum_drop_chance <= 0:
        raise PotionContentError("Potion drop chances must be positive")
    if not 0 <= rules.failed_choice_multiplier <= 1:
        raise PotionContentError("Potion failed_choice_multiplier must be between 0 and 1")
    if rules.max_drops_per_exploration != 1:
        raise PotionContentError("Potion drops must be capped at one per exploration")
    return rules


def _activation_rules(value: Any) -> PotionActivationRules:
    if not isinstance(value, dict):
        raise PotionContentError("Potion activation_rules must be an object")
    rules = PotionActivationRules(
        max_simultaneous_effect_groups=_required_int(value, "max_simultaneous_effect_groups"),
        same_effect_group_policy=_required_str(value, "same_effect_group_policy"),
        replacement_requires_confirmation=bool(value.get("replacement_requires_confirmation")),
    )
    if rules.max_simultaneous_effect_groups <= 0:
        raise PotionContentError("Potion active group limit must be positive")
    if rules.same_effect_group_policy != "replace_existing_effect":
        raise PotionContentError("Unsupported same-effect-group potion policy")
    if not rules.replacement_requires_confirmation:
        raise PotionContentError("Potion replacements must require confirmation")
    return rules


def _potion_item(entry: Any) -> PotionItem:
    if not isinstance(entry, dict):
        raise PotionContentError("Potion item entries must be objects")
    effect = entry.get("effect")
    if not isinstance(effect, dict):
        raise PotionContentError(f"Potion {entry.get('key')} effect must be an object")
    return PotionItem(
        key=_required_str(entry, "key"),
        name=_required_str(entry, "name"),
        category=_required_str(entry, "category"),
        potion_type=_required_str(entry, "potion_type"),
        effect_group=_required_str(entry, "effect_group"),
        tier=_required_int(entry, "tier"),
        rarity=_required_str(entry, "rarity"),
        description=_required_str(entry, "description"),
        icon_key=_required_str(entry, "icon_key"),
        duration_seconds=_required_int(entry, "duration_seconds"),
        min_explore_level=_required_int(entry, "min_explore_level"),
        max_explore_level=_required_int(entry, "max_explore_level"),
        exploration_drop_weight=_required_int(entry, "exploration_drop_weight"),
        inventory_stack_limit=_required_int(entry, "inventory_stack_limit"),
        consumable=bool(entry.get("consumable")),
        enabled=bool(entry.get("enabled")),
        sort_order=_required_int(entry, "sort_order"),
        effect=dict(effect),
        thumbnail_asset=_optional_str(entry, "thumbnail_asset"),
    )


def _validate_items(items: tuple[PotionItem, ...]) -> None:
    enabled = [item for item in items if item.enabled]
    if len(enabled) != 90:
        raise PotionContentError(f"Expected 90 enabled potion definitions, found {len(enabled)}")
    keys = [item.key for item in items]
    names = [item.name for item in items]
    if len(keys) != len(set(keys)):
        raise PotionContentError("Potion keys must be unique")
    if len(names) != len(set(names)):
        raise PotionContentError("Potion names must be unique")

    by_group: dict[str, list[PotionItem]] = defaultdict(list)
    for item in enabled:
        _validate_item_basics(item)
        _validate_effect(item)
        by_group[item.effect_group].append(item)

    if set(by_group) != set(EXPECTED_POTION_GROUPS):
        raise PotionContentError(f"Potion groups must be exactly {EXPECTED_POTION_GROUPS}")
    for group in EXPECTED_POTION_GROUPS:
        group_items = sorted(by_group[group], key=lambda item: item.tier)
        if [item.tier for item in group_items] != list(range(1, 16)):
            raise PotionContentError(f"Potion group {group} must have tiers 1 through 15")
        strengths = [_effect_strength(item) for item in group_items]
        durations = [item.duration_seconds for item in group_items]
        for index in range(1, len(group_items)):
            if strengths[index] < strengths[index - 1]:
                raise PotionContentError(f"Potion group {group} effect strength decreases at tier {index + 1}")
            if durations[index] < durations[index - 1]:
                raise PotionContentError(f"Potion group {group} duration decreases at tier {index + 1}")

    for level in range(1, 151):
        eligible_groups = {
            item.effect_group
            for item in enabled
            if item.min_explore_level <= level <= item.max_explore_level
        }
        missing = set(EXPECTED_POTION_GROUPS) - eligible_groups
        if missing:
            raise PotionContentError(f"Explore level {level} lacks potion groups: {sorted(missing)}")


def _validate_item_basics(item: PotionItem) -> None:
    if item.category != "potion" or item.potion_type != item.effect_group:
        raise PotionContentError(f"Potion {item.key} has inconsistent type metadata")
    if item.effect_group not in EXPECTED_POTION_GROUPS:
        raise PotionContentError(f"Potion {item.key} has unsupported effect group {item.effect_group}")
    if item.tier < 1:
        raise PotionContentError(f"Potion {item.key} has invalid tier")
    if item.duration_seconds <= 0:
        raise PotionContentError(f"Potion {item.key} has invalid duration")
    if item.min_explore_level < 1 or item.max_explore_level < item.min_explore_level:
        raise PotionContentError(f"Potion {item.key} has invalid explore-level range")
    if item.exploration_drop_weight <= 0:
        raise PotionContentError(f"Potion {item.key} has invalid drop weight")
    if item.inventory_stack_limit <= 0:
        raise PotionContentError(f"Potion {item.key} has invalid stack limit")
    if not item.consumable:
        raise PotionContentError(f"Potion {item.key} must be consumable")


def _validate_effect(item: PotionItem) -> None:
    effect = item.effect
    kind = effect.get("kind")
    operation = effect.get("operation")
    expected = {
        "xp": ("combat_xp_multiplier", "multiply_bonus"),
        "max_hp": ("max_hp_multiplier", "multiply_bonus"),
        "healing": ("heal_between_battles", "max_hp_percent_with_flat_cap"),
        "attack": ("attack_multiplier", "multiply_bonus"),
        "defense": ("defense_multiplier", "multiply_bonus"),
        "luck": ("maximum_enemy_reward_chance", "proc_chance"),
    }[item.effect_group]
    if (kind, operation) != expected:
        raise PotionContentError(f"Potion {item.key} has unsupported effect {kind}/{operation}")
    if kind in {"combat_xp_multiplier", "max_hp_multiplier", "attack_multiplier", "defense_multiplier"}:
        bonus = _required_number(effect, "bonus")
        final_multiplier = _required_number(effect, "final_multiplier")
        if bonus <= 0 or final_multiplier <= 1:
            raise PotionContentError(f"Potion {item.key} multiplier must be positive")
        if abs(final_multiplier - (1 + bonus)) > 0.000001:
            raise PotionContentError(f"Potion {item.key} final_multiplier must equal 1 + bonus")
    elif kind == "heal_between_battles":
        if _required_number(effect, "max_hp_percent") <= 0:
            raise PotionContentError(f"Potion {item.key} healing percent must be positive")
        if _required_int(effect, "flat_cap") <= 0 or _required_int(effect, "minimum_heal") <= 0:
            raise PotionContentError(f"Potion {item.key} healing caps must be positive")
    elif kind == "maximum_enemy_reward_chance":
        chance = _required_number(effect, "chance")
        if not 0 < chance <= 1:
            raise PotionContentError(f"Potion {item.key} luck chance must be between 0 and 1")


def _effect_strength(item: PotionItem) -> tuple[float, float]:
    effect = item.effect
    kind = effect["kind"]
    if kind == "heal_between_battles":
        return float(effect["max_hp_percent"]), float(effect["flat_cap"])
    if kind == "maximum_enemy_reward_chance":
        return float(effect["chance"]), 0.0
    return float(effect["bonus"]), 0.0


def _activation_applies(activation: PotionActivation, at: datetime) -> bool:
    return ensure_utc(activation.activated_at) <= at < ensure_utc(activation.effective_ends_at)


def _activation_sort_key(activation: PotionActivation) -> tuple[datetime, int]:
    return ensure_utc(activation.activated_at), int(activation.id or 0)


def _percent(value: Any) -> str:
    percent = float(value) * 100
    if abs(percent - round(percent)) < 0.001:
        return f"{int(round(percent))}%"
    return f"{percent:.1f}%"


def _required_str(entry: Mapping[str, Any], field: str) -> str:
    value = entry.get(field)
    if not isinstance(value, str) or not value.strip():
        raise PotionContentError(f"Potion content missing string field: {field}")
    return value.strip()


def _optional_str(entry: Mapping[str, Any], field: str) -> str | None:
    value = entry.get(field)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise PotionContentError(f"Potion content field must be a string: {field}")
    return value.strip()


def _required_int(entry: Mapping[str, Any], field: str) -> int:
    value = entry.get(field)
    if not isinstance(value, int) or isinstance(value, bool):
        raise PotionContentError(f"Potion content missing integer field: {field}")
    return value


def _required_number(entry: Mapping[str, Any], field: str) -> float:
    value = entry.get(field)
    if not isinstance(value, int | float) or isinstance(value, bool):
        raise PotionContentError(f"Potion content missing number field: {field}")
    return float(value)


POTION_CONTENT = load_potion_content()


def refresh_potion_content(document: dict[str, Any]) -> PotionContent:
    global POTION_CONTENT
    POTION_CONTENT = load_potion_content(document=document)
    return POTION_CONTENT
