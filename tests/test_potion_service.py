from __future__ import annotations

from collections import Counter
from datetime import timedelta

import pytest
from sqlalchemy import func, select

from bot.models import PotionActivation, PotionInventoryStack
from bot.services.potion_service import (
    EXPECTED_POTION_GROUPS,
    PotionActiveSlotLimitError,
    PotionReplacementRequired,
    PotionService,
)
from tests.conftest import make_player


class FixedDropRng:
    def __init__(self, roll: float = 0.0) -> None:
        self.roll = roll

    def random(self) -> float:
        return self.roll

    def choices(self, population, weights, k):
        return [population[0]]


def test_potion_content_has_expected_groups_and_tiers():
    content = PotionService().content
    enabled = [item for item in content.items if item.enabled]
    counts = Counter(item.effect_group for item in enabled)

    assert len(enabled) == 90
    assert set(counts) == set(EXPECTED_POTION_GROUPS)
    assert all(count == 15 for count in counts.values())
    for group in EXPECTED_POTION_GROUPS:
        tiers = [item.tier for item in enabled if item.effect_group == group]
        assert sorted(tiers) == list(range(1, 16))


def test_potion_drop_chance_matches_design_notes():
    service = PotionService()

    assert service.drop_chance(dungeon_level=1, encounter_rarity="common", successful=True) == pytest.approx(0.025)
    assert service.drop_chance(dungeon_level=10, encounter_rarity="uncommon", successful=True) == pytest.approx(0.0305)
    assert service.drop_chance(dungeon_level=18, encounter_rarity="rare", successful=True) == pytest.approx(0.0355)
    assert service.drop_chance(dungeon_level=18, encounter_rarity="common", successful=False) == pytest.approx(0.011725)


def test_exploration_drop_adds_one_inventory_stack(db, now):
    service = PotionService()
    player = make_player(db, now=now)

    item = service.maybe_award_exploration_drop(
        db,
        player,
        dungeon_level=1,
        encounter_rarity="common",
        successful=True,
        rng=FixedDropRng(0.0),
    )

    assert item is not None
    stack = db.scalar(select(PotionInventoryStack).where(PotionInventoryStack.player_id == player.id))
    assert stack is not None
    assert stack.item_key == item.key
    assert stack.quantity == 1


def test_potion_consumption_is_idempotent_and_respects_boundaries(db, now):
    service = PotionService()
    player = make_player(db, now=now)
    service.add_drop(db, player, "potion_xp_01")

    result = service.consume(db, player, "potion_xp_01", idempotency_token="abc", now=now)
    repeated = service.consume(db, player, "potion_xp_01", idempotency_token="abc", now=now)

    assert repeated.idempotent is True
    assert repeated.activation.id == result.activation.id
    assert db.scalar(select(PotionInventoryStack.quantity)) == 0
    assert db.scalar(select(func.count()).select_from(PotionActivation)) == 1
    assert [effect.item.key for effect in service.active_effects_at(db, player, now)] == ["potion_xp_01"]
    assert service.active_effects_at(db, player, now + timedelta(seconds=result.item.duration_seconds)) == ()


def test_same_group_potion_must_expire_before_another_can_be_consumed(db, now):
    service = PotionService()
    player = make_player(db, now=now)
    service.add_drop(db, player, "potion_xp_01")
    service.add_drop(db, player, "potion_xp_02")
    first = service.consume(db, player, "potion_xp_01", idempotency_token="first", now=now)

    replace_at = now + timedelta(minutes=5)
    with pytest.raises(PotionReplacementRequired):
        service.consume(db, player, "potion_xp_02", idempotency_token="second", now=replace_at)

    assert first.activation.effective_ends_at == first.activation.original_expires_at
    assert db.scalar(select(PotionInventoryStack.quantity).where(PotionInventoryStack.item_key == "potion_xp_02")) == 1
    assert [effect.item.key for effect in service.active_effects_at(db, player, replace_at)] == ["potion_xp_01"]

    after_expiration = now + timedelta(seconds=first.item.duration_seconds)
    service.consume(db, player, "potion_xp_02", idempotency_token="second", now=after_expiration)

    assert [effect.item.key for effect in service.active_effects_at(db, player, after_expiration)] == ["potion_xp_02"]


def test_three_active_group_limit_blocks_fourth_group(db, now):
    service = PotionService()
    player = make_player(db, now=now)
    for key in ("potion_xp_01", "potion_attack_01", "potion_defense_01", "potion_luck_01"):
        service.add_drop(db, player, key)

    service.consume(db, player, "potion_xp_01", idempotency_token="xp", now=now)
    service.consume(db, player, "potion_attack_01", idempotency_token="atk", now=now)
    service.consume(db, player, "potion_defense_01", idempotency_token="def", now=now)

    with pytest.raises(PotionActiveSlotLimitError):
        service.consume(db, player, "potion_luck_01", idempotency_token="luck", now=now)
