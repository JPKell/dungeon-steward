from __future__ import annotations

import random
from types import SimpleNamespace

import discord
import pytest

from bot.services.potion_service import PotionInventoryEntry, PotionService
from bot.views.exploration import (
    STAT_ALLOCATION_PROFILE,
    DefenseLevelSelectView,
    ExplorationView,
    ExploreLevelSelectView,
    PostExplorationView,
    PotionInventoryView,
    StewardsHallView,
    _stat_allocation_summary_embed,
)


class DummyChoice:
    def __init__(self, key: str, label: str) -> None:
        self.key = key
        self.label = label


class DummyEncounter:
    def __init__(self, choices: list[DummyChoice]) -> None:
        self.choices = choices


class DummySessionFactory:
    pass


class DummyDefenseService:
    pass


class DummyShopService:
    pass


class DummyExplorationService:
    pass


def test_exploration_choices_are_shuffled(monkeypatch: pytest.MonkeyPatch) -> None:
    choices = [
        DummyChoice("hero", "Heroic Action"),
        DummyChoice("villain", "Villainous Action"),
        DummyChoice("destabilize", "Destabilize Action"),
    ]
    encounter = DummyEncounter(choices)

    monkeypatch.setattr(random, "shuffle", lambda x: x.reverse())

    view = ExplorationView(
        session_factory=DummySessionFactory(),
        exploration_service=DummyExplorationService(),
        defense_service=DummyDefenseService(),
        shop_service=DummyShopService(),
        resolution_key="test-key",
        owner_user_id=1,
        encounter=encounter,
    )

    assert [button.label for button in view.children if isinstance(button, discord.ui.Button)] == [
        "Destabilize Action",
        "Villainous Action",
        "Heroic Action",
    ]


def test_action_view_can_include_stat_allocation_buttons() -> None:
    view = PostExplorationView(
        session_factory=DummySessionFactory(),
        exploration_service=DummyExplorationService(),
        defense_service=DummyDefenseService(),
        shop_service=DummyShopService(),
        owner_user_id=1,
        stat_allocation_context=STAT_ALLOCATION_PROFILE,
    )

    assert [button.label for button in view.children if isinstance(button, discord.ui.Button)] == [
        "Explore",
        "Defend",
        "Shop",
        "Steward's Hall",
        "ATK +1",
        "DEF +1",
        "SPD +1",
    ]


def test_defending_action_view_keeps_return_button_by_default() -> None:
    view = PostExplorationView(
        session_factory=DummySessionFactory(),
        exploration_service=DummyExplorationService(),
        defense_service=DummyDefenseService(),
        shop_service=DummyShopService(),
        owner_user_id=1,
        is_defending=True,
    )

    labels = [button.label for button in view.children if isinstance(button, discord.ui.Button)]

    assert "Return from Dungeon" in labels
    assert "Defend" not in labels
    assert labels == ["Explore", "Return from Dungeon", "Shop", "Steward's Hall"]


def test_defending_result_view_can_suppress_return_button() -> None:
    view = PostExplorationView(
        session_factory=DummySessionFactory(),
        exploration_service=DummyExplorationService(),
        defense_service=DummyDefenseService(),
        shop_service=DummyShopService(),
        owner_user_id=1,
        is_defending=True,
        allow_defense_return_button=False,
    )

    labels = [button.label for button in view.children if isinstance(button, discord.ui.Button)]

    assert "Return from Dungeon" not in labels
    assert "Defend" not in labels
    assert labels == ["Explore", "Shop", "Steward's Hall"]


def test_dungeon_level_selectors_do_not_include_return_buttons() -> None:
    options = [discord.SelectOption(label="Level 1", value="1")]
    explore = ExploreLevelSelectView(
        session_factory=DummySessionFactory(),
        exploration_service=DummyExplorationService(),
        defense_service=DummyDefenseService(),
        shop_service=DummyShopService(),
        owner_user_id=1,
        options=options,
        is_defending=True,
    )
    defense = DefenseLevelSelectView(
        session_factory=DummySessionFactory(),
        exploration_service=DummyExplorationService(),
        defense_service=DummyDefenseService(),
        shop_service=DummyShopService(),
        owner_user_id=1,
        options=options,
        is_defending=True,
    )

    for view in (explore, defense):
        labels = [button.label for button in view.children if isinstance(button, discord.ui.Button)]
        assert "Return from Dungeon" not in labels
        assert "Stop Defending" not in labels
        assert "Defend" not in labels


def test_stat_allocation_summary_ignores_image_only_banner_embed() -> None:
    banner = discord.Embed()
    banner.set_image(url="attachment://banner.png")
    content = discord.Embed(title="Profile")
    content.add_field(name="Level", value="3")
    interaction = SimpleNamespace(message=SimpleNamespace(embeds=[banner, content]))

    response = _stat_allocation_summary_embed(interaction, stat="attack", remaining_points=2)

    assert response.title == "Profile"
    assert response.image.url is None
    assert any(field.name == "Stat Allocation" for field in response.fields)


def test_hall_and_defense_selector_include_inventory_button() -> None:
    hall = StewardsHallView(
        session_factory=DummySessionFactory(),
        exploration_service=DummyExplorationService(),
        defense_service=DummyDefenseService(),
        shop_service=DummyShopService(),
        owner_user_id=1,
    )
    defense = DefenseLevelSelectView(
        session_factory=DummySessionFactory(),
        exploration_service=DummyExplorationService(),
        defense_service=DummyDefenseService(),
        shop_service=DummyShopService(),
        owner_user_id=1,
        options=[discord.SelectOption(label="Level 1", value="1")],
    )

    assert "Inventory" in [button.label for button in hall.children if isinstance(button, discord.ui.Button)]
    assert "Inventory" in [button.label for button in defense.children if isinstance(button, discord.ui.Button)]


def test_potion_inventory_select_is_capped_to_owned_items() -> None:
    service = PotionService()
    entries = tuple(
        PotionInventoryEntry(stack=SimpleNamespace(quantity=1), item=item)
        for item in service.content.items[:30]
    )

    view = PotionInventoryView(
        session_factory=DummySessionFactory(),
        exploration_service=DummyExplorationService(),
        defense_service=DummyDefenseService(),
        shop_service=DummyShopService(),
        owner_user_id=1,
        origin="hall",
        entries=entries,
    )
    select = next(child for child in view.children if isinstance(child, discord.ui.Select))

    assert len(select.options) == 25
